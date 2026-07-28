#!/usr/bin/env python3
"""Install the OpenCode workflow in the selected Windows/WSL environment.

Requires Python 3.10+. Cross-environment installs delegate to the target
environment's Python so paths, locking, and runtime validation remain native.
"""

from __future__ import annotations

import argparse
import contextlib
import contextvars
import copy
import hashlib
import io
import json
import math
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, NamedTuple


SCRIPT_DIR = Path(__file__).resolve().parent
AGENTS_PATH = SCRIPT_DIR / "agents.json"
LOCK_TIMEOUT_SECONDS = 30.0
LOCK_STALE_SECONDS = 10.0
LOCK_HEARTBEAT_SECONDS = 1.0
MINIMUM_PYTHON = (3, 10)
CROSS_ENV_TIMEOUT_SECONDS = 180.0
CONVERSION_TIMEOUT_SECONDS = 30.0
WSLPATH_EXECUTABLE = Path("/usr/bin/wslpath")
WSL_INIT_EXECUTABLE = Path("/init")
WINDOWS_CMD_EXECUTABLE = Path("/mnt/c/Windows/System32/cmd.exe")
MANAGED_FILES = (
    "instructions.md",
    "agents/plan.md",
    "agents/test.md",
    "agents/build.md",
    "agents/review.md",
    "agents/general.md",
    "agents/audit.md",
    "skills/exhaustive-review/SKILL.md",
)
DEBUG_COMMANDS = (
    ("debug", "config"),
    ("debug", "skill"),
    ("debug", "agent", "audit"),
    ("debug", "agent", "review"),
)
REMOTE_BOOTSTRAP = """\
import hashlib, io, json, pathlib, runpy, sys, tempfile, zipfile
payload = sys.stdin.buffer.read()
with zipfile.ZipFile(io.BytesIO(payload)) as archive, tempfile.TemporaryDirectory(prefix="opencode-installer-") as temporary:
    manifest = json.loads(archive.read("manifest.json"))
    for relative, expected in manifest.items():
        content = archive.read(relative)
        if hashlib.sha256(content).hexdigest() != expected:
            raise SystemExit(f"Installer bundle integrity failure: {relative}")
        destination = pathlib.Path(temporary, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    sys.argv = [str(pathlib.Path(temporary, "install.py")), *sys.argv[1:]]
    runpy.run_path(sys.argv[0], run_name="__main__")
"""
_ACTIVE_PATH_GUARD: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "active_path_guard", default=None
)


def _strip_jsonc_comments(source: str) -> str:
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(source):
        character = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if in_string:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue
        if character == '"':
            in_string = True
            output.append(character)
            index += 1
            continue
        if character == "/" and following == "/":
            output.append(" ")
            index += 2
            while index < len(source) and source[index] not in "\r\n":
                index += 1
            continue
        if character == "/" and following == "*":
            output.append(" ")
            index += 2
            while index + 1 < len(source):
                if source[index : index + 2] == "*/":
                    index += 2
                    break
                if source[index] in "\r\n":
                    output.append(source[index])
                index += 1
            else:
                raise ValueError("Unterminated block comment in OpenCode config")
            continue
        output.append(character)
        index += 1
    if in_string:
        raise ValueError("Unterminated string in OpenCode config")
    return "".join(output)


def _strip_trailing_commas(source: str) -> str:
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(source):
        character = source[index]
        if in_string:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue
        if character == '"':
            in_string = True
            output.append(character)
            index += 1
            continue
        if character == ",":
            lookahead = index + 1
            while lookahead < len(source) and source[lookahead].isspace():
                lookahead += 1
            if lookahead < len(source) and source[lookahead] in "]}":
                index += 1
                continue
        output.append(character)
        index += 1
    return "".join(output)


def _reject_non_finite(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite JSON numbers are not allowed")
    if isinstance(value, dict):
        for nested in value.values():
            _reject_non_finite(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_non_finite(nested)


def parse_jsonc(source: str) -> dict[str, Any]:
    """Parse JSONC without corrupting comment-like text inside strings."""
    try:
        parsed = json.loads(
            _strip_trailing_commas(_strip_jsonc_comments(source.lstrip("\ufeff"))),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"Non-finite JSON number is not allowed: {value}")
            ),
        )
    except (json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"Invalid OpenCode JSON/JSONC: {error}") from error
    if not isinstance(parsed, dict):
        raise ValueError("OpenCode config root must be an object")
    _reject_non_finite(parsed)
    return parsed


def load_agents(path: Path) -> dict[str, Any]:
    try:
        agents = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid managed agent manifest {path}: {error}") from error
    if not isinstance(agents, dict) or not agents:
        raise ValueError("Managed agent manifest must be a non-empty object")
    return agents


