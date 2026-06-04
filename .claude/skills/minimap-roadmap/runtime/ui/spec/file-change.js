// package/minimap/ui/spec/file-change.js
//
// Pure predicate for detecting that the active spec file changed on disk
// since the last full UI load. The browser-side polling loop calls this
// every refresh tick; a `true` result means we should show the sticky
// "this file changed on disk" warning banner. DOM-free so it can be
// unit-tested under `node --test`.
//
// Watermark semantics:
// - `lastSeen` is the hash captured the last time we fully reloaded the
//   spec (initial load, apply suggestion, rollback, or click-to-reload).
//   It is "" before the first successful load.
// - `fresh` is the hash returned by the most recent getSessionContext.
// - We only fire when BOTH are non-empty and they differ. Treating a
//   missing hash as "changed" would flash a banner on every transient
//   server hiccup — too noisy for the signal we want.

export function detectSpecFileChange(lastSeen, fresh) {
  if (!lastSeen || !fresh) return false;
  return lastSeen !== fresh;
}
