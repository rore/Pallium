"""Unit tests for ``semantic/reconnaissance.py`` — PR 3.

Each of the 7 reconnaissance-verb predicates is exercised across:
1. Known-ecosystem positive match (python, node, cargo, docker, etc.).
2. Unknown-ecosystem positive match (synthetic ``xyzlang``) — locks the
   spec invariant that a fresh ecosystem admits without code change.
3. Non-reconnaissance-verb rejection (the argv looks similar but the
   verb is missing / mis-shaped).

Plus deterministic-ordering tests for the dispatcher, sensitive-anchor
exclusion for ``file_read_recon``, IPv4 disqualifier for ``version_query``
semver extraction, ``test`` verb restriction to file-check flags, and
predicate purity.
"""

from __future__ import annotations

import pytest

from semantic.reconnaissance import (
    CONFIG_ANCHOR_BASENAMES,
    COMMAND_PREDICATES,
    ReconnaissanceEvent,
    SENSITIVE_ANCHOR_BASENAMES,
    detect_reconnaissance,
    is_config_anchor,
    match_cat_config_recon,
    match_command_lookup,
    match_directory_probe,
    match_file_read_recon,
    match_help_query,
    match_port_probe,
    match_version_query,
)
from tests.fixtures.operational_fact import make_bash_turn, make_turn


# ---------------------------------------------------------------------------
# Predicate 1 — command_lookup: which/where/type/command -v
# ---------------------------------------------------------------------------


class TestCommandLookup:
    def test_which_python_known_ecosystem(self):
        turn = make_bash_turn(1, "which python", output_tail="/usr/local/bin/python")
        ev = match_command_lookup(turn.commands[0], turn)
        assert ev is not None
        assert ev.verb == "command_lookup"
        assert ev.target == "python"
        assert ev.discovered_value == "/usr/local/bin/python"

    def test_where_python_windows(self):
        turn = make_bash_turn(1, "where python", output_tail="C:\\Python312\\python.exe")
        ev = match_command_lookup(turn.commands[0], turn)
        assert ev is not None
        assert ev.target == "python"

    def test_type_git(self):
        turn = make_bash_turn(1, "type git", output_tail="git is /usr/bin/git")
        ev = match_command_lookup(turn.commands[0], turn)
        assert ev is not None
        assert ev.target == "git"

    def test_command_dash_v(self):
        # POSIX ``command -v`` — argv[0]="command", argv[1]="-v",
        # target=argv[2]. Without ``-v``, ``command`` alone must NOT
        # fire (bare ``command`` bypasses shell functions, not lookup).
        turn = make_bash_turn(1, "command -v pytest", output_tail="/venv/bin/pytest")
        ev = match_command_lookup(turn.commands[0], turn)
        assert ev is not None
        assert ev.target == "pytest"

    def test_command_without_v_flag_rejected(self):
        # Bare ``command foo`` is not lookup — POSIX uses this to
        # bypass shell functions/aliases. Must not fire.
        turn = make_bash_turn(1, "command foo bar", output_tail="")
        assert match_command_lookup(turn.commands[0], turn) is None

    def test_unknown_ecosystem_xyzlang(self):
        # Locks the ecosystem-agnostic contract.
        turn = make_bash_turn(1, "which xyzlang", output_tail="/usr/local/bin/xyzlang")
        ev = match_command_lookup(turn.commands[0], turn)
        assert ev is not None
        assert ev.target == "xyzlang"
        assert ev.discovered_value == "/usr/local/bin/xyzlang"

    def test_non_lookup_command_rejected(self):
        turn = make_bash_turn(1, "python --version", output_tail="Python 3.12.4")
        assert match_command_lookup(turn.commands[0], turn) is None


# ---------------------------------------------------------------------------
# Predicate 2 — version_query: --version / -V / --ver
# ---------------------------------------------------------------------------


