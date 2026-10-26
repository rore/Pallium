"""Read-only identity from the authoritative Hermes session cwd.

Identity spelling and bounded discovery mirror Codex hooks. This packaged module
has no dependency on another host integration or the Pallium application.
"""
from __future__ import annotations
import hashlib
import os
import re
import stat
import subprocess
import time
import unicodedata
import urllib.parse
from pathlib import Path


_WORK_REF_PREFIXES = ("slice/", "feat/", "feature/", "fix/", "bug/", "chore/", "demo/")

_BASE_BRANCHES = frozenset({"main", "master", "develop", "trunk", "head"})

_WORK_REF_SECRET_RE = re.compile(
    r"(?:\bgh[pousr]_[A-Za-z0-9]{30,255}\b|"
    r"\bxox(?:[abpr]-\d{6,20}-\d{6,20}-[A-Za-z0-9]{20,64}|[a-z]-[A-Za-z0-9-]{20,255})\b|"
    r"\bsk-(?:(?:ant-api\d{2}|proj)-)?[A-Za-z0-9_-]{20,255}\b|"
    r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|"
    r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b)",
    re.IGNORECASE,
)

REDACTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"Bearer\s+\S+", re.IGNORECASE), "Bearer [REDACTED]"),
    (re.compile(r"(PASSWORD|SECRET|TOKEN|KEY|AUTH)\s*=\s*\S+", re.IGNORECASE), r"\1=[REDACTED]"),
    (re.compile(r"-----BEGIN [A-Z ]+KEY-----.*?-----END[^\n]*", re.IGNORECASE | re.DOTALL), "[REDACTED KEY BLOCK]"),
    (re.compile(r"(mongodb|postgres|mysql|redis)://\S+", re.IGNORECASE), r"\1://[REDACTED]"),
    (re.compile(r"(Authorization|Cookie):\s*.+", re.IGNORECASE), r"\1: [REDACTED]"),
]


def redact_sensitive(text: str) -> str:
    """Apply redaction patterns to strip secrets from text."""
    for pattern, replacement in REDACTION_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _windows_drive_is_local(value: str) -> bool:
    if os.name != "nt":
        return True
    drive, _ = os.path.splitdrive(value)
    if not drive:
        return False
    try:
        import ctypes

        drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive + "\\")
    except (AttributeError, OSError, ValueError):
        return False
    return drive_type not in {0, 1, 4}

def _is_local_absolute_path(value: object) -> bool:
    if not isinstance(value, str) or not value or len(value) > 4096:
        return False
    backslash = chr(92)
    normalized = value.replace("/", backslash)
    if normalized.startswith(
        (backslash * 2, backslash * 2 + "?" + backslash, backslash * 2 + "." + backslash)
    ):
        return False
    try:
        return Path(value).is_absolute() and _windows_drive_is_local(value)
    except (OSError, ValueError):
        return False

def _safe_lstat(path: Path) -> os.stat_result:
    info = path.lstat()
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if stat.S_ISLNK(info.st_mode) or (getattr(info, "st_file_attributes", 0) & reparse):
        raise OSError("unsafe reparse point")
    return info

def _safe_directory_chain(path: Path) -> None:
    for component in (*reversed(path.parents), path):
        info = _safe_lstat(component)
        if not stat.S_ISDIR(info.st_mode):
            raise OSError("unsafe path component")

def _bounded_text(path: Path, limit: int) -> str:
    before = _safe_lstat(path)
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise OSError("unsafe metadata file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        signature = lambda info: (
            info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns
        )
        if not stat.S_ISREG(opened.st_mode) or signature(opened) != signature(before):
            raise OSError("metadata file changed")
        raw = os.read(descriptor, limit + 1)
        if signature(os.fstat(descriptor)) != signature(opened):
            raise OSError("metadata file changed")
    finally:
        os.close(descriptor)
    if len(raw) > limit:
        raise OSError("metadata file too large")
    return raw.decode("utf-8", errors="strict")

def _single_line(text: str) -> str | None:
    if text.endswith("\r\n"):
        text = text[:-2]
    elif text.endswith("\n"):
        text = text[:-1]
    return None if "\r" in text or "\n" in text else text

def _valid_branch(branch: str) -> bool:
    if not branch or len(branch) > 1024 or branch.startswith(("/", ".")) or branch.endswith(("/", ".")):
        return False
    if "//" in branch or ".." in branch or "@{" in branch or "\\" in branch:
        return False
    if any(ord(char) < 32 or ord(char) == 127 or char in " ~^:?*[" for char in branch):
        return False
    return all(
        part and not part.startswith(".") and not part.endswith(".lock")
        for part in branch.split("/")
    )

