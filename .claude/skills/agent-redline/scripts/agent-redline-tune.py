#!/usr/bin/env python
"""
agent-redline-tune — zone-calibration helper.

Computes per-zone-entry firing rates for a batch of past PRs against the
current policy. Used during the first weeks of shadow mode to confirm
that the policy's hypothesis matches the team's actual PR distribution.

Input formats (pick one):

    --pr-dir <dir>
        A directory of plain-text files; each file is one PR's
        newline-separated list of changed files. File name is used
        as the PR identifier. This is the format produced by:

            gh pr list --state merged --limit 30 --json number \
                --jq '.[].number' | while read n; do
              gh pr diff "$n" --name-only > "pr-$n.txt"
            done

    --pr-list <file>
        A file with one PR identifier per line plus changed files,
        separated by tabs. (Produced by some custom CI exports.)
        Format: <pr-id>\t<file>\t<file>\t...

Output: a markdown report ranking each red/watch entry by firing rate,
plus an overall verdict-distribution summary.

Usage:
    python scripts/agent-redline-tune.py --policy agent-policy.yaml \
        --pr-dir /path/to/prs

The script does not need network access; it reads the policy and the
pre-collected PR file-lists. Producing the file-lists with `gh pr diff`
is a one-time step the user runs.

This is the v0.1 manual version of frequency-aware tuning. Automated
firing-rate tracking inside the reporter is roadmap.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.reporter.reporter import (  # noqa: E402
    Diff,
    classify,
    classify_files,
    load_policy,
    matches,
)


def load_prs_from_dir(pr_dir: Path) -> dict[str, list[str]]:
    """Read each *.txt file in pr_dir as one PR's changed-files list."""
    if not pr_dir.is_dir():
        raise SystemExit(f"error: --pr-dir {pr_dir} is not a directory")
    out: dict[str, list[str]] = {}
    for f in sorted(pr_dir.iterdir()):
        if not f.is_file():
            continue
        if f.suffix not in (".txt", ".list", ""):
            continue
        files = [
            line.strip()
            for line in f.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        if files:
            out[f.stem] = files
    return out


def load_prs_from_list(pr_list: Path) -> dict[str, list[str]]:
    """Each line: <pr-id>\\t<file>\\t<file>\\t..."""
    out: dict[str, list[str]] = {}
    for line in pr_list.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        out[parts[0]] = [p for p in parts[1:] if p]
    return out


def fetch_prs(repo: str, limit: int = 30) -> dict[str, list[str]]:
    """
    Fetch the most-recent merged PRs from `repo` via `gh`, return
    {pr_id: [changed_file_paths]}. Same shape as load_prs_from_dir.

    `repo` accepts either "owner/name" (default host) or "host/owner/name";
    `gh --repo` parses the host out of the argument natively. Read-only —
    no clones, no writes to the target repo. Requires `gh` on PATH.

    Raises SystemExit on `gh pr list` failure so bootstrap can stop cleanly.
    Per-PR fetch failures are skipped so a partial sample is still useful.
    """
    list_cmd = [
        "gh", "pr", "list", "--repo", repo, "--state", "merged",
        "--limit", str(limit), "--json", "number",
    ]
    p = subprocess.run(
        list_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if p.returncode != 0:
        raise SystemExit(f"error: gh pr list failed: {p.stderr}")
    pr_list = json.loads(p.stdout)

    out: dict[str, list[str]] = {}
    for pr in pr_list:
        n = pr["number"]
        view_cmd = [
            "gh", "pr", "view", str(n), "--repo", repo, "--json", "files",
        ]
        v = subprocess.run(
            view_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if v.returncode != 0:
            # Skip a PR we can't read; the rest of the sample is still useful.
            continue
        meta = json.loads(v.stdout)
        files = [f["path"] for f in meta.get("files", []) if f.get("path")]
        if files:
            out[f"pr-{n}"] = files
    return out


def fetch_push_history(
    repo_path: Path,
    branch: str = "main",
    limit: int = 30,
) -> dict[str, list[str]]:
    """
    Walk `git log <branch>` for the most-recent `limit` commits and return
    {commit-<sha>: [changed_file_paths]} — same shape as fetch_prs, treating
    each commit as one changeset.

    For push-driven repos this is the calibration analogue of fetch_prs:
    each commit is one bootstrap-style "push to main" event. Squash-merged
    PRs naturally collapse to one commit each here, so push-mode and
    PR-mode samples are roughly comparable on volume.

    Read-only — uses `git log` and `git show --name-only`. No fetches, no
    writes. Reflects the local repo's current view of `branch`.

    Raises SystemExit on git failure so bootstrap can stop cleanly.
    Per-commit failures are skipped so a partial sample is still useful.
    """
    if not (repo_path / ".git").exists():
        raise SystemExit(f"error: {repo_path} is not a git repository")
    list_cmd = [
        "git", "-C", str(repo_path), "log", branch,
        f"--max-count={limit}", "--format=%H",
    ]
    p = subprocess.run(
        list_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if p.returncode != 0:
        raise SystemExit(f"error: git log {branch} failed: {p.stderr}")
    shas = [line.strip() for line in p.stdout.splitlines() if line.strip()]

    out: dict[str, list[str]] = {}
    for sha in shas:
        # `git show --name-only --format=` for that one commit's files only.
        show_cmd = [
            "git", "-C", str(repo_path), "show",
            "--name-only", "--format=", sha,
        ]
        v = subprocess.run(
            show_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if v.returncode != 0:
            continue
        files = [line.strip() for line in v.stdout.splitlines() if line.strip()]
        if files:
            out[f"commit-{sha[:8]}"] = files
    return out


def firing_rates(
    prs: dict[str, list[str]],
    policy: dict[str, Any],
) -> dict[str, dict[tuple[str, str], int]]:
    """
    For each zone in the policy (red / blue / watch) return a count of how
    many PRs touched at least one file matching each policy entry.

    Returned shape:
      {
        "red":   {(path, reason): count, ...},
        "blue":  {(path, reason): count, ...},
        "watch": {(path, reason): count, ...},
      }
    """
    counts: dict[str, dict[tuple[str, str], int]] = {
        "red": defaultdict(int),
        "blue": defaultdict(int),
        "watch": defaultdict(int),
    }
    zones = policy.get("zones", {}) or {}
    for zone in ("red", "blue", "watch"):
        entries = zones.get(zone, []) or []
        for pr_files in prs.values():
            for entry in entries:
                key = (entry["path"], entry.get("reason", ""))
                if any(matches(f, entry["path"]) for f in pr_files):
                    counts[zone][key] += 1
                    # Don't break — count each entry independently per PR.
    return counts


def verdict_distribution(prs: dict[str, list[str]], policy: dict[str, Any]) -> dict[str, int]:
    """Count verdict types across the PR set."""
    dist: dict[str, int] = defaultdict(int)
    for files in prs.values():
        diff = Diff(changed_files=files, files_changed=len(files), lines_changed=0)
        v = classify(policy, diff)
        dist[v.verdict] += 1
    return dict(dist)


def classify_rate(rate: float) -> str:
    """Recommendation tier for a firing rate."""
    if rate >= 0.80:
        return "TOO BROAD — most PRs touch this. Downgrade to watch or split."
    if rate >= 0.50:
        return "PROBABLY TOO BROAD — fires on a majority. Try to split the path."
    if rate >= 0.30:
        return "AMBIGUOUS — may be split-able; re-evaluate after window 2."
    if rate >= 0.05:
        return "PROBABLY RIGHT — fires on a minority of changesets."
    return "RARE — confirm this is the structural surface you wanted to flag, not dead code."


def suggest_tuning(
    counts: dict[str, dict[tuple[str, str], int]],
    n_prs: int,
    threshold_demote: float = 0.30,
) -> list[dict[str, Any]]:
    """
    Inspect firing rates and return concrete tuning suggestions.

    Returned shape (one dict per suggestion):
        {
          "path": "<glob>",
          "reason": "<from policy>",
          "current_zone": "red" | "watch" | "blue",
          "action": "demote" | "split" | "keep",
          "rate": 0.42,
          "fired": 21,
          "n_prs": 50,
          "note": "<one-line human-readable rationale>",
        }

    Currently emits one rule: red entries firing at or above `threshold_demote`
    of PRs are marked `demote` (move to watch or blue). The bootstrap skill
    presents these to the developer for confirmation; this function never
    edits the policy itself.
    """
    if n_prs <= 0:
        return []
    suggestions: list[dict[str, Any]] = []
    for (path, reason), fired in counts.get("red", {}).items():
        rate = fired / n_prs
        if rate >= threshold_demote:
            suggestions.append({
                "path": path,
                "reason": reason,
                "current_zone": "red",
                "action": "demote",
                "rate": round(rate, 2),
                "fired": fired,
                "n_prs": n_prs,
                "note": (
                    f"red rule fires on {round(rate*100)}% of PRs — "
                    f"alert-fatigue territory, consider moving to watch"
                ),
            })
    return suggestions


def render_markdown(
    counts: dict[str, dict[tuple[str, str], int]],
    dist: dict[str, int],
    n_prs: int,
) -> str:
    lines: list[str] = []
    lines.append(f"# agent-redline tuning report — {n_prs} changeset(s)")
    lines.append("")
    lines.append("Firing rate per zone entry. Red entries that fire on most changesets are alert-fatigue traps and should move to the `watch` list or split. (A changeset is a merged PR or, for push-driven repos, a single commit.)")
    lines.append("")

    # Verdict distribution
    lines.append("## Verdict distribution")
    lines.append("")
    lines.append("| Verdict | Changesets | Share |")
    lines.append("|---|---:|---:|")
    for verdict, n in sorted(dist.items(), key=lambda x: -x[1]):
        share = (n / n_prs * 100) if n_prs else 0
        lines.append(f"| {verdict} | {n} | {share:.0f}% |")
    lines.append("")

    # Per-zone tables
    for zone_label, zone_key in (("Red", "red"), ("Watch", "watch"), ("Blue", "blue")):
        entries = counts.get(zone_key, {})
        if not entries:
            continue
        lines.append(f"## {zone_label} zone — firing rates")
        lines.append("")
        lines.append("| Path | Reason | Changesets hit | Rate | Recommendation |")
        lines.append("|---|---|---:|---:|---|")
        rows = sorted(entries.items(), key=lambda kv: -kv[1])
        for (path, reason), n in rows:
            rate = (n / n_prs) if n_prs else 0.0
            rec = classify_rate(rate) if zone_key == "red" else ""
            lines.append(f"| `{path}` | {reason} | {n} | {rate*100:.0f}% | {rec} |")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Compute zone firing rates against a policy")
    p.add_argument("--policy", required=True, type=Path, help="Path to agent-policy.yaml")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--pr-dir", type=Path, help="Directory of *.txt files, one per PR")
    src.add_argument("--pr-list", type=Path, help="Single file with <pr-id>\\t<file>... per line")
    src.add_argument(
        "--repo",
        type=str,
        help="Fetch from `gh pr list --repo <repo>` directly. "
             "Format: owner/name (default host) or host/owner/name (e.g., github.example.com/owner/repo).",
    )
    src.add_argument(
        "--push-history",
        action="store_true",
        help="Calibrate against the consuming repo's git push history (each commit is one "
             "changeset). For push-driven repos. Use with --branch and optionally --repo-path.",
    )
    p.add_argument(
        "--branch",
        type=str,
        default="main",
        help="With --push-history: which branch's commits to walk (default: main).",
    )
    p.add_argument(
        "--repo-path",
        type=Path,
        default=Path.cwd(),
        help="With --push-history: filesystem path to the consuming git repo (default: cwd).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=30,
        help="With --repo: number of merged PRs to fetch. With --push-history: number of "
             "commits to walk. Default 30.",
    )
    p.add_argument("--out", type=Path, help="Write report to this file (default: stdout)")
    p.add_argument(
        "--suggest",
        action="store_true",
        help="Emit JSON tuning suggestions (rules to demote) instead of the markdown report. "
             "Used by bootstrap mode to drive a developer confirmation flow.",
    )
    args = p.parse_args(argv)

    policy = load_policy(args.policy)

    if args.pr_dir:
        prs = load_prs_from_dir(args.pr_dir)
    elif args.pr_list:
        prs = load_prs_from_list(args.pr_list)
    elif args.push_history:
        prs = fetch_push_history(args.repo_path, branch=args.branch, limit=args.limit)
    else:
        prs = fetch_prs(args.repo, limit=args.limit)

    if not prs:
        sys.stderr.write("error: no PRs found in input\n")
        return 1

    counts = firing_rates(prs, policy)
    dist = verdict_distribution(prs, policy)

    if args.suggest:
        suggestions = suggest_tuning(counts, len(prs))
        payload = {
            "n_prs": len(prs),
            "verdict_distribution": dist,
            "suggestions": suggestions,
        }
        text = json.dumps(payload, indent=2)
    else:
        text = render_markdown(counts, dist, len(prs))

    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