class TestVersionQuery:
    def test_python_version(self):
        turn = make_bash_turn(1, "python --version", output_tail="Python 3.12.4")
        ev = match_version_query(turn.commands[0], turn)
        assert ev is not None
        assert ev.verb == "version_query"
        assert ev.target == "python"
        assert ev.discovered_value == "3.12.4"

    def test_docker_version(self):
        turn = make_bash_turn(
            1, "docker --version",
            output_tail="Docker version 24.0.6, build ed223bc",
        )
        ev = match_version_query(turn.commands[0], turn)
        assert ev is not None
        assert ev.discovered_value == "24.0.6"

    def test_short_v_flag(self):
        turn = make_bash_turn(1, "node -V", output_tail="v20.10.0")
        ev = match_version_query(turn.commands[0], turn)
        assert ev is not None
        assert ev.target == "node"

    def test_unknown_ecosystem_xyzlang(self):
        turn = make_bash_turn(1, "xyzlang --version", output_tail="xyzlang 3.14.15")
        ev = match_version_query(turn.commands[0], turn)
        assert ev is not None
        assert ev.target == "xyzlang"
        assert ev.discovered_value == "3.14.15"

    def test_ipv4_in_output_not_extracted_as_version(self):
        # IPv4 disqualifier: 127.0.0.1 is 3-part-shaped but must NOT
        # become a discovered_value. Live-DB motivation.
        turn = make_bash_turn(
            1, "curl --version",
            output_tail="curl 7.88 connecting to 127.0.0.1",
        )
        ev = match_version_query(turn.commands[0], turn)
        assert ev is not None
        # Version line is "curl 7.88 connecting to 127.0.0.1" — but the
        # 3-part strict regex needs 3 numeric parts; 7.88 is 2-part and
        # 127.0.0.1 is 4-octet (rejected). No version extracted, but the
        # verb still fires with empty discovered_value.
        assert ev.discovered_value == ""

    def test_version_extraction_line_scoped(self):
        # The semver regex only fires on lines that mention "version" or
        # the command's basename — this rejects unrelated 3-part numbers
        # elsewhere in output_tail (e.g. timestamps).
        turn = make_bash_turn(
            1, "python --version",
            output_tail="12.34.56 (irrelevant timestamp)\nPython 3.12.4\n",
        )
        ev = match_version_query(turn.commands[0], turn)
        assert ev is not None
        assert ev.discovered_value == "3.12.4"

    def test_non_version_query_rejected(self):
        turn = make_bash_turn(1, "python script.py", output_tail="")
        assert match_version_query(turn.commands[0], turn) is None


# ---------------------------------------------------------------------------
# Predicate 3 — help_query: --help / -h / -?
# ---------------------------------------------------------------------------


class TestHelpQuery:
    def test_python_help(self):
        turn = make_bash_turn(1, "python --help", output_tail="usage: python ...")
        ev = match_help_query(turn.commands[0], turn)
        assert ev is not None
        assert ev.verb == "help_query"
        assert ev.target == "python"

    def test_short_h(self):
        turn = make_bash_turn(1, "git -h", output_tail="usage: git ...")
        ev = match_help_query(turn.commands[0], turn)
        assert ev is not None
        assert ev.target == "git"

    def test_unknown_ecosystem(self):
        turn = make_bash_turn(1, "xyzlang --help", output_tail="usage: xyzlang ...")
        ev = match_help_query(turn.commands[0], turn)
        assert ev is not None
        assert ev.target == "xyzlang"

    def test_no_help_flag_rejected(self):
        turn = make_bash_turn(1, "python script.py", output_tail="")
        assert match_help_query(turn.commands[0], turn) is None


# ---------------------------------------------------------------------------
# Predicate 4 — port_probe: curl -sI / wget --spider / nc -z
# ---------------------------------------------------------------------------


class TestPortProbe:
    def test_curl_head_probe(self):
        turn = make_bash_turn(1, "curl -sI http://localhost:8000/health", output_tail="HTTP/2 200")
        ev = match_port_probe(turn.commands[0], turn)
        assert ev is not None
        assert ev.verb == "port_probe"
        assert "localhost:8000" in ev.target

    def test_nc_z_probe(self):
        turn = make_bash_turn(1, "nc -z localhost 5432", output_tail="")
        ev = match_port_probe(turn.commands[0], turn)
        assert ev is not None
        assert "localhost:5432" in ev.target

    def test_wget_spider(self):
        turn = make_bash_turn(1, "wget --spider https://api.example.com:443/", output_tail="")
        ev = match_port_probe(turn.commands[0], turn)
        assert ev is not None

    def test_non_probe_curl_rejected(self):
        # Plain ``curl URL`` (no -sI/--head/-z) is a fetch, not a probe.
        turn = make_bash_turn(1, "curl http://localhost:8000/api", output_tail="{}")
        assert match_port_probe(turn.commands[0], turn) is None


# ---------------------------------------------------------------------------
# Predicate 5 — file_read_recon: Read tool events (per-turn)
# ---------------------------------------------------------------------------