def _find_repo(cwd: object) -> tuple[Path, Path] | None:
    if not _is_local_absolute_path(cwd):
        return None
    current = Path(os.path.normpath(cwd))
    try:
        _safe_directory_chain(current)
    except (OSError, ValueError):
        return None

    for _ in range(64):
        marker = current / ".git"
        try:
            marker_info = _safe_lstat(marker)
        except FileNotFoundError:
            parent = current.parent
            if parent == current:
                return None
            current = parent
            continue
        except (OSError, ValueError):
            return None

        try:
            if stat.S_ISDIR(marker_info.st_mode):
                git_dir = marker
            elif stat.S_ISREG(marker_info.st_mode):
                pointer = _single_line(_bounded_text(marker, 4096))
                if pointer is None or not pointer.startswith("gitdir: "):
                    return None
                target = pointer[len("gitdir: "):]
                if not target:
                    return None
                git_dir = Path(target)
                if not git_dir.is_absolute():
                    git_dir = marker.parent / git_dir
                git_dir = Path(os.path.abspath(os.path.normpath(git_dir)))
                if not _is_local_absolute_path(str(git_dir)):
                    return None
                _safe_directory_chain(git_dir)
            else:
                return None
            return current, git_dir
        except (OSError, UnicodeError, ValueError):
            return None
    return None

def _structural_work_refs(cwd: object) -> list[str]:
    repo = _find_repo(cwd)
    if repo is None:
        return []
    root, git_dir = repo
    head_path = git_dir / "HEAD"
    try:
        head = _single_line(_bounded_text(head_path, 4096))
        prefix = "ref: refs/heads/"
        if head is None or not head.startswith(prefix):
            return []
        branch = head[len(prefix):]
        if not _valid_branch(branch) or branch.lower() in _BASE_BRANCHES:
            return []
    except (OSError, UnicodeError, ValueError):
        return []

    refs = [f"git-branch:{branch}"]
    slug = branch
    for work_prefix in _WORK_REF_PREFIXES:
        if slug.startswith(work_prefix):
            slug = slug[len(work_prefix):]
            break
    slug = slug.replace("/", "-")
    try:
        workflow = root / ".agent-workflow"
        tasks = workflow / "tasks"
        record = tasks / f"{slug}.md"
        for directory in (workflow, tasks):
            info = _safe_lstat(directory)
            if not stat.S_ISDIR(info.st_mode):
                raise OSError("unsafe workflow path")
        record_info = _safe_lstat(record)
        if not stat.S_ISREG(record_info.st_mode):
            raise OSError("unsafe work record")
        resolved_tasks = tasks.resolve(strict=True)
        resolved_record = record.resolve(strict=True)
        if resolved_record.parent != resolved_tasks:
            raise OSError("escaping work record")
        text = _bounded_text(resolved_record, 256 * 1024)
        start = text.find("<!-- agent-workflow:start -->")
        finish = text.find("<!-- agent-workflow:end -->", start + 1)
        if start >= 0 and finish > start:
            refs.append(f"agent-workflow:{slug}")
    except (OSError, UnicodeError, ValueError):
        pass

    try:
        if _single_line(_bounded_text(head_path, 4096)) != head:
            return []
    except (OSError, UnicodeError, ValueError):
        return []
    return refs

def canonical_git_remote(url: str) -> str | None:
    if not isinstance(url, str) or not url.strip():
        return None
    raw = url.strip()
    if "\\" in raw:
        return None
    if any(
        0xD800 <= ord(char) <= 0xDFFF
        or ord(char) < 0x20
        or 0x7F <= ord(char) <= 0x9F
        for char in raw
    ):
        return None

    scp = re.fullmatch(
        r"(?P<user>[^/@:]+)@(?P<host>[^/:]+):(?P<path>.+)", raw
    )
    if scp:
        if any(char.isspace() for char in scp.group("user") + scp.group("host")):
            return None
        scheme, host, port, path = (
            "ssh",
            scp.group("host"),
            None,
            scp.group("path"),
        )
    else:
        try:
            parsed = urllib.parse.urlsplit(raw)
            if parsed.netloc.rsplit("@", 1)[-1].endswith(":"):
                return None
            if parsed.scheme not in {"https", "ssh"} or not parsed.hostname:
                return None
            if parsed.password is not None or (
                parsed.username is not None and parsed.scheme != "ssh"
            ):
                return None
            if parsed.username is not None and not re.fullmatch(
                r"[A-Za-z0-9._-]+", parsed.username
            ):
                return None
            if re.search(
                r"%(?![0-9A-Fa-f]{2})",
                parsed.path + parsed.query + parsed.fragment,
            ):
                return None
            suffix = urllib.parse.unquote(
                "&".join(part for part in (parsed.query, parsed.fragment) if part),
                errors="strict",
            )
            if suffix and (
                redact_sensitive(suffix) != suffix
                or re.search(r"(?i)(?:token|password|secret|api[_-]?key)=", suffix)
            ):
                return None
            scheme, host, port, path = (
                parsed.scheme,
                parsed.hostname,
                parsed.port,
                urllib.parse.unquote(parsed.path, errors="strict"),
            )
            port = str(port) if port is not None else None
        except (ValueError, UnicodeError):
            return None

    if (
        not host
        or not host.isascii()
        or "%" in host
        or not path
        or redact_sensitive(path) != path
        or _WORK_REF_SECRET_RE.search(path)
        or any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in path)
    ):
        return None
    try:
        if port is not None and not 1 <= int(port) <= 65535:
            return None
        default = "22" if scheme == "ssh" else "443"
    except ValueError:
        return None
    authority = host.lower()
    if port is not None and port != default:
        authority += f":{int(port)}"
    path = unicodedata.normalize("NFC", path).strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if not path or any(part in {"", ".", ".."} for part in path.split("/")):
        return None
    if host.lower() == "github.com":
        path = path.lower()
    return f"git:{authority}/{path}"

