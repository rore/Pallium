#!/usr/bin/env python3
"""agent-workflow tuner — read-only PR-history analyser used by bootstrap.

Two responsibilities, both fed by the same GitHub API calls:

1. **Calibration.** For each red rule in the repo's
   ``agent-redline-policy.yaml``, compute the percentage of the
   last N merged PRs that touched paths matching the rule. Rules that
   fire >70% are alert-fatigue candidates → propose demotion to
   ``watch``. Rules that fire 0% may be irrelevant → flag for human
   review.

2. **CODEOWNERS inference.** For each merged PR, fetch APPROVED
   reviewers. Cross-reference against the org's teams. The team that
   accounts for ≥50% of approvals becomes the proposed default
   codeowner. Teams with ≥30% become co-owner candidates flagged for
   human review.

Both outputs are markdown blocks suitable for direct paste into the
bootstrap proposal doc.

The script is read-only: it queries via ``gh`` (PR mode) and writes
nothing to the consuming repo. Errors during inspection (rate limit,
auth, missing repo) produce a ``## Inspection skipped: <reason>``
block instead of failing — bootstrap then falls back to its
placeholder behaviour.

Usage::

    python scripts/agent-workflow-tune.py --repo myorg/myrepo
    python scripts/agent-workflow-tune.py --repo myorg/myrepo --limit 30 --gh-host github.example.com

When ``--gh-host`` is omitted, the host is derived from
``git config --get remote.origin.url`` so the tuner targets the same
GHE / GitHub host the repository actually lives on. Pass ``--gh-host``
explicitly to override (or to query a repo outside the current
working directory).

Test mode (used by ``tests/tuner/``)::

    python scripts/agent-workflow-tune.py --mock-gh-fixture tests/tuner/fixtures/dominant-team/
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Calibration thresholds — over-firing is alert fatigue, under-firing
# is irrelevant. Numbers are conservative; bootstrap can tune later.
_OVERFIRE_THRESHOLD = 0.70
_UNDERFIRE_THRESHOLD = 0.0  # exactly zero — anything that fires at all is signal

# CODEOWNERS team thresholds — defaults are intentional; the tuner
# always discloses the percentages so the human can override.
_DEFAULT_OWNER_THRESHOLD = 0.50
_CO_OWNER_THRESHOLD = 0.30


# ---------------------------------------------------------------------------
# Paginated-response parsing
# ---------------------------------------------------------------------------


def _merge_paginated_arrays(raw: str) -> list:
    """Flatten a ``gh api --paginate --jq '[...]'`` response into one list.

    ``gh``'s ``--paginate`` concatenates the output of every page. When the
    ``--jq`` filter wraps each page in an array (``[...]``), the combined
    stdout is one JSON array **per page** — e.g. ``[1,2]\\n[3,4]`` — which
    ``json.loads`` rejects with ``JSONDecodeError: Extra data``. This decodes
    each document in turn and concatenates the arrays. Blank input → ``[]``.
    A single page (the un-paginated case) is handled as the trivial one-doc
    path, so callers can route both paginated and single-shot calls through
    it safely.
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    decoder = json.JSONDecoder()
    merged: list = []
    idx = 0
    length = len(raw)
    while idx < length:
        while idx < length and raw[idx].isspace():
            idx += 1
        if idx >= length:
            break
        value, end = decoder.raw_decode(raw, idx)
        if isinstance(value, list):
            merged.extend(value)
        else:
            merged.append(value)
        idx = end
    return merged


# ---------------------------------------------------------------------------
# Host detection
# ---------------------------------------------------------------------------


def _detect_gh_host_from_git(repo_root: Path | None = None) -> str | None:
    """Parse ``git config remote.origin.url`` and return the host.

    Bootstrap typically runs in the consuming repo, where the origin
    URL points at the same GHE host the PR history lives on. Returning
    that host as the ``GH_HOST`` default keeps the tuner portable —
    it works on github.com, GHE, or any private GitHub host without a
    hard-coded default. Returns ``None`` if origin is missing, the URL
    doesn't parse, or the host looks like the public github.com (where
    ``gh`` already defaults correctly).

    The user can still override via ``--gh-host``.
    """
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=str(repo_root) if repo_root else None,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    if not url:
        return None

    # ssh: git@host:org/repo.git
    if url.startswith("git@"):
        host = url.split("@", 1)[1].split(":", 1)[0]
    # https: https://[user@]host/org/repo[.git]
    elif "://" in url:
        rest = url.split("://", 1)[1]
        if "@" in rest:
            rest = rest.split("@", 1)[1]
        host = rest.split("/", 1)[0]
    else:
        return None

    host = host.strip().lower()
    if not host or host in ("github.com", "www.github.com"):
        # gh defaults to github.com — no need to set GH_HOST.
        return None
    return host


