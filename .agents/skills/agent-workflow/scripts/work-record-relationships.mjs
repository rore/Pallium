import { load, YAML11_SCHEMA } from "./vendor/js-yaml.mjs";

const decoder = new TextDecoder("utf-8", { fatal: true });
const MAX_CONFIG_BYTES = 65536;
const MAX_RELATIONSHIPS_BYTES = 65536;
const MAX_CONTAINERS = 10000;
const ROUTINE = ["Outcome", "Target", "Scope", "Constraints", "Completion criteria", "Risk", "Complexity", "Reason", "Approach", "Verification", "State"];
const EXPANDED = ["Outcome", "Target", "Scope", "Constraints", "Completion criteria", "Risk", "Complexity", "Reason", "Discovery", "Material assumptions", "Plan", "Verification plan", "Plan review", "Approvals", "State"];
const STATES = new Set(["Ready to implement", "Blocked", "Blocked or returned to planning", "Ready for review"]);
const DEVICES = new Set(["CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$", ...Array.from({ length: 9 }, (_, i) => `COM${i + 1}`), ...Array.from({ length: 9 }, (_, i) => `LPT${i + 1}`)]);
const INVALID = (reason) => ({ status: "invalid", reason });
const UNSUPPORTED = (reason) => ({ status: "unsupported", reason });

function decode(bytes) {
  if (!(bytes instanceof Uint8Array)) throw new TypeError("expected UTF-8 bytes");
  return decoder.decode(bytes);
}

function byteLength(text) {
  return new TextEncoder().encode(text).byteLength;
}

function wellFormed(text) {
  return !/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(text);
}

function normalizeTaskPath(template) {
  if (typeof template !== "string" || !wellFormed(template) || !template || byteLength(template) > 4096 || /\p{Cc}/u.test(template) || (template.match(/\{slug\}/g) ?? []).length !== 1) return null;
  const path = template.replaceAll("\\", "/");
  if (path.startsWith("/") || /^[A-Za-z]:/.test(path) || path.split("/").some((part) => part === "." || part === "..")) return null;
  return path.split("/").filter(Boolean).join("/");
}

function isPlainMapping(value) {
  const prototype = Object.getPrototypeOf(value);
  return prototype === null || prototype === Object.prototype;
}

function checkYamlGraph(root) {
  const visited = new WeakSet();
  const active = new WeakSet();
  const stack = [{ value: root, exit: false }];
  let count = 0;
  while (stack.length) {
    const item = stack.pop();
    const value = item.value;
    if (item.exit) {
      active.delete(value);
      continue;
    }
    if (value === null || typeof value === "string" || typeof value === "boolean") continue;
    if (typeof value === "number" && Number.isFinite(value)) continue;
    if (typeof value !== "object") throw UNSUPPORTED("unsupported_yaml_type");
    if (!Array.isArray(value) && !isPlainMapping(value)) throw UNSUPPORTED("unsupported_yaml_type");
    if (active.has(value)) throw INVALID("invalid_config");
    if (visited.has(value)) continue;
    if (++count > MAX_CONTAINERS) throw INVALID("invalid_config");
    visited.add(value);
    active.add(value);
    stack.push({ value, exit: true });
    const children = Array.isArray(value) ? value : Object.values(value);
    for (let i = children.length - 1; i >= 0; i--) stack.push({ value: children[i], exit: false });
  }
}

export function decodeConfig(configBytes) {
  if (!(configBytes instanceof Uint8Array)) return INVALID("invalid_utf8");
  if (configBytes.byteLength > MAX_CONFIG_BYTES) return INVALID("config_too_large");
  let text;
  try {
    text = decode(configBytes);
  } catch {
    return INVALID("invalid_utf8");
  }
  try {
    const data = load(text, { schema: YAML11_SCHEMA, json: false, maxDepth: 100, maxAliases: 100, maxTotalMergeKeys: 10000 });
    if (!data || !isPlainMapping(data)) return INVALID("invalid_config");
    checkYamlGraph(data);
    if (!Number.isInteger(data.version) || typeof data.version === "boolean") return INVALID("invalid_config");
    if (data.version !== 1) return UNSUPPORTED("unsupported_config_version");
    if (!isPlainMapping(data.workRecord) || typeof data.workRecord.backend !== "string") return INVALID("invalid_config");
    if (data.workRecord.backend !== "local") return UNSUPPORTED("unsupported_backend");
    if (!isPlainMapping(data.workRecord.local)) return INVALID("invalid_config");
    if (typeof data.workRecord.local.taskPath !== "string") return INVALID("invalid_config");
    const task_path = normalizeTaskPath(data.workRecord.local.taskPath);
    return task_path ? { status: "ok", task_path } : INVALID("invalid_task_path");
  } catch (error) {
    return error?.status ? error : INVALID("invalid_config");
  }
}