def _normalize_remote_url(url: str) -> str:
    """Normalize a git remote URL to a canonical form.

    git@github.com:user/repo.git -> github.com/user/repo
    https://github.com/user/repo.git -> github.com/user/repo
    """
    url = url.strip().lower()
    if url.startswith("git@"):
        url = url[4:]
        url = url.replace(":", "/", 1)
    elif "://" in url:
        url = url.split("://", 1)[1]
    if url.endswith(".git"):
        url = url[:-4]
    url = url.rstrip("/")
    if "@" in url.split("/")[0]:
        url = url.split("@", 1)[1]
    return url

def _path_container(cwd: str) -> str:
    norm = os.path.normcase(os.path.normpath(cwd))
    h = hashlib.sha256(norm.encode()).hexdigest()[:12]
    label = _sanitize_path_label(Path(norm).name)
    if label:
        return f"path:{label}:{h}"
    return f"path:{h}"

def _sanitize_path_label(name: str) -> str:
    """Lowercase, collapse non-[a-z0-9._-] to '_', trim, cap at 32 chars."""
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9._-]+", "_", name)
    name = name.strip("._-")
    return name[:32]

def _git(cwd: str, args: list[str], deadline: float) -> str | None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError("project resolution timed out")
    # Inherited Git overrides must never select another repository or config.
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0")
    try:
        result = subprocess.run(["git", *args], cwd=cwd, env=env,
            capture_output=True, text=True, encoding="utf-8", errors="strict",
            timeout=min(1.0, remaining))
    except subprocess.TimeoutExpired as error:
        raise ValueError("project resolution timed out") from error
    except (OSError, UnicodeError) as error:
        raise ValueError("Git project resolution unavailable") from error
    if len(result.stdout) > 64 * 1024:
        raise ValueError("Git project metadata exceeds its bound")
    return result.stdout.strip() if result.returncode == 0 else None


def resolve_scope(cwd: object, previous: dict | None = None,
                  actor_override: str | None = None) -> dict:
    """Propose a binding; the caller owns Relay admission and persistence.

    Invalid/stale/remote cwd raises ValueError. Valid transient non-Git cwd
    retains the prior pin until a Git project is recognized. No process cwd,
    network, persistent cache or write supplies authority.
    """
    if not _is_local_absolute_path(cwd):
        raise ValueError("a local absolute session cwd is required")
    current = os.path.normpath(cwd)
    try:
        _safe_directory_chain(Path(current))
    except (OSError, ValueError) as error:
        raise ValueError("session cwd must be an existing local directory without reparse points") from error
    previous = previous if isinstance(previous, dict) else {}
    pinned = previous.get("container_ref")
    pinned = pinned if isinstance(pinned, str) and pinned else None
    deadline = time.monotonic() + 3.0
    repository_ref = None
    container = _path_container(current)
    if _find_repo(current) is not None:
        remote = _git(current, ["remote", "get-url", "origin"], deadline)
        if remote:
            if "?" in remote or "#" in remote:
                raise ValueError("origin is not a safe supported Git remote")
            repository_ref = canonical_git_remote(remote)
            # Keep legacy spelling only after validating credentials and secrets.
            if repository_ref is None:
                raise ValueError("origin is not a safe supported Git remote")
            container = "git:" + _normalize_remote_url(remote)
        else:
            roots = _git(current, ["rev-list", "--max-parents=0", "HEAD"], deadline)
            root = roots.splitlines()[0] if roots else ""
            if re.fullmatch(r"[0-9a-fA-F]{40,64}", root):
                container = "repo:" + root[:12]
                repository_ref = "repo:" + root.lower()
    transient = pinned is not None and container.startswith("path:")
    if transient:
        container = pinned
    override = actor_override if isinstance(actor_override, str) else ""
    actor = override.strip() or os.environ.get("PALLIUM_HOOK_ACTOR_REF", "").strip()
    if not actor:
        actor = _git(current, ["config", "user.name"], deadline) or "local"
    if (not isinstance(actor, str) or actor != actor.strip() or not 0 < len(actor) <= 255
            or not actor.isprintable()):
        raise ValueError("project actor identity is not supported")
    if (not isinstance(container, str) or container != container.strip() or not 0 < len(container) <= 512
            or not container.isprintable()):
        raise ValueError("project container identity is not supported")
    refs = []
    if repository_ref:
        refs = [{"scope_ref": f"roadmap:v1:{repository_ref}#roadmap" if ref.startswith("agent-workflow:") else repository_ref,
                 "local_ref": ref} for ref in _structural_work_refs(current)]
    return {"cwd": current, "container_ref": container, "actor_ref": actor, "work_refs": refs}