# ---------------------------------------------------------------------------
# gh wrapper (mockable for tests)
# ---------------------------------------------------------------------------


class GhRunner:
    """Wraps subprocess calls to ``gh`` so tests can substitute fixtures."""

    def __init__(self, gh_host: str | None = None, fixture_root: Path | None = None):
        self.gh_host = gh_host
        self.fixture_root = fixture_root
        # In-process cache for team memberships so a multi-PR run
        # doesn't repeat queries for the same user×team pair.
        self._team_member_cache: dict[str, set[str]] = {}

    def _run(self, args: list[str]) -> str:
        """Invoke ``gh`` and return stdout, raising on non-zero exit."""
        env = os.environ.copy()
        if self.gh_host:
            env["GH_HOST"] = self.gh_host
        result = subprocess.run(
            ["gh"] + args,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"gh {' '.join(args)} failed: {result.stderr.strip()}"
            )
        return result.stdout

    def list_merged_prs(self, repo: str, limit: int) -> list[dict]:
        """Return the last N merged PRs with their numbers + base-ref info."""
        if self.fixture_root:
            return _read_fixture(self.fixture_root / "merged-prs.json")
        raw = self._run([
            "pr", "list", "--state", "merged", "--limit", str(limit),
            "--repo", repo, "--json", "number,baseRefName,changedFiles",
        ])
        return json.loads(raw)

    def pr_changed_files(self, repo: str, pr_number: int) -> list[str]:
        """File paths changed in a PR."""
        if self.fixture_root:
            return _read_fixture(
                self.fixture_root / f"pr-{pr_number}-files.json"
            )
        raw = self._run([
            "api", f"repos/{repo}/pulls/{pr_number}/files",
            "--paginate", "--jq", "[.[].filename]",
        ])
        return _merge_paginated_arrays(raw)

    def pr_approvers(self, repo: str, pr_number: int) -> list[str]:
        """Approved-state reviewer logins, deduplicated."""
        if self.fixture_root:
            return _read_fixture(
                self.fixture_root / f"pr-{pr_number}-approvers.json"
            )
        raw = self._run([
            "api", f"repos/{repo}/pulls/{pr_number}/reviews",
            "--paginate",
            "--jq", '[.[] | select(.state == "APPROVED") | .user.login] | unique',
        ])
        # --paginate yields one `unique` array per page; dedupe across pages.
        return sorted(set(_merge_paginated_arrays(raw)))

    def org_teams(self, org: str) -> list[str]:
        """List of team slugs in the org."""
        if self.fixture_root:
            return _read_fixture(self.fixture_root / "org-teams.json")
        raw = self._run([
            "api", f"orgs/{org}/teams",
            "--paginate", "--jq", "[.[].slug]",
        ])
        return _merge_paginated_arrays(raw)

    def team_members(self, org: str, team_slug: str) -> set[str]:
        """Members of one team. Cached per session."""
        cache_key = f"{org}/{team_slug}"
        if cache_key in self._team_member_cache:
            return self._team_member_cache[cache_key]
        if self.fixture_root:
            raw = _read_fixture(
                self.fixture_root / f"team-{team_slug}-members.json"
            )
        else:
            raw_text = self._run([
                "api", f"orgs/{org}/teams/{team_slug}/members",
                "--paginate", "--jq", "[.[].login]",
            ])
            raw = _merge_paginated_arrays(raw_text)
        members = set(raw)
        self._team_member_cache[cache_key] = members
        return members