def merge_config(
    existing: dict[str, Any],
    *,
    instruction_path: str,
    managed_agents: dict[str, Any],
    lsp_enabled: bool | None,
) -> dict[str, Any]:
    """Return a merged copy while preserving unmanaged configuration."""
    merged = copy.deepcopy(existing)
    merged.setdefault("$schema", "https://opencode.ai/config.json")
    instructions = merged.get("instructions", [])
    if not isinstance(instructions, list) or not all(
        isinstance(item, str) for item in instructions
    ):
        raise ValueError("OpenCode 'instructions' must be an array of strings")
    merged["instructions"] = [
        item for item in instructions if item != instruction_path
    ] + [instruction_path]
    agents = merged.get("agent", {})
    if not isinstance(agents, dict):
        raise ValueError("OpenCode 'agent' must be an object")
    merged_agents = copy.deepcopy(agents)
    for name, definition in managed_agents.items():
        merged_agents[name] = copy.deepcopy(definition)
    merged["agent"] = merged_agents
    if lsp_enabled is not None:
        merged["lsp"] = lsp_enabled
    return merged


def _state_directory() -> Path:
    if os.name == "nt":
        configured = os.environ.get("LOCALAPPDATA")
        root = Path(configured) if configured else Path.home() / "AppData" / "Local"
    else:
        configured = os.environ.get("XDG_STATE_HOME")
        root = Path(configured) if configured else Path.home() / ".local" / "state"
    state_directory = root / "opencode-workflow-installer"
    state_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if state_directory.is_symlink() or not state_directory.is_dir():
        raise ValueError(f"Unsafe installer state directory: {state_directory}")
    if os.name != "nt":
        state_directory.chmod(0o700)
    return state_directory


def _lock_age(lock_directory: Path) -> float:
    timestamps = [lock_directory.stat(follow_symlinks=False).st_mtime]
    owner = lock_directory / "owner"
    try:
        timestamps.append(owner.stat(follow_symlinks=False).st_mtime)
    except FileNotFoundError:
        pass
    return max(0.0, time.time() - max(timestamps))


def _reclaim_stale_lock(lock_directory: Path) -> bool:
    try:
        if _lock_age(lock_directory) <= LOCK_STALE_SECONDS:
            return False
        stale = lock_directory.with_name(
            f"{lock_directory.name}.stale-{uuid.uuid4().hex}"
        )
        lock_directory.rename(stale)
    except (FileNotFoundError, OSError):
        return False
    shutil.rmtree(stale, ignore_errors=True)
    return True


def _refresh_lock_lease(lock_directory: Path) -> None:
    owner = lock_directory / "owner"
    if os.name == "nt":
        os.utime(lock_directory, None)
        os.utime(owner, None)
        return
    os.utime(lock_directory, None, follow_symlinks=False)
    os.utime(owner, None, follow_symlinks=False)


@contextlib.contextmanager
def _shared_target_lock(target: Path) -> Iterator[None]:
    """Serialize cooperating Windows and WSL writers to one target tree."""
    lock_directory = target.with_name(
        f".{target.name.lstrip('.')}.workflow-install-lock"
    )
    lock_directory.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    token = uuid.uuid4().hex
    while True:
        try:
            lock_directory.mkdir()
            (lock_directory / "owner").write_text(token, encoding="ascii")
            break
        except FileExistsError:
            if _is_link_or_reparse(lock_directory) or not lock_directory.is_dir():
                raise ValueError(f"Unsafe shared installer lock: {lock_directory}")
            if _reclaim_stale_lock(lock_directory):
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out acquiring shared target lock: {target}")
            time.sleep(0.05)
    stop_heartbeat = threading.Event()

    def heartbeat() -> None:
        while not stop_heartbeat.wait(LOCK_HEARTBEAT_SECONDS):
            try:
                if (lock_directory / "owner").read_text(encoding="ascii") != token:
                    return
                _refresh_lock_lease(lock_directory)
            except FileNotFoundError:
                return
            except OSError:
                continue

    heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()
    try:
        yield
    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=LOCK_HEARTBEAT_SECONDS * 2)
        try:
            if (lock_directory / "owner").read_text(encoding="ascii") == token:
                (lock_directory / "owner").unlink()
                lock_directory.rmdir()
        except FileNotFoundError:
            pass


@contextlib.contextmanager
def _file_lock(identity: str) -> Iterator[None]:
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    lock_path = _state_directory() / "locks" / f"{digest}.lock"
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_file = lock_path.open("a+b")
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"0")
                lock_file.flush()
            while True:
                try:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    acquired = True
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Timed out acquiring installer lock: {identity}")
                    time.sleep(0.05)
        else:
            import fcntl

            while True:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Timed out acquiring installer lock: {identity}")
                    time.sleep(0.05)
        yield
    finally:
        try:
            if acquired and os.name == "nt":
                import msvcrt

                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            elif acquired:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()