function scanJsonKeys(source) {
  const stack = [];
  let rootValue = false;
  const takeValue = () => {
    if (!stack.length) {
      rootValue = true;
      return;
    }
    const frame = stack.at(-1);
    if (frame.type === "object") frame.state = "comma";
    else if (frame.state === "value" || frame.state === "valueOrEnd") frame.state = "comma";
  };
  for (let i = 0; i < source.length;) {
    const ch = source[i];
    if (/\s/.test(ch)) { i++; continue; }
    const frame = stack.at(-1);
    if (ch === '"') {
      let end = i + 1;
      while (end < source.length) {
        if (source[end] === "\\") { end += 2; continue; }
        if (source[end++] === '"') break;
      }
      const token = source.slice(i, end);
      if (frame?.type === "object" && frame.state === "keyOrEnd") {
        const key = JSON.parse(token);
        if (frame.keys.has(key)) throw new Error("duplicate key");
        frame.keys.add(key);
        frame.state = "colon";
      } else takeValue();
      i = end;
      continue;
    }
    if (ch === "{") {
      takeValue();
      stack.push({ type: "object", state: "keyOrEnd", keys: new Set() });
      i++;
      continue;
    }
    if (ch === "[") {
      takeValue();
      stack.push({ type: "array", state: "valueOrEnd" });
      i++;
      continue;
    }
    if (ch === "}") { stack.pop(); i++; continue; }
    if (ch === "]") { stack.pop(); i++; continue; }
    if (ch === ":") { if (frame?.type === "object") frame.state = "value"; i++; continue; }
    if (ch === ",") {
      if (frame?.type === "object") frame.state = "keyOrEnd";
      else if (frame?.type === "array") frame.state = "value";
      i++;
      continue;
    }
    takeValue();
    while (i < source.length && !/[\s,\]}]/.test(source[i])) i++;
  }
  if (!rootValue || stack.length) throw new Error("invalid JSON");
}

function stripSurroundingHints(value) {
  let text = value.replace(/^[ \t\r\n]+|[ \t\r\n]+$/g, "");
  while (text.startsWith("<!--")) {
    const end = text.indexOf("-->");
    if (end < 0) throw new Error("unterminated hint");
    text = text.slice(end + 3).replace(/^[ \t\r\n]+|[ \t\r\n]+$/g, "");
  }
  while (text.endsWith("-->")) {
    const start = text.lastIndexOf("<!--");
    if (start < 0) throw new Error("unmatched hint");
    text = text.slice(0, start).replace(/^[ \t\r\n]+|[ \t\r\n]+$/g, "");
  }
  return text;
}

function validString(value) {
  return typeof value === "string" && wellFormed(value) && value.length > 0 && !/^[\p{White_Space}\p{Cc}]+$/u.test(value) && !/\p{Cc}/u.test(value);
}