def _read_fixture(path: Path) -> list:
    """Read a JSON fixture file; empty list when missing.

    Tests organise fixtures by filename so a tuner run against a fixture
    directory just dispatches by name. Missing files mean "empty
    response" — matches how the real GitHub API often replies.
    """
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Policy reader — minimal, for calibration only
# ---------------------------------------------------------------------------


def _read_red_rules(policy_path: Path) -> list[dict]:
    """Extract red-zone path rules from agent-redline-policy.yaml.

    We don't import pyyaml as a hard dependency — bootstrap already
    requires it, but the tuner can ship without if the policy parsing
    is best-effort. Use the existing yaml import only when present.
    Returns ``[{path, reason, checkpoint}, ...]`` or empty list.
    """
    if not policy_path.exists():
        return []
    try:
        import yaml  # type: ignore
    except ImportError:
        return []
    try:
        policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(policy, dict):
        return []
    red = (policy.get("zones") or {}).get("red") or []
    return [r for r in red if isinstance(r, dict) and "path" in r]


def _glob_to_regex(pattern: str) -> re.Pattern:
    """Convert a shell-style glob into an anchored regex.

    Ported verbatim from the redline reporter
    (``core/agent-redline/core/reporter/reporter.py``) so the tuner's
    firing-rate calibration matches CI's zone classification exactly.
    Differs from ``fnmatch`` in two important ways:
      - ``**`` matches zero or more path components (including empty)
      - ``*`` matches anything except ``/``
    """
    i = 0
    out = ["^"]
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                # `**` — zero or more components.
                if i + 2 < len(pattern) and pattern[i + 2] == "/":
                    out.append("(?:.*/)?")
                    i += 3
                    continue
                else:
                    out.append(".*")
                    i += 2
                    continue
            else:
                out.append("[^/]*")
                i += 1
                continue
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = i + 1
            if j < len(pattern) and pattern[j] in "!^":
                j += 1
            if j < len(pattern) and pattern[j] == "]":
                j += 1
            while j < len(pattern) and pattern[j] != "]":
                j += 1
            if j >= len(pattern):
                out.append(r"\[")
            else:
                content = pattern[i + 1:j]
                if content.startswith("!"):
                    content = "^" + content[1:]
                out.append("[" + content + "]")
                i = j + 1
                continue
        elif c == ".":
            out.append(r"\.")
        elif c == "/":
            out.append("/")
        elif c in "()|+^$":
            out.append("\\" + c)
        else:
            out.append(re.escape(c))
        i += 1
    out.append("$")
    return re.compile("".join(out))


def _path_matches_rule(file_path: str, rule_glob: str) -> bool:
    """Glob-match a file path against a rule's path pattern.

    Mirrors what redline's reporter does — ``**`` spans path components,
    ``*`` stays within one. See ``_glob_to_regex``.
    """
    return bool(_glob_to_regex(rule_glob).match(file_path))


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


def calibrate(
    runner: GhRunner,
    repo: str,
    limit: int,
    policy_path: Path,
) -> list[dict]:
    """Compute firing-rate suggestions per red rule.

    Returns a list of suggestion dicts: ``[{rule, fired, total, rate,
    suggestion}, ...]``. ``suggestion`` is one of ``demote-to-watch``,
    ``review-relevance``, or ``keep-as-is``.
    """
    red_rules = _read_red_rules(policy_path)
    if not red_rules:
        return []

    prs = runner.list_merged_prs(repo, limit)
    if not prs:
        return []

    suggestions: list[dict] = []
    for rule in red_rules:
        path_glob = rule["path"]
        fired = 0
        for pr in prs:
            files = runner.pr_changed_files(repo, pr["number"])
            if any(_path_matches_rule(f, path_glob) for f in files):
                fired += 1
        rate = fired / len(prs)
        if rate > _OVERFIRE_THRESHOLD:
            suggestion = "demote-to-watch"
        elif rate == _UNDERFIRE_THRESHOLD:
            suggestion = "review-relevance"
        else:
            suggestion = "keep-as-is"
        suggestions.append({
            "rule": rule,
            "fired": fired,
            "total": len(prs),
            "rate": rate,
            "suggestion": suggestion,
        })
    return suggestions


# ---------------------------------------------------------------------------
# CODEOWNERS inference
# ---------------------------------------------------------------------------