class TestFileReadRecon:
    def test_read_pyproject(self):
        turn = make_turn(1, files_read=["pyproject.toml"])
        events = match_file_read_recon(turn)
        assert len(events) == 1
        assert events[0].verb == "file_read_recon"
        assert events[0].target == "pyproject.toml"

    def test_read_package_json(self):
        turn = make_turn(1, files_read=["package.json"])
        events = match_file_read_recon(turn)
        assert len(events) == 1

    def test_read_go_mod_unknown_ecosystem_locked_by_anchor_list(self):
        turn = make_turn(1, files_read=["go.mod"])
        events = match_file_read_recon(turn)
        assert len(events) == 1

    def test_read_non_anchor_file_rejected(self):
        turn = make_turn(1, files_read=["random_script.py"])
        assert match_file_read_recon(turn) == []

    def test_read_env_file_sensitive_excluded(self):
        # .env files contain secrets. Even though they are technically
        # config-anchor-shaped, the predicate must NOT emit — belt-and-
        # braces with PR 0's redaction.
        turn = make_turn(1, files_read=[".env"])
        assert match_file_read_recon(turn) == []

    def test_read_env_local_sensitive_excluded(self):
        turn = make_turn(1, files_read=[".env.local"])
        assert match_file_read_recon(turn) == []

    def test_case_insensitive_makefile(self):
        # ``Makefile`` and ``makefile`` both match — casefolded in the
        # allowlist.
        for name in ("Makefile", "makefile", "GNUmakefile"):
            turn = make_turn(1, files_read=[name])
            events = match_file_read_recon(turn)
            assert len(events) == 1, name

    def test_multiple_anchors_same_turn(self):
        turn = make_turn(1, files_read=["pyproject.toml", "package.json", ".env"])
        events = match_file_read_recon(turn)
        # Two anchors, one sensitive-excluded.
        assert len(events) == 2
        targets = {ev.target for ev in events}
        assert targets == {"pyproject.toml", "package.json"}

    def test_read_with_path_prefix(self):
        # Basename check only — repo-nested config is still an anchor.
        turn = make_turn(1, files_read=["/src/pyproject.toml"])
        events = match_file_read_recon(turn)
        assert len(events) == 1
        # target is the basename, not the full path.
        assert events[0].target == "pyproject.toml"


# ---------------------------------------------------------------------------
# Predicate 6 — cat_config_recon: cat of config-anchor file
# ---------------------------------------------------------------------------


class TestCatConfigRecon:
    def test_cat_pyproject(self):
        turn = make_bash_turn(1, "cat pyproject.toml", output_tail="[project]\nname = ...")
        ev = match_cat_config_recon(turn.commands[0], turn)
        assert ev is not None
        assert ev.verb == "cat_config_recon"
        assert ev.target == "pyproject.toml"

    def test_cat_dockerfile(self):
        turn = make_bash_turn(1, "cat Dockerfile", output_tail="FROM python:3.12")
        ev = match_cat_config_recon(turn.commands[0], turn)
        assert ev is not None

    def test_cat_non_anchor_rejected(self):
        turn = make_bash_turn(1, "cat some_script.py", output_tail="")
        assert match_cat_config_recon(turn.commands[0], turn) is None

    def test_cat_env_file_sensitive_excluded(self):
        turn = make_bash_turn(1, "cat .env", output_tail="")
        assert match_cat_config_recon(turn.commands[0], turn) is None

    def test_cat_with_path_prefix(self):
        turn = make_bash_turn(1, "cat ./src/package.json", output_tail="")
        ev = match_cat_config_recon(turn.commands[0], turn)
        assert ev is not None
        assert ev.target == "package.json"

    def test_cat_heredoc_write_rejected(self):
        # ``cat > path <<EOF`` is a redirect-write, NOT recon. The
        # tokenizer via _shell_word_head (PR 2) truncates before ``>``,
        # so ``pyproject.toml`` never appears in the argv slice.
        turn = make_bash_turn(
            1, "cat > pyproject.toml <<'EOF'\nfoo\nEOF",
            output_tail="",
        )
        assert match_cat_config_recon(turn.commands[0], turn) is None


# ---------------------------------------------------------------------------
# Predicate 7 — directory_probe: ls / stat / find / test -f
# ---------------------------------------------------------------------------


