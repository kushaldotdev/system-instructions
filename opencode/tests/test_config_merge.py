from __future__ import annotations

import importlib.util
import json
import math
import os
import stat
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
