// package/minimap/ui/markdown.js
//
// Hand-rolled markdown -> HTML renderer. Browser-native ES module, DOM-free.
// Lifted intact from app.js so it can be unit-tested under `node --test`.
//
// Has its own private `escapeHtml` because the one in app.js has a much
// broader caller set; duplicating 8 lines is cheaper than coupling the two.

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

// Decide whether an href can navigate inside a browser tab. Web schemes,
// mailto, tel, and same-page fragments all work; relative or absolute
// filesystem paths do not — those resolve only inside an editor (VS Code,
// Cursor, etc.) where the source spec was authored. Emitting `<a href>`
// for filesystem paths produces a clickable link that 404s against the
// minimap server, which is worse than rendering the link text as plain
// text.
//
// We also block dangerous schemes (javascript:, data:, vbscript:) here so
// the call site can fall back to the same plain-text path.
function isNavigableHref(href) {
  const stripped = String(href).trim().toLowerCase();
  if (!stripped) return false;
  if (stripped.startsWith("javascript:")) return false;
  if (stripped.startsWith("data:")) return false;
  if (stripped.startsWith("vbscript:")) return false;
  if (stripped.startsWith("http://")) return true;
  if (stripped.startsWith("https://")) return true;
  if (stripped.startsWith("mailto:")) return true;
  if (stripped.startsWith("tel:")) return true;
  // Same-page fragments — browser-navigable.
  if (stripped.startsWith("#")) return true;
  // Anything else (relative paths like ../foo.py, absolute paths like
  // /Users/me/x or C:/code/y, exotic schemes we don't recognize) — render
  // the text but drop the wrapper.
  return false;
}

export function renderInlineMarkdown(value) {
  let html = escapeHtml(value);
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  // [text](url) — link replacement runs LAST so the text can contain the
  // tag output of the earlier passes (e.g. <code>x</code> from a backtick
  // span, <strong>x</strong> from bold). Both captures are already
  // HTML-escaped from the first pass, so we don't need to re-escape; we
  // only emit an <a href> for browser-navigable hrefs. Non-navigable
  // hrefs (filesystem paths, dangerous schemes) collapse to the link
  // text — broken links are worse than no link.
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_match, text, url) => {
    if (!isNavigableHref(url)) return text;
    return `<a href="${url}">${text}</a>`;
  });
  return html;
}

