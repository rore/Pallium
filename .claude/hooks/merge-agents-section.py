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
- Malformed (end before start, only one marker) -> no write, print "malformed",
  exit 3 so the caller/agent notices rather than silently trusting it.

stdlib only; safe to run repeatedly.

Usage:
    python merge-agents-section.py --file CLAUDE.md --template <agents-section.md.template>
"""
import argparse
import os
import sys

START = "<!-- agent-workflow:agents-section:start -->"
END = "<!-- agent-workflow:agents-section:end -->"


def reconcile(text, template_body):
    """Return (new_text, status). status in {updated,no change,no markers,malformed}."""
    s = text.find(START)
    e = text.find(END)
    if s == -1 and e == -1:
        return text, "no markers"
    if s == -1 or e == -1 or e < s:
        return text, "malformed"
    before = text[:s]
    after = text[e + len(END):]
    body = template_body.strip("\n")
    new_block = START + "\n" + body + "\n" + END
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
        with open(args.file, encoding="utf-8") as fh:
            text = fh.read()
    except Exception as exc:
        sys.stderr.write("error: cannot read %s (%s)\n" % (args.file, exc))
        return 1
    try:
        with open(args.template, encoding="utf-8") as fh:
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
