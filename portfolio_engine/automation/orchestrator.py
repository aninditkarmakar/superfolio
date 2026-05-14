"""Automation orchestrator: validates requests, persists job lifecycle, coordinates runs."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from portfolio_engine.automation.adapters import get_adapter
from portfolio_engine.automation.config import load_integration_config
from portfolio_engine.automation.ingestion import dry_run_payload, load_payload
from portfolio_engine.automation.sanitization import sanitize_error_message
from portfolio_engine.automation.summary import build_child_summary, build_parent_summary
from portfolio_engine.automation.targets import AutomationValidationError, validate_target_inputs
from portfolio_engine.automation.types import AutomationRunRequest, VALID_MODES, VALID_TARGET_TYPES
from portfolio_engine.database import (
    AutomationJobAccountAdd,
    AutomationJobAccountFinalize,
    AutomationJobFinalize,
    AutomationJobStart,
)


@dataclass
class AutomationRunResult:
    automation_job_id: str | None
    status: str
    summary: dict[str, Any]
    error_message: str | None = None
    automation_job_account_ids: tuple[str, ...] = ()


def run_automation(request: AutomationRunRequest, *, database, adapter=None) -> AutomationRunResult:
    """Orchestrate an automation run: validate, persist, and execute accounts.

    Steps performed:
    1. Load integration config (raises ValueError for unknown key — not persisted).
    2. Resolve adapter from config if not provided.
    3. Mark stale running rows as failed using the config timeout.
    4. Create the parent automation_jobs row (DB errors propagate — not caught here).
    5. Validate the request; on failure, finalize parent as failed and return.
    6. Resolve target accounts; empty resolved set is a preflight failure.
    7. Insert automation_job_accounts child rows for each resolved account.
    8. Preflight-validate adapter config; on RuntimeError, finalize parent as failed and return.
    9. Execute dry-run per account; finalize each child and then finalize the parent.
    """
    config = load_integration_config(request.integration_key)

    if adapter is None:
        adapter = get_adapter(config.adapter_key)

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
        accounts = _resolve_accounts(request, config, database)
        if not accounts:
            raise AutomationValidationError("empty resolved account set")
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

    child_pairs: list[tuple[str, Any]] = []
    try:
        for account in accounts:
            child_id = database.add_automation_job_account(
                AutomationJobAccountAdd(
                    automation_job_id=job_id,
                    account_id=account.account_id,
                )
            )
            child_pairs.append((child_id, account))
    except Exception as exc:
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
        raise

    child_ids = [cid for cid, _ in child_pairs]

    try:
        adapter.preflight_validate_config(config)
    except RuntimeError as exc:
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
            automation_job_account_ids=tuple(child_ids),
        )

    child_statuses: list[str] = []
    child_summaries: list[dict[str, Any]] = []

    if request.mode == "dry-run":
        for child_id, account in child_pairs:
            database.mark_automation_job_account_running(child_id)
            try:
                payload = adapter.fetch_payload(account, request, config)
                child_summary = dry_run_payload(
                    payload.xml_text,
                    account_external_id=account.account_external_id,
                    start_date=str(request.requested_start_date),
                    end_date=str(request.requested_end_date),
                )
            except Exception as exc:
                error_message = sanitize_error_message(str(exc))
                failed_child_summary = build_child_summary(error_category="fetch_or_parse_error")
                database.finalize_automation_job_account(
                    AutomationJobAccountFinalize(
                        automation_job_account_id=child_id,
                        status="failed",
                        ingestion_run_id=None,
                        summary=failed_child_summary,
                        error_message=error_message,
                    )
                )
                child_statuses.append("failed")
                child_summaries.append(failed_child_summary)
                continue
            database.finalize_automation_job_account(
                AutomationJobAccountFinalize(
                    automation_job_account_id=child_id,
                    status="succeeded",
                    ingestion_run_id=None,
                    summary=child_summary,
                    error_message=None,
                )
            )
            child_statuses.append("succeeded")
            child_summaries.append(child_summary)
    else:
        for child_id, account in child_pairs:
            database.mark_automation_job_account_running(child_id)
            try:
                if request.mode == "load" and database.has_overlapping_automation_load(
                    integration_key=request.integration_key,
                    account_id=account.account_id,
                    requested_start_date=request.requested_start_date,
                    requested_end_date=request.requested_end_date,
                    exclude_automation_job_id=job_id,
                ):
                    raise RuntimeError("overlapping_load_job")
                payload = adapter.fetch_payload(account, request, config)
                ingestion_run_id, child_status, child_summary, child_message = load_payload(
                    payload.xml_text,
                    database=database,
                    brokerage_code=config.brokerage_code,
                    account_external_id=account.account_external_id,
                    source_type=config.source_type,
                    source_name=payload.source_name,
                    start_date=str(request.requested_start_date),
                    end_date=str(request.requested_end_date),
                )
            except Exception as exc:
                error_message = sanitize_error_message(str(exc))
                is_overlap = isinstance(exc, RuntimeError) and str(exc) == "overlapping_load_job"
                error_category = "overlapping_load_job" if is_overlap else "fetch_or_parse_error"
                failed_child_summary = build_child_summary(error_category=error_category)
                database.finalize_automation_job_account(
                    AutomationJobAccountFinalize(
                        automation_job_account_id=child_id,
                        status="failed",
                        ingestion_run_id=None,
                        summary=failed_child_summary,
                        error_message=error_message,
                    )
                )
                child_statuses.append("failed")
                child_summaries.append(failed_child_summary)
                continue
            database.finalize_automation_job_account(
                AutomationJobAccountFinalize(
                    automation_job_account_id=child_id,
                    status=child_status,
                    ingestion_run_id=ingestion_run_id,
                    summary=child_summary,
                    error_message=child_message,
                )
            )
            child_statuses.append(child_status)
            child_summaries.append(child_summary)

    parent_status = _derive_parent_status(child_statuses)
    parent_summary = build_parent_summary(child_statuses, child_summaries)
    database.finalize_automation_job(
        AutomationJobFinalize(
            automation_job_id=job_id,
            status=parent_status,
            summary=parent_summary,
            error_message=None,
        )
    )
    return AutomationRunResult(
        automation_job_id=job_id,
        status=parent_status,
        summary=parent_summary,
        automation_job_account_ids=tuple(child_ids),
    )


def _resolve_accounts(request: AutomationRunRequest, config, database) -> list:
    """Resolve the target accounts for the automation run from the database."""
    if request.target_type == "portfolio":
        return database.resolve_automation_portfolio_accounts(
            portfolio_name=request.portfolio_name or "",
            brokerage_code=config.brokerage_code,
        )
    return database.resolve_automation_account_targets(
        brokerage_code=config.brokerage_code,
        account_external_ids=list(request.account_external_ids),
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


def _derive_parent_status(child_statuses: list[str]) -> str:
    """Derive the parent job status from the list of child account statuses.

    succeeded         — all children succeeded
    failed            — all children failed (or no children)
    partially_succeeded — mixed results or any child partially_succeeded
    """
    if not child_statuses:
        return "failed"
    if all(s == "succeeded" for s in child_statuses):
        return "succeeded"
    if all(s == "failed" for s in child_statuses):
        return "failed"
    return "partially_succeeded"
