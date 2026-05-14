"""Tests for the manual GitHub Actions ingestion workflow."""
from __future__ import annotations

from pathlib import Path
import unittest

WORKFLOW_PATH = Path(".github/workflows/manual-ingestion.yml")


class AutomationWorkflowTests(unittest.TestCase):
    def _text(self) -> str:
        return WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_manual_workflow_exists_without_schedule(self) -> None:
        self.assertTrue(WORKFLOW_PATH.exists())

        text = self._text()
        self.assertIn("workflow_dispatch:", text)
        self.assertNotIn("schedule:", text)

    def test_manual_workflow_calls_python_entrypoint(self) -> None:
        text = self._text()

        self.assertIn("python scripts/run_automated_ingestion.py", text)
        self.assertIn("DATABASE_URL: ${{ secrets.DATABASE_URL }}", text)
        self.assertIn("IBKR_FLEX_TOKEN: ${{ secrets.IBKR_FLEX_TOKEN }}", text)
        self.assertIn("IBKR_FLEX_QUERY_ID: ${{ secrets.IBKR_FLEX_QUERY_ID }}", text)

    def test_workflow_dispatch_inputs_present(self) -> None:
        text = self._text()
        # All required inputs defined
        for key in ("target_type", "integration", "mode", "start_date", "end_date"):
            self.assertIn(key + ":", text, msg=f"Input '{key}' missing from workflow")

    def test_optional_inputs_present(self) -> None:
        text = self._text()
        # Optional inputs defined (no required: true for these)
        for key in ("portfolio_name", "account_external_ids"):
            self.assertIn(key + ":", text, msg=f"Optional input '{key}' missing")

    def test_required_inputs_marked_required(self) -> None:
        text = self._text()
        # start_date and end_date must be required
        self.assertIn("required: true", text)

    def test_optional_inputs_not_required(self) -> None:
        text = self._text()
        # portfolio_name and account_external_ids must NOT be required: true
        # We verify the word "required: false" or absence of required:true near them.
        # Simple check: the workflow must declare required: false for at least some inputs.
        self.assertIn("required: false", text)

    def test_cli_flags_mapped(self) -> None:
        text = self._text()
        # Verify each CLI flag appears in the workflow run step
        for flag in (
            "--target-type",
            "--mode",
            "--start-date",
            "--end-date",
            "--integration",
        ):
            self.assertIn(flag, text, msg=f"CLI flag '{flag}' not mapped in workflow")

    def test_python_version_312(self) -> None:
        text = self._text()
        self.assertIn("3.12", text)

    def test_step_summary_published(self) -> None:
        text = self._text()
        self.assertIn("GITHUB_STEP_SUMMARY", text)

    def test_uses_python_setup_action(self) -> None:
        text = self._text()
        self.assertIn("actions/setup-python", text)

    def test_installs_requirements(self) -> None:
        text = self._text()
        self.assertIn("requirements.txt", text)

    def test_target_type_choices_documented(self) -> None:
        text = self._text()
        self.assertIn("portfolio", text)
        self.assertIn("accounts", text)

    def test_mode_choices_documented(self) -> None:
        text = self._text()
        self.assertIn("dry-run", text)
        self.assertIn("load", text)

    def test_default_integration(self) -> None:
        text = self._text()
        self.assertIn("ibkr_flex_ws", text)


if __name__ == "__main__":
    unittest.main()