def infer_codeowners(
    runner: GhRunner,
    repo: str,
    limit: int,
) -> dict:
    """Compute team-approval distribution from PR history.

    Returns ``{teams: [{slug, count, rate}, ...], total_approvals,
    unique_approvers, default_team, co_owner_candidates}``. Empty when
    no PRs or no team data.
    """
    org = repo.split("/", 1)[0] if "/" in repo else None
    if not org:
        return {"teams": [], "total_approvals": 0, "unique_approvers": 0,
                "default_team": None, "co_owner_candidates": []}

    prs = runner.list_merged_prs(repo, limit)
    if not prs:
        return {"teams": [], "total_approvals": 0, "unique_approvers": 0,
                "default_team": None, "co_owner_candidates": []}

    # Step 1: collect all approvers across all PRs.
    approver_counts: Counter = Counter()
    for pr in prs:
        for u in runner.pr_approvers(repo, pr["number"]):
            approver_counts[u] += 1

    total_approvals = sum(approver_counts.values())
    if total_approvals == 0:
        return {"teams": [], "total_approvals": 0, "unique_approvers": 0,
                "default_team": None, "co_owner_candidates": []}

    # Step 2: list teams in the org, fetch each team's members once.
    teams = runner.org_teams(org)
    team_members: dict[str, set[str]] = {
        slug: runner.team_members(org, slug) for slug in teams
    }

    # Step 3: map each approver to all teams they belong to. An approver
    # in multiple teams contributes their count to each — that's the
    # honest representation (we don't know which team they were
    # reviewing on behalf of).
    team_counts: Counter = Counter()
    for user, count in approver_counts.items():
        for slug, members in team_members.items():
            if user in members:
                team_counts[slug] += count

    ranked = [
        {"slug": slug, "count": count, "rate": count / total_approvals}
        for slug, count in team_counts.most_common()
    ]

    default_team = None
    co_owner_candidates: list[dict] = []
    for entry in ranked:
        if entry["rate"] >= _DEFAULT_OWNER_THRESHOLD and default_team is None:
            default_team = entry
        elif entry["rate"] >= _CO_OWNER_THRESHOLD:
            co_owner_candidates.append(entry)

    return {
        "teams": ranked,
        "total_approvals": total_approvals,
        "unique_approvers": len(approver_counts),
        "default_team": default_team,
        "co_owner_candidates": co_owner_candidates,
        "org": org,
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def render_calibration(suggestions: list[dict]) -> str:
    """Render the calibration block as markdown."""
    out: list[str] = ["## Calibration suggestions", ""]
    if not suggestions:
        out.append(
            "_No red rules in `agent-redline-policy.yaml`, or no PR "
            "history available for calibration._"
        )
        return "\n".join(out) + "\n"
    out.append(
        "Each red rule was checked against the recent merged PRs to see how "
        "often it fires. Rules firing very often (>70%) may produce alert "
        "fatigue; rules firing zero times may be misconfigured."
    )
    out.append("")
    out.append("| Path | Firing rate | Suggestion |")
    out.append("|---|---|---|")
    for s in suggestions:
        path = s["rule"]["path"]
        pct = f"{s['fired']}/{s['total']} ({int(s['rate']*100)}%)"
        if s["suggestion"] == "demote-to-watch":
            note = "Demote to `watch` (over-firing → alert fatigue)"
        elif s["suggestion"] == "review-relevance":
            note = "Review for relevance (never fired in window)"
        else:
            note = "Keep as-is"
        out.append(f"| `{path}` | {pct} | {note} |")
    out.append("")
    return "\n".join(out) + "\n"


def render_codeowners(data: dict, repo: str) -> str:
    """Render the CODEOWNERS proposal block as markdown."""
    out: list[str] = ["## Proposed `.github/CODEOWNERS`", ""]
    if not data.get("default_team") and not data.get("teams"):
        out.append(
            "_Inspection inconclusive: no team accounted for ≥30% of "
            "approvals, or no team data available. Use the placeholder "
            "below and update with your team slug before applying._"
        )
        out.append("")
        out.append("```")
        out.append("*    @TODO-codeowners-team")
        out.append("```")
        return "\n".join(out) + "\n"

    default = data["default_team"]
    org = data["org"]
    total = data["total_approvals"]
    out.append(
        f"Based on inspection of the last {total} approvals across the "
        f"recent merged PRs:"
    )
    out.append("")
    out.append("```")
    if default:
        pct = int(default["rate"] * 100)
        out.append(
            f"# Default codeowner: @{org}/{default['slug']} accounts for "
            f"{default['count']}/{total} approvals ({pct}%)."
        )
        out.append(f"*    @{org}/{default['slug']}")
    else:
        out.append("# No team meets the 50% bar; update before applying.")
        out.append("*    @TODO-codeowners-team")
    if data["co_owner_candidates"]:
        out.append("")
        out.append("# Co-owner candidates flagged for human review:")
        for c in data["co_owner_candidates"]:
            pct = int(c["rate"] * 100)
            out.append(
                f"# - @{org}/{c['slug']} — {c['count']}/{total} approvals "
                f"({pct}%). Add as co-owner for specific paths if appropriate."
            )
    out.append("```")
    out.append("")
    out.append(
        "**Apply with:** a maintainer commits this file at "
        "`.github/CODEOWNERS`, then enables `Require Code Owner review` in "
        "branch protection."
    )
    out.append("")
    return "\n".join(out) + "\n"


def render_skipped(reason: str) -> str:
    """Render the skipped block when inspection couldn't run."""
    return (
        f"## Inspection skipped: {reason}\n\n"
        f"Bootstrap should fall back to the `@TODO-*` CODEOWNERS placeholder "
        f"and document the gap in the Phase 6 self-summary.\n"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent-workflow-tune",
        description=(
            "Read-only PR-history analyser for agent-workflow bootstrap. "
            "Emits calibration suggestions for the red-zone policy and a "
            "CODEOWNERS proposal based on actual review distribution."
        ),
    )
    parser.add_argument("--repo", help="GitHub repo as <org>/<name>")
    parser.add_argument("--limit", type=int, default=30,
                        help="Number of recent merged PRs to inspect")
    parser.add_argument("--gh-host", default=None,
                        help=(
                            "GH_HOST for gh. Defaults to the host parsed "
                            "from `git config remote.origin.url`; falls "
                            "back to gh's own default when origin is "
                            "absent or points at github.com."
                        ))
    parser.add_argument("--policy", type=Path,
                        default=Path("agent-redline-policy.yaml"),
                        help="Path to agent-redline-policy.yaml (for calibration)")
    parser.add_argument("--mock-gh-fixture", type=Path, default=None,
                        help="Test-only: read responses from fixture dir")
    args = parser.parse_args(argv)

    if not args.repo and not args.mock_gh_fixture:
        parser.error("--repo is required (unless --mock-gh-fixture is given)")

    fixture_root = args.mock_gh_fixture
    if fixture_root is not None:
        # Fixture mode for tests — read the repo from the fixture dir
        # so we can run without specifying --repo.
        meta_path = fixture_root / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            args.repo = meta.get("repo", args.repo or "TEST/test-repo")
        else:
            args.repo = args.repo or "TEST/test-repo"

    if "/" not in args.repo:
        sys.stderr.write(
            f"error: --repo must be <org>/<name>, got {args.repo!r}\n"
        )
        return 2

    # Resolve gh host. Explicit --gh-host wins; otherwise derive from
    # the origin remote so a tuner run from inside a GHE clone targets
    # that GHE host without needing the flag. Fixture mode bypasses
    # both — tests run offline.
    gh_host = args.gh_host
    if gh_host is None and fixture_root is None:
        gh_host = _detect_gh_host_from_git()

    runner = GhRunner(gh_host=gh_host, fixture_root=fixture_root)

    try:
        calibration = calibrate(runner, args.repo, args.limit, args.policy)
        codeowners = infer_codeowners(runner, args.repo, args.limit)
    except RuntimeError as exc:
        sys.stdout.buffer.write(render_skipped(str(exc)).encode("utf-8"))
        return 0
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        sys.stdout.buffer.write(
            render_skipped(f"gh unavailable: {exc}").encode("utf-8")
        )
        return 0

    out = render_calibration(calibration) + "\n" + render_codeowners(
        codeowners, args.repo
    )
    sys.stdout.buffer.write(out.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