def _backup_path(config_path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = config_path.with_name(f"{config_path.name}.bak-{timestamp}")
    suffix = 1
    while candidate.exists():
        candidate = config_path.with_name(
            f"{config_path.name}.bak-{timestamp}-{suffix}"
        )
        suffix += 1
    return candidate


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    guard = _ACTIVE_PATH_GUARD.get()
    if guard is not None:
        os.fsync(guard.directory(path))
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class PathGuard:
    """Retain ancestor authority while managed paths are mutated."""

    def __init__(self, authority: Path) -> None:
        self.authority = Path(os.path.abspath(authority))
        self._posix_descriptors: dict[Path, int] = {}
        self._windows_handles: dict[Path, int] = {}

    def __enter__(self) -> PathGuard:
        self.directory(self.authority)
        self._token = _ACTIVE_PATH_GUARD.set(self)
        return self

    def __exit__(self, *_exception: object) -> None:
        _ACTIVE_PATH_GUARD.reset(self._token)
        for descriptor in reversed(tuple(self._posix_descriptors.values())):
            os.close(descriptor)
        if self._windows_handles:
            import ctypes

            close_handle = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
            for handle in reversed(tuple(self._windows_handles.values())):
                close_handle(handle)

    def _relative_parts(self, directory: Path) -> tuple[str, ...]:
        directory = Path(os.path.abspath(directory))
        _assert_safe_path(self.authority, directory)
        return directory.relative_to(self.authority).parts

    def _verify_posix(self, directory: Path, descriptor: int) -> None:
        opened = os.fstat(descriptor)
        current = directory.stat(follow_symlinks=False)
        if stat.S_ISLNK(current.st_mode) or (
            opened.st_dev,
            opened.st_ino,
        ) != (current.st_dev, current.st_ino):
            raise RuntimeError(f"Managed directory identity changed: {directory}")

    def _posix_directory(self, directory: Path) -> int:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        root = self._posix_descriptors.get(self.authority)
        if root is None:
            root = os.open(self.authority, flags)
            self._posix_descriptors[self.authority] = root
        current = self.authority
        descriptor = root
        self._verify_posix(current, descriptor)
        for part in self._relative_parts(directory):
            current = current / part
            existing = self._posix_descriptors.get(current)
            if existing is None:
                try:
                    os.mkdir(part, mode=0o755, dir_fd=descriptor)
                except FileExistsError:
                    pass
                existing = os.open(part, flags, dir_fd=descriptor)
                self._posix_descriptors[current] = existing
            descriptor = existing
            self._verify_posix(current, descriptor)
        return descriptor

    def _windows_directory(self, directory: Path) -> int:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        create_file.restype = wintypes.HANDLE
        current = self.authority
        paths = (current, *(current.joinpath(*self._relative_parts(directory)[:index]) for index in range(1, len(self._relative_parts(directory)) + 1)))
        for path in paths:
            if path not in self._windows_handles:
                path.mkdir(exist_ok=True)
                if _is_link_or_reparse(path):
                    raise ValueError(f"Refusing linked managed directory: {path}")
                handle = create_file(
                    str(path),
                    0x0001,
                    0x0001 | 0x0002,
                    None,
                    3,
                    0x02000000 | 0x00200000,
                    None,
                )
                if handle == wintypes.HANDLE(-1).value:
                    raise OSError(ctypes.get_last_error(), f"Cannot retain directory: {path}")
                self._windows_handles[path] = int(handle)
            if _is_link_or_reparse(path):
                raise RuntimeError(f"Managed directory identity changed: {path}")
        return self._windows_handles[directory]

    def directory(self, directory: Path) -> int:
        directory = Path(os.path.abspath(directory))
        if os.name == "nt":
            return self._windows_directory(directory)
        return self._posix_directory(directory)


def _guarded_unlink(path: Path, *, missing_ok: bool = False) -> None:
    guard = _ACTIVE_PATH_GUARD.get()
    if guard is None or os.name == "nt":
        path.unlink(missing_ok=missing_ok)
        return
    descriptor = guard.directory(path.parent)
    try:
        os.unlink(path.name, dir_fd=descriptor)
    except FileNotFoundError:
        if not missing_ok:
            raise


def _atomic_write(path: Path, content: bytes, source_stat: os.stat_result | None) -> None:
    guard = _ACTIVE_PATH_GUARD.get()
    if guard is not None:
        guard.directory(path.parent)
    if guard is not None and os.name != "nt":
        parent_descriptor = guard.directory(path.parent)
        temporary_name = f".{path.name}.{uuid.uuid4().hex}.tmp"
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=parent_descriptor,
        )
        try:
            with os.fdopen(descriptor, "wb") as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
                if source_stat is not None:
                    os.fchmod(temporary.fileno(), stat.S_IMODE(source_stat.st_mode))
                    if hasattr(os, "fchown"):
                        os.fchown(
                            temporary.fileno(), source_stat.st_uid, source_stat.st_gid
                        )
            guard.directory(path.parent)
            os.replace(
                temporary_name,
                path.name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            os.fsync(parent_descriptor)
        except Exception:
            try:
                os.unlink(temporary_name, dir_fd=parent_descriptor)
            except FileNotFoundError:
                pass
            raise
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        if source_stat is not None:
            os.chmod(temporary_path, stat.S_IMODE(source_stat.st_mode))
            if os.name != "nt" and hasattr(os, "chown"):
                temporary_stat = temporary_path.stat(follow_symlinks=False)
                if (
                    temporary_stat.st_uid != source_stat.st_uid
                    or temporary_stat.st_gid != source_stat.st_gid
                ):
                    os.chown(temporary_path, source_stat.st_uid, source_stat.st_gid)
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    except Exception:
        _guarded_unlink(temporary_path, missing_ok=True)
        raise


def update_config_file(
    *,
    config_path: Path,
    instruction_path: str,
    agents_path: Path,
    lsp_enabled: bool | None,
) -> tuple[bool, Path | None]:
    """Validate, back up, and atomically update one config file."""
    with _file_lock(f"config:{os.path.abspath(config_path)}"):
        if _is_link_or_reparse(config_path):
            raise ValueError(f"Refusing to replace linked config: {config_path}")
        existing_source: str | None = None
        existing_stat: os.stat_result | None = None
        if config_path.exists():
            existing_stat = config_path.stat(follow_symlinks=False)
            existing_source = config_path.read_text(encoding="utf-8-sig")
            existing = parse_jsonc(existing_source)
        else:
            existing = {}
        merged = merge_config(
            existing,
            instruction_path=instruction_path,
            managed_agents=load_agents(agents_path),
            lsp_enabled=lsp_enabled,
        )
        if existing_source is not None and parse_jsonc(existing_source) == merged:
            return False, None
        serialized = (
            json.dumps(merged, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        ).encode("utf-8")
        backup = None
        if config_path.exists():
            backup = _backup_path(config_path)
            try:
                _atomic_write(backup, config_path.read_bytes(), existing_stat)
            except Exception:
                _guarded_unlink(backup, missing_ok=True)
                raise
        if existing_source is not None:
            current_source = config_path.read_text(encoding="utf-8-sig")
            if current_source != existing_source:
                if backup is not None:
                    _guarded_unlink(backup, missing_ok=True)
                raise RuntimeError(
                    f"OpenCode config changed during merge; retry: {config_path}"
                )
        replaced = False
        try:
            _atomic_write(config_path, serialized, existing_stat)
            replaced = True
            parse_jsonc(config_path.read_text(encoding="utf-8"))
        except Exception:
            if replaced:
                if backup is not None and backup.exists():
                    _atomic_write(config_path, backup.read_bytes(), existing_stat)
                    _guarded_unlink(backup, missing_ok=True)
                else:
                    _guarded_unlink(config_path, missing_ok=True)
                    _fsync_directory(config_path.parent)
            if backup is not None and backup.exists():
                _guarded_unlink(backup)
            raise
        return True, backup


def _is_link_or_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(attributes & reparse_flag)


def _assert_safe_path(authority: Path, path: Path) -> None:
    authority = Path(os.path.abspath(authority))
    candidate = Path(os.path.abspath(path))
    try:
        common = Path(os.path.commonpath((authority, candidate)))
    except ValueError as error:
        raise ValueError(f"Refusing target outside selected root: {path}") from error
    if common != authority:
        raise ValueError(f"Refusing target outside selected root: {path}")
    current = candidate
    while current != authority:
        if _is_link_or_reparse(current):
            raise ValueError(f"Refusing linked managed path: {current}")
        current = current.parent


def _select_config(target: Path) -> Path:
    jsonc = target / "opencode.jsonc"
    json_file = target / "opencode.json"
    if jsonc.is_file() or _is_link_or_reparse(jsonc):
        return jsonc
    if json_file.is_file() or _is_link_or_reparse(json_file):
        return json_file
    return jsonc


class Snapshot(NamedTuple):
    content: bytes
    metadata: os.stat_result


class InstallReceipt(NamedTuple):
    target: Path
    prior: dict[Path, Snapshot | None]
    published: dict[Path, bytes | None]
    owned: tuple[Path, ...]
    backup: Path | None
    backup_content: bytes | None


def _snapshot(path: Path) -> Snapshot | None:
    if not path.is_file():
        return None
    return Snapshot(path.read_bytes(), path.stat(follow_symlinks=False))


def _restore_owned_file(
    path: Path, prior: Snapshot | None, published: bytes | None
) -> None:
    if path.exists() and published is not None and path.read_bytes() != published:
        print(f"  [warn] rollback preserved newer file: {path}", file=sys.stderr)
        return
    if path.exists():
        _guarded_unlink(path)
    if prior is not None:
        _atomic_write(path, prior.content, prior.metadata)


def _rollback_install(receipt: InstallReceipt) -> None:
    for path in reversed(receipt.owned):
        _restore_owned_file(path, receipt.prior[path], receipt.published.get(path))
    if (
        receipt.backup is not None
        and receipt.backup.exists()
        and receipt.backup_content is not None
        and receipt.backup.read_bytes() == receipt.backup_content
    ):
        _guarded_unlink(receipt.backup)
    for directory in (
        receipt.target / "skills" / "exhaustive-review",
        receipt.target / "skills",
        receipt.target / "agents",
        receipt.target,
    ):
        try:
            directory.rmdir()
        except OSError:
            pass


def _validate_runtime(config: Path, runtime_directory: Path) -> None:
    executable = _trusted_opencode_executable()
    if executable is None:
        print("  [warn] opencode not found; runtime discovery validation skipped")
        return
    installed = parse_jsonc(config.read_text(encoding="utf-8"))
    validation = {
        "$schema": "https://opencode.ai/config.json",
        "instructions": installed.get("instructions", []),
        "agent": installed.get("agent", {}),
    }
    if "lsp" in installed:
        validation["lsp"] = installed["lsp"]
    safe_config = config.with_name(f".{config.name}.validation.json")
    _atomic_write(
        safe_config,
        (json.dumps(validation, indent=2, allow_nan=False) + "\n").encode(),
        None,
    )
    environment = _sanitized_environment()
    environment["OPENCODE_CONFIG"] = str(safe_config)
    environment["OPENCODE_DISABLE_DEFAULT_PLUGINS"] = "1"
    environment["OPENCODE_PURE"] = "1"
    try:
        for arguments in DEBUG_COMMANDS:
            subprocess.run(
                (executable, *arguments),
                cwd=runtime_directory,
                env=environment,
                check=True,
                stdout=subprocess.DEVNULL,
                timeout=CROSS_ENV_TIMEOUT_SECONDS,
            )
    finally:
        _guarded_unlink(safe_config, missing_ok=True)


def _preflight_config(
    config: Path, instruction_path: str, lsp_enabled: bool | None
) -> None:
    if _is_link_or_reparse(config):
        raise ValueError(f"Refusing linked config: {config}")
    existing = (
        parse_jsonc(config.read_text(encoding="utf-8-sig"))
        if config.exists()
        else {}
    )
    merge_config(
        existing,
        instruction_path=instruction_path,
        managed_agents=load_agents(AGENTS_PATH),
        lsp_enabled=lsp_enabled,
    )


def install_to(
    target: Path,
    *,
    authority: Path,
    runtime_directory: Path,
    lsp_enabled: bool | None,
    label: str,
) -> InstallReceipt:
    target = Path(os.path.abspath(target))
    authority = Path(os.path.abspath(authority))
    instruction_path = str(target / "instructions.md")
    config = _select_config(target)
    managed_destinations = [target / relative for relative in MANAGED_FILES]
    for path in (target, config, *managed_destinations):
        _assert_safe_path(authority, path)
    _preflight_config(config, instruction_path, lsp_enabled)

    print(f"\n-- {label}\n   target: {target}")
    with (
        _shared_target_lock(target),
        _file_lock(f"target:{target}"),
        PathGuard(authority),
    ):
        for path in (target, config, *managed_destinations):
            _assert_safe_path(authority, path)
        if _select_config(target) != config:
            raise RuntimeError(f"Config selection changed; retry installation: {target}")

        prior = {path: _snapshot(path) for path in (*managed_destinations, config)}
        published: dict[Path, bytes | None] = {}
        owned: list[Path] = []
        backup: Path | None = None
        backup_content: bytes | None = None
        try:
            for relative, destination in zip(
                MANAGED_FILES, managed_destinations, strict=True
            ):
                _assert_safe_path(authority, destination)
                source = SCRIPT_DIR / relative
                source_content = source.read_bytes()
                published[destination] = source_content
                owned.append(destination)
                source_metadata = source.stat(follow_symlinks=False)
                destination_metadata = (
                    destination.stat(follow_symlinks=False)
                    if destination.exists()
                    else source_metadata
                )
                _atomic_write(destination, source_content, destination_metadata)

            changed, backup = update_config_file(
                config_path=config,
                instruction_path=instruction_path,
                agents_path=AGENTS_PATH,
                lsp_enabled=lsp_enabled,
            )
            if changed:
                published[config] = config.read_bytes()
                owned.append(config)
                if backup is not None:
                    backup_content = backup.read_bytes()
            _validate_runtime(config, runtime_directory)
        except Exception:
            _rollback_install(
                InstallReceipt(
                    target,
                    prior,
                    published,
                    tuple(owned),
                    backup,
                    backup_content,
                )
            )
            raise

        print("   [copy] instructions, six agents, exhaustive-review skill")
        print(f"   [{'update' if config in owned else 'skip'}] {config}")
        if backup is not None:
            print(f"   [backup] {backup}")
        return InstallReceipt(
            target,
            prior,
            published,
            tuple(owned),
            backup,
            backup_content,
        )


class InstallScope(NamedTuple):
    target: Path
    authority: Path
    runtime_directory: Path
    label: str


class EnvironmentPlan(NamedTuple):
    install_current: bool
    remote_target: str | None


def _preflight_scope(scope: InstallScope, lsp_enabled: bool | None) -> None:
    target = Path(os.path.abspath(scope.target))
    authority = Path(os.path.abspath(scope.authority))
    config = _select_config(target)
    for path in (
        target,
        config,
        *(target / relative for relative in MANAGED_FILES),
    ):
        _assert_safe_path(authority, path)
    _preflight_config(config, str(target / "instructions.md"), lsp_enabled)


def _required_sources() -> None:
    for relative in (*MANAGED_FILES, "agents.json"):
        source = SCRIPT_DIR / relative
        if not source.is_file():
            raise FileNotFoundError(f"Missing installer source: {source}")


def _parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install OpenCode workflow in Windows, WSL, or both"
    )
    parser.add_argument("--global", dest="install_global", action="store_true")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--both", action="store_true")
    parser.add_argument(
        "--environment",
        choices=("current", "windows", "wsl", "both"),
        help="target current environment, Windows, WSL, or both",
    )
    parser.add_argument(
        "--wsl-distro",
        help="WSL distribution for Windows-to-WSL installation (default distro if omitted)",
    )
    parser.add_argument("--no-prompt", action="store_true")
    parser.add_argument("--preflight-only", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--quiet-success", action="store_true", help=argparse.SUPPRESS)
    lsp = parser.add_mutually_exclusive_group()
    lsp.add_argument("--lsp", dest="lsp_enabled", action="store_true")
    lsp.add_argument("--no-lsp", dest="lsp_enabled", action="store_false")
    parser.set_defaults(lsp_enabled=None)
    return parser.parse_args(argv)


def _select_scopes(arguments: argparse.Namespace) -> tuple[bool, Path | None]:
    install_global = bool(arguments.install_global or arguments.both)
    project = arguments.project
    if arguments.both and project is None:
        project = Path.cwd()
    if not install_global and project is None:
        if arguments.no_prompt or not sys.stdin.isatty():
            install_global = True
        else:
            choice = input("Install globally, for project, or both? [g/p/b/q] (g): ").strip().lower()
            if choice in ("", "g"):
                install_global = True
            elif choice == "p":
                entered = input(f"Project directory ({Path.cwd()}): ").strip()
                project = Path(entered) if entered else Path.cwd()
            elif choice == "b":
                install_global = True
                entered = input(f"Project directory ({Path.cwd()}): ").strip()
                project = Path(entered) if entered else Path.cwd()
            elif choice == "q":
                raise SystemExit(0)
            else:
                raise ValueError("Invalid install scope")
    return install_global, project


def _host_environment() -> str:
    if os.name == "nt":
        return "windows"
    if os.environ.get("WSL_DISTRO_NAME"):
        return "wsl"
    try:
        version = Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        version = ""
    return "wsl" if "microsoft" in version else "linux"


def _environment_plan(host: str, requested: str) -> EnvironmentPlan:
    if requested == "current" or requested == host:
        return EnvironmentPlan(True, None)
    if host == "linux":
        raise ValueError(
            f"Environment '{requested}' is only available when running from Windows or WSL"
        )
    if requested == "both":
        return EnvironmentPlan(True, "windows" if host == "wsl" else "wsl")
    if host == "wsl" and requested == "windows":
        return EnvironmentPlan(False, "windows")
    if host == "windows" and requested == "wsl":
        return EnvironmentPlan(False, "wsl")
    raise ValueError(f"Cannot install environment '{requested}' from {host}")


def _select_environment(arguments: argparse.Namespace, host: str) -> str:
    if arguments.environment is not None:
        return str(arguments.environment)
    if arguments.no_prompt or not sys.stdin.isatty() or host == "linux":
        return "current"
    if host == "wsl":
        prompt = "Install in WSL, Windows, or both? [c/w/b/q] (c): "
        choices = {"": "current", "c": "current", "w": "windows", "b": "both"}
    else:
        prompt = "Install in Windows, WSL, or both? [c/l/b/q] (c): "
        choices = {"": "current", "c": "current", "l": "wsl", "b": "both"}
    choice = input(prompt).strip().lower()
    if choice == "q":
        raise SystemExit(0)
    try:
        return choices[choice]
    except KeyError as error:
        raise ValueError("Invalid environment selection") from error


def _sanitized_environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("PYTHON")
        and key not in {"OPENCODE_CONFIG", "OPENCODE_CONFIG_CONTENT"}
    }


def _trusted_opencode_executable() -> str | None:
    executable_name = "opencode.exe" if os.name == "nt" else "opencode"
    candidates = [
        Path.home() / ".opencode" / "bin" / executable_name,
        Path.home() / ".local" / "bin" / executable_name,
    ]
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(Path(local_app_data) / "OpenCode" / executable_name)
        roaming_app_data = os.environ.get("APPDATA")
        app_data = (
            Path(roaming_app_data)
            if roaming_app_data
            else Path.home() / "AppData" / "Roaming"
        )
        candidates.append(
            app_data
            / "npm"
            / "node_modules"
            / "opencode-ai"
            / "bin"
            / executable_name
        )
    else:
        candidates.extend(
            (Path("/usr/local/bin/opencode"), Path("/usr/bin/opencode"))
        )
    for candidate in candidates:
        if candidate.is_file() and not _is_link_or_reparse(candidate):
            return str(candidate)
    return None


def _run_capture(command: tuple[str, ...]) -> str:
    result = subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=True,
        env=_sanitized_environment(),
        timeout=CONVERSION_TIMEOUT_SECONDS,
    )
    value = result.stdout.replace("\x00", "").strip()
    if not value:
        raise RuntimeError(f"Command returned no path: {' '.join(command)}")
    return value


