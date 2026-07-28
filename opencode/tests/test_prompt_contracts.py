from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT.parent


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class PromptContractTests(unittest.TestCase):
    def test_exhaustive_review_skill_defines_complete_method(self) -> None:
        content = read("skills/exhaustive-review/SKILL.md").lower()

        for phrase in (
            "impact radius",
            "authority matrix",
            "lifecycle matrix",
            "action-closure matrix",
            "concurrency matrix",
            "single review",
            "specialist review",
            "synthesis review",
            "residual risks",
            "executive summary",
            "recommended remediation",
            "continue",
        ):
            self.assertIn(phrase, content)

    def test_instructions_route_single_and_deep_review(self) -> None:
        content = read("instructions.md").lower()

        for phrase in (
            "automatic review selection",
            "single review",
            "deep review",
            "multiple reviewers",
            "skip review",
            "freeze",
            "all specialist",
        ):
            self.assertIn(phrase, content)

    def test_agents_shift_discovery_left(self) -> None:
        plan = read("agents/plan.md").lower()
        test = read("agents/test.md").lower()
        build = read("agents/build.md").lower()
        review = read("agents/review.md").lower()
        audit = read("agents/audit.md").lower()
        general = read("agents/general.md").lower()

        for matrix in (
            "authority matrix",
            "lifecycle matrix",
            "action-closure matrix",
            "concurrency matrix",
        ):
            self.assertIn(matrix, plan)
        self.assertIn("plan is a hypothesis", test)
        self.assertIn("red", test)
        self.assertIn("hard termination", test)
        self.assertIn("finally", build)
        self.assertIn("invariant ledger", build)
        self.assertIn("exhaustive-review", review)
        self.assertIn("synthesis", review)
        self.assertIn("human-readable", review)
        self.assertIn("executive summary", review)
        self.assertNotIn("trust this context", review)
        self.assertIn("mode: all", audit)
        self.assertIn("exhaustive-review", audit)
        self.assertIn("never fix", audit)
        self.assertIn("high-risk", general)

    def test_agent_manifest_includes_audit(self) -> None:
        manifest = json.loads(read("agents.json"))

        self.assertEqual(manifest["audit"]["mode"], "all")
        self.assertEqual(
            manifest["audit"]["model"], "9router-chatgpt/cx/gpt-5.6-sol"
        )
        self.assertEqual(
            manifest["audit"]["permission"]["edit"],
            {
                "*": "deny",
                ".agents/review/**": "allow",
                "**/.agents/review/**": "allow",
            },
        )
        self.assertEqual(manifest["audit"]["permission"]["bash"], "allow")
        self.assertEqual(manifest["review"]["permission"]["bash"], "allow")
        self.assertIn("only path the audit may modify", read("agents/audit.md").lower())

    def test_installers_include_skill_and_audit_contracts(self) -> None:
        installer = read("install.py")

        self.assertIn("skills/exhaustive-review", installer)
        self.assertIn('"--both"', installer)
        self.assertIn('("debug", "agent", "audit")', installer)
        self.assertIn("Path.home()", installer)
        self.assertNotIn("wsl.exe", installer)
        self.assertNotIn("cmd.exe", installer)
        self.assertNotIn("USERPROFILE", installer)

    def test_review_skip_is_not_reported_as_completed_workflow(self) -> None:
        instructions = read("instructions.md").lower()
        self.assertIn("review skipped", instructions)
        self.assertIn("not workflow complete", instructions)

    def test_generated_artifacts_use_second_precision_timestamps(self) -> None:
        timestamp = "YYYY-MM-DD-HH-MM-SS"
        instructions = read("instructions.md")
        review = read("agents/review.md")
        audit = read("agents/audit.md")
        skill = read("skills/exhaustive-review/SKILL.md")
        standalone = (REPOSITORY_ROOT / "INSTRUCTIONS.md").read_text(encoding="utf-8")
        modular = (REPOSITORY_ROOT / ".agents" / "SYSTEM_PROMPT.md").read_text(
            encoding="utf-8"
        )
        checkpoint = (
            REPOSITORY_ROOT / ".agents" / "CHECKPOINT.md.template"
        ).read_text(encoding="utf-8")
        readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
        normalized_review = " ".join(review.lower().split())
        normalized_audit = " ".join(audit.lower().split())

        self.assertIn(f".agents/review/{timestamp}-", instructions)
        self.assertIn(f".agents/plan/{timestamp}-", instructions)
        self.assertIn(f".agents/state/{timestamp}-", instructions)
        self.assertIn("every generated project artifact", instructions)
        self.assertIn(f".agents/review/{timestamp}-", review)
        self.assertIn(f".agents/review/{timestamp}-", audit)
        self.assertIn(timestamp, skill)
        self.assertIn("never overwrite", instructions.lower())
        self.assertIn("native clock command", normalized_review)
        self.assertIn("native clock command", normalized_audit)
        self.assertIn("shell commands must be read-only", normalized_review)
        self.assertIn("shell commands must be read-only", normalized_audit)
        for source in (standalone, modular):
            self.assertIn(f".agents/plan/{timestamp}-", source)
            self.assertIn(f".agents/state/{timestamp}-", source)
            self.assertIn("Never overwrite", source)
        self.assertIn(f".agents/plan/{timestamp}-", checkpoint)
        self.assertIn(f".agents/state/{timestamp}-", readme)

        for source in (instructions, review, audit, standalone, modular, checkpoint, readme):
            self.assertNotIn("YYYY-MM-DD-<", source)

    def test_review_evaluation_fixture_documents_expected_detection(self) -> None:
        content = read("evaluation/exhaustive-review-scenarios.md").lower()

        for phrase in (
            "state authority",
            "hard termination",
            "stale response",
            "finding freeze",
            "expected specialist lenses",
            "expected findings",
        ):
            self.assertIn(phrase, content)


if __name__ == "__main__":
    unittest.main()
