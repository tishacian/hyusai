"""PostgreSQL aggregates over a tested translation of native COMPAT reads.

Strict/shadow IAM and migration-managed HITL use the native reader. No result or
permission cache crosses a transaction. Compat has no shadow observations to
emit: the candidate IAM decision is explicitly non-authoritative in that mode.
"""

import json
from datetime import timedelta

from sqlalchemy import text

from app.api.v1.endpoints.workspace_jobs import _can_access_job
from app.models.workspace_job import WorkspaceJob
from app.services.chat_execution_policy import migration_059_system_id
from app.services.iam.decision_plane import AuthorizationMode, resolve_mode
from app.services.run_access import can_view_private_chat_runs
from app.services.run_engine.execution_contract import WORKBENCH_EXECUTION_SURFACES

from .projection import TERMINAL, iso

# Exactly the characters removed by Python str.strip(), including NBSP. A
# plain SQL trim would broaden ownership for a tab-padded workbench surface.
_CANONICAL_TIMESTAMP = r"^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\.[0-9]{1,6})?Z$"
_PYTHON_WHITESPACE = "".join(chr(value) for value in range(0x3100) if chr(value).isspace())


def _empty():
    return dict(
        total=0,
        by_status={},
        by_kind={},
        durations={},
        costs=[],
        cost_known_count=0,
        cost_unknown_count=0,
        cost_complete=False,
        snapshot_only_count=0,
    )