def _trusted_wsl_executable() -> str:
    if os.name != "nt":
        raise RuntimeError("wsl.exe can only be resolved by a Windows host")
    import ctypes

    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.WinDLL("kernel32", use_last_error=True).GetSystemWindowsDirectoryW(
        buffer, len(buffer)
    )
    if length == 0 or length >= len(buffer):
        raise OSError(ctypes.get_last_error(), "Cannot resolve Windows system directory")
    executable = Path(buffer.value) / "System32" / "wsl.exe"
    if not executable.is_file() or _is_link_or_reparse(executable):
        raise RuntimeError(f"Trusted wsl.exe not found: {executable}")
    return str(executable)


def _trusted_wslpath_executable() -> str:
    executable = WSLPATH_EXECUTABLE
    if not executable.is_file():
        raise RuntimeError(f"Trusted wslpath not found: {executable}")
    try:
        resolved = executable.resolve(strict=True)
    except OSError as error:
        raise RuntimeError(f"Trusted wslpath not found: {executable}") from error
    if executable.is_symlink() and resolved != WSL_INIT_EXECUTABLE:
        raise RuntimeError(
            f"Trusted wslpath has unexpected symlink target: {executable} -> {resolved}"
        )
    metadata = resolved.stat(follow_symlinks=False)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or getattr(metadata, "st_uid", 0) != 0
        or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or not os.access(resolved, os.X_OK)
    ):
        raise RuntimeError(f"Trusted wslpath target is unsafe: {resolved}")
    return str(executable)