export function renderMarkdownToHtml(markdown, options = {}) {
  const normalized = String(markdown || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const sourceLines = normalized.split("\n");
  const blocks = [];

  // Source-line attribute helper. The spec-review UI uses these to anchor
  // margin cards to the exact line each block came from in the source file —
  // see spec/render.js for the lookup. 1-based to match the line numbering
  // the server emits in `anchor.lineStart` / `anchorStatus.lineStart`.
  //
  // Off by default — only the spec-review render path opts in via
  // `options.emitLines: true`. Other callers (the scope panel preview, the
  // setup readme, etc.) don't care about line metadata and would only pay
  // the HTML-weight cost. `options.lineOffset` shifts the values, e.g. to
  // skip past frontmatter that the caller stripped before rendering.
  const emitLines = options.emitLines === true;
  const lineOffset = Number.isFinite(options.lineOffset) ? options.lineOffset : 0;
  const lineAttr = (sourceLineIndex) => emitLines ? ` data-spec-source-line="${sourceLineIndex + 1 + lineOffset}"` : "";

  function expandIndentation(value) {
    return String(value || "").replace(/\t/g, "    ");
  }

  function getIndentation(value) {
    const expanded = expandIndentation(value);
    const match = expanded.match(/^(\s*)/);
    return match ? match[1].length : 0;
  }

  function getListMarker(value) {
    const expanded = expandIndentation(value);
    let match = expanded.match(/^(\s*)([-*])\s+(.+)$/);
    if (match) {
      return { indent: match[1].length, ordered: false, content: match[3] };
    }

    match = expanded.match(/^(\s*)(\d+)\.\s+(.+)$/);
    if (match) {
      return { indent: match[1].length, ordered: true, content: match[3] };
    }

    return null;
  }

  function isHorizontalRule(value) {
    return /^ {0,3}([-*_])(?:\s*\1){2,}\s*$/.test(value);
  }

  function splitTableRow(value) {
    const trimmed = String(value || "").trim();
    const withoutEdges = trimmed.replace(/^\|/, "").replace(/\|$/, "");
    return withoutEdges.split("|").map((cell) => cell.trim());
  }

  function isTableDelimiterLine(value) {
    const cells = splitTableRow(value);
    return cells.length > 1 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
  }

  function tableAlignments(value) {
    return splitTableRow(value).map((cell) => {
      const left = cell.startsWith(":");
      const right = cell.endsWith(":");
      if (left && right) {
        return "center";
      }
      if (right) {
        return "right";
      }
      return "left";
    });
  }

  function isTableStart(index) {
    return index + 1 < sourceLines.length
      && sourceLines[index].includes("|")
      && isTableDelimiterLine(sourceLines[index + 1]);
  }

  function parseTable(startIndex) {
    const headerCells = splitTableRow(sourceLines[startIndex]);
    const alignments = tableAlignments(sourceLines[startIndex + 1]);
    const rows = [];
    let index = startIndex + 2;

    // Per-row source lines so the rendered <tr> can carry the line it came
    // from. Used by the spec-review UI to anchor a comment to the row.
    const headerLineAttr = lineAttr(startIndex);
    const rowLineAttrs = [];
    while (index < sourceLines.length && sourceLines[index].trim() && sourceLines[index].includes("|")) {
      rowLineAttrs.push(lineAttr(index));
      rows.push(splitTableRow(sourceLines[index]));
      index += 1;
    }

    const alignStyle = (cellIndex) => ` style="text-align: ${alignments[cellIndex] || "left"}"`;
    const header = `<thead><tr${headerLineAttr}>${headerCells.map((cell, cellIndex) => `<th${alignStyle(cellIndex)}>${renderInlineMarkdown(cell)}</th>`).join("")}</tr></thead>`;
    const body = rows.length
      ? `<tbody>${rows.map((row, rowIndex) => `<tr${rowLineAttrs[rowIndex]}>${headerCells.map((_, cellIndex) => `<td${alignStyle(cellIndex)}>${renderInlineMarkdown(row[cellIndex] || "")}</td>`).join("")}</tr>`).join("")}</tbody>`
      : "";

    return {
      html: `<div class="markdown-table-wrap"${lineAttr(startIndex)}><table>${header}${body}</table></div>`,
      nextIndex: index,
    };
  }

  function parseBlockquote(startIndex) {
    const quoteLines = [];
    let index = startIndex;

    while (index < sourceLines.length) {
      const match = sourceLines[index].match(/^>\s?(.*)$/);
      if (!match) {
        break;
      }
      quoteLines.push(match[1]);
      index += 1;
    }

    // Inner blockquote content is rendered with its own line numbering, but
    // we suppress the attribute on inner blocks because their lines aren't
    // a direct mapping back to the outer document (we'd need to track the
    // `>` prefix offsets to be accurate, and the placement use case
    // doesn't need this granularity — the outer <blockquote> already has
    // a line attr that pins the whole region).
    const quoteHtml = renderMarkdownToHtml(quoteLines.join("\n"), { emitLines: false });
    return {
      html: `<blockquote${lineAttr(startIndex)}>${quoteHtml}</blockquote>`,
      nextIndex: index,
    };
  }

  function parseCodeBlock(startIndex) {
    const codeLines = [];
    let index = startIndex + 1;

    while (index < sourceLines.length && !sourceLines[index].startsWith("```")) {
      codeLines.push(sourceLines[index]);
      index += 1;
    }

    if (index < sourceLines.length && sourceLines[index].startsWith("```")) {
      index += 1;
    }

    return {
      html: `<pre${lineAttr(startIndex)}><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`,
      nextIndex: index,
    };
  }

  function parseParagraph(startIndex) {
    const paragraphLines = [];
    let index = startIndex;

    while (index < sourceLines.length) {
      const rawLine = sourceLines[index];
      const trimmed = rawLine.trim();
      if (!trimmed) {
        break;
      }
      if (trimmed.startsWith("```") || trimmed.startsWith(">") || trimmed.match(/^(#{1,6})\s+(.+)$/) || getListMarker(rawLine) || isHorizontalRule(trimmed) || isTableStart(index)) {
        break;
      }

      paragraphLines.push(trimmed);
      index += 1;
    }

    return {
      html: `<p${lineAttr(startIndex)}>${renderInlineMarkdown(paragraphLines.join(" "))}</p>`,
      nextIndex: index,
    };
  }

  function parseList(startIndex, baseIndent, ordered) {
    const tagName = ordered ? "ol" : "ul";
    const items = [];
    let index = startIndex;

    while (index < sourceLines.length) {
      const marker = getListMarker(sourceLines[index]);
      if (!marker || marker.indent !== baseIndent || marker.ordered !== ordered) {
        break;
      }

      // Source line of THIS list item's marker. Captured before we consume
      // the line so each <li> carries its own line, not the list's.
      const itemStartIndex = index;
      const paragraphLines = [marker.content.trim()];
      const children = [];
      index += 1;

      while (index < sourceLines.length) {
        const rawLine = sourceLines[index];
        const trimmed = rawLine.trim();

        if (!trimmed) {
          let lookahead = index + 1;
          while (lookahead < sourceLines.length && !sourceLines[lookahead].trim()) {
            lookahead += 1;
          }
          if (lookahead >= sourceLines.length) {
            index = lookahead;
            break;
          }

          const nextMarker = getListMarker(sourceLines[lookahead]);
          const nextIndent = getIndentation(sourceLines[lookahead]);
          const nextTrimmed = sourceLines[lookahead].trim();
          if ((nextMarker && nextMarker.indent <= baseIndent) || (!nextMarker && nextIndent <= baseIndent && !nextTrimmed.startsWith("```") && !nextTrimmed.match(/^(#{1,6})\s+(.+)$/))) {
            index = lookahead;
            break;
          }

          index = lookahead;
          continue;
        }

        if (trimmed.startsWith("```")) {
          const parsedCode = parseCodeBlock(index);
          children.push(parsedCode.html);
          index = parsedCode.nextIndex;
          continue;
        }

        const nestedMarker = getListMarker(rawLine);
        if (nestedMarker) {
          if (nestedMarker.indent > baseIndent) {
            const parsedList = parseList(index, nestedMarker.indent, nestedMarker.ordered);
            children.push(parsedList.html);
            index = parsedList.nextIndex;
            continue;
          }

          break;
        }

        const indent = getIndentation(rawLine);
        if (trimmed.match(/^(#{1,6})\s+(.+)$/) && indent <= baseIndent) {
          break;
        }

        if (indent > baseIndent) {
          paragraphLines.push(trimmed);
          index += 1;
          continue;
        }

        break;
      }

      const paragraphHtml = renderInlineMarkdown(paragraphLines.join(" "));
      const itemAttr = lineAttr(itemStartIndex);
      if (children.length > 0) {
        items.push(`<li${itemAttr}><p>${paragraphHtml}</p>${children.join("")}</li>`);
      } else {
        items.push(`<li${itemAttr}>${paragraphHtml}</li>`);
      }
    }

    return {
      html: `<${tagName}${lineAttr(startIndex)}>${items.join("")}</${tagName}>`,
      nextIndex: index,
    };
  }

  let index = 0;
  while (index < sourceLines.length) {
    const rawLine = sourceLines[index];
    const trimmed = rawLine.trim();

    if (!trimmed) {
      index += 1;
      continue;
    }

    if (trimmed.startsWith("```")) {
      const parsedCode = parseCodeBlock(index);
      blocks.push(parsedCode.html);
      index = parsedCode.nextIndex;
      continue;
    }

    if (trimmed.startsWith(">")) {
      const parsedQuote = parseBlockquote(index);
      blocks.push(parsedQuote.html);
      index = parsedQuote.nextIndex;
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      const level = headingMatch[1].length;
      blocks.push(`<h${level}${lineAttr(index)}>${renderInlineMarkdown(headingMatch[2])}</h${level}>`);
      index += 1;
      continue;
    }

    const listMarker = getListMarker(rawLine);
    if (listMarker) {
      const parsedList = parseList(index, listMarker.indent, listMarker.ordered);
      blocks.push(parsedList.html);
      index = parsedList.nextIndex;
      continue;
    }

    if (isHorizontalRule(trimmed)) {
      blocks.push(`<hr${lineAttr(index)} />`);
      index += 1;
      continue;
    }

    if (isTableStart(index)) {
      const parsedTable = parseTable(index);
      blocks.push(parsedTable.html);
      index = parsedTable.nextIndex;
      continue;
    }

    const paragraph = parseParagraph(index);
    blocks.push(paragraph.html);
    index = paragraph.nextIndex;
  }

  return blocks.join("");
}
