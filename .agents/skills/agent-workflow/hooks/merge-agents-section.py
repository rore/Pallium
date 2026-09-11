#!/usr/bin/env python3
"""Reconcile the agent-workflow agents-section marker block in an instruction file.

Bootstrap appends a marker-wrapped agents-section to a consumer's AGENTS.md /
CLAUDE.md on first install. On RE-bootstrap to a newer skill version the section
text may have changed upstream; this helper refreshes ONLY the bytes between the
markers to match the current template, leaving every byte of surrounding human
prose untouched.

Behaviour:
- Markers present + enclosed content differs from the template -> rewrite only
  the enclosed span, print "updated".
- Markers present + already matches -> no write, print "no change" (idempotent).
- Markers absent -> no write, print "no markers" (the caller handles the
  first-install append; this helper never inserts markers itself).
- Malformed (end before start, a lone marker, or more than one marker
  pair) -> no write, print "malformed", exit 3 so the caller/agent notices
  rather than silently trusting it or refreshing only the first block.

The refreshed span is rewritten with the file's existing line ending
(CRLF or LF), so surrounding prose is preserved byte-for-byte.

stdlib only; safe to run repeatedly.

Usage:
    python merge-agents-section.py --file CLAUDE.md --template <agents-section.md.template>
"""
import argparse
import os
import sys

START = "<!-- agent-workflow:agents-section:start -->"
END = "<!-- agent-workflow:agents-section:end -->"


def _detect_newline(text):
    """Return the file's line ending: '\\r\\n' if any CRLF is present, else '\\n'.

    Used to build the refreshed marker block with the SAME EOL as the
    surrounding prose, so a CRLF AGENTS.md keeps its bytes instead of
    being silently rewritten to LF.
    """
    return "\r\n" if "\r\n" in text else "\n"


def reconcile(text, template_body):
    """Return (new_text, status). status in {updated,no change,no markers,malformed}."""
    start_count = text.count(START)
    end_count = text.count(END)
    if start_count == 0 and end_count == 0:
        return text, "no markers"
    # Exactly one start AND one end is the only well-formed shape. Two
    # complete blocks (2/2), a lone marker (1/0, 0/1), or any other count
    # is malformed — refreshing "the first" would leave a stale block
    # behind, which is worse than refusing.
    if start_count != 1 or end_count != 1:
        return text, "malformed"
    s = text.find(START)
    e = text.find(END)
    if e < s:
        return text, "malformed"
    before = text[:s]
    after = text[e + len(END):]
    eol = _detect_newline(text)
    # strip("\r\n") (not just "\n") so a CRLF template doesn't leave a stray
    # `\r` at the boundaries that would survive normalization below.
    body = template_body.strip("\r\n")
    # Normalise the template body to the file's EOL so the whole refreshed
    # span matches the surrounding prose byte-for-byte.
    body = body.replace("\r\n", "\n").replace("\n", eol)
    new_block = START + eol + body + eol + END
    new_text = before + new_block + after
    if new_text == text:
        return text, "no change"
    return new_text, "updated"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="instruction file (AGENTS.md/CLAUDE.md)")
    ap.add_argument("--template", required=True, help="agents-section.md.template to render into the block")
    args = ap.parse_args()

    try:
        # newline="" preserves the file's existing line endings (universal
        # newline translation would turn CRLF into LF before we ever see
        # it, defeating the byte-preservation promise).
        with open(args.file, encoding="utf-8", newline="") as fh:
            text = fh.read()
    except Exception as exc:
        sys.stderr.write("error: cannot read %s (%s)\n" % (args.file, exc))
        return 1
    try:
        with open(args.template, encoding="utf-8", newline="") as fh:
            template_body = fh.read()
    except Exception as exc:
        sys.stderr.write("error: cannot read %s (%s)\n" % (args.template, exc))
        return 1

    new_text, status = reconcile(text, template_body)
    if status == "malformed":
        sys.stderr.write("error: %s has a start or end marker but not a valid pair\n" % args.file)
        return 3
    if status in ("no change", "no markers"):
        print("%s: %s (left untouched)." % (args.file, status))
        return 0

    tmp = args.file + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(new_text)
        os.replace(tmp, args.file)  # atomic
    except Exception as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        sys.stderr.write("error: could not write %s (%s)\n" % (args.file, exc))
        return 1
    print("%s: refreshed the agents-section marker block from the template." % args.file)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        sys.stderr.write("error: %s\n" % exc)
        sys.exit(1)
