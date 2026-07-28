from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]


class PythonInstallerTests(unittest.TestCase):
    def run_installer(
        self,
        home: Path,
        *arguments: str,
        cwd: Path | None = None,
        fail_debug: str | None = None,
        fail_debug_config: Path | None = None,
        extra_environment: Mapping[str, str] | None = None,
        stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["HOME"] = str(home)
        fake_bin = home / ".opencode" / "bin"
        fake_bin.mkdir(parents=True, exist_ok=True)
        fake_opencode = fake_bin / "opencode"
        fake_opencode.write_text(
            '#!/usr/bin/env sh\n'
            'printf "%s\\n" "$*" >> "$HOME/opencode-calls.txt"\n'
            'if [ -n "${FAIL_DEBUG:-}" ] && [ "$*" = "$FAIL_DEBUG" ]; then '
            'if [ -z "${FAIL_DEBUG_CONFIG:-}" ]; then exit 23; fi; '
            'case "${OPENCODE_CONFIG:-}" in "$FAIL_DEBUG_CONFIG"*) exit 23;; esac; fi\n',
            encoding="utf-8",
        )
        fake_opencode.chmod(0o755)
        environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
        if fail_debug is not None:
            environment["FAIL_DEBUG"] = fail_debug
        if fail_debug_config is not None:
            environment["FAIL_DEBUG_CONFIG"] = str(fail_debug_config)
        if extra_environment is not None:
            environment.update(extra_environment)
        command = [sys.executable, str(ROOT / "install.py"), *arguments]
        if "FAKE_WINDOWS_HOME" in environment:
            bootstrap = (
                "import importlib.util, os, pathlib, sys; "
                f"p=pathlib.Path({str(ROOT / 'install.py')!r}); "
                "s=importlib.util.spec_from_file_location('workflow_installer', p); "
                "m=importlib.util.module_from_spec(s); sys.modules[s.name]=m; "
                "s.loader.exec_module(m); "
                "m._trusted_wslpath_executable=lambda: os.environ['FAKE_WSLPATH']; "
                "m._trusted_windows_python=lambda _w: (os.environ['FAKE_WINDOWS_PYTHON'], '-3'); "
                "raise SystemExit(m.main(sys.argv[1:]))"
            )
            environment["FAKE_WINDOWS_PYTHON"] = str(home / "test-bin" / "py.exe")
            environment["FAKE_WSLPATH"] = str(home / "test-bin" / "wslpath")
            command = [sys.executable, "-c", bootstrap, *arguments]
        return subprocess.run(
            command,
            cwd=cwd or ROOT,
            env=environment,
            check=False,
            text=True,
            input=stdin,
            capture_output=True,
            timeout=60,
        )

    def add_fake_wsl_interop(
        self,
        home: Path,
        *,
        windows_home: Path,
        fail_windows_debug: str | None = None,
    ) -> dict[str, str]:
        fake_bin = home / "test-bin"
        fake_bin.mkdir(parents=True, exist_ok=True)
        py = fake_bin / "py.exe"
        py.write_text(
            '#!/usr/bin/env sh\n'
            'printf "%s\\n" "$*" >> "$HOME/windows-python-calls.txt"\n'
            'if [ -n "${FAIL_WINDOWS_INSTALL:-}" ]; then '
            'case "$*" in *--preflight-only*) ;; *) exit 29;; esac; fi\n'
            'if [ "$1" = "-3" ]; then shift; fi\n'
            'exec env HOME="$FAKE_WINDOWS_HOME" XDG_STATE_HOME="$FAKE_WINDOWS_HOME/state" python3 "$@"\n',
            encoding="utf-8",
        )
        py.chmod(0o755)
        wslpath = fake_bin / "wslpath"
        wslpath.write_text(
            '#!/usr/bin/env sh\n'
            'if [ "$1" = "-w" ]; then printf "C:\\\\Mapped\\\\%s\\n" "$(basename "$2")"; exit 0; fi\n'
            'if [ "$1" = "-u" ]; then printf "%s\\n" "$HOME/test-bin/py.exe"; exit 0; fi\n'
            'exit 2\n',
            encoding="utf-8",
        )
        wslpath.chmod(0o755)
        environment = {
            "WSL_DISTRO_NAME": "TestDistro",
            "FAKE_WINDOWS_HOME": str(windows_home),
        }
        if fail_windows_debug is not None:
            environment["FAIL_WINDOWS_INSTALL"] = fail_windows_debug
        return environment

    def test_global_install_copies_skill_and_audit_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            target = home / ".config" / "opencode"
            target.mkdir(parents=True)
            config = target / "opencode.jsonc"
            config.write_text(
                '''{
                  // Existing settings remain semantically intact.
                  "plugin": ["keep-me"],
                  "agent": {"custom": {"mode": "subagent"}},
                }''',
                encoding="utf-8",
            )

            first = self.run_installer(
                home,
                "--global",
                "--no-prompt",
            )
            self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
            self.assertTrue((target / "agents" / "audit.md").is_file())
            self.assertTrue(
                (target / "skills" / "exhaustive-review" / "SKILL.md").is_file()
            )
            merged = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(merged["plugin"], ["keep-me"])
            self.assertEqual(merged["agent"]["custom"], {"mode": "subagent"})
            self.assertIn("audit", merged["agent"])
            runtime_calls = (home / "opencode-calls.txt").read_text(encoding="utf-8")
            self.assertIn("debug config", runtime_calls)
            self.assertIn("debug skill", runtime_calls)
            self.assertIn("debug agent audit", runtime_calls)
            self.assertIn("debug agent review", runtime_calls)

            first_content = config.read_bytes()
            second = self.run_installer(
                home,
                "--global",
                "--no-prompt",
            )
            self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
            self.assertEqual(config.read_bytes(), first_content)

    def test_project_install_is_not_skipped_by_unmanaged_global_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            project = root / "project"
            global_target = home / ".config" / "opencode"
            global_target.mkdir(parents=True)
            project.mkdir()
            (global_target / "opencode.jsonc").write_text(
                '{"plugin":["unmanaged"]}', encoding="utf-8"
            )

            result = self.run_installer(
                home,
                "--project",
                str(project),
                "--no-prompt",
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue((project / ".opencode" / "agents" / "audit.md").is_file())
            self.assertTrue(
                (
                    project
                    / ".opencode"
                    / "skills"
                    / "exhaustive-review"
                    / "SKILL.md"
                ).is_file()
            )

    def test_malformed_config_does_not_publish_managed_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            project = root / "project"
            target = project / ".opencode"
            home.mkdir()
            target.mkdir(parents=True)
            config = target / "opencode.jsonc"
            config.write_text('{"broken": [}', encoding="utf-8")
            instructions = target / "instructions.md"
            instructions.write_text("previous instructions", encoding="utf-8")

            result = self.run_installer(
                home,
                "--project",
                str(project),
                "--no-prompt",
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(config.read_text(encoding="utf-8"), '{"broken": [}')
            self.assertEqual(instructions.read_text(encoding="utf-8"), "previous instructions")
            self.assertFalse((target / "agents" / "audit.md").exists())

    def test_runtime_validation_failure_rolls_back_managed_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            project = root / "project"
            target = project / ".opencode"
            home.mkdir()
            (target / "agents").mkdir(parents=True)
            (target / "instructions.md").write_text("old instructions", encoding="utf-8")
            (target / "agents" / "audit.md").write_text("old audit", encoding="utf-8")
            (target / "opencode.jsonc").write_text('{"plugin":["old"]}', encoding="utf-8")

            result = self.run_installer(
                home,
                "--project",
                str(project),
                "--no-prompt",
                fail_debug="debug agent audit",
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((target / "instructions.md").read_text(encoding="utf-8"), "old instructions")
            self.assertEqual((target / "agents" / "audit.md").read_text(encoding="utf-8"), "old audit")
            self.assertEqual(json.loads((target / "opencode.jsonc").read_text()), {"plugin": ["old"]})
            self.assertFalse((target / "agents" / "plan.md").exists())

    @unittest.skipIf(os.name == "nt", "POSIX symlink fixture")
    def test_symlinked_project_opencode_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            project = root / "project"
            external = root / "external"
            home.mkdir()
            project.mkdir()
            external.mkdir()
            (project / ".opencode").symlink_to(external, target_is_directory=True)

            result = self.run_installer(
                home,
                "--project",
                str(project),
                "--no-prompt",
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(external.iterdir()), [])

    def test_global_and_project_flags_install_both_in_any_order(self) -> None:
        for arguments in (("--global", "--project"), ("--project", "--global")):
            with self.subTest(arguments=arguments), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                home = root / "home"
                project = root / "project"
                home.mkdir()
                project.mkdir()
                if arguments[0] == "--global":
                    invocation = ("--global", "--project", str(project))
                else:
                    invocation = ("--project", str(project), "--global")

                result = self.run_installer(
                    home,
                    *invocation,
                    "--no-prompt",
                )

                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertTrue((home / ".config" / "opencode" / "agents" / "audit.md").is_file())
                self.assertTrue((project / ".opencode" / "agents" / "audit.md").is_file())

    def test_conflicting_lsp_flags_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            result = self.run_installer(
                home,
                "--global",
                "--lsp",
                "--no-lsp",
                "--no-prompt",
            )
            self.assertNotEqual(result.returncode, 0)

    def test_combined_scope_failure_preserves_completed_first_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            project = root / "project"
            home.mkdir()
            project_target = project / ".opencode"
            project_target.mkdir(parents=True)
            project_config = project_target / "opencode.jsonc"
            project_config.write_text('{"plugin":["project"]}', encoding="utf-8")
            project_instructions = project_target / "instructions.md"
            project_instructions.write_text("project old", encoding="utf-8")

            result = self.run_installer(
                home,
                "--global",
                "--project",
                str(project),
                "--no-prompt",
                fail_debug="debug agent review",
                fail_debug_config=project_target,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(
                (
                    home
                    / ".config"
                    / "opencode"
                    / "agents"
                    / "audit.md"
                ).is_file()
            )
            self.assertEqual(project_config.read_text(encoding="utf-8"), '{"plugin":["project"]}')
            self.assertEqual(project_instructions.read_text(encoding="utf-8"), "project old")
            self.assertEqual(list(project_target.glob("opencode.json*.bak-*")), [])

    def test_wsl_can_install_global_workflow_into_windows_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "wsl-home"
            windows_home = root / "windows-home"
            home.mkdir()
            windows_home.mkdir()
            environment = self.add_fake_wsl_interop(home, windows_home=windows_home)

            result = self.run_installer(
                home,
                "--environment",
                "windows",
                "--global",
                "--no-prompt",
                extra_environment=environment,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertFalse((home / ".config" / "opencode").exists())
            windows_calls = (home / "windows-python-calls.txt").read_text(
                encoding="utf-8"
            )
            self.assertIn("-3", windows_calls)
            self.assertIn("--environment current", windows_calls)
            self.assertIn("--global", windows_calls)

    def test_wsl_can_install_global_workflow_into_both_environments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "wsl-home"
            windows_home = root / "windows-home"
            home.mkdir()
            windows_home.mkdir()
            environment = self.add_fake_wsl_interop(home, windows_home=windows_home)

            result = self.run_installer(
                home,
                "--environment",
                "both",
                "--global",
                "--no-prompt",
                extra_environment=environment,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue(
                (home / ".config" / "opencode" / "agents" / "audit.md").is_file()
            )
            self.assertTrue(
                (
                    windows_home
                    / ".config"
                    / "opencode"
                    / "agents"
                    / "audit.md"
                ).is_file()
            )
            self.assertIn(
                "--environment current",
                (home / "windows-python-calls.txt").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                result.stdout.count(
                    "Installed exhaustive-review workflow in the selected environment(s)."
                ),
                1,
            )

    def test_windows_failure_preserves_prior_wsl_install_for_idempotent_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "wsl-home"
            windows_home = root / "windows-home"
            home.mkdir()
            windows_home.mkdir()
            environment = self.add_fake_wsl_interop(
                home,
                windows_home=windows_home,
                fail_windows_debug="debug agent review",
            )

            result = self.run_installer(
                home,
                "--environment",
                "both",
                "--global",
                "--no-prompt",
                extra_environment=environment,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(
                (home / ".config" / "opencode" / "agents" / "audit.md").is_file()
            )
            self.assertFalse((windows_home / ".config" / "opencode").exists())
            self.assertIn("Completed targets remain installed", result.stderr)
            self.assertIn("rerun", result.stderr)

    def test_remote_timeout_returns_clean_reconciliation_message(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "wsl-home"
            windows_home = root / "windows-home"
            home.mkdir()
            windows_home.mkdir()
            environment = self.add_fake_wsl_interop(home, windows_home=windows_home)
            environment["FAIL_WINDOWS_INSTALL"] = "timeout"
            py = home / "test-bin" / "py.exe"
            source = py.read_text(encoding="utf-8")
            py.write_text(
                source.replace(
                    'if [ -n "${FAIL_WINDOWS_INSTALL:-}" ]; then ',
                    'if [ "${FAIL_WINDOWS_INSTALL:-}" = "timeout" ]; then sleep 2; fi\n'
                    'if [ -n "${FAIL_WINDOWS_INSTALL:-}" ]; then ',
                ),
                encoding="utf-8",
            )
            bootstrap_timeout = (
                "import importlib.util, os, pathlib, sys; "
                f"p=pathlib.Path({str(ROOT / 'install.py')!r}); "
                "s=importlib.util.spec_from_file_location('workflow_installer', p); "
                "m=importlib.util.module_from_spec(s); sys.modules[s.name]=m; "
                "s.loader.exec_module(m); m.CROSS_ENV_TIMEOUT_SECONDS=0.05; "
                "m._trusted_wslpath_executable=lambda: os.environ['FAKE_WSLPATH']; "
                "m._trusted_windows_python=lambda _w: (os.environ['FAKE_WINDOWS_PYTHON'], '-3'); "
                "raise SystemExit(m.main(sys.argv[1:]))"
            )
            environment["FAKE_WINDOWS_PYTHON"] = str(py)
            environment["FAKE_WSLPATH"] = str(home / "test-bin" / "wslpath")
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    bootstrap_timeout,
                    "--environment",
                    "windows",
                    "--global",
                    "--no-prompt",
                ],
                cwd=ROOT,
                env={**os.environ, "HOME": str(home), **environment},
                text=True,
                capture_output=True,
                timeout=10,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("Traceback", result.stderr)
            self.assertIn("timed out", result.stderr.lower())

if __name__ == "__main__":
    unittest.main()
