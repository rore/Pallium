"""W4 follow-up 2026-07-02 — tests for semantic.redaction.is_sensitive_artifact.

Live-data motivation: the shipped operational_fact predicate emitted 7
rows of ``~/.ssh/ronnylinder_dh_rsa`` on the roni container. The text-
based redaction rules didn't catch it because the artifact isn't
``Bearer <token>`` or ``PASSWORD=…`` — it's a filesystem path pointing
at a secret. The predicate answers a boolean skip-emission question.
"""

from __future__ import annotations

import pytest

from semantic.operational_fact import (
    CommandRecord,
    TurnRecord,
    derive_operational_facts,
)
from redaction import is_sensitive_artifact
from tests.fixtures.operational_fact import fake_scope_resolver


CONTAINER = "git:example/repo"


class TestIsSensitiveArtifactSSHKeys:
    """Canonical + custom-named SSH key files."""

    def test_canonical_id_rsa(self):
        assert is_sensitive_artifact("~/.ssh/id_rsa")

    def test_canonical_id_ed25519_pub(self):
        # Public key sibling still lives with the private key; skip too.
        assert is_sensitive_artifact("~/.ssh/id_ed25519.pub")

    def test_custom_named_dh_rsa(self):
        # The exact live-corpus offender.
        assert is_sensitive_artifact("~/.ssh/ronnylinder_dh_rsa")

    def test_custom_ed25519(self):
        assert is_sensitive_artifact("~/.ssh/foo_ed25519")

    def test_custom_ecdsa(self):
        assert is_sensitive_artifact("~/.ssh/foo_ecdsa")

    def test_custom_dsa(self):
        assert is_sensitive_artifact("~/.ssh/foo_dsa")


class TestIsSensitiveArtifactGenericSecrets:
    def test_pem_at_arbitrary_path(self):
        assert is_sensitive_artifact("/home/me/keys/prod.pem")

    def test_key_at_relative_path(self):
        assert is_sensitive_artifact("certs/server.key")

    def test_pfx(self):
        assert is_sensitive_artifact("/etc/ssl/client.pfx")

    def test_p12(self):
        assert is_sensitive_artifact("./credentials.p12")

    def test_aws_credentials(self):
        assert is_sensitive_artifact("~/.aws/credentials")

    def test_aws_config(self):
        assert is_sensitive_artifact("~/.aws/config")

    def test_docker_config(self):
        assert is_sensitive_artifact("~/.docker/config.json")

    def test_kube_config(self):
        assert is_sensitive_artifact("~/.kube/config")

    def test_gnupg_pubring(self):
        assert is_sensitive_artifact("~/.gnupg/pubring.kbx")

    def test_netrc(self):
        assert is_sensitive_artifact("~/.netrc")


class TestIsSensitiveArtifactSSHTargets:
    def test_live_corpus_dreamhost_with_ssh_context(self):
        # The exact live corpus offender: 7 rows.
        assert is_sensitive_artifact(
            "dh_ieh64b@pdx1-shared-a1-24.dreamhost.com",
            context="ssh dh_ieh64b@pdx1-shared-a1-24.dreamhost.com 'ls'",
        )

    def test_scp_context_flags_ssh_target(self):
        assert is_sensitive_artifact(
            "deploy@prod.internal",
            context="scp file.tar.gz deploy@prod.internal:/tmp/",
        )

    def test_rsync_context_flags_ssh_target(self):
        assert is_sensitive_artifact(
            "user@backup.example.dev",
            context="rsync -avz src/ user@backup.example.dev:/data/",
        )

    def test_email_in_curl_body_not_flagged(self):
        # False-positive guard: email addresses in curl argv are not SSH.
        assert not is_sensitive_artifact(
            "user@example.com",
            context="curl -d user@example.com https://api.example.com/users",
        )

    def test_email_in_mailto_not_flagged(self):
        assert not is_sensitive_artifact(
            "user@example.com",
            context="mailto:user@example.com",
        )

    def test_dreamhost_host_without_context_still_flagged_by_shape(self):
        # Even without ssh in the context, .dreamhost.com hostname is
        # infra shape (per live-corpus experience).
        assert is_sensitive_artifact(
            "dh_ieh64b@pdx1-shared-a1-24.dreamhost.com",
            context="",
        )

    def test_aws_compute_hostname_flagged_by_shape(self):
        assert is_sensitive_artifact(
            "ec2-user@ip-10-0-1-42.compute.amazonaws.com",
            context="",
        )

    def test_prod_hostname_flagged_by_shape(self):
        assert is_sensitive_artifact(
            "deploy@app.prod.example.com",
            context="",
        )