def _resolve_default_wsl_distro(executable: str) -> str:
    distributions = [
        line.strip()
        for line in _run_capture((executable, "--list", "--quiet")).splitlines()
        if line.strip()
    ]
    if not distributions:
        raise RuntimeError("No WSL distribution is available")
    return distributions[0]


def _wsl_prefix(distro: str | None) -> tuple[str, ...]:
    executable = _trusted_wsl_executable()
    selected = distro or _resolve_default_wsl_distro(executable)
    return (executable, "-d", selected)


def _installer_bundle() -> bytes:
    contents: dict[str, bytes] = {"install.py": Path(__file__).read_bytes()}
    for relative in (*MANAGED_FILES, "agents.json"):
        contents[relative] = (SCRIPT_DIR / relative).read_bytes()
    manifest = {
        relative: hashlib.sha256(content).hexdigest()
        for relative, content in contents.items()
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True))
        for relative, content in contents.items():
            archive.writestr(relative, content)
    return output.getvalue()


def _windows_local_app_data(wslpath: str) -> Path:
    command = WINDOWS_CMD_EXECUTABLE
    if not command.is_file() or _is_link_or_reparse(command):
        raise RuntimeError(f"Trusted Windows command processor not found: {command}")
    windows_path = _run_capture(
        (str(command), "/d", "/s", "/c", "echo(%LOCALAPPDATA%")
    )
    converted = Path(_run_capture((wslpath, "-u", windows_path)))
    if not converted.is_dir() or _is_link_or_reparse(converted):
        raise RuntimeError(f"Unsafe Windows LocalAppData path: {converted}")
    return converted


