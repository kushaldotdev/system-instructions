from __future__ import annotations

import importlib.util
import io
import json
import math
import os
import stat
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MERGER_PATH = ROOT / "install.py"


def load_merger():
    spec = importlib.util.spec_from_file_location("opencode_installer", MERGER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load config merger")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConfigMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.merger = load_merger()
        self.managed_agents = json.loads((ROOT / "agents.json").read_text())

    def test_jsonc_merge_preserves_unrelated_configuration(self) -> None:
        source = r'''
        {
          // A comment containing { braces } must not break parsing.
          "$schema": "https://opencode.ai/config.json",
          "instructions": ["keep.md", "/managed/instructions.md",],
          "plugin": ["example-plugin"],
          "mcp": {"demo": {"enabled": false}},
          "agent": {
            "custom": {"mode": "subagent", "prompt": "literal { value }"},
            "plan": {"model": "old/model"},
          },
        }
        '''

        parsed = self.merger.parse_jsonc(source)
        merged = self.merger.merge_config(
            parsed,
            instruction_path="/managed/instructions.md",
            managed_agents=self.managed_agents,
            lsp_enabled=None,
        )

        self.assertEqual(merged["plugin"], ["example-plugin"])
        self.assertEqual(merged["mcp"], {"demo": {"enabled": False}})
        self.assertEqual(merged["agent"]["custom"]["prompt"], "literal { value }")
        self.assertEqual(merged["agent"]["plan"], self.managed_agents["plan"])
        self.assertEqual(
            merged["instructions"].count("/managed/instructions.md"), 1
        )

    def test_merge_is_idempotent_and_lsp_is_only_changed_when_requested(self) -> None:
        original = {"lsp": {"python": {"disabled": True}}, "agent": {}}
        first = self.merger.merge_config(
            original,
            instruction_path="/managed/instructions.md",
            managed_agents=self.managed_agents,
            lsp_enabled=None,
        )
        second = self.merger.merge_config(
            first,
            instruction_path="/managed/instructions.md",
            managed_agents=self.managed_agents,
            lsp_enabled=None,
        )

        self.assertEqual(first, second)
        self.assertEqual(first["lsp"], {"python": {"disabled": True}})

    def test_atomic_write_leaves_invalid_original_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "opencode.jsonc"
            original = '{ "broken": [ }'
            config_path.write_text(original, encoding="utf-8")

            with self.assertRaises(ValueError):
                self.merger.update_config_file(
                    config_path=config_path,
                    instruction_path="/managed/instructions.md",
                    agents_path=ROOT / "agents.json",
                    lsp_enabled=None,
                )

            self.assertEqual(config_path.read_text(encoding="utf-8"), original)

    def test_non_finite_json_values_are_rejected(self) -> None:
        for source in ('{"value": NaN}', '{"value": Infinity}', '{"value": -Infinity}', '{"value": 1e400}'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                parsed = self.merger.parse_jsonc(source)
                self.assertFalse(
                    any(
                        isinstance(value, float) and not math.isfinite(value)
                        for value in parsed.values()
                    )
                )

    def test_comments_preserve_json_token_boundaries(self) -> None:
        for source in (
            '{"value": 1/* comment */2}',
            '{"value": tr/* comment */ue}',
            '{"value": 1// comment\r\n2}',
        ):
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.merger.parse_jsonc(source)

        self.assertEqual(
            self.merger.parse_jsonc(
                '{/* lead */"url":"https://example.test/a/*literal*/",// row\r\n"values":[1,/* gap */2,],}'
            ),
            {
                "url": "https://example.test/a/*literal*/",
                "values": [1, 2],
            },
        )

    @unittest.skipIf(os.name == "nt", "POSIX mode assertion")
    def test_existing_config_mode_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "opencode.jsonc"
            config_path.write_text('{"plugin": ["keep"]}', encoding="utf-8")
            config_path.chmod(0o640)

            self.merger.update_config_file(
                config_path=config_path,
                instruction_path="/managed/instructions.md",
                agents_path=ROOT / "agents.json",
                lsp_enabled=None,
            )

            self.assertEqual(stat.S_IMODE(config_path.stat().st_mode), 0o640)

    @unittest.skipIf(os.name == "nt", "POSIX symlink assertion")
    def test_config_symlink_is_rejected_without_mutating_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            external = root / "external.jsonc"
            external.write_text('{"plugin": ["keep"]}', encoding="utf-8")
            config_path = root / "opencode.jsonc"
            config_path.symlink_to(external)

            with self.assertRaises(ValueError):
                self.merger.update_config_file(
                    config_path=config_path,
                    instruction_path="/managed/instructions.md",
                    agents_path=ROOT / "agents.json",
                    lsp_enabled=None,
                )

            self.assertTrue(config_path.is_symlink())
            self.assertEqual(external.read_text(encoding="utf-8"), '{"plugin": ["keep"]}')

    def test_failed_atomic_write_removes_its_new_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "opencode.jsonc"
            original = b'{"plugin": ["keep"]}'
            config_path.write_bytes(original)

            with mock.patch.object(
                self.merger, "_atomic_write", side_effect=OSError("disk full")
            ), self.assertRaises(OSError):
                self.merger.update_config_file(
                    config_path=config_path,
                    instruction_path="/managed/instructions.md",
                    agents_path=ROOT / "agents.json",
                    lsp_enabled=None,
                )

            self.assertEqual(config_path.read_bytes(), original)
            self.assertEqual(list(Path(temp_dir).glob("*.bak-*")), [])

    def test_failed_atomic_backup_publish_leaves_no_backup_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "opencode.jsonc"
            original = b'{"plugin": ["keep"]}'
            config_path.write_bytes(original)
            real_atomic_write = self.merger._atomic_write

            def fail_backup(path, content, source_stat):
                if ".bak-" in path.name:
                    raise OSError("backup disk failure")
                return real_atomic_write(path, content, source_stat)

            with mock.patch.object(
                self.merger, "_atomic_write", side_effect=fail_backup
            ), self.assertRaises(OSError):
                self.merger.update_config_file(
                    config_path=config_path,
                    instruction_path="/managed/instructions.md",
                    agents_path=ROOT / "agents.json",
                    lsp_enabled=None,
                )

            self.assertEqual(config_path.read_bytes(), original)
            self.assertEqual(list(Path(temp_dir).glob("*.bak-*")), [])

    def test_lock_cleanup_tracks_successful_acquisition(self) -> None:
        source = MERGER_PATH.read_text(encoding="utf-8")
        self.assertIn("acquired = False", source)
        self.assertIn("if acquired:", source)

    def test_environment_plans_are_symmetric_for_windows_and_wsl(self) -> None:
        self.assertEqual(
            self.merger._environment_plan("wsl", "windows"),
            self.merger.EnvironmentPlan(False, "windows"),
        )
        self.assertEqual(
            self.merger._environment_plan("wsl", "both"),
            self.merger.EnvironmentPlan(True, "windows"),
        )
        self.assertEqual(
            self.merger._environment_plan("windows", "wsl"),
            self.merger.EnvironmentPlan(False, "wsl"),
        )
        self.assertEqual(
            self.merger._environment_plan("windows", "both"),
            self.merger.EnvironmentPlan(True, "wsl"),
        )
        with self.assertRaisesRegex(ValueError, "only available"):
            self.merger._environment_plan("linux", "windows")

    def test_windows_delegates_to_selected_wsl_distro_python(self) -> None:
        with mock.patch.object(
            self.merger, "_wsl_prefix", return_value=("wsl.exe", "-d", "Ubuntu")
        ), mock.patch.object(
            self.merger, "_run_capture", return_value="/mnt/c/project"
        ) as run_capture:
            command = self.merger._remote_install_command(
                remote_target="wsl",
                install_global=True,
                project=Path(r"C:\project"),
                lsp_enabled=False,
                distro="Ubuntu",
            )

        run_capture.assert_called_once_with(
            (
                "wsl.exe",
                "-d",
                "Ubuntu",
                "--",
                "/usr/bin/wslpath",
                "-u",
                r"C:\project",
            )
        )

        self.assertEqual(
            command,
            (
                "wsl.exe",
                "-d",
                "Ubuntu",
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
                self.merger.REMOTE_BOOTSTRAP,
                "--environment",
                "current",
                "--no-prompt",
                "--quiet-success",
                "--global",
                "--project",
                "/mnt/c/project",
                "--no-lsp",
            ),
        )

    def test_remote_bundle_is_complete_and_hash_verified(self) -> None:
        bundle = self.merger._installer_bundle()
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            expected = {"install.py", "agents.json", *self.merger.MANAGED_FILES}
            self.assertEqual(set(manifest), expected)
            for relative, digest in manifest.items():
                self.assertEqual(
                    self.merger.hashlib.sha256(archive.read(relative)).hexdigest(),
                    digest,
                )

    def test_cross_process_environment_removes_python_startup_controls(self) -> None:
        with mock.patch.dict(
            self.merger.os.environ,
            {
                "PYTHONHOME": "/hostile/home",
                "PYTHONPATH": "/hostile/path",
                "PYTHONSTARTUP": "/hostile/startup.py",
                "OPENCODE_CONFIG": "/hostile/config",
                "PATH": "/trusted/path",
            },
            clear=True,
        ):
            environment = self.merger._sanitized_environment()

        self.assertEqual(environment, {"PATH": "/trusted/path"})

    def test_default_wsl_distro_is_resolved_once_for_conversion_and_execution(self) -> None:
        with mock.patch.object(
            self.merger, "_trusted_wsl_executable", return_value="wsl.exe"
        ), mock.patch.object(
            self.merger, "_resolve_default_wsl_distro", return_value="Pinned"
        ) as resolve, mock.patch.object(
            self.merger, "_run_capture", return_value="/mnt/c/project"
        ):
            command = self.merger._remote_install_command(
                remote_target="wsl",
                install_global=False,
                project=Path(r"C:\project"),
                lsp_enabled=None,
                distro=None,
            )

        resolve.assert_called_once_with("wsl.exe")
        self.assertEqual(command[:3], ("wsl.exe", "-d", "Pinned"))

    def test_cross_environment_subprocesses_are_bounded(self) -> None:
        with mock.patch.object(self.merger.subprocess, "run") as run:
            run.return_value.stdout = "/converted/path"
            self.merger._run_capture(("converter", "argument"))

        self.assertEqual(
            run.call_args.kwargs["timeout"], self.merger.CONVERSION_TIMEOUT_SECONDS
        )

    def test_stale_shared_lock_is_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "project" / ".opencode"
            target.parent.mkdir()
            lock = target.with_name(".opencode.workflow-install-lock")
            lock.mkdir()
            (lock / "owner").write_text("dead", encoding="ascii")
            stale_time = time.time() - self.merger.LOCK_STALE_SECONDS - 1
            os.utime(lock / "owner", (stale_time, stale_time))
            os.utime(lock, (stale_time, stale_time))
            self.assertGreater(
                self.merger._lock_age(lock), self.merger.LOCK_STALE_SECONDS
            )

            with self.merger._shared_target_lock(target):
                self.assertNotEqual(
                    (lock / "owner").read_text(encoding="ascii"), "dead"
                )
            self.assertFalse(lock.exists())

    def test_active_shared_lock_is_not_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "project" / ".opencode"
            target.parent.mkdir()
            with self.merger._shared_target_lock(target):
                with self.assertRaises(TimeoutError), mock.patch.object(
                    self.merger, "LOCK_TIMEOUT_SECONDS", 0.05
                ):
                    with self.merger._shared_target_lock(target):
                        self.fail("active lock must remain exclusive")

    def test_transient_heartbeat_error_does_not_abandon_active_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(
            self.merger, "LOCK_HEARTBEAT_SECONDS", 0.01
        ), mock.patch.object(
            self.merger, "LOCK_STALE_SECONDS", 0.08
        ), mock.patch.object(
            self.merger, "LOCK_TIMEOUT_SECONDS", 0.02
        ):
            target = Path(temp_dir) / "project" / ".opencode"
            target.parent.mkdir()
            first_heartbeat = threading.Event()
            real_utime = self.merger.os.utime
            failed = False

            def transient_utime(*args, **kwargs):
                nonlocal failed
                if not failed:
                    failed = True
                    first_heartbeat.set()
                    raise OSError("transient filesystem error")
                return real_utime(*args, **kwargs)

            with mock.patch.object(
                self.merger.os, "utime", side_effect=transient_utime
            ), self.merger._shared_target_lock(target):
                self.assertTrue(first_heartbeat.wait(0.2))
                time.sleep(0.12)
                with self.assertRaises(TimeoutError):
                    with self.merger._shared_target_lock(target):
                        self.fail("active lease must survive a transient heartbeat error")

    def test_windows_lock_lease_refresh_avoids_unsupported_symlink_flag(self) -> None:
        lock = Path(r"C:\project\.opencode.workflow-install-lock")
        with mock.patch.object(self.merger.os, "name", "nt"), mock.patch.object(
            self.merger.os, "utime"
        ) as utime:
            self.merger._refresh_lock_lease(lock)

        self.assertEqual(
            utime.call_args_list,
            [mock.call(lock, None), mock.call(lock / "owner", None)],
        )

    @unittest.skipIf(os.name == "nt", "POSIX dir_fd confinement regression")
    def test_path_guard_keeps_publication_in_opened_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            authority = Path(temp_dir) / "authority"
            managed = authority / "managed"
            external = Path(temp_dir) / "external"
            managed.mkdir(parents=True)
            external.mkdir()
            with self.merger.PathGuard(authority):
                original = managed.rename(authority / "detached")
                managed.symlink_to(external, target_is_directory=True)
                with self.assertRaises((RuntimeError, ValueError)):
                    self.merger._atomic_write(managed / "escaped.txt", b"no", None)
            self.assertFalse((external / "escaped.txt").exists())
            self.assertFalse((original / "escaped.txt").exists())

    @unittest.skipUnless(
        Path("/usr/bin/wslpath").exists() and Path("/init").exists(),
        "WSL runtime fixture",
    )
    def test_wsl_runtime_symlink_is_accepted_as_trusted_wslpath(self) -> None:
        self.assertTrue(Path("/usr/bin/wslpath").is_symlink())
        self.assertEqual(Path("/usr/bin/wslpath").resolve(), Path("/init"))
        self.assertEqual(
            self.merger._trusted_wslpath_executable(), "/usr/bin/wslpath"
        )

    def test_unexpected_wslpath_symlink_target_is_rejected(self) -> None:
        with mock.patch.object(
            self.merger,
            "WSLPATH_EXECUTABLE",
            Path("/usr/bin/unexpected-wslpath"),
        ), mock.patch.object(
            self.merger.Path,
            "is_file",
            return_value=True,
        ), mock.patch.object(
            self.merger.Path,
            "is_symlink",
            return_value=True,
        ), mock.patch.object(
            self.merger.Path,
            "resolve",
            return_value=Path("/tmp/attacker"),
        ):
            with self.assertRaisesRegex(RuntimeError, "Trusted wslpath"):
                self.merger._trusted_wslpath_executable()

    def test_windows_python_uses_trusted_local_app_data_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local_app_data = Path(temp_dir)
            launcher = local_app_data / "Microsoft/WindowsApps/py.exe"
            launcher.parent.mkdir(parents=True)
            launcher.write_bytes(b"launcher")
            launcher.chmod(0o755)

            with mock.patch.object(
                self.merger,
                "_windows_local_app_data",
                return_value=local_app_data,
            ):
                invocation = self.merger._trusted_windows_python(
                    "/usr/bin/wslpath"
                )

            self.assertEqual(invocation, (str(launcher), "-3"))

    def test_windows_python_direct_fallback_does_not_receive_launcher_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local_app_data = Path(temp_dir)
            interpreter = local_app_data / "Python/bin/python.exe"
            interpreter.parent.mkdir(parents=True)
            interpreter.write_bytes(b"interpreter")
            interpreter.chmod(0o755)

            with mock.patch.object(
                self.merger,
                "_windows_local_app_data",
                return_value=local_app_data,
            ):
                invocation = self.merger._trusted_windows_python(
                    "/usr/bin/wslpath"
                )

            self.assertEqual(invocation, (str(interpreter),))

    def test_windows_opencode_discovers_npm_installed_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            executable = (
                home
                / "AppData/Roaming/npm/node_modules/opencode-ai/bin/opencode.exe"
            )
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"opencode")

            with mock.patch.object(
                self.merger.os, "name", "nt"
            ), mock.patch.object(
                self.merger.Path, "home", return_value=home
            ):
                resolved = self.merger._trusted_opencode_executable()

            self.assertEqual(resolved, str(executable))

    def test_wsl_delegates_project_to_windows_python_with_converted_paths(self) -> None:
        captures = iter((r"C:\Mapped\project",))

        with mock.patch.object(
            self.merger,
            "_trusted_wslpath_executable",
            return_value="/usr/bin/wslpath",
        ), mock.patch.object(
            self.merger, "_run_capture", side_effect=lambda _command: next(captures)
        ), mock.patch.object(
            self.merger,
            "_trusted_windows_python",
            return_value=("/mnt/c/Windows/py.exe", "-3"),
        ):
            command = self.merger._remote_install_command(
                remote_target="windows",
                install_global=False,
                project=Path("/home/user/project"),
                lsp_enabled=True,
                distro=None,
            )

        self.assertEqual(
            command,
            (
                "/mnt/c/Windows/py.exe",
                "-3",
                "-I",
                "-c",
                self.merger.REMOTE_BOOTSTRAP,
                "--environment",
                "current",
                "--no-prompt",
                "--quiet-success",
                "--project",
                r"C:\Mapped\project",
                "--lsp",
            ),
        )

    def test_interactive_environment_options_follow_host(self) -> None:
        arguments = self.merger._parse_arguments([])
        with mock.patch.object(self.merger.sys.stdin, "isatty", return_value=True), mock.patch(
            "builtins.input", return_value="b"
        ):
            self.assertEqual(
                self.merger._select_environment(arguments, "wsl"), "both"
            )
        with mock.patch.object(self.merger.sys.stdin, "isatty", return_value=True), mock.patch(
            "builtins.input", return_value="l"
        ):
            self.assertEqual(
                self.merger._select_environment(arguments, "windows"), "wsl"
            )

        no_prompt = self.merger._parse_arguments(["--no-prompt"])
        self.assertEqual(
            self.merger._select_environment(no_prompt, "windows"), "current"
        )


if __name__ == "__main__":
    unittest.main()