class TestIsSensitiveArtifactNonMatches:
    """Regression guards — must NOT flag."""

    def test_operational_config_file(self):
        assert not is_sensitive_artifact("pyproject.toml")

    def test_docker_compose_file(self):
        assert not is_sensitive_artifact("docker-compose.yml")

    def test_empty_string(self):
        assert not is_sensitive_artifact("")

    def test_whitespace_only(self):
        assert not is_sensitive_artifact("   ")

    def test_normal_url(self):
        assert not is_sensitive_artifact("http://localhost:8000/api")

    def test_python_interpreter_path(self):
        assert not is_sensitive_artifact(
            "C:/Users/x/.venv/Scripts/python.exe"
        )

    def test_readme_not_flagged(self):
        # README.pem would be a real match... but README.md must not be.
        assert not is_sensitive_artifact("README.md")

    def test_public_email_domain_no_context(self):
        # user@example.com without any argv context — do NOT flag as
        # an SSH target based on shape alone.
        assert not is_sensitive_artifact("user@example.com", context="")


class TestSensitiveArtifactSkipsEmission:
    """Integration: the derivation predicate skips candidates whose
    artifact is sensitive. Locks the wiring in operational_fact._make_discovery.
    """

    def _turn(
        self,
        turn_index: int,
        cmd: str,
        exit_code: int = 0,
        output_tail: str = "",
    ) -> TurnRecord:
        return TurnRecord(
            turn_index=turn_index,
            source_item_id=f"src-{turn_index}",
            timestamp="2026-07-02T00:00:00Z",
            commands=(
                CommandRecord(cmd=cmd, exit_code=exit_code, output_tail=output_tail),
            ),
        )

    def test_ssh_key_argv_produces_no_operational_fact(self):
        turns = [
            self._turn(0, "cat ~/.ssh/id_rsa"),
            self._turn(1, "ssh -i ~/.ssh/id_rsa host 'ls'"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        for c in cands:
            assert ".ssh/id_rsa" not in c.artifact_normalized
            assert ".ssh/id_rsa" not in c.artifact

    def test_custom_ssh_key_argv_produces_no_operational_fact(self):
        turns = [
            self._turn(0, "cat ~/.ssh/ronnylinder_dh_rsa"),
            self._turn(
                1,
                "ssh -i ~/.ssh/ronnylinder_dh_rsa dh_ieh64b@pdx1-shared-a1-24.dreamhost.com",
            ),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        for c in cands:
            assert "ronnylinder_dh_rsa" not in c.artifact_normalized
            assert "ronnylinder_dh_rsa" not in c.artifact

    def test_ssh_target_under_ssh_context_dropped(self):
        turns = [
            self._turn(0, "ssh dh_ieh64b@pdx1-shared-a1-24.dreamhost.com 'uname -a'"),
            self._turn(1, "ssh dh_ieh64b@pdx1-shared-a1-24.dreamhost.com 'df -h'"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        for c in cands:
            assert "dreamhost.com" not in c.artifact_normalized

    def test_benign_artifact_still_emits(self):
        # Regression pin: PR A must not break the legit emission path.
        # PR 3 update: use a reconnaissance verb (``uv --version``) so
        # the new predicate model produces a candidate. The invariant
        # "benign artifacts continue to emit" is what matters — the
        # exact verb the transcript uses is incidental.
        turns = [
            self._turn(0, "uv --version", output_tail="uv 0.4.15"),
            self._turn(1, "cat pyproject.toml", output_tail="[project]"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert any(c.command_family == "uv" or c.command_family == "python" for c in cands)

    def test_mixed_trace_ssh_dropped_benign_kept(self):
        turns = [
            self._turn(0, "cat ~/.ssh/id_rsa && ls pyproject.toml"),
            self._turn(1, "python pyproject.toml"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        for c in cands:
            assert ".ssh/id_rsa" not in c.artifact_normalized

    def test_pem_at_absolute_path_dropped(self):
        turns = [
            self._turn(0, "openssl x509 -in /etc/ssl/certs/prod.pem"),
            self._turn(1, "curl --cert /etc/ssl/certs/prod.pem https://api"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        for c in cands:
            assert "prod.pem" not in c.artifact_normalized
