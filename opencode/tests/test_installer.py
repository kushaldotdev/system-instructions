from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ShellInstallerTests(unittest.TestCase):
    def run_installer(
        self,
        home: Path,
        *arguments: str,
        cwd: Path | None = None,
        fail_debug: str | None = None,
        fail_debug_config: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["HOME"] = str(home)
        fake_bin = home / "test-bin"
        fake_bin.mkdir(parents=True, exist_ok=True)
        fake_opencode = fake_bin / "opencode"
        fake_opencode.write_text(
            '#!/usr/bin/env sh\n'
            'printf "%s\\n" "$*" >> "$HOME/opencode-calls.txt"\n'
            'if [ -n "${FAIL_DEBUG:-}" ] && [ "$*" = "$FAIL_DEBUG" ] && '
            '{ [ -z "${FAIL_DEBUG_CONFIG:-}" ] || [ "${OPENCODE_CONFIG:-}" = "$FAIL_DEBUG_CONFIG" ]; }; '
            'then exit 23; fi\n',
            encoding="utf-8",
        )
        fake_opencode.chmod(0o755)
        environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
        if fail_debug is not None:
            environment["FAIL_DEBUG"] = fail_debug
        if fail_debug_config is not None:
            environment["FAIL_DEBUG_CONFIG"] = str(fail_debug_config)
        return subprocess.run(
            [sys.executable, str(ROOT / "install.py"), *arguments],
            cwd=cwd or ROOT,
            env=environment,
            check=False,
            text=True,
            capture_output=True,
            timeout=60,
        )

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

    def test_combined_scope_runtime_failure_rolls_back_first_scope(self) -> None:
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
                fail_debug_config=project_config,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((home / ".config" / "opencode").exists())
            self.assertEqual(project_config.read_text(encoding="utf-8"), '{"plugin":["project"]}')
            self.assertEqual(project_instructions.read_text(encoding="utf-8"), "project old")
            self.assertEqual(list(project_target.glob("opencode.json*.bak-*")), [])


if __name__ == "__main__":
    unittest.main()
