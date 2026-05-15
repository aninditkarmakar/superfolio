"""Tests for the manual GitHub Actions ingestion workflow."""
from __future__ import annotations

from pathlib import Path
import unittest
import yaml

WORKFLOW_PATH = Path(".github/workflows/manual-ingestion.yml")


class AutomationWorkflowTests(unittest.TestCase):
    def _text(self) -> str:
        return WORKFLOW_PATH.read_text(encoding="utf-8")

    def _parsed(self) -> dict:
        return yaml.safe_load(self._text())

    def _workflow_inputs(self) -> dict:
        # PyYAML parses bare 'on' as Python True
        return self._parsed()[True]["workflow_dispatch"]["inputs"]

    def _ingestion_step(self) -> dict:
        wf = self._parsed()
        steps = wf["jobs"]["ingest"]["steps"]
        for step in steps:
            if step.get("id") == "ingestion":
                return step
        raise AssertionError("Step with id='ingestion' not found")

    def test_manual_workflow_exists_without_schedule(self) -> None:
        self.assertTrue(WORKFLOW_PATH.exists())

        text = self._text()
        self.assertIn("workflow_dispatch:", text)
        self.assertNotIn("schedule:", text)

    def test_manual_workflow_calls_python_entrypoint(self) -> None:
        text = self._text()

        self.assertIn("python scripts/run_automated_ingestion.py", text)
        self.assertIn("DATABASE_URL: ${{ secrets.DATABASE_URL }}", text)

    def test_workflow_requires_master_key_secret(self) -> None:
        text = Path(".github/workflows/manual-ingestion.yml").read_text(encoding="utf-8")

        self.assertIn("SUPERFOLIO_CREDENTIAL_MASTER_KEY", text)
        self.assertNotIn("IBKR_FLEX_TOKEN:", text)
        self.assertNotIn("IBKR_FLEX_QUERY_ID:", text)

    def test_workflow_uses_master_key_not_per_login_secrets(self) -> None:
        text = Path(".github/workflows/manual-ingestion.yml").read_text(encoding="utf-8")

        self.assertIn("SUPERFOLIO_CREDENTIAL_MASTER_KEY: ${{ secrets.SUPERFOLIO_CREDENTIAL_MASTER_KEY }}", text)
        self.assertNotIn("IBKR_FLEX_TOKEN:", text)
        self.assertNotIn("IBKR_FLEX_QUERY_ID:", text)

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
        inputs = self._workflow_inputs()
        for key in ("target_type", "mode", "start_date", "end_date"):
            self.assertTrue(
                inputs[key].get("required"),
                msg=f"Input '{key}' should have required: true",
            )

    def test_optional_inputs_not_required(self) -> None:
        inputs = self._workflow_inputs()
        for key in ("portfolio_name", "account_external_ids"):
            self.assertFalse(
                inputs[key].get("required"),
                msg=f"Input '{key}' should not be required (required: true absent/false)",
            )

    # --- Issue 2: no raw ${{ inputs.* }} interpolation inside run blocks ---
    def test_no_raw_input_interpolation_in_run(self) -> None:
        run_script = self._ingestion_step().get("run", "")
        self.assertNotIn(
            "${{ inputs.",
            run_script,
            "Raw ${{ inputs.* }} found in run block — shell injection risk",
        )

    # --- Issue 2: all inputs bound to step-level env vars ---
    def test_inputs_bound_to_step_env(self) -> None:
        env = self._ingestion_step().get("env", {})
        expected = (
            "TARGET_TYPE",
            "INTEGRATION",
            "MODE",
            "START_DATE",
            "END_DATE",
            "PORTFOLIO_NAME",
            "ACCOUNT_EXTERNAL_IDS",
        )
        for var in expected:
            self.assertIn(var, env, msg=f"Step env var '{var}' not bound")

    # --- Issue 3: EXTRA_FLAGS uses a bash array, not a plain string ---
    def test_extra_flags_uses_bash_array(self) -> None:
        run_script = self._ingestion_step().get("run", "")
        self.assertIn("EXTRA_FLAGS=()", run_script, "EXTRA_FLAGS must be initialised as an array")
        self.assertIn("EXTRA_FLAGS+=(", run_script, "EXTRA_FLAGS must be appended to with EXTRA_FLAGS+=()")
        self.assertIn('"${EXTRA_FLAGS[@]}"', run_script, "EXTRA_FLAGS must be expanded as array")

    # --- Issue 1: summary written unconditionally via set +e / set -e ---
    def test_summary_written_unconditionally(self) -> None:
        run_script = self._ingestion_step().get("run", "")
        self.assertIn("set +e", run_script, "set +e required before pipeline to survive CLI failure")
        self.assertIn("set -e", run_script, "set -e required after pipeline capture")
        self.assertIn("PIPESTATUS[0]", run_script, "CLI exit code must be captured via PIPESTATUS[0]")


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
