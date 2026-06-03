// package/minimap/ui/spec/anchors.js
//
// Pure offset/text-mapping helpers for spec anchors. DOM-free and state-free.
// Lifted from app.js so they can be unit-tested under `node --test`. The
// DOM-touching parts of the spec subsystem (getSpecSelectionText,
// captureSpecSelectedQuote, etc.) stay in app.js until Phase 4.

// Local copy of normalizeAnchorWhitespace (still defined in app.js for
// non-anchor callers). Keeping a private copy here keeps the module pure.
function normalizeAnchorWhitespace(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

export function buildWhitespaceNormalizedMap(value) {
  const normalized = [];
  const originalIndexes = [];
  let lastWasSpace = true;

  const source = String(value || "");
  for (let index = 0; index < source.length; index += 1) {
    const char = source[index];
    if (/\s/.test(char)) {
      if (!lastWasSpace) {
        normalized.push(" ");
        originalIndexes.push(index);
        lastWasSpace = true;
      }
      continue;
    }

    normalized.push(char);
    originalIndexes.push(index);
    lastWasSpace = false;
  }

  if (normalized.at(-1) === " ") {
    normalized.pop();
    originalIndexes.pop();
  }

  return {
    text: normalized.join(""),
    originalIndexes,
  };
}

// Like buildWhitespaceNormalizedMap, but also strips inline markdown markers
// that the spec renderer hides (backtick code spans, **bold**, *italic*) so a
// rendered DOM selection like "Both shipped (ClawMem, agentmemory)" can be
// matched back to source markdown that was "Both shipped (`ClawMem`, `agentmemory`)".
//
// Each char in the returned text maps to its origin source offset via
// originalIndexes — for stripped markers (backticks, asterisks) the markers
// themselves are excluded; only inner-span chars survive in the map. Match
// against the same renderer that renderInlineMarkdown uses (only those three
// patterns); other markdown ([](), ![]) is left literal because the renderer
// does not strip them either.
export function buildRenderedNormalizedMap(value) {
  const source = String(value || "");
  const normalized = [];
  const originalIndexes = [];
  let lastWasSpace = true;

  const pushChar = (char, sourceIndex) => {
    if (/\s/.test(char)) {
      if (!lastWasSpace) {
        normalized.push(" ");
        originalIndexes.push(sourceIndex);
        lastWasSpace = true;
      }
      return;
    }
    normalized.push(char);
    originalIndexes.push(sourceIndex);
    lastWasSpace = false;
  };

  // Try to detect the start of an inline marker at `index`. Returns the
  // 1-or-2-char marker string if a balanced closer exists later in the
  // source, or "" otherwise. This deliberately mirrors renderInlineMarkdown's
  // greedy-but-non-nested matching; complex markdown (escapes, nesting) is
  // left literal so we never lose chars from the source map.
  const detectMarker = (index) => {
    const ch = source[index];
    const next = source[index + 1];
    if (ch === "`") {
      const close = source.indexOf("`", index + 1);
      // Renderer requires non-empty inner content: `[^`]+`
      if (close > index + 1) return "`";
      return "";
    }
    if (ch === "*" && next === "*") {
      // Match ** ... ** (non-greedy on first ** close)
      const close = source.indexOf("**", index + 2);
      if (close > index + 2) return "**";
      return "";
    }
    if (ch === "*") {
      // Single * for italics — renderer matches /\*([^*]+)\*/ (no nested *).
      // Find the next unescaped single * that is NOT part of **.
      let cursor = index + 1;
      while (cursor < source.length) {
        if (source[cursor] === "*") {
          // Bare star is the closer if it's not the start of **.
          if (source[cursor + 1] !== "*") return "*";
          // ** sequence inside an italic span — bail; renderer wouldn't match.
          return "";
        }
        cursor += 1;
      }
      return "";
    }
    return "";
  };

  let i = 0;
  while (i < source.length) {
    const marker = detectMarker(i);
    if (!marker) {
      pushChar(source[i], i);
      i += 1;
      continue;
    }

    const innerStart = i + marker.length;
    const close = source.indexOf(marker, innerStart);
    if (close === -1 || close === innerStart) {
      // detectMarker promised a closer, but be defensive.
      pushChar(source[i], i);
      i += 1;
      continue;
    }

    // Emit inner chars with their actual source offsets; markers themselves
    // are skipped (they don't appear in the rendered text).
    for (let k = innerStart; k < close; k += 1) {
      pushChar(source[k], k);
    }
    i = close + marker.length;
  }

  if (normalized.at(-1) === " ") {
    normalized.pop();
    originalIndexes.pop();
  }

  return {
    text: normalized.join(""),
    originalIndexes,
  };
}

export function sourceQuoteForRenderedSelection(selectionText, sourceContent) {
  return resolveSourceQuoteFromRendered(selectionText, sourceContent).quote;
}

// Like sourceQuoteForRenderedSelection but also returns a 1-based line range
// in sourceContent for the matched source slice. The line range is
// what we forward to the server as a disambiguation hint when the same
// quote appears more than once in the file (e.g. once in prose and once
// inside a fenced code block). Returns lineRange = null when the rendered
// selection couldn't be mapped back to the source.
//
// `occurrenceIndex` is optional: a 0-based count of which match of the
// selected text the user picked. When the same rendered text appears more
// than once and we know which one (because we counted occurrences in the
// rendered DOM before the live selection's start), we pick the matching
// source occurrence — without it, indexOf would always return the first
// match and the line hint would point at the wrong spot.
export function resolveSourceQuoteFromRendered(selectionText, sourceContent, occurrenceIndex = 0) {
  const normalizedSelection = normalizeAnchorWhitespace(selectionText);
  if (!normalizedSelection) {
    return { quote: "", lineRange: null, quoteOffset: null };
  }

  const content = String(sourceContent || "");

  // Try the markdown-aware map first — selections from the rendered DOM lack
  // backticks / ** / * that the source carries, so a literal source lookup
  // would miss. The map walks markers as the renderer does, so the rendered
  // selection lines up with the stripped view.
  const renderedSource = buildRenderedNormalizedMap(content);
  let matchIndex = nthOccurrence(renderedSource.text, normalizedSelection, occurrenceIndex);
  let mapped = renderedSource;

  // Fall back to the plain whitespace-normalized map (preserves markers).
  // Matters when the user selects a code-span itself: rendered text contains
  // the inner content, but if the user copied source-form text (with backticks)
  // we still want to find it.
  if (matchIndex === -1) {
    const literalSource = buildWhitespaceNormalizedMap(content);
    matchIndex = nthOccurrence(literalSource.text, normalizedSelection, occurrenceIndex);
    mapped = literalSource;
  }

  if (matchIndex === -1) {
    return { quote: selectionText.trim(), lineRange: null, quoteOffset: null };
  }

  const start = mapped.originalIndexes[matchIndex];
  const end = mapped.originalIndexes[matchIndex + normalizedSelection.length - 1] + 1;
  const sliced = content.slice(start, end);
  // Trim adjusts the start/end. Recompute the trimmed span so the line
  // range still describes the visible text the user selected.
  const leading = sliced.length - sliced.replace(/^\s+/, "").length;
  const trailing = sliced.length - sliced.replace(/\s+$/, "").length;
  const trimmedStart = start + leading;
  const trimmedEnd = end - trailing;
  const lineRange = computeLineRange(content, trimmedStart, trimmedEnd - trimmedStart);
  // Char offset of the trimmed selection start in sourceContent. The
  // server uses this as the strongest disambiguation hint when the same
  // phrase appears multiple times — including twice on the same line, where
  // the line range alone can't pick a winner.
  return { quote: sliced.trim(), lineRange, quoteOffset: trimmedStart };
}

// Index of the nth (0-based) occurrence of `needle` in `haystack`, or
// the index of the LAST occurrence when n is past the end (clamps so a
// stale rendered count never silently rolls back to occurrence 0).
// Returns -1 when there are no matches at all.
export function nthOccurrence(haystack, needle, n) {
  let cursor = haystack.indexOf(needle);
  if (cursor === -1) return -1;
  let last = cursor;
  let i = 0;
  while (i < n) {
    cursor = haystack.indexOf(needle, cursor + 1);
    if (cursor === -1) return last;
    last = cursor;
    i += 1;
  }
  return last;
}

// 1-based line range for a [start, start+length) span in `text`. Mirrors the
// server's lineRangeForOffset in src/sessions.js so the hint we send lines
// up with what createTextAnchor computes server-side.
export function computeLineRange(text, start, length) {
  if (typeof start !== "number" || start < 0) {
    return null;
  }
  const before = text.slice(0, start);
  const selected = text.slice(start, start + Math.max(0, length));
  const lineStart = before.split(/\r?\n/).length;
  const lineEnd = lineStart + selected.split(/\r?\n/).length - 1;
  return { lineStart, lineEnd };
}

export function normalizeVisibleText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

// Mirror of stripMarkdownSyntax in src/sessions.js (kept in sync via the
// tri-tree parity test). Strips inline markdown markers and leading heading
// hashes so a quote captured from a rendered view (no backticks, no `### `)
// still finds its block in the rendered HTML, and vice versa.
export function stripMarkdownSyntaxForUi(value) {
  return String(value || "")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/[`*_]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

// Decode literal backslash escapes (\n, \r, \t, \\) in suggestion content.
// Authors — particularly LLMs — sometimes emit `\n` as a two-character
// literal instead of a real newline. Without this the diff body renders the
// `\n` glyphs verbatim, which is unreadable. We decode conservatively: only
// the four common escapes, only when not already a real newline.
export function decodeLiteralEscapes(value) {
  if (typeof value !== "string" || value.indexOf("\\") === -1) return String(value || "");
  return value.replace(/\\([nrt\\])/g, (_, ch) => {
    if (ch === "n") return "\n";
    if (ch === "r") return "\r";
    if (ch === "t") return "\t";
    return "\\";
  });
}
