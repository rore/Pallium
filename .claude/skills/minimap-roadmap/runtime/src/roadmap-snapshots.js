import { randomUUID } from "node:crypto";

const DEFAULT_LIMITS = Object.freeze({
  maxConcurrent: 2,
  maxQueued: 8,
  jobTimeoutMs: 30_000,
  freshMs: 30_000,
  retainMs: 5 * 60_000,
  maxEntries: 16,
  maxBytes: 64 * 1024 * 1024,
});

function snapshotError(code, status, message) {
  return Object.assign(new Error(message), { code, status });
}

function abortError(signal) {
  return signal?.reason || Object.assign(new Error("The operation was aborted."), { name: "AbortError" });
}

export function createRoadmapSnapshotCoordinator(options = {}) {
  const limits = { ...DEFAULT_LIMITS, ...options.limits };
  const now = options.now || Date.now;
  const createId = options.createId || randomUUID;
  const cache = new Map();
  const byId = new Map();
  const jobs = new Set();
  const queue = [];
  let cacheBytes = 0;
  let epoch = 0;
  let running = 0;
  let lastAdmissionWasPriority = false;

  function removeEntry(entry) {
    if (cache.get(entry.key) === entry) cache.delete(entry.key);
    byId.delete(entry.id);
    cacheBytes -= entry.bytes;
  }

  function expireEntries() {
    const time = now();
    for (const entry of cache.values()) if (time >= entry.expiresAt) removeEntry(entry);
  }

  function touch(entry) {
    cache.delete(entry.key);
    cache.set(entry.key, entry);
    entry.lastUsedAt = now();
  }

  function queueCount() {
    return new Set(queue.map((job) => job.key)).size;
  }

  function hasRunningJobForKey(job) {
    return [...jobs].some((other) => other !== job && other.key === job.key && other.running);
  }

  function nextQueuedJob() {
    const eligible = queue.filter((job) => !job.finished && !job.terminalError && !hasRunningJobForKey(job));
    if (!eligible.length) return null;
    const priority = eligible.find((job) => job.priority);
    const regular = eligible.find((job) => !job.priority);
    if (priority && regular) return lastAdmissionWasPriority ? regular : priority;
    return priority || regular;
  }

  function finishJob(job) {
    if (job.finished) return;
    job.finished = true;
    job.completed = true;
    clearTimeout(job.timer);
    const index = queue.indexOf(job);
    if (index !== -1) queue.splice(index, 1);
    jobs.delete(job);
    if (job.running) {
      job.running = false;
      running -= 1;
    }
  }

  function rejectSubscribers(job, error) {
    for (const subscriber of [...job.subscribers]) {
      job.subscribers.delete(subscriber);
      subscriber.signal?.removeEventListener("abort", subscriber.onAbort);
      subscriber.reject(error);
    }
  }

  function abortJob(job, error) {
    if (job.finished || job.completed || job.terminalError) return;
    job.terminalError = error;
    rejectSubscribers(job, error);
    job.controller.abort(error);
    if (!job.running) finishJob(job);
    schedule();
  }

  function retain(entry) {
    expireEntries();
    const previous = cache.get(entry.key);
    if (previous) removeEntry(previous);
    if (limits.maxEntries <= 0 || limits.maxBytes <= 0) return;

    const fullBytes = Buffer.byteLength(entry.valueJson) + Buffer.byteLength(entry.manifestJson) + Buffer.byteLength(entry.admissionJson);
    let keepValue = fullBytes <= limits.maxBytes;
    let bytes = keepValue ? fullBytes : Buffer.byteLength(entry.manifestJson);
    if (bytes > limits.maxBytes) return;

    while (cache.size >= limits.maxEntries || cacheBytes + bytes > limits.maxBytes) {
      const oldest = cache.values().next().value;
      if (!oldest) return;
      removeEntry(oldest);
    }

    entry.bytes = bytes;
    if (!keepValue) {
      entry.valueJson = null;
      entry.admissionJson = null;
    }
    cache.set(entry.key, entry);
    byId.set(entry.id, entry);
    cacheBytes += bytes;
  }

  function responseFor(entry, { stale = false, refreshing = false, valueJson = entry.valueJson } = {}) {
    let materialized = false;
    let value;
    return {
      valueJson,
      get value() {
        if (!materialized) {
          value = valueJson === null ? null : JSON.parse(valueJson);
          materialized = true;
        }
        return value;
      },
      set value(next) { value = next; materialized = true; },
      snapshot: { id: entry.id, validatedAt: entry.validatedAt, stale, refreshing },
      generation: entry.epoch,
    };
  }

  function currentJob(key) {
    return [...jobs].find((job) => job.key === key && job.epoch === epoch
      && !job.finished && !job.completed && !job.terminalError);
  }

  function publish(job, loaded) {
    if (job.epoch !== epoch || job.terminalError || !job.subscribers.size) return null;
    if (!loaded || typeof loaded !== "object" || !Object.hasOwn(loaded, "value")) {
      throw new TypeError("Snapshot scan must return a value.");
    }
    const valueJson = JSON.stringify(loaded.value);
    if (typeof valueJson !== "string") throw new TypeError("Snapshot value must be JSON serializable.");
    const manifestJson = JSON.stringify(loaded.manifest ?? null);
    const admissionJson = JSON.stringify(loaded.admission ?? null);
    const validatedAt = new Date(now()).toISOString();
    const entry = {
      key: job.key,
      id: createId(),
      epoch: job.epoch,
      validatedAt,
      expiresAt: now() + limits.retainMs,
      lastUsedAt: now(),
      invalidated: false,
      valueJson,
      manifestJson,
      admissionJson,
      bytes: 0,
    };
    if (job.retain) retain(entry);
    return { entry, valueJson };
  }

  function settleSuccess(job, loaded) {
    const published = publish(job, loaded);
    if (!published) {
      const error = job.terminalError || snapshotError("snapshot_invalidated", 409, "Snapshot was invalidated before publication.");
      job.completed = true;
      rejectSubscribers(job, error);
      return;
    }
    job.completed = true;
    for (const subscriber of [...job.subscribers]) {
      job.subscribers.delete(subscriber);
      subscriber.signal?.removeEventListener("abort", subscriber.onAbort);
      subscriber.resolve(responseFor(published.entry, { valueJson: published.valueJson }));
    }
  }

  function start(job) {
    if (job.finished || job.terminalError || job.running || hasRunningJobForKey(job)) return;
    job.running = true;
    running += 1;
    lastAdmissionWasPriority = job.priority;
    Promise.resolve()
      .then(() => {
        if (job.controller.signal.aborted) throw abortError(job.controller.signal);
        return job.load({ signal: job.controller.signal, generation: job.epoch });
      })
      .then((loaded) => settleSuccess(job, loaded))
      .catch((error) => {
        job.completed = true;
        rejectSubscribers(job, job.terminalError || error);
      })
      .finally(() => {
        finishJob(job);
        schedule();
      });
  }

  function schedule() {
    while (running < limits.maxConcurrent) {
      const job = nextQueuedJob();
      if (!job) return;
      const index = queue.indexOf(job);
      if (index !== -1) queue.splice(index, 1);
      start(job);
    }
  }

  function subscribe(job, signal) {
    if (signal?.aborted) return Promise.reject(abortError(signal));
    return new Promise((resolve, reject) => {
      const subscriber = { resolve, reject, signal, onAbort: null };
      subscriber.onAbort = () => {
        if (!job.subscribers.delete(subscriber)) return;
        signal.removeEventListener("abort", subscriber.onAbort);
        reject(abortError(signal));
        if (!job.subscribers.size) abortJob(job, abortError(signal));
      };
      job.subscribers.add(subscriber);
      signal?.addEventListener("abort", subscriber.onAbort, { once: true });
      if (signal?.aborted) subscriber.onAbort();
    });
  }

  function enqueue({ key, load, signal, priority, retain }) {
    const existing = currentJob(key);
    if (existing) return subscribe(existing, signal);
    if (signal?.aborted) return Promise.reject(abortError(signal));

    const job = {
      key, load, priority: Boolean(priority), retain, epoch, controller: new AbortController(),
      subscribers: new Set(), running: false, finished: false, completed: false, terminalError: null, timer: null,
    };
    jobs.add(job);
    queue.push(job);
    const promise = subscribe(job, signal);
    job.timer = setTimeout(() => abortJob(job,
      snapshotError("snapshot_unavailable", 503, "Snapshot scan exceeded its 30-second budget.")), limits.jobTimeoutMs);
    schedule();
    if (!job.running && queueCount() > limits.maxQueued) {
      abortJob(job, snapshotError("snapshot_unavailable", 503, "Snapshot queue is full."));
    }
    return promise;
  }

  async function read({ key, cached = false, signal, load, admit, priority = false, retain = true }) {
    if (signal?.aborted) throw abortError(signal);
    expireEntries();
    if (!retain && cache.has(key)) removeEntry(cache.get(key));
    const entry = cache.get(key);
    if (retain && cached && entry?.valueJson !== null && entry) {
      let admitted = false;
      try {
        if (typeof admit === "function") {
          admitted = await admit(JSON.parse(entry.admissionJson), { signal });
        }
      } catch (error) {
        if (signal?.aborted) throw abortError(signal);
      }
      if (signal?.aborted) throw abortError(signal);
      if (admitted && cache.get(key) === entry && now() < entry.expiresAt) {
        touch(entry);
        return responseFor(entry, {
          stale: entry.invalidated || entry.epoch !== epoch || now() - Date.parse(entry.validatedAt) >= limits.freshMs,
          refreshing: Boolean(currentJob(key)),
        });
      }
      if (cache.get(key) === entry) removeEntry(entry);
    }
    return enqueue({ key, load, signal, priority, retain });
  }

  function getManifest(id, key) {
    expireEntries();
    const entry = byId.get(id);
    if (!entry || entry.key !== key || entry.invalidated || entry.epoch !== epoch) return null;
    return JSON.parse(entry.manifestJson);
  }

  function invalidateAll() {
    epoch += 1;
    for (const entry of cache.values()) entry.invalidated = true;
    for (const job of [...jobs]) {
      abortJob(job, snapshotError("snapshot_invalidated", 409, "Snapshot changed during validation."));
    }
  }

  return { read, getManifest, invalidateAll, generation: () => epoch };
}