class TestDirectoryProbe:
    def test_ls_dir(self):
        turn = make_bash_turn(1, "ls src/", output_tail="foo.py\nbar.py\n")
        ev = match_directory_probe(turn.commands[0], turn)
        assert ev is not None
        assert ev.verb == "directory_probe"

    def test_stat_file(self):
        turn = make_bash_turn(1, "stat pyproject.toml", output_tail="File: pyproject.toml")
        ev = match_directory_probe(turn.commands[0], turn)
        assert ev is not None

    def test_find_files(self):
        turn = make_bash_turn(1, "find . -name '*.py'", output_tail="./foo.py\n./bar.py\n")
        ev = match_directory_probe(turn.commands[0], turn)
        assert ev is not None

    def test_test_dash_f_admitted(self):
        # ``test -f/-e/-d/-r/-w/-x <path>`` is the restricted admissible
        # form. The path is the target.
        turn = make_bash_turn(1, "test -f pyproject.toml", output_tail="")
        ev = match_directory_probe(turn.commands[0], turn)
        assert ev is not None
        assert "pyproject.toml" in ev.target

    def test_test_dash_e_admitted(self):
        turn = make_bash_turn(1, "test -e /etc/passwd", output_tail="")
        ev = match_directory_probe(turn.commands[0], turn)
        assert ev is not None

    def test_test_dollar_question_rejected(self):
        # ``test $? -eq 0`` is a shell-conditional invocation, not a
        # file check. Variable expansion as target is noise.
        turn = make_bash_turn(1, "test $? -eq 0", output_tail="")
        assert match_directory_probe(turn.commands[0], turn) is None

    def test_test_string_comparison_rejected(self):
        # ``test "$var" = "foo"`` is string comparison, not file check.
        turn = make_bash_turn(1, "test $var = foo", output_tail="")
        assert match_directory_probe(turn.commands[0], turn) is None


# ---------------------------------------------------------------------------
# Dispatcher — deterministic ordering + first-match wins
# ---------------------------------------------------------------------------


class TestDispatcher:
    def test_detect_reconnaissance_returns_events_for_all_verbs(self):
        turn = make_turn(
            1,
            commands=[
                ("which python", 0, "/usr/local/bin/python"),
                ("python --version", 0, "Python 3.12.4"),
                ("cat pyproject.toml", 0, "[project]"),
            ],
            files_read=["package.json"],
        )
        events = detect_reconnaissance(turn)
        verbs = {ev.verb for ev in events}
        assert "command_lookup" in verbs
        assert "version_query" in verbs
        assert "cat_config_recon" in verbs
        assert "file_read_recon" in verbs

    def test_first_match_wins_on_argv_collision(self):
        # ``prog --version --help`` triggers both version_query and
        # help_query. Order: command_lookup > version_query > help_query.
        # The winner must be version_query (help is unlikely to also
        # apply to the same argv but the ordering must be deterministic).
        turn = make_bash_turn(1, "python --version --help", output_tail="Python 3.12.4")
        events = detect_reconnaissance(turn)
        # Exactly one command-oriented event for this argv (first match).
        recon_events = [ev for ev in events if ev.tool == "Bash"]
        assert len(recon_events) == 1
        assert recon_events[0].verb == "version_query"

    def test_failed_command_skipped(self):
        turn = make_bash_turn(1, "which python", exit_code=1, output_tail="")
        events = detect_reconnaissance(turn)
        # Failed commands are not evidence.
        bash_events = [ev for ev in events if ev.tool == "Bash"]
        assert bash_events == []

    def test_empty_command_skipped(self):
        turn = make_turn(1, commands=[("", 0, "")])
        events = detect_reconnaissance(turn)
        assert events == []

    def test_purity_same_input_same_output(self):
        # Predicates are pure — no clock, no random, no state.
        turn = make_turn(
            1,
            commands=[("which python", 0, "/usr/bin/python")],
            files_read=["pyproject.toml"],
        )
        events1 = detect_reconnaissance(turn)
        events2 = detect_reconnaissance(turn)
        assert events1 == events2


# ---------------------------------------------------------------------------
# Config-anchor allow-list public API
# ---------------------------------------------------------------------------


class TestConfigAnchorAllowlist:
    def test_canonical_anchors_present(self):
        # The core set the plan calls out.
        for name in ("pyproject.toml", "package.json", "Makefile",
                     "docker-compose.yml", "go.mod", "Cargo.toml"):
            assert is_config_anchor(name), name

    def test_case_insensitive_lookup(self):
        assert is_config_anchor("Makefile")
        assert is_config_anchor("makefile")
        assert is_config_anchor("GNUMAKEFILE") or is_config_anchor("GNUmakefile")

    def test_sensitive_anchors_excluded_from_predicate(self):
        # SENSITIVE_ANCHOR_BASENAMES must be a proper set; can overlap
        # with CONFIG_ANCHOR_BASENAMES conceptually (e.g. .env* is
        # sensitive, not config).
        assert ".env" in SENSITIVE_ANCHOR_BASENAMES
        assert ".env.local" in SENSITIVE_ANCHOR_BASENAMES

    def test_random_file_not_anchor(self):
        assert not is_config_anchor("random_file.py")
        assert not is_config_anchor("main.rs")

    def test_command_predicates_tuple_is_immutable(self):
        # Must be a tuple, not a list — locks the deterministic order.
        assert isinstance(COMMAND_PREDICATES, tuple)
        assert len(COMMAND_PREDICATES) == 6