function validateRelationships(raw) {
  const json = stripSurroundingHints(raw);
  if (byteLength(json) > MAX_RELATIONSHIPS_BYTES) throw INVALID("relationships_too_large");
  let value;
  try {
    scanJsonKeys(json);
    value = JSON.parse(json);
  } catch {
    throw INVALID("invalid_json");
  }
  if (!value || Array.isArray(value) || typeof value !== "object" || Object.keys(value).sort().join() !== "pull_requests,schema_version,sources") throw INVALID("invalid_relationships");
  if (!Number.isInteger(value.schema_version) || typeof value.schema_version === "boolean") throw INVALID("invalid_relationships");
  if (value.schema_version < 1) throw INVALID("invalid_relationships");
  if (value.schema_version > 1) throw UNSUPPORTED("unsupported_relationship_version");
  if (value.sources !== null && !Array.isArray(value.sources)) throw INVALID("invalid_relationships");
  const identities = new Set();
  let unsupportedSourceUrl = false;
  for (const source of value.sources ?? []) {
    if (!source || Array.isArray(source) || typeof source !== "object") throw INVALID("invalid_relationships");
    const keys = Object.keys(source).sort().join();
    if (keys !== "local_ref,provider,scope_ref" && keys !== "local_ref,provider,scope_ref,url") throw INVALID("invalid_relationships");
    if (![source.provider, source.scope_ref, source.local_ref].every(validString)) throw INVALID("invalid_relationships");
    if (Object.hasOwn(source, "url")) {
      if (!validString(source.url)) throw INVALID("invalid_relationships");
      const sourceUrlStatus = httpsUrlAuthority(source.url);
      if (!sourceUrlStatus) throw INVALID("invalid_relationships");
      if (sourceUrlStatus === "unsupported") unsupportedSourceUrl = true;
    }
    const identity = JSON.stringify([source.provider, source.scope_ref, source.local_ref]);
    if (identities.has(identity)) throw INVALID("invalid_relationships");
    identities.add(identity);
  }
  if (!Array.isArray(value.pull_requests)) throw INVALID("invalid_relationships");
  const prs = new Set();
  let unsupportedPr = false;
  for (const url of value.pull_requests) {
    if (!validString(url) || /[\\\u0000-\u0020\u007f]/u.test(url)) throw INVALID("invalid_relationships");
    if (!httpsUrlAuthority(url)) throw INVALID("invalid_relationships");
    const match = /^https:\/\/github\.com\/([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)\/([A-Za-z0-9_.-]+)\/pull\/([1-9][0-9]*)$/i.exec(url);
    if (!match) {
      unsupportedPr = true;
      continue;
    }
    if ([".", ".."].includes(match[2])) throw INVALID("invalid_relationships");
    const identity = `${match[1].toLowerCase()}/${match[2].toLowerCase()}/${match[3]}`;
    if (prs.has(identity)) throw INVALID("invalid_relationships");
    prs.add(identity);
  }
  if (unsupportedPr) throw UNSUPPORTED("unsupported_pr_url");
  if (unsupportedSourceUrl) throw UNSUPPORTED("unsupported_source_url");
  return value;
}

function httpsUrlAuthority(value) {
  if (typeof value !== "string" || !/^https:\/\//i.test(value) || !wellFormed(value) || /[\\\p{White_Space}\p{Cc}]/u.test(value)) return null;
  const match = /^https:\/\/([^/?#]+)/i.exec(value);
  if (!match || /[@%]/u.test(match[1])) return null;
  const authority = match[1];
  if (authority.startsWith("[")) {
    const closing = authority.indexOf("]");
    if (closing < 0 || (authority.slice(closing + 1) !== "" && !/^:[0-9]+$/u.test(authority.slice(closing + 1)))) return null;
    const port = authority.slice(closing + 2);
    if (authority.slice(closing + 1).startsWith(":") && Number(port) > 65535) return null;
    try {
      new URL(`https://[${authority.slice(1, closing)}]/`);
      return "supported";
    } catch {
      return null;
    }
  }
  if ((authority.match(/:/gu) ?? []).length > 1) return null;
  const colon = authority.indexOf(":");
  const host = colon < 0 ? authority : authority.slice(0, colon);
  const port = colon < 0 ? null : authority.slice(colon + 1);
  if (port !== null && (!/^[0-9]+$/u.test(port) || Number(port) > 65535)) return null;
  if (!host) return null;
  const finalDot = host.endsWith(".");
  const hostWithoutDot = finalDot ? host.slice(0, -1) : host;
  const labels = hostWithoutDot.split(".");
  if (!hostWithoutDot || labels.some((label) => !label)) return null;
  if (/[^\x00-\x7F]/u.test(host)) {
    if ([...hostWithoutDot].length > 253 || labels.some((label) => [...label].length > 63)) return null;
    if (labels.some((label) => !/^(?:[A-Za-z0-9_-]|[^\x00-\x7F])+$/u.test(label))) return null;
    if (/^(?:[0-9]+|0x[0-9a-f]*)$/iu.test(labels.at(-1))) return null;
    return "unsupported";
  }
  if (hostWithoutDot.length > 253 || labels.some((label) => label.length > 63) || labels.some((label) => !/^[A-Za-z0-9_-]+$/u.test(label))) return null;
  if (/^(?:[0-9]+|0x[0-9a-f]*)$/iu.test(labels.at(-1))) {
    if (finalDot || labels.length !== 4 || labels.some((label) => !/^(?:0|[1-9][0-9]*)$/u.test(label) || Number(label) > 255)) return null;
  }
  return "supported";
}

function validateSlug(slug) {
  return typeof slug === "string" && wellFormed(slug) && byteLength(slug) > 0 && byteLength(slug) <= 255 &&
    !/[\p{White_Space}\p{Cc}<>:"|?*\\/]/u.test(slug) && !slug.startsWith(".") && !/[. ]$/u.test(slug) &&
    !DEVICES.has(slug.split(".", 1)[0].toUpperCase());
}

function findTitle(text) {
  let fenceChar = "";
  let fenceLength = 0;
  for (const line of text.split("\n")) {
    const fence = /^ {0,3}(`{3,}|~{3,})/.exec(line);
    if (fence) {
      if (!fenceChar) {
        fenceChar = fence[1][0];
        fenceLength = fence[1].length;
      } else if (fence[1][0] === fenceChar && fence[1].length >= fenceLength) {
        fenceChar = "";
      }
      continue;
    }
    if (fenceChar) continue;
    const heading = /^ {0,3}#(?:[ \t]+)(.*?)\s*$/.exec(line);
    if (heading) return heading[1].replace(/[ \t]+#+[ \t]*$/u, "").trim();
  }
  return null;
}

export function decodeRecord(recordBytes, { task_path, record_path } = {}) {
  let text;
  try {
    text = decode(recordBytes);
  } catch {
    return INVALID("invalid_utf8");
  }
  text = text.replace(/\r\n?/g, "\n");
  const template = normalizeTaskPath(task_path);
  if (!template) return INVALID("invalid_task_path");
  if (typeof record_path !== "string" || !wellFormed(record_path) || !record_path || byteLength(record_path) > 4096 || record_path.includes("\\") || record_path.startsWith("/") || record_path.split("/").some((part) => !part || part === "." || part === "..") || /\p{Cc}/u.test(record_path)) return INVALID("invalid_record_path");
  const [prefix, suffix] = template.split("{slug}");
  if (!record_path.startsWith(prefix) || !record_path.endsWith(suffix)) return INVALID("invalid_record_path");
  const slug = record_path.slice(prefix.length, record_path.length - suffix.length || undefined);
  if (!validateSlug(slug)) return INVALID("invalid_slug");
  if (template.replace("{slug}", slug) !== record_path) return INVALID("invalid_record_path");
  const starts = [...text.matchAll(/^[ \t]*<!-- agent-workflow:start -->[ \t]*$/gm)];
  const ends = [...text.matchAll(/^[ \t]*<!-- agent-workflow:end -->[ \t]*$/gm)];
  if (starts.length !== 1 || ends.length !== 1 || ends[0].index < starts[0].index) return INVALID("invalid_record");
  const block = text.slice(starts[0].index + starts[0][0].length, ends[0].index);
  const headers = [...block.matchAll(/^\*\*([^*]+?):\*\*[ \t]*/gm)];
  const fields = Object.create(null);
  for (let i = 0; i < headers.length; i++) {
    const label = headers[i][1].trim();
    if (Object.hasOwn(fields, label)) return INVALID("invalid_record");
    const raw = block.slice(headers[i].index + headers[i][0].length, headers[i + 1]?.index ?? block.length);
    fields[label] = label === "Relationships" ? raw : raw.replace(/<!--[\s\S]*?-->/g, "").trim();
  }
  const risk = fields.Risk;
  const complexity = fields.Complexity;
  if (!new Set(["Routine", "Elevated", "High"]).has(risk) || !new Set(["Simple", "Moderate", "Large"]).has(complexity)) return INVALID("invalid_record");
  const routine = risk === "Routine" && complexity === "Simple";
  const required = routine ? ROUTINE : EXPANDED;
  const optional = ["Requirement baseline", "Behavior changes", "Relationships"];
  if (!routine) optional.push("Exceptions");
  if (Object.keys(fields).some((field) => !required.includes(field) && !optional.includes(field)) || required.some((field) => !Object.hasOwn(fields, field) || (!fields[field] && !(routine && field === "Reason") && !(!routine && field === "Approvals")))) return INVALID("invalid_record");
  const state = fields.State?.replace(/[.]+$/u, "").trim();
  if (!STATES.has(state)) return INVALID("invalid_record_state");
  let relationships = null;
  if (Object.hasOwn(fields, "Relationships")) {
    try {
      relationships = validateRelationships(fields.Relationships);
    } catch (error) {
      return error?.status ? error : INVALID("invalid_relationships");
    }
  }
  const title = findTitle(text) || fields.Outcome;
  return { status: Object.hasOwn(fields, "Relationships") ? "declared" : "legacy", work_record_ref: `agent-workflow:${slug}`, title, recorded_state: state, relationships };
}