def _trusted_windows_python(wslpath: str) -> tuple[str, ...]:
    local_app_data = _windows_local_app_data(wslpath)
    launchers = (
        local_app_data / "Microsoft" / "WindowsApps" / "py.exe",
        local_app_data / "Programs" / "Python" / "Launcher" / "py.exe",
    )
    interpreters = [local_app_data / "Python" / "bin" / "python.exe"]
    interpreters.extend(
        sorted(
            (local_app_data / "Python").glob("pythoncore-*/*python.exe"),
            reverse=True,
        )
    )
    for executable, arguments in (
        *((candidate, ("-3",)) for candidate in launchers),
        *((candidate, ()) for candidate in interpreters),
    ):
        try:
            within_local_app_data = (
                Path(os.path.commonpath((local_app_data, executable)))
                == local_app_data
            )
        except ValueError:
            within_local_app_data = False
        if (
            within_local_app_data
            and executable.is_file()
            and not _is_link_or_reparse(executable)
            and os.access(executable, os.X_OK)
        ):
            return (str(executable), *arguments)
    raise RuntimeError(
        "Windows Python 3.10+ was not found in trusted LocalAppData locations"
    )


def _convert_project_for_remote(
    project: Path | None,
    *,
    remote_target: str,
    wsl_prefix: tuple[str, ...] | None,
) -> str | None:
    if project is None:
        return None
    if remote_target == "windows":
        executable = _trusted_wslpath_executable()
        return _run_capture((executable, "-w", str(project)))
    if wsl_prefix is None:
        raise RuntimeError("Pinned WSL distribution is required for path conversion")
    return _run_capture(
        (*wsl_prefix, "--", "/usr/bin/wslpath", "-u", str(project))
    )