def aggregate_compat(
    db,
    workspace,
    user,
    *,
    read_context,
    start,
    until,
    metric,
    kind,
    status,
    system_id,
    bucket,
    time_basis,
):
    """Return aggregates or None when the native boundary cannot be translated.

    PostgreSQL 17 is the Compose/Helm target. On <=15 the native path remains
    available; pg_input_is_valid (16+) makes malformed historical dates/numbers
    a missing measurement instead of an aggregate-wide SQL cast exception.
    """
    bind = db.get_bind()
    if bind.dialect.name != "postgresql" or bind.dialect.server_version_info < (16,):
        return None
    read_context.require_scope(db, workspace, user)
    if migration_059_system_id(workspace) is not None:
        return None
    for resource in ("run", "system", "skill_invocation"):
        if (
            resolve_mode(
                read_context.iam.config,
                resource_kind=resource,
                action="read",
                db=db,
                mode_cache=read_context.iam.mode_cache,
            )
            is not AuthorizationMode.COMPAT
        ):
            return None
    # Service-window membership and receipt asset grants are not translated.
    # Refuse the entire fast path whenever these kinds can enter the requested
    # population. The native reader applies current grants, including historical
    # receipts whose evidence has since been requalified. Never aggregate first.
    if kind is None or kind in {"service_window", "delivery_receipt"}:
        protected = db.execute(
            text("""
            SELECT 1 FROM activities a WHERE a.workspace_id = :workspace
              AND a.kind IN ('service_window', 'delivery_receipt')
              AND (:kind IS NULL OR a.kind = :kind)
              AND (:status IS NULL OR a.status = :status)
              AND (:system_id IS NULL OR a.system_id = :system_id)
              AND (:time_basis = 'finished' OR (a.created_at >= :start AND a.created_at < :until))
            LIMIT 1
            """),
            dict(
                workspace=workspace.id,
                kind=kind,
                status=status,
                system_id=system_id or None,
                time_basis=time_basis,
                start=start,
                until=until,
            ),
        ).first()
        if protected:
            return None
    # BRD has catalogue/document authorization beyond ordinary job ownership.
    # Keep that native check. If the exceptional population is large, the
    # whole request falls back; this bound never truncates aggregate totals.
    brd_jobs = (
        db.query(WorkspaceJob)
        .filter_by(workspace_id=workspace.id, kind="brd_generation")
        .limit(257)
        .all()
    )
    if len(brd_jobs) > 256:
        return None
    allowed_brd = [row.id for row in brd_jobs if _can_access_job(db, row, user, workspace)]
    # A malformed legacy projection must retain the native fallback semantics.
    # Canonical invocation projections have exactly their native parent Run.
    mismatch = db.execute(
        text("""
        SELECT 1 FROM activities a JOIN skill_invocations i ON i.id = a.native_id
        WHERE a.workspace_id = :workspace AND a.kind = 'skill_invocation'
          AND a.run_id IS DISTINCT FROM i.run_id LIMIT 1
    """),
        {"workspace": workspace.id},
    ).first()
    if mismatch:
        return None

    params = dict(
        workspace=workspace.id,
        user_id=user.id,
        start=start,
        until=until,
        metric=metric,
        kind=kind,
        status=status,
        system_id=system_id or None,
        bucket=bucket,
        time_basis=time_basis,
        admin=read_context.admin,
        see_private=can_view_private_chat_runs(
            db, user=user, workspace=workspace, membership=read_context.iam.membership
        ),
        whitespace=_PYTHON_WHITESPACE,
        workbench=list(WORKBENCH_EXECUTION_SURFACES),
        terminal=list(TERMINAL),
        allowed_brd=allowed_brd,
        start_prefix=(start - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S"),
        until_prefix=(until + timedelta(days=1, seconds=1)).strftime("%Y-%m-%dT%H:%M:%S"),
    )
    # PostgreSQL accepts values Python rejects (24:00, leap seconds) and rounds
    # >6 fractional digits. Normalize a bounded distinct historical population
    # with the very same parser as the native reader; never approximate it.
    exceptions = {}
    if time_basis == "finished":
        from .series import _date

        raw_dates = (
            db.execute(
                text("""
            SELECT DISTINCT a.snapshot ->> 'finished_at'
            FROM activities a WHERE a.workspace_id = :workspace
              AND (:kind IS NULL OR a.kind = :kind)
              AND (:status IS NULL OR a.status = :status)
              AND (:system_id IS NULL OR a.system_id = :system_id)
              AND a.status = ANY(:terminal)
              AND ((substr(a.snapshot ->> 'finished_at', 1, 19) >= :start_prefix
                AND substr(a.snapshot ->> 'finished_at', 1, 19) < :until_prefix)
                OR (a.created_at >= :start AND a.created_at < :until)
                OR a.snapshot ->> 'finished_at' NOT LIKE '____-__-__T__:__:__%')
              AND json_typeof(a.snapshot -> 'finished_at') = 'string'
              AND NOT (a.snapshot ->> 'finished_at' ~ :canonical_timestamp)
            LIMIT 129
        """),
                {**params, "canonical_timestamp": _CANONICAL_TIMESTAMP},
            )
            .scalars()
            .all()
        )
        if len(raw_dates) > 128:
            return None
        for raw in raw_dates:
            try:
                parsed = _date(raw)
            except (OverflowError, TypeError):
                return None  # Native error semantics remain authoritative.
            exceptions[raw] = parsed.isoformat() if parsed is not None else None
    params.update(canonical_timestamp=_CANONICAL_TIMESTAMP, exceptions=json.dumps(exceptions))
    # Canonical dates are UTC. A historical naive string has that same meaning;
    # explicit offsets are normalized before bucketing, as in the native path.
    db.execute(text("SET LOCAL TIME ZONE 'UTC'"))
    statement = text("""
    WITH authorized AS MATERIALIZED (
      SELECT a.kind, a.status, a.origin, a.created_at,
        CASE WHEN :time_basis = 'created' THEN a.created_at
          WHEN json_typeof(a.snapshot -> 'finished_at') IS DISTINCT FROM 'string' THEN NULL
          WHEN a.snapshot ->> 'finished_at' ~ :canonical_timestamp
            AND pg_input_is_valid(a.snapshot ->> 'finished_at', 'timestamp with time zone')
          THEN (a.snapshot ->> 'finished_at')::timestamptz AT TIME ZONE 'UTC'
          ELSE (CAST(:exceptions AS jsonb) ->> (a.snapshot ->> 'finished_at'))::timestamp
        END AS occurred,
        CASE WHEN json_typeof(a.snapshot -> 'measurements' -> 'duration_ms') = 'number'
          AND pg_input_is_valid(a.snapshot -> 'measurements' ->> 'duration_ms', 'double precision')
          THEN (a.snapshot -> 'measurements' ->> 'duration_ms')::double precision
        END AS raw_duration,
        CASE WHEN :metric = 'cost' THEN c.cost_usd END AS compute_cost,
        CASE WHEN :metric = 'cost' THEN i.cost END AS invocation_cost,
        CASE WHEN :metric = 'cost' THEN i.provider_cost_usd END AS provider_cost,
        CASE WHEN :metric = 'cost' THEN i.cost_measured END AS cost_measured,
        CASE WHEN :metric = 'cost' THEN i.metrics -> 'cost_evidence' ->> 'state' END AS evidence_state,
        CASE WHEN :metric = 'cost' THEN i.metrics -> 'cost_evidence' ->> 'currency' END AS evidence_currency
      FROM activities a
      LEFT JOIN runs r ON r.id = a.run_id AND r.workspace_id = a.workspace_id
      LEFT JOIN systems s ON s.id = a.system_id AND s.workspace_id = a.workspace_id
      LEFT JOIN skill_invocations i ON (:kind IS NULL OR :kind = 'skill_invocation') AND a.kind = 'skill_invocation' AND i.id = a.native_id
      LEFT JOIN compute_runs c ON (:kind IS NULL OR :kind = 'compute_run') AND a.kind = 'compute_run' AND c.id = a.native_id AND c.workspace_id = a.workspace_id
      LEFT JOIN workspace_jobs j ON (:kind IS NULL OR :kind = 'workspace_job') AND a.kind = 'workspace_job' AND j.id = a.native_id AND j.workspace_id = a.workspace_id
      LEFT JOIN sessions session ON (:kind IS NULL OR :kind = 'workspace_job') AND session.id = j.session_id AND session.workspace_id = a.workspace_id
      WHERE a.workspace_id = :workspace
        AND (:kind IS NULL OR a.kind = :kind)
        AND (:status IS NULL OR a.status = :status)
        AND (:system_id IS NULL OR a.system_id = :system_id)
        AND CASE WHEN :time_basis = 'created' THEN a.created_at >= :start AND a.created_at < :until
          ELSE a.status = ANY(:terminal) AND (
            (substr(a.snapshot ->> 'finished_at', 1, 19) >= :start_prefix
             AND substr(a.snapshot ->> 'finished_at', 1, 19) < :until_prefix)
            OR (a.created_at >= :start AND a.created_at < :until)
            OR a.snapshot ->> 'finished_at' NOT LIKE '____-__-__T__:__:__%') END
        AND CASE WHEN nullif(a.run_id, '') IS NOT NULL THEN r.id IS NOT NULL AND (
          :admin OR r.initiated_by_user_id = :user_id OR (
            NOT (lower(btrim(coalesce(r.execution_surface, ''), :whitespace)) = ANY(:workbench)
              OR lower(btrim(coalesce(r.trigger, ''), :whitespace)) = ANY(:workbench))
            AND (r.trigger IS DISTINCT FROM 'chat_agentic' OR :see_private)))
          WHEN nullif(a.system_id, '') IS NOT NULL THEN s.id IS NOT NULL
          ELSE :admin OR a.owner_id = :user_id END
        AND (a.kind <> 'skill_invocation' OR (i.id IS NOT NULL AND i.run_id = a.run_id))
        AND (a.kind <> 'compute_run' OR (c.id IS NOT NULL AND (:admin OR c.user_id = :user_id)))
        AND (a.kind <> 'workspace_job' OR (j.id IS NOT NULL AND CASE WHEN j.kind = 'brd_generation'
          THEN j.id = ANY(:allowed_brd)
          ELSE :admin OR j.created_by_user_id = :user_id
            OR (session.user_id = :user_id AND session.status <> 'deleted') END))
    ), normalized AS (
      SELECT *,
        CASE WHEN kind = 'compute_run' THEN compute_cost
          WHEN cost_measured IS TRUE AND evidence_state IN ('measured', 'calculated')
            AND length(evidence_currency) = 3 AND evidence_currency ~ '^[A-Za-z]{3}$'
          THEN CASE WHEN evidence_state = 'measured' AND upper(evidence_currency) = 'USD'
            THEN provider_cost ELSE invocation_cost END END AS raw_amount,
        CASE WHEN kind = 'compute_run' THEN 'USD' ELSE upper(evidence_currency) END AS currency,
        CASE WHEN kind = 'compute_run' THEN 'infrastructure_allocation'
          WHEN evidence_state = 'measured' THEN 'provider_measured'
          WHEN evidence_state = 'calculated' THEN 'catalogue_calculated' END AS basis
      FROM authorized WHERE occurred >= :start AND occurred < :until
    ), measured AS MATERIALIZED (
      SELECT date_trunc(:bucket, occurred) AS bucket, kind, status, origin,
        CASE WHEN raw_duration >= 0 AND raw_duration < 'Infinity'::double precision THEN raw_duration END AS duration,
        CASE WHEN raw_amount >= 0 AND raw_amount < 'Infinity'::double precision THEN raw_amount END AS amount,
        currency, basis
      FROM normalized
    )
    SELECT 'counts' AS section, bucket, jsonb_build_object(
      'kind', kind, 'status', status, 'total', count(*),
      'snapshot_only', count(*) FILTER (WHERE origin = 'snapshot_only')) AS payload
    FROM measured GROUP BY GROUPING SETS ((bucket, kind, status), (kind, status))
    UNION ALL
    SELECT 'durations', bucket, jsonb_build_object(
      'kind', kind, 'eligible_count', count(*), 'measured_count', count(duration),
      'p50_ms', percentile_disc(0.5) WITHIN GROUP (ORDER BY duration),
      'p95_ms', percentile_disc(0.95) WITHIN GROUP (ORDER BY duration))
    FROM measured WHERE status = ANY(:terminal)
    GROUP BY GROUPING SETS ((bucket, kind), (kind))
    UNION ALL
    SELECT 'costs', bucket, jsonb_build_object(
      'basis', CASE WHEN amount IS NULL THEN NULL ELSE basis END,
      'currency', CASE WHEN amount IS NULL THEN NULL ELSE currency END,
      'known_amount', sum(amount), 'count', count(*))
    FROM measured WHERE :metric = 'cost'
    GROUP BY GROUPING SETS (
      (bucket, CASE WHEN amount IS NULL THEN NULL ELSE basis END, CASE WHEN amount IS NULL THEN NULL ELSE currency END),
      (CASE WHEN amount IS NULL THEN NULL ELSE basis END, CASE WHEN amount IS NULL THEN NULL ELSE currency END))
    UNION ALL
    SELECT 'missing', NULL, jsonb_build_object('total', count(*))
    FROM authorized WHERE :time_basis = 'finished' AND occurred IS NULL
      AND created_at >= :start AND created_at < :until
    """)
    rows = db.execute(statement, params).all()
    width = timedelta(days=1) if bucket == "day" else timedelta(hours=1)
    slot = start.replace(minute=0, second=0, microsecond=0)
    if bucket == "day":
        slot = slot.replace(hour=0)
    cells = {}
    while slot < until:
        cells[slot] = _empty()
        slot += width
    totals, missing = _empty(), 0
    for section, slot, payload in rows:
        if section == "missing":
            missing = payload["total"]
            continue
        current = totals if slot is None else cells[slot]
        if section == "counts":
            amount = payload["total"]
            current["total"] += amount
            for category in ("kind", "status"):
                counts = current["by_" + category]
                counts[payload[category]] = counts.get(payload[category], 0) + amount
            current["snapshot_only_count"] += payload["snapshot_only"]
        elif section == "durations":
            native_kind = payload.pop("kind")
            current["durations"][native_kind] = payload
        elif payload["basis"] is None:
            current["cost_unknown_count"] += payload["count"]
        else:
            current["cost_known_count"] += payload["count"]
            current["costs"].append(
                dict(
                    basis=payload["basis"],
                    currency=payload["currency"],
                    known_amount=payload["known_amount"],
                    known_count=payload["count"],
                )
            )
    for current in [totals, *cells.values()]:
        current["cost_complete"] = current["total"] > 0 and current["cost_unknown_count"] == 0
        current["costs"].sort(key=lambda item: (item["basis"], item["currency"]))
    return (
        totals,
        [
            dict(
                **current, **{"from": iso(max(slot, start)), "until": iso(min(slot + width, until))}
            )
            for slot, current in cells.items()
        ],
        missing,
    )
