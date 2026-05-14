"""Automation orchestrator: validates requests, persists job lifecycle, coordinates runs."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from portfolio_engine.automation.config import load_integration_config
from portfolio_engine.automation.sanitization import sanitize_error_message
from portfolio_engine.automation.summary import build_parent_summary
from portfolio_engine.automation.targets import AutomationValidationError, validate_target_inputs
from portfolio_engine.automation.types import AutomationRunRequest, VALID_MODES, VALID_TARGET_TYPES
from portfolio_engine.database import AutomationJobFinalize, AutomationJobStart


@dataclass
class AutomationRunResult:
    automation_job_id: str | None
    status: str
    summary: dict[str, Any]
    error_message: str | None = None


def run_automation(request: AutomationRunRequest, *, database) -> AutomationRunResult:
    """Orchestrate an automation run: validate, persist, and (in future tasks) execute accounts.

    Steps performed in this slice (Task 10):
    1. Load integration config (raises ValueError for unknown key — not persisted).
    2. Mark stale running rows as failed using the config timeout.
    3. Create the parent automation_jobs row (DB errors propagate — not caught here).
    4. Validate the request; on failure, finalize parent as failed and return.
    5. Return a placeholder result — target resolution/account loop handled in Task 11+.
    """
    config = load_integration_config(request.integration_key)

    stale_before = datetime.now(timezone.utc) - timedelta(
        minutes=config.stale_running_timeout_minutes
    )
    database.fail_stale_automation_runs(
        stale_before=stale_before,
        error_message="stale_run_timeout",
    )

    job_id = database.create_automation_job(
        AutomationJobStart(
            trigger_type="manual",
            target_type=request.target_type,
            portfolio_id=None,
            integration_key=request.integration_key,
            mode=request.mode,
            requested_start_date=request.requested_start_date,
            requested_end_date=request.requested_end_date,
        )
    )

    try:
        _validate_request(request)
    except (AutomationValidationError, ValueError) as exc:
        error_message = sanitize_error_message(str(exc))
        summary = build_parent_summary([], [])
        database.finalize_automation_job(
            AutomationJobFinalize(
                automation_job_id=job_id,
                status="failed",
                summary=summary,
                error_message=error_message,
            )
        )
        return AutomationRunResult(
            automation_job_id=job_id,
            status="failed",
            summary=summary,
            error_message=error_message,
        )

    # Task 11+ will implement target resolution and the account execution loop.
    summary = build_parent_summary([], [])
    error_message = "target execution not implemented yet"
    database.finalize_automation_job(
        AutomationJobFinalize(
            automation_job_id=job_id,
            status="failed",
            summary=summary,
            error_message=error_message,
        )
    )
    return AutomationRunResult(
        automation_job_id=job_id,
        status="failed",
        summary=summary,
        error_message=error_message,
    )


def _validate_request(request: AutomationRunRequest) -> None:
    """Raise AutomationValidationError or ValueError for invalid request parameters."""
    if request.target_type not in VALID_TARGET_TYPES:
        raise AutomationValidationError(
            f"invalid target_type '{request.target_type}': must be one of {sorted(VALID_TARGET_TYPES)}"
        )
    if request.mode not in VALID_MODES:
        raise AutomationValidationError(
            f"invalid mode '{request.mode}': must be one of {sorted(VALID_MODES)}"
        )
    if request.requested_start_date > request.requested_end_date:
        raise AutomationValidationError(
            f"requested_start_date {request.requested_start_date} must not be after"
            f" requested_end_date {request.requested_end_date}"
        )
    validate_target_inputs(
        target_type=request.target_type,
        portfolio_name=request.portfolio_name,
        account_external_ids=request.account_external_ids,
    )