def _remote_install_command(
    *,
    remote_target: str,
    install_global: bool,
    project: Path | None,
    lsp_enabled: bool | None,
    distro: str | None,
) -> tuple[str, ...]:
    prefix = _wsl_prefix(distro) if remote_target == "wsl" else None
    converted_project = _convert_project_for_remote(
        project,
        remote_target=remote_target,
        wsl_prefix=prefix,
    )
    delegated_arguments = [
        "--environment",
        "current",
        "--no-prompt",
        "--quiet-success",
    ]
    if install_global:
        delegated_arguments.append("--global")
    if converted_project is not None:
        delegated_arguments.extend(("--project", converted_project))
    if lsp_enabled is True:
        delegated_arguments.append("--lsp")
    elif lsp_enabled is False:
        delegated_arguments.append("--no-lsp")

    if remote_target == "windows":
        wslpath = _trusted_wslpath_executable()
        python = _trusted_windows_python(wslpath)
        return (
            *python,
            "-I",
            "-c",
            REMOTE_BOOTSTRAP,
            *delegated_arguments,
        )

    if prefix is None:
        raise RuntimeError("Pinned WSL distribution is required")
    return (
        *prefix,
        "--",
        "/usr/bin/env",
        "-u",
        "PYTHONHOME",
        "-u",
        "PYTHONPATH",
        "-u",
        "PYTHONSTARTUP",
        "/usr/bin/python3",
        "-I",
        "-c",
        REMOTE_BOOTSTRAP,
        *delegated_arguments,
    )


