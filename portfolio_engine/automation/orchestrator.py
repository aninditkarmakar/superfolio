"""Automation orchestrator: validates requests, persists job lifecycle, coordinates runs."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from portfolio_engine.automation.adapters import get_adapter
from portfolio_engine.automation.config import load_integration_config
from portfolio_engine.automation.credentials import (
    CredentialDecryptionError,
    CredentialMasterKeyError,
    SecretValue,
    decrypt_secret,
    load_master_key,
)
from portfolio_engine.automation.fetch_errors import safe_fetch_error_category
from portfolio_engine.automation.ingestion import dry_run_payload, load_payload
from portfolio_engine.automation.sanitization import sanitize_error_message
from portfolio_engine.automation.summary import (
    COUNT_KEYS,
    RECORD_TYPES,
    build_child_summary,
    build_parent_summary,
    empty_record_counts,
)
from portfolio_engine.automation.targets import AutomationValidationError, validate_target_inputs
from portfolio_engine.automation.types import (
    AutomationRunRequest,
    IntegrationConnectionContext,
    IntegrationFeedContext,
    VALID_MODES,
    VALID_TARGET_TYPES,
)
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

    # Resolve portfolio_id before creating the parent job so the DB check constraint
    # (portfolio_id IS NOT NULL for target_type='portfolio') is always satisfied.
    # If the portfolio cannot be found, raise before creating any job record — the schema
    # cannot persist a portfolio job without a valid portfolio_id.
    portfolio_id: str | None = None
    if request.target_type == "portfolio":
        portfolio_name = request.portfolio_name or ""
        portfolio_id = database.get_portfolio_id_by_name(portfolio_name)
        if portfolio_id is None:
            raise AutomationValidationError(
                f"portfolio not found or inactive: {portfolio_name!r}"
            )

    job_id = database.create_automation_job(
        AutomationJobStart(
            trigger_type="manual",
            target_type=request.target_type,
            portfolio_id=portfolio_id,
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
    # Statuses/summaries for targets that lack a connection assignment (failed immediately).
    early_failed_statuses: list[str] = []
    early_failed_summaries: list[dict[str, Any]] = []
    # Accounts that have a valid connection assignment and proceed to execution.
    assigned_pairs: list[tuple[str, Any]] = []
    try:
        for account in accounts:
            child_id = database.add_automation_job_account(
                AutomationJobAccountAdd(
                    automation_job_id=job_id,
                    account_id=account.account_id,
                    connection_id=getattr(account, "connection_id", None),
                )
            )
            child_pairs.append((child_id, account))

            if getattr(account, "connection_id", None) is None:
                # No integration connection assigned — fail this child immediately.
                failed_summary = build_child_summary(error_category="missing_integration_connection")
                database.finalize_automation_job_account(
                    AutomationJobAccountFinalize(
                        automation_job_account_id=child_id,
                        status="failed",
                        ingestion_run_id=None,
                        summary=failed_summary,
                        error_message="missing_integration_connection",
                    )
                )
                early_failed_statuses.append("failed")
                early_failed_summaries.append(failed_summary)
            else:
                assigned_pairs.append((child_id, account))
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

    # Group assigned accounts by connection_id for credential loading per connection.
    connection_groups: dict[str, list[tuple[str, Any]]] = {}
    for child_id, account in assigned_pairs:
        cid = account.connection_id  # guaranteed non-None for assigned_pairs
        if cid not in connection_groups:
            connection_groups[cid] = []
        connection_groups[cid].append((child_id, account))

    try:
        adapter.preflight_validate_config(config)
    except RuntimeError as exc:
        error_message = sanitize_error_message(str(exc))
        failed_child_summary = build_child_summary(error_category="preflight_failed")
        for child_id, _ in assigned_pairs:
            database.finalize_automation_job_account(
                AutomationJobAccountFinalize(
                    automation_job_account_id=child_id,
                    status="failed",
                    ingestion_run_id=None,
                    summary=failed_child_summary,
                    error_message=error_message,
                )
            )
        child_statuses_preflight = (
            early_failed_statuses + ["failed"] * len(assigned_pairs)
        )
        child_summaries_preflight = (
            early_failed_summaries + [failed_child_summary] * len(assigned_pairs)
        )
        summary = build_parent_summary(child_statuses_preflight, child_summaries_preflight)
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

    # Load master key from environment for credential decryption.
    raw_master_key = os.environ.get("SUPERFOLIO_CREDENTIAL_MASTER_KEY")

    child_statuses: list[str] = []
    child_summaries: list[dict[str, Any]] = []

    # Pairs that passed credential/preflight checks, eligible for fetch.
    fetch_pairs: list[tuple[str, Any]] = []
    # Connection groups that passed preflight, for multi-feed fetch.
    fetch_groups: list[tuple[Any, list[Any], list[tuple[str, Any]]]] = []
    # Pairs whose connection group failed credential/preflight checks.
    connection_failed_statuses: list[str] = []
    connection_failed_summaries: list[dict[str, Any]] = []

    # If the adapter implements preflight_connection, load credentials per connection group
    # before running fetches. Adapters that do not implement it use the legacy flow.
    adapter_supports_connection_preflight = (
        hasattr(adapter, "preflight_connection")
        and callable(getattr(adapter, "preflight_connection"))
    )

    if adapter_supports_connection_preflight:
        # Validate the master key once before iterating connection groups — it is a
        # system-wide configuration value that applies to all connections equally.
        try:
            master_key = load_master_key(raw_master_key)
        except CredentialMasterKeyError:
            for group_pairs in connection_groups.values():
                _fail_group(
                    group_pairs, "credential_master_key_error",
                    database, connection_failed_statuses, connection_failed_summaries,
                )
            master_key = None  # type: ignore[assignment]

        for connection_id, group_pairs in connection_groups.items():
            if master_key is None:
                # All groups already failed above; skip iteration body.
                continue

            connection_name = getattr(group_pairs[0][1], "connection_name", None) or connection_id

            try:
                raw_creds = database.list_active_connection_credentials(connection_id)
                decrypted_creds: dict[str, SecretValue] = {
                    name: decrypt_secret(ciphertext, master_key)
                    for name, ciphertext in raw_creds.items()
                }
            except CredentialDecryptionError:
                _fail_group(
                    group_pairs, "credential_decryption_failed",
                    database, connection_failed_statuses, connection_failed_summaries,
                )
                continue

            if "flex_token" not in decrypted_creds:
                _fail_group(
                    group_pairs, "missing_connection_credential",
                    database, connection_failed_statuses, connection_failed_summaries,
                )
                continue

            feed_records = database.list_active_integration_feeds(connection_id)
            feed_contexts: list[IntegrationFeedContext] = []
            feed_build_error: str | None = None
            for feed_record in feed_records:
                feed_cred_name = f"feed:{feed_record.feed_key}:query_id"
                if feed_cred_name not in decrypted_creds:
                    feed_build_error = "missing_feed_secret"
                    break
                feed_contexts.append(
                    IntegrationFeedContext(
                        feed_id=feed_record.id,
                        feed_key=feed_record.feed_key,
                        display_name=feed_record.display_name,
                        secrets={"query_id": decrypted_creds[feed_cred_name]},
                    )
                )

            if feed_build_error is not None:
                _fail_group(
                    group_pairs, feed_build_error,
                    database, connection_failed_statuses, connection_failed_summaries,
                )
                continue

            connection_context = IntegrationConnectionContext(
                connection_id=connection_id,
                integration_key=config.integration_key,
                brokerage_code=config.brokerage_code,
                name=connection_name,
                credentials=decrypted_creds,
            )

            try:
                adapter.preflight_connection(connection_context, tuple(feed_contexts))
            except RuntimeError as exc:
                error_msg = sanitize_error_message(str(exc))
                failed_summary = build_child_summary(error_category="connection_preflight_failed")
                for child_id, _ in group_pairs:
                    database.finalize_automation_job_account(
                        AutomationJobAccountFinalize(
                            automation_job_account_id=child_id,
                            status="failed",
                            ingestion_run_id=None,
                            summary=failed_summary,
                            error_message=error_msg,
                        )
                    )
                    connection_failed_statuses.append("failed")
                    connection_failed_summaries.append(failed_summary)
                continue

            for pair in group_pairs:
                fetch_pairs.append(pair)
            fetch_groups.append((connection_context, feed_contexts, list(group_pairs)))
    else:
        fetch_pairs = list(assigned_pairs)

    # Detect whether the adapter supports per-feed payload fetching.
    adapter_supports_feed_payload = (
        hasattr(adapter, "fetch_feed_payload")
        and callable(getattr(adapter, "fetch_feed_payload"))
    )

    if request.mode == "dry-run":
        if adapter_supports_feed_payload:
            _execute_dry_run_multi_feed(
                fetch_groups=fetch_groups,
                adapter=adapter,
                request=request,
                database=database,
                child_statuses=child_statuses,
                child_summaries=child_summaries,
            )
        else:
            for child_id, account in fetch_pairs:
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
        if adapter_supports_feed_payload:
            _execute_load_multi_feed(
                fetch_groups=fetch_groups,
                adapter=adapter,
                request=request,
                database=database,
                config=config,
                job_id=job_id,
                child_statuses=child_statuses,
                child_summaries=child_summaries,
            )
        else:
            for child_id, account in fetch_pairs:
                database.mark_automation_job_account_running(child_id)
                try:
                    if database.has_overlapping_automation_load(
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

    all_statuses = early_failed_statuses + connection_failed_statuses + child_statuses
    all_summaries = early_failed_summaries + connection_failed_summaries + child_summaries
    parent_status = _derive_parent_status(all_statuses)
    parent_summary = build_parent_summary(all_statuses, all_summaries)
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


def _fail_group(
    group_pairs: list[tuple[str, Any]],
    error_category: str,
    database: Any,
    failed_statuses: list[str],
    failed_summaries: list[dict[str, Any]],
) -> None:
    """Finalize all children in a connection group as failed with the given error_category."""
    error_msg = sanitize_error_message(error_category)
    failed_summary = build_child_summary(error_category=error_category)
    for child_id, _ in group_pairs:
        database.finalize_automation_job_account(
            AutomationJobAccountFinalize(
                automation_job_account_id=child_id,
                status="failed",
                ingestion_run_id=None,
                summary=failed_summary,
                error_message=error_msg,
            )
        )
        failed_statuses.append("failed")
        failed_summaries.append(failed_summary)


def _resolve_accounts(request: AutomationRunRequest, config, database) -> list:
    """Resolve the target accounts for the automation run from the database."""
    return database.resolve_automation_targets_with_connections(
        target_type=request.target_type,
        portfolio_name=request.portfolio_name or "",
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


def _execute_dry_run_multi_feed(
    *,
    fetch_groups: list[tuple[Any, list[Any], list[tuple[str, Any]]]],
    adapter: Any,
    request: Any,
    database: Any,
    child_statuses: list[str],
    child_summaries: list[dict[str, Any]],
) -> None:
    """Execute multi-feed dry-run for all connection groups.

    For each connection group, iterates feeds in stable (alphabetical) feed_key order,
    fetches each payload via adapter.fetch_feed_payload, runs dry_run_payload per account,
    aggregates record counts, builds feed_results, derives child status, and finalizes
    each account child row.
    """
    for connection_ctx, feed_ctxs, group_pairs in fetch_groups:
        # Guard: fail the entire connection group if there are no active feeds.
        # An empty feed list cannot produce any results; silently succeeding via
        # `all([])` would violate the no-active-feeds contract.
        if not feed_ctxs:
            failed_summary = build_child_summary(error_category="no_active_feeds")
            for child_id, _ in group_pairs:
                database.mark_automation_job_account_running(child_id)
                database.finalize_automation_job_account(
                    AutomationJobAccountFinalize(
                        automation_job_account_id=child_id,
                        status="failed",
                        ingestion_run_id=None,
                        summary=failed_summary,
                        error_message="no_active_feeds",
                    )
                )
                child_statuses.append("failed")
                child_summaries.append(failed_summary)
            continue

        # Mark all accounts in this group as running before processing feeds.
        for child_id, _ in group_pairs:
            database.mark_automation_job_account_running(child_id)

        # Initialize per-account feed results accumulator.
        account_feed_results: dict[str, list[dict[str, Any]]] = {
            cid: [] for cid, _ in group_pairs
        }

        # Fetch each feed in stable alphabetical feed_key order.
        for feed_ctx in sorted(feed_ctxs, key=lambda f: f.feed_key):
            try:
                payload = adapter.fetch_feed_payload(connection_ctx, feed_ctx, request)
                for child_id, account in group_pairs:
                    per_feed_summary = dry_run_payload(
                        payload.xml_text,
                        account_external_id=account.account_external_id,
                        start_date=str(request.requested_start_date),
                        end_date=str(request.requested_end_date),
                    )
                    account_feed_results[child_id].append({
                        "feed_key": feed_ctx.feed_key,
                        "display_name": feed_ctx.display_name or feed_ctx.feed_key,
                        "status": "succeeded",
                        "record_counts": per_feed_summary["record_counts"],
                    })
            except Exception as exc:
                err_msg = sanitize_error_message(str(exc))
                for child_id, _ in group_pairs:
                    account_feed_results[child_id].append({
                        "feed_key": feed_ctx.feed_key,
                        "display_name": feed_ctx.display_name or feed_ctx.feed_key,
                        "status": "failed",
                        "error_category": safe_fetch_error_category(exc),
                        "record_counts": empty_record_counts(),
                        "message": err_msg,
                    })

        # Finalize each account based on its aggregated feed results.
        for child_id, account in group_pairs:
            feed_results = account_feed_results[child_id]
            feed_statuses = [fr["status"] for fr in feed_results]

            if all(s == "succeeded" for s in feed_statuses):
                child_status = "succeeded"
                child_error_category: str | None = None
            elif all(s == "failed" for s in feed_statuses):
                child_status = "failed"
                child_error_category = "feed_fetch_failed"
            else:
                child_status = "partially_succeeded"
                child_error_category = None

            # Aggregate record counts across all succeeded feeds.
            agg = empty_record_counts()
            for fr in feed_results:
                if fr["status"] == "succeeded":
                    rc = fr.get("record_counts", {})
                    for rt in RECORD_TYPES:
                        for key in COUNT_KEYS:
                            agg[rt][key] += rc.get(rt, {}).get(key, 0)

            child_summary = build_child_summary(
                cash_supported=agg["cash_flows"]["supported"],
                cash_inserted=agg["cash_flows"]["inserted"],
                cash_duplicates=agg["cash_flows"]["duplicates"],
                cash_skipped_unknown_account=agg["cash_flows"]["skipped_unknown_account"],
                cash_skipped_inactive_account=agg["cash_flows"]["skipped_inactive_account"],
                cash_skipped_other_account=agg["cash_flows"]["skipped_other_account"],
                cash_conflicts=agg["cash_flows"]["conflicts"],
                nav_supported=agg["daily_nav_snapshots"]["supported"],
                nav_inserted=agg["daily_nav_snapshots"]["inserted"],
                nav_duplicates=agg["daily_nav_snapshots"]["duplicates"],
                nav_skipped_unknown_account=agg["daily_nav_snapshots"]["skipped_unknown_account"],
                nav_skipped_inactive_account=agg["daily_nav_snapshots"]["skipped_inactive_account"],
                nav_skipped_other_account=agg["daily_nav_snapshots"]["skipped_other_account"],
                nav_conflicts=agg["daily_nav_snapshots"]["conflicts"],
                error_category=child_error_category,
                feed_results=feed_results,
            )

            database.finalize_automation_job_account(
                AutomationJobAccountFinalize(
                    automation_job_account_id=child_id,
                    status=child_status,
                    ingestion_run_id=None,
                    summary=child_summary,
                    error_message=None,
                )
            )
            child_statuses.append(child_status)
            child_summaries.append(child_summary)


def _execute_load_multi_feed(
    *,
    fetch_groups: list[tuple[Any, list[Any], list[tuple[str, Any]]]],
    adapter: Any,
    request: Any,
    database: Any,
    config: Any,
    job_id: str,
    child_statuses: list[str],
    child_summaries: list[dict[str, Any]],
) -> None:
    """Execute multi-feed load for all connection groups.

    For each connection group:
    - Guard against empty feed list (no_active_feeds).
    - For each account, run the date-overlap check once before loading any feed.
    - If overlap is detected, fail that account without fetching any feeds.
    - Otherwise, fetch each feed payload in stable (alphabetical) feed_key order,
      call load_payload per feed (each gets its own ingestion run), accumulate
      record counts from succeeded/partially-succeeded feeds, and build feed_results.
    - Derive child status: all succeeded → succeeded; all failed → failed; mixed →
      partially_succeeded. Finalize each account child row accordingly.
    """
    for connection_ctx, feed_ctxs, group_pairs in fetch_groups:
        # Guard: fail the entire connection group if there are no active feeds.
        if not feed_ctxs:
            failed_summary = build_child_summary(error_category="no_active_feeds")
            for child_id, _ in group_pairs:
                database.mark_automation_job_account_running(child_id)
                database.finalize_automation_job_account(
                    AutomationJobAccountFinalize(
                        automation_job_account_id=child_id,
                        status="failed",
                        ingestion_run_id=None,
                        summary=failed_summary,
                        error_message="no_active_feeds",
                    )
                )
                child_statuses.append("failed")
                child_summaries.append(failed_summary)
            continue

        sorted_feeds = sorted(feed_ctxs, key=lambda f: f.feed_key)

        for child_id, account in group_pairs:
            database.mark_automation_job_account_running(child_id)

            # Run account/date overlap check once before loading any feed.
            if database.has_overlapping_automation_load(
                integration_key=request.integration_key,
                account_id=account.account_id,
                requested_start_date=request.requested_start_date,
                requested_end_date=request.requested_end_date,
                exclude_automation_job_id=job_id,
            ):
                overlap_summary = build_child_summary(error_category="overlapping_load_job")
                database.finalize_automation_job_account(
                    AutomationJobAccountFinalize(
                        automation_job_account_id=child_id,
                        status="failed",
                        ingestion_run_id=None,
                        summary=overlap_summary,
                        error_message="overlapping_load_job",
                    )
                )
                child_statuses.append("failed")
                child_summaries.append(overlap_summary)
                continue

            # Fetch and load each feed in stable alphabetical feed_key order.
            feed_results: list[dict[str, Any]] = []
            for feed_ctx in sorted_feeds:
                try:
                    payload = adapter.fetch_feed_payload(connection_ctx, feed_ctx, request)
                    _ingestion_run_id, feed_status, feed_summary, _feed_msg = load_payload(
                        payload.xml_text,
                        database=database,
                        brokerage_code=config.brokerage_code,
                        account_external_id=account.account_external_id,
                        source_type=config.source_type,
                        source_name=payload.source_name,
                        start_date=str(request.requested_start_date),
                        end_date=str(request.requested_end_date),
                    )
                    feed_results.append({
                        "feed_key": feed_ctx.feed_key,
                        "display_name": feed_ctx.display_name or feed_ctx.feed_key,
                        "status": feed_status,
                        "record_counts": feed_summary["record_counts"],
                    })
                except Exception as exc:
                    err_msg = sanitize_error_message(str(exc))
                    feed_results.append({
                        "feed_key": feed_ctx.feed_key,
                        "display_name": feed_ctx.display_name or feed_ctx.feed_key,
                        "status": "failed",
                        "error_category": safe_fetch_error_category(exc),
                        "record_counts": empty_record_counts(),
                        "message": err_msg,
                    })

            # Derive child status from per-feed statuses.
            feed_statuses = [fr["status"] for fr in feed_results]
            if all(s == "succeeded" for s in feed_statuses):
                child_status = "succeeded"
                child_error_category: str | None = None
            elif all(s == "failed" for s in feed_statuses):
                child_status = "failed"
                child_error_category = "feed_fetch_failed"
            else:
                child_status = "partially_succeeded"
                child_error_category = None

            # Aggregate record counts from all non-failed feeds.
            agg = empty_record_counts()
            for fr in feed_results:
                if fr["status"] in ("succeeded", "partially_succeeded"):
                    rc = fr.get("record_counts", {})
                    for rt in RECORD_TYPES:
                        for key in COUNT_KEYS:
                            agg[rt][key] += rc.get(rt, {}).get(key, 0)

            child_summary = build_child_summary(
                cash_supported=agg["cash_flows"]["supported"],
                cash_inserted=agg["cash_flows"]["inserted"],
                cash_duplicates=agg["cash_flows"]["duplicates"],
                cash_skipped_unknown_account=agg["cash_flows"]["skipped_unknown_account"],
                cash_skipped_inactive_account=agg["cash_flows"]["skipped_inactive_account"],
                cash_skipped_other_account=agg["cash_flows"]["skipped_other_account"],
                cash_conflicts=agg["cash_flows"]["conflicts"],
                nav_supported=agg["daily_nav_snapshots"]["supported"],
                nav_inserted=agg["daily_nav_snapshots"]["inserted"],
                nav_duplicates=agg["daily_nav_snapshots"]["duplicates"],
                nav_skipped_unknown_account=agg["daily_nav_snapshots"]["skipped_unknown_account"],
                nav_skipped_inactive_account=agg["daily_nav_snapshots"]["skipped_inactive_account"],
                nav_skipped_other_account=agg["daily_nav_snapshots"]["skipped_other_account"],
                nav_conflicts=agg["daily_nav_snapshots"]["conflicts"],
                error_category=child_error_category,
                feed_results=feed_results,
            )

            database.finalize_automation_job_account(
                AutomationJobAccountFinalize(
                    automation_job_account_id=child_id,
                    status=child_status,
                    ingestion_run_id=None,
                    summary=child_summary,
                    error_message=None,
                )
            )
            child_statuses.append(child_status)
            child_summaries.append(child_summary)
