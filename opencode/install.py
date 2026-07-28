#!/usr/bin/env python3
"""Install the OpenCode workflow in the Python host environment.

Run this file with WSL Python to install in WSL, or Windows Python to install
in Windows. Requires Python 3.10+ and never modifies another environment.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import math
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, NamedTuple


SCRIPT_DIR = Path(__file__).resolve().parent
AGENTS_PATH = SCRIPT_DIR / "agents.json"
LOCK_TIMEOUT_SECONDS = 30.0
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
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, content: bytes, source_stat: os.stat_result | None) -> None:
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
        temporary_path.unlink(missing_ok=True)
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
                backup.unlink(missing_ok=True)
                raise
        if existing_source is not None:
            current_source = config_path.read_text(encoding="utf-8-sig")
            if current_source != existing_source:
                if backup is not None:
                    backup.unlink(missing_ok=True)
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
                    os.replace(backup, config_path)
                    _fsync_directory(config_path.parent)
                else:
                    config_path.unlink(missing_ok=True)
                    _fsync_directory(config_path.parent)
            if backup is not None and backup.exists():
                backup.unlink()
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
        path.unlink()
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
        receipt.backup.unlink()
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
    executable = shutil.which("opencode")
    if executable is None:
        print("  [warn] opencode not found; runtime discovery validation skipped")
        return
    environment = os.environ.copy()
    environment["OPENCODE_CONFIG"] = str(config)
    environment["OPENCODE_DISABLE_DEFAULT_PLUGINS"] = "1"
    for arguments in DEBUG_COMMANDS:
        subprocess.run(
            (executable, *arguments),
            cwd=runtime_directory,
            env=environment,
            check=True,
            stdout=subprocess.DEVNULL,
        )


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
    with _file_lock(f"target:{target}"):
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
        description="Install OpenCode workflow in this Python environment"
    )
    parser.add_argument("--global", dest="install_global", action="store_true")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--both", action="store_true")
    parser.add_argument("--no-prompt", action="store_true")
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


def main(argv: list[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    receipts: list[InstallReceipt] = []
    try:
        _required_sources()
        install_global, project = _select_scopes(arguments)
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
        for scope in scopes:
            _preflight_scope(scope, arguments.lsp_enabled)
        for scope in scopes:
            receipts.append(
                install_to(
                    scope.target,
                    authority=scope.authority,
                    runtime_directory=scope.runtime_directory,
                    lsp_enabled=arguments.lsp_enabled,
                    label=scope.label,
                )
            )
    except (
        OSError,
        RuntimeError,
        subprocess.CalledProcessError,
        TimeoutError,
        ValueError,
    ) as error:
        for receipt in reversed(receipts):
            _rollback_install(receipt)
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("\nInstalled exhaustive-review workflow in the current environment.")
    print("Quit and restart OpenCode for config-time changes to take effect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