def _local_scopes(
    install_global: bool,
    project: Path | None,
) -> list[InstallScope]:
    scopes: list[InstallScope] = []
    if install_global:
        home = Path.home().resolve()
        scopes.append(
            InstallScope(
                home / ".config" / "opencode",
                home,
                home,
                "Global OpenCode workflow",
            )
        )
    if project is not None:
        project = project.expanduser().resolve(strict=True)
        if not project.is_dir():
            raise ValueError(f"Invalid project directory: {project}")
        scopes.append(
            InstallScope(
                project / ".opencode",
                project,
                project,
                "Project OpenCode workflow",
            )
        )
    return scopes


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < MINIMUM_PYTHON:
        print("ERROR: Python 3.10 or newer is required", file=sys.stderr)
        return 1
    arguments = _parse_arguments(argv)
    completed: list[str] = []
    remote_attempted = False
    try:
        _required_sources()
        install_global, project = _select_scopes(arguments)
        host = _host_environment()
        requested_environment = _select_environment(arguments, host)
        environment_plan = _environment_plan(host, requested_environment)
        scopes = _local_scopes(install_global, project) if environment_plan.install_current else []
        for scope in scopes:
            _preflight_scope(scope, arguments.lsp_enabled)
        remote_command: tuple[str, ...] | None = None
        bundle: bytes | None = None
        if environment_plan.remote_target is not None:
            remote_command = _remote_install_command(
                remote_target=environment_plan.remote_target,
                install_global=install_global,
                project=project,
                lsp_enabled=arguments.lsp_enabled,
                distro=arguments.wsl_distro,
            )
            bundle = _installer_bundle()
            preflight_command = (*remote_command, "--preflight-only")
            subprocess.run(
                preflight_command,
                input=bundle,
                env=_sanitized_environment(),
                check=True,
                timeout=CROSS_ENV_TIMEOUT_SECONDS,
            )
        if arguments.preflight_only:
            return 0
        for scope in scopes:
            install_to(
                scope.target,
                authority=scope.authority,
                runtime_directory=scope.runtime_directory,
                lsp_enabled=arguments.lsp_enabled,
                label=scope.label,
            )
            completed.append(scope.label)
        if remote_command is not None and bundle is not None:
            remote_attempted = True
            subprocess.run(
                remote_command,
                input=bundle,
                env=_sanitized_environment(),
                check=True,
                timeout=CROSS_ENV_TIMEOUT_SECONDS,
            )
            completed.append(f"{environment_plan.remote_target} environment")
    except (
        OSError,
        RuntimeError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        TimeoutError,
        ValueError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        if completed:
            print(
                "Completed targets remain installed: " + ", ".join(completed),
                file=sys.stderr,
            )
            print("Fix the error and rerun; installation is idempotent.", file=sys.stderr)
        if remote_attempted:
            print(
                "Remote completion may be unknown after a transport timeout; rerun safely to reconcile it.",
                file=sys.stderr,
            )
        return 1

    if not arguments.quiet_success:
        print("\nInstalled exhaustive-review workflow in the selected environment(s).")
        print("Quit and restart OpenCode for config-time changes to take effect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
