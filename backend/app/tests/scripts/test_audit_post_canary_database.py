from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from scripts import audit_post_canary_database as audit

SHA = "a" * 40
LIVE_SHA = "b" * 40
SFTP_SHA = "c" * 40
DEPLOYMENT_ID = "safe-deploy-test"
LEDGER_SHA256 = "b" * 64
RUN_ID = "10000000-0000-0000-0000-000000000001"
INVOCATION_IDS = [
    "20000000-0000-0000-0000-000000000001",
    "20000000-0000-0000-0000-000000000002",
]
WORKSPACES = {
    "atlas": "30000000-0000-0000-0000-000000000001",
    "boreal": "30000000-0000-0000-0000-000000000002",
    "cinder": "30000000-0000-0000-0000-000000000003",
    "delta": "30000000-0000-0000-0000-000000000004",
}
SFTP_LINK_ID = "40000000-0000-0000-0000-000000000001"
SFTP_USER_ID = "40000000-0000-0000-0000-000000000002"
SFTP_ACCESS_ID = "ra1_private-sftp-canary-access"
SFTP_LABEL = "Private release canary"
SFTP_PASSWORD_HASH = "$2b$12$private-hash-never-in-a-receipt"
SFTP_OPERATOR = "private.operator@example.invalid"
SFTP_AUDIT_IDS = [f"50000000-0000-0000-0000-00000000000{index}" for index in range(1, 5)]
SFTP_TIMESTAMPS = [
    datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=10 - index) for index in range(6)
]


def _pair(primary_key: str, content: str) -> tuple[str, str]:
    return audit._sha([primary_key]), audit._sha({"content": content})


def _table(
    rows: list[tuple[str, str]],
    *,
    normalization: list[str] | None = None,
    controlled_rows: dict[str, str] | None = None,
    sftp_audits: dict[str, dict[str, str]] | None = None,
    sftp_link: dict[str, str] | None = None,
    navigation: dict[str, list[tuple[str, str]]] | None = None,
) -> dict[str, object]:
    accumulator = audit._MultisetAccumulator()
    for primary_key_hash, row_hash in rows:
        accumulator.add_hashes(primary_key_hash, row_hash)
    navigation_accumulators: dict[str, audit._MultisetAccumulator] = {}
    for workspace_hash, workspace_rows in (navigation or {}).items():
        navigation_accumulator = audit._MultisetAccumulator()
        for primary_key_hash, row_hash in workspace_rows:
            navigation_accumulator.add_hashes(primary_key_hash, row_hash)
        navigation_accumulators[workspace_hash] = navigation_accumulator
    return audit._table_payload(
        primary_keys=["id"],
        accumulator=accumulator,
        normalization=normalization or [],
        controlled_rows=controlled_rows or {},
        canonical_navigation=navigation_accumulators,
        controlled_sftp_audits=sftp_audits or {},
        controlled_sftp_link=sftp_link,
    )


def _ledger() -> dict[str, object]:
    return {
        "kind": "safe_controlled_chat_ledger",
        "outcome": "passed",
        "commit_sha": SHA,
        "deployment_id": DEPLOYMENT_ID,
        "run_id": RUN_ID,
        "invocation_ids": INVOCATION_IDS,
    }


def _binding(with_ledger: bool) -> dict[str, Any]:
    return audit._ledger_binding(
        run_id=RUN_ID if with_ledger else None,
        invocation_ids=INVOCATION_IDS if with_ledger else [],
        ledger_sha256=LEDGER_SHA256 if with_ledger else None,
    )


def _inventory(tables: dict[str, object], *, with_ledger: bool) -> dict[str, object]:
    identities = sorted(
        [
            {
                "slug": slug,
                "workspace_id_sha256": audit._sha([workspace_id]),
            }
            for slug, workspace_id in WORKSPACES.items()
        ],
        key=lambda item: item["slug"],
    )
    binding = _binding(with_ledger)
    return {
        "schema_version": audit.SCHEMA_VERSION,
        "kind": "postgresql_row_inventory",
        "profile": audit.INVENTORY_PROFILE,
        "candidate_sha": SHA,
        "deployment_id": DEPLOYMENT_ID,
        "content_serialized": False,
        "detail_policy": ("controlled-ledger-rows-and-navigation-workspace-aggregates-only"),
        "table_count": len(tables),
        "tables": tables,
        "inventory_sha256": audit._inventory_sha256(
            tables=tables,
            workspace_identities=identities,
            ledger_binding=binding,
        ),
        "business_inventory_sha256": audit._sha(audit._business_projection(tables)),
        "workspace_identities": identities,
        "workspace_identities_sha256": audit._sha(identities),
        "ledger_binding": binding,
    }


def _fixtures() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    existing_user = _pair("existing-user", "stable")
    baseline_tables = {
        "users": _table([existing_user], normalization=["last_login"]),
        "runs": _table([]),
        "skill_invocations": _table([]),
        "audit_logs": _table([]),
        "systems": _table([]),
        "event_entity": _table([]),
    }
    current_tables = deepcopy(baseline_tables)
    controlled_run = _pair(RUN_ID, "controlled-run")
    controlled_invocations = [
        _pair(value, f"invocation-{index}") for index, value in enumerate(INVOCATION_IDS)
    ]
    current_tables["runs"] = _table([controlled_run], controlled_rows=dict([controlled_run]))
    current_tables["skill_invocations"] = _table(
        controlled_invocations,
        controlled_rows=dict(controlled_invocations),
    )
    navigation: dict[str, list[tuple[str, str]]] = {}
    navigation_rows: list[tuple[str, str]] = []
    for index, workspace_id in enumerate(WORKSPACES.values()):
        row = _pair(f"audit-{index}", f"navigation-{index}")
        navigation_rows.append(row)
        navigation[audit._sha([workspace_id])] = [row]
    current_tables["audit_logs"] = _table(
        navigation_rows,
        navigation=navigation,
    )
    return (
        _inventory(baseline_tables, with_ledger=False),
        _inventory(current_tables, with_ledger=True),
        _inventory(deepcopy(current_tables), with_ledger=True),
    )


def _compare(
    baseline: dict[str, object],
    post: dict[str, object],
    final: dict[str, object],
    *,
    ledger: dict[str, object] | None = None,
    workspace_ids: list[str] | None = None,
) -> dict[str, object]:
    return audit.compare_inventory(
        baseline=baseline,
        post_canary=post,
        final=final,
        ledger=ledger or _ledger(),
        candidate_sha=SHA,
        deployment_id=DEPLOYMENT_ID,
        ledger_sha256=LEDGER_SHA256,
        baseline_file_sha256="c" * 64,
        post_canary_file_sha256="d" * 64,
        final_file_sha256="e" * 64,
        canary_workspace_ids=workspace_ids or list(WORKSPACES.values()),
    )


def _refresh_inventory(inventory: dict[str, object]) -> None:
    tables = inventory["tables"]
    identities = inventory["workspace_identities"]
    binding = inventory["ledger_binding"]
    assert isinstance(tables, dict)
    assert isinstance(identities, list)
    assert isinstance(binding, dict)
    inventory["table_count"] = len(tables)
    inventory["workspace_identities_sha256"] = audit._sha(identities)
    inventory["inventory_sha256"] = audit._inventory_sha256(
        tables=tables,
        workspace_identities=identities,
        ledger_binding=binding,
    )
    inventory["business_inventory_sha256"] = audit._sha(audit._business_projection(tables))


def _sftp_link_row(*, status: str) -> dict[str, object]:
    updated_at = SFTP_TIMESTAMPS[0] if status == "active" else SFTP_TIMESTAMPS[3]
    return {
        "id": SFTP_LINK_ID,
        "workspace_id": WORKSPACES["atlas"],
        "created_by_user_id": SFTP_USER_ID,
        "label": SFTP_LABEL,
        "access_id": SFTP_ACCESS_ID,
        "password_hash": SFTP_PASSWORD_HASH,
        "status": status,
        "expires_at": None,
        "max_file_size_mb": 100,
        "allowed_extensions": ["pdf"],
        "created_at": SFTP_TIMESTAMPS[0],
        "updated_at": updated_at,
    }


def _sftp_audit_rows() -> list[dict[str, object]]:
    common = {
        "workspace_id": WORKSPACES["atlas"],
        "trace_id": None,
        "agent_id": None,
    }
    return [
        {
            **common,
            "id": SFTP_AUDIT_IDS[0],
            "timestamp": SFTP_TIMESTAMPS[1],
            "event_type": "deposit.link.created",
            "actor": SFTP_OPERATOR,
            "details": {
                "access_id": SFTP_ACCESS_ID,
                "link_id": SFTP_LINK_ID,
                "label": SFTP_LABEL,
            },
            "severity": "info",
        },
        {
            **common,
            "id": SFTP_AUDIT_IDS[1],
            "timestamp": SFTP_TIMESTAMPS[2],
            "event_type": "deposit.sftp.auth.success",
            "actor": f"sftp:{SFTP_ACCESS_ID}",
            "details": {
                "access_id": SFTP_ACCESS_ID,
                "link_id": SFTP_LINK_ID,
            },
            "severity": "info",
        },
        {
            **common,
            "id": SFTP_AUDIT_IDS[2],
            "timestamp": SFTP_TIMESTAMPS[4],
            "event_type": "deposit.link.revoked",
            "actor": SFTP_OPERATOR,
            "details": {
                "access_id": SFTP_ACCESS_ID,
                "link_id": SFTP_LINK_ID,
            },
            "severity": "info",
        },
        {
            **common,
            "id": SFTP_AUDIT_IDS[3],
            "timestamp": SFTP_TIMESTAMPS[5],
            "event_type": "deposit.sftp.auth.failed",
            "actor": f"sftp:{SFTP_ACCESS_ID}",
            "details": {
                "access_id": SFTP_ACCESS_ID,
                "link_id": SFTP_LINK_ID,
                "reason": "inactive_or_expired",
            },
            "severity": "warning",
        },
    ]


def _sftp_ledger() -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": audit.SFTP_LEDGER_KIND,
        "live_sha": LIVE_SHA,
        "release_a_sha": SHA,
        "sftp_sha": SFTP_SHA,
        "deployment_id": DEPLOYMENT_ID,
        "hostname_sha256": "d" * 64,
        "workspace_id": WORKSPACES["atlas"],
        "link_id": SFTP_LINK_ID,
        "access_id": SFTP_ACCESS_ID,
        "operator_actor": SFTP_OPERATOR,
        "link_label": SFTP_LABEL,
        "credential_fingerprint_sha256": "e" * 64,
        "sftp_container_id": "f" * 64,
        "sftp_image_id": f"sha256:{'1' * 64}",
        "sftp_port": 2222,
        "runtime_identity_sha256": "2" * 64,
        "active_sftp_session_count": 0,
    }


def _sftp_controlled_audits(*, stage: str) -> dict[str, dict[str, str]]:
    limit = 2 if stage == "active" else 4
    return {
        phase: {
            "primary_key_sha256": audit._sha([row["id"]]),
            "row_sha256": audit._sha(row),
            "occurred_at": audit._utc_timestamp(row["timestamp"]),
        }
        for row, (phase, _, _) in zip(
            _sftp_audit_rows()[:limit], audit.SFTP_AUDIT_PHASES[:limit], strict=True
        )
    }


def _sftp_link_invariant() -> str:
    return audit._sha(
        {
            key: value
            for key, value in _sftp_link_row(status="active").items()
            if key not in {"status", "updated_at"}
        }
    )


def _sftp_fixtures() -> (
    tuple[
        dict[str, object],
        dict[str, object],
        dict[str, object],
        dict[str, object],
    ]
):
    existing_user = _pair("existing-user", "stable")
    existing_audit = _pair("existing-audit", "stable")
    existing_link = _pair("existing-link", "stable")
    existing_file = _pair("existing-file", "stable")
    baseline_tables = {
        "users": _table([existing_user], normalization=["last_login"]),
        "runs": _table([]),
        "skill_invocations": _table([]),
        "systems": _table([]),
        "audit_logs": _table([existing_audit]),
        "deposit_access_links": _table([existing_link]),
        "deposit_files": _table([existing_file]),
        "event_entity": _table([]),
    }
    ledger = _sftp_ledger()
    active_audits = _sftp_controlled_audits(stage="active")
    revoked_audits = _sftp_controlled_audits(stage="revoked")
    active_rows = {
        "deposit_access_links": {
            audit._sha([SFTP_LINK_ID]): audit._sha(_sftp_link_row(status="active"))
        },
        "audit_logs": {
            row["primary_key_sha256"]: row["row_sha256"] for row in active_audits.values()
        },
    }
    revoked_rows = {
        "deposit_access_links": {
            audit._sha([SFTP_LINK_ID]): audit._sha(_sftp_link_row(status="revoked"))
        },
        "audit_logs": {
            row["primary_key_sha256"]: row["row_sha256"] for row in revoked_audits.values()
        },
    }

    post_tables = deepcopy(baseline_tables)
    post_tables["deposit_access_links"] = _table(
        [existing_link, *active_rows["deposit_access_links"].items()],
        controlled_rows=active_rows["deposit_access_links"],
        sftp_link={
            "primary_key_sha256": audit._sha([SFTP_LINK_ID]),
            "row_sha256": active_rows["deposit_access_links"][audit._sha([SFTP_LINK_ID])],
            "invariant_sha256": _sftp_link_invariant(),
            "status": "active",
        },
    )
    post_tables["audit_logs"] = _table(
        [existing_audit, *active_rows["audit_logs"].items()],
        controlled_rows=active_rows["audit_logs"],
        sftp_audits=active_audits,
    )
    final_tables = deepcopy(baseline_tables)
    final_tables["deposit_access_links"] = _table(
        [existing_link, *revoked_rows["deposit_access_links"].items()],
        controlled_rows=revoked_rows["deposit_access_links"],
        sftp_link={
            "primary_key_sha256": audit._sha([SFTP_LINK_ID]),
            "row_sha256": revoked_rows["deposit_access_links"][audit._sha([SFTP_LINK_ID])],
            "invariant_sha256": _sftp_link_invariant(),
            "status": "revoked",
        },
    )
    final_tables["audit_logs"] = _table(
        [existing_audit, *revoked_rows["audit_logs"].items()],
        controlled_rows=revoked_rows["audit_logs"],
        sftp_audits=revoked_audits,
    )
    return (
        _inventory(baseline_tables, with_ledger=False),
        _inventory(post_tables, with_ledger=False),
        _inventory(final_tables, with_ledger=False),
        ledger,
    )


def _compare_sftp(
    baseline: dict[str, object],
    post: dict[str, object],
    final: dict[str, object],
    ledger: dict[str, object],
) -> dict[str, object]:
    ledger_bytes = audit._json_bytes(ledger) + b"\n"
    return audit.compare_sftp_canary_inventory(
        baseline=baseline,
        post_canary=post,
        final=final,
        sftp_ledger=ledger,
        candidate_sha=SHA,
        deployment_id=DEPLOYMENT_ID,
        sftp_ledger_sha256=hashlib.sha256(ledger_bytes).hexdigest(),
        baseline_file_sha256="7" * 64,
        post_canary_file_sha256="8" * 64,
        final_file_sha256="9" * 64,
    )


def test_controlled_canary_comparison_uses_exact_bounded_deltas() -> None:
    baseline, post, final = _fixtures()
    result = _compare(baseline, post, final)

    assert result["result"] == "passed"
    assert all(result["checks"].values())
    assert result["summary"]["added_rows_by_table"] == {
        "audit_logs": 4,
        "runs": 1,
        "skill_invocations": 2,
    }
    assert result["stages"]["final"]["runs"]["expected_delta_count"] == 1
    assert [row["slug"] for row in result["canary_workspaces"]] == sorted(WORKSPACES)
    serialized = json.dumps(result)
    for raw_identity in [RUN_ID, *INVOCATION_IDS, *WORKSPACES.values()]:
        assert raw_identity not in serialized


@pytest.mark.parametrize("mutation", ["modified", "deleted", "foreign_addition"])
def test_controlled_canary_rejects_unapproved_business_mutation(mutation: str) -> None:
    baseline, post, final = _fixtures()
    tables = final["tables"]
    assert isinstance(tables, dict)
    if mutation == "modified":
        tables["users"] = _table([_pair("existing-user", "changed")], normalization=["last_login"])
    elif mutation == "deleted":
        tables["users"] = _table([], normalization=["last_login"])
    else:
        tables["systems"] = _table([_pair("foreign", "unexpected")])
    _refresh_inventory(final)

    assert _compare(baseline, post, final)["result"] == "failed"


def test_unlisted_keycloak_like_table_is_not_volatile() -> None:
    baseline, post, final = _fixtures()
    for inventory in (baseline, post, final):
        tables = inventory["tables"]
        assert isinstance(tables, dict)
        tables["user_session_shadow"] = _table([])
        _refresh_inventory(inventory)
    final_tables = final["tables"]
    assert isinstance(final_tables, dict)
    final_tables["user_session_shadow"] = _table([_pair("foreign-session", "unexpected")])
    _refresh_inventory(final)

    assert "user_session_shadow" not in audit.KEYCLOAK_VOLATILE_TABLES
    assert _compare(baseline, post, final)["result"] == "failed"


def test_explicit_keycloak_volatile_table_is_allowed() -> None:
    baseline, post, final = _fixtures()
    for inventory in (post, final):
        tables = inventory["tables"]
        assert isinstance(tables, dict)
        tables["event_entity"] = _table([_pair("login-event", "volatile")])
        _refresh_inventory(inventory)

    assert _compare(baseline, post, final)["result"] == "passed"


def test_controlled_details_must_match_ledger_and_full_table_delta() -> None:
    baseline, post, final = _fixtures()
    tables = final["tables"]
    assert isinstance(tables, dict)
    controlled = _pair(RUN_ID, "controlled-run")
    foreign = _pair("40000000-0000-0000-0000-000000000001", "foreign")
    tables["runs"] = _table(
        [controlled, foreign],
        controlled_rows=dict([controlled]),
    )
    _refresh_inventory(final)

    assert _compare(baseline, post, final)["result"] == "failed"


def test_navigation_aggregate_delta_must_be_canonical_for_each_workspace() -> None:
    baseline, post, final = _fixtures()
    audit_table = final["tables"]["audit_logs"]
    assert isinstance(audit_table, dict)
    navigation = audit_table["canonical_navigation_by_workspace"]
    assert isinstance(navigation, dict)
    navigation.pop(audit._sha([WORKSPACES["cinder"]]))
    _refresh_inventory(final)

    assert _compare(baseline, post, final)["result"] == "failed"


def test_canary_workspace_set_is_dynamic_but_navigation_bound() -> None:
    baseline, post, final = _fixtures()
    extra_id = "30000000-0000-0000-0000-000000000005"
    identities = baseline["workspace_identities"]
    assert isinstance(identities, list)
    identities.append({"slug": "foreign", "workspace_id_sha256": audit._sha([extra_id])})
    identities.sort(key=lambda item: item["slug"])
    for inventory in (baseline, post, final):
        inventory["workspace_identities"] = deepcopy(identities)
        _refresh_inventory(inventory)

    comparison = _compare(
        baseline,
        post,
        final,
        workspace_ids=[*list(WORKSPACES.values())[:3], extra_id],
    )
    assert comparison["result"] == "failed"


def test_ledger_identity_mismatch_is_rejected() -> None:
    baseline, post, final = _fixtures()
    ledger = _ledger()
    ledger["commit_sha"] = "f" * 40

    with pytest.raises(audit.PostCanaryDatabaseError, match="ledger is invalid"):
        _compare(baseline, post, final, ledger=ledger)


def test_commutative_multiset_is_order_independent_and_domain_separated() -> None:
    rows = [_pair(f"row-{index}", f"value-{index}") for index in range(20)]
    forward = audit._MultisetAccumulator()
    backward = audit._MultisetAccumulator()
    for primary_key_hash, row_hash in rows:
        forward.add_hashes(primary_key_hash, row_hash)
    for primary_key_hash, row_hash in reversed(rows):
        backward.add_hashes(primary_key_hash, row_hash)

    assert forward.count == backward.count == len(rows)
    assert forward.contract() == backward.contract()
    contract = forward.contract()
    assert contract["domains"] == audit.ACCUMULATOR_DOMAINS
    assert len(set(contract["sums"].values())) == 2


def test_artifact_shape_remains_bounded_for_two_and_a_half_million_rows() -> None:
    accumulator = audit._MultisetAccumulator()
    accumulator.add_hashes("1" * 64, "2" * 64, multiplicity=2_500_000)
    table = audit._table_payload(
        primary_keys=["id"],
        accumulator=accumulator,
        normalization=[],
        controlled_rows={},
        canonical_navigation={},
    )
    serialized = json.dumps(table, sort_keys=True)

    assert table["row_count"] == 2_500_000
    assert "rows" not in table
    assert len(serialized.encode("utf-8")) < 1_024
    assert set(table["multiset"]["sums"]) == {"primary_key", "row_state"}


def test_snapshot_cli_accepts_optional_ledger_and_binds_its_digest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ledger_path = tmp_path / "ledger.json"
    ledger_bytes = json.dumps(_ledger(), sort_keys=True).encode("utf-8")
    ledger_path.write_bytes(ledger_bytes)
    captured: dict[str, Any] = {}

    def fake_build_inventory(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"result": "passed", "content_serialized": False}

    monkeypatch.setattr(audit, "build_inventory", fake_build_inventory)
    code = audit.main(
        [
            "snapshot",
            "--sha",
            SHA,
            "--deployment-id",
            DEPLOYMENT_ID,
            "--ledger",
            str(ledger_path),
        ]
    )

    assert code == 0
    assert captured["ledger"] == _ledger()
    assert captured["ledger_sha256"] == hashlib.sha256(ledger_bytes).hexdigest()
    assert json.loads(capsys.readouterr().out)["content_serialized"] is False


def test_sftp_lifecycle_comparison_allows_only_the_exact_private_ledger_delta() -> None:
    baseline, post, final, ledger = _sftp_fixtures()

    result = _compare_sftp(baseline, post, final, ledger)

    assert result["result"] == "passed"
    assert result["kind"] == "agentium-release-a-sftp-postgres-ledger"
    assert set(result) == {
        "schema_version",
        "kind",
        "result",
        "live_sha",
        "release_a_sha",
        "sftp_sha",
        "deployment_id",
        "hostname_sha256",
        "workspace_id_sha256",
        "link_id_sha256",
        "access_id_sha256",
        "credential_fingerprint_sha256",
        "sftp_container_id",
        "sftp_image_id",
        "sftp_port",
        "runtime_identity_sha256",
        "link_status",
        "auth_failed_reason",
        "remaining_active_link_count",
        "active_sftp_session_count",
        "deposit_file_delta_count",
        "audits",
        "binding_sha256",
        "collected_at",
    }
    assert result["link_status"] == "revoked"
    assert result["auth_failed_reason"] == "inactive_or_expired"
    assert result["remaining_active_link_count"] == 0
    assert result["active_sftp_session_count"] == 0
    assert result["deposit_file_delta_count"] == 0
    assert set(result["audits"]) == {
        "created",
        "auth_success",
        "revoked",
        "auth_failed_inactive",
    }
    assert all(row["count"] == 1 for row in result["audits"].values())
    assert result["binding_sha256"] == audit._release_a_ledger_binding(result)
    encoded = audit._canonical_sftp_receipt(result)
    assert len(encoded) <= audit.MAX_SFTP_RECEIPT_BYTES
    assert (
        encoded
        == (
            json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        ).encode()
    )
    for private_value in (
        SFTP_LINK_ID,
        SFTP_ACCESS_ID,
        SFTP_USER_ID,
        WORKSPACES["atlas"],
        SFTP_LABEL,
        SFTP_PASSWORD_HASH,
        SFTP_OPERATOR,
        *SFTP_AUDIT_IDS,
    ):
        assert private_value.encode() not in encoded


@pytest.mark.parametrize(
    "mutation",
    [
        "deposit_file_added",
        "other_table_added",
        "preexisting_row_modified",
        "preexisting_row_deleted",
        "audit_added",
        "audit_missing",
        "audit_duplicate",
        "link_modified",
        "link_invariant_modified",
        "audit_suppressed",
    ],
)
def test_sftp_lifecycle_rejects_every_unexpected_database_delta(
    mutation: str,
) -> None:
    baseline, post, final, ledger = _sftp_fixtures()
    tables = final["tables"]
    assert isinstance(tables, dict)
    audit_table = tables["audit_logs"]
    assert isinstance(audit_table, dict)
    link_table = tables["deposit_access_links"]
    assert isinstance(link_table, dict)
    revoked_audit_rows = dict(audit_table["controlled_rows"])
    revoked_audits = deepcopy(audit_table["controlled_sftp_audits"])
    existing_audit = _pair("existing-audit", "stable")
    if mutation == "deposit_file_added":
        tables["deposit_files"] = _table(
            [
                _pair("existing-file", "stable"),
                _pair("unexpected-file", "forbidden"),
            ]
        )
    elif mutation == "other_table_added":
        tables["systems"] = _table([_pair("unexpected-system", "forbidden")])
    elif mutation == "preexisting_row_modified":
        tables["users"] = _table([_pair("existing-user", "changed")], normalization=["last_login"])
    elif mutation == "preexisting_row_deleted":
        tables["users"] = _table([], normalization=["last_login"])
    elif mutation == "audit_added":
        tables["audit_logs"] = _table(
            [
                existing_audit,
                *revoked_audit_rows.items(),
                _pair("unexpected-audit", "forbidden"),
            ],
            controlled_rows=revoked_audit_rows,
            sftp_audits=revoked_audits,
        )
    elif mutation == "audit_missing":
        removed_phase = "auth_failed_inactive"
        removed = revoked_audits.pop(removed_phase)
        retained = {
            key: value
            for key, value in revoked_audit_rows.items()
            if key != removed["primary_key_sha256"]
        }
        tables["audit_logs"] = _table(
            [existing_audit, *retained.items()],
            controlled_rows=retained,
            sftp_audits=revoked_audits,
        )
    elif mutation == "audit_duplicate":
        duplicated = next(iter(revoked_audit_rows.items()))
        tables["audit_logs"] = _table(
            [existing_audit, *revoked_audit_rows.items(), duplicated],
            controlled_rows=revoked_audit_rows,
            sftp_audits=revoked_audits,
        )
    elif mutation == "link_modified":
        link_hash = audit._sha([SFTP_LINK_ID])
        changed = audit._sha({"forbidden": "modified"})
        tables["deposit_access_links"] = _table(
            [_pair("existing-link", "stable"), (link_hash, changed)],
            controlled_rows={link_hash: changed},
        )
    elif mutation == "link_invariant_modified":
        revoked_link_rows = dict(link_table["controlled_rows"])
        link_hash, link_row_hash = next(iter(revoked_link_rows.items()))
        tables["deposit_access_links"] = _table(
            [_pair("existing-link", "stable"), (link_hash, link_row_hash)],
            controlled_rows=revoked_link_rows,
            sftp_link={
                "primary_key_sha256": link_hash,
                "row_sha256": link_row_hash,
                "invariant_sha256": "f" * 64,
                "status": "revoked",
            },
        )
    else:
        tables["audit_logs"] = _table(
            list(revoked_audit_rows.items()),
            controlled_rows=revoked_audit_rows,
            sftp_audits=revoked_audits,
        )
    _refresh_inventory(final)

    with pytest.raises(audit.PostCanaryDatabaseError):
        _compare_sftp(baseline, post, final, ledger)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_key",
        "extra_key",
        "release_mismatch",
        "deployment_mismatch",
        "live_equals_release",
        "invalid_workspace",
        "invalid_access",
        "non_canary_access",
        "active_session",
        "invalid_container",
        "invalid_image",
    ],
)
def test_sftp_private_ledger_is_closed_and_fail_closed(
    mutation: str,
) -> None:
    baseline, post, final, ledger = _sftp_fixtures()
    if mutation == "missing_key":
        ledger.pop("workspace_id")
    elif mutation == "extra_key":
        ledger["raw_password"] = "forbidden"
    elif mutation == "release_mismatch":
        ledger["release_a_sha"] = "f" * 40
    elif mutation == "deployment_mismatch":
        ledger["deployment_id"] = "foreign-deployment"
    elif mutation == "live_equals_release":
        ledger["live_sha"] = SHA
    elif mutation == "invalid_workspace":
        ledger["workspace_id"] = "not-a-uuid"
    elif mutation == "invalid_access":
        ledger["access_id"] = " access "
    elif mutation == "non_canary_access":
        ledger["access_id"] = "ordinary-access"
    elif mutation == "active_session":
        ledger["active_sftp_session_count"] = 1
    elif mutation == "invalid_container":
        ledger["sftp_container_id"] = "f" * 63
    else:
        ledger["sftp_image_id"] = "1" * 64

    with pytest.raises(audit.PostCanaryDatabaseError, match="SFTP"):
        _compare_sftp(baseline, post, final, ledger)


def test_sftp_private_rows_are_semantically_verified_before_hashes_escape() -> None:
    ledger = audit._sftp_ledger_contract(
        _sftp_ledger(), candidate_sha=SHA, deployment_id=DEPLOYMENT_ID
    )
    active_link = _sftp_link_row(status="active")
    active_audits = _sftp_audit_rows()[:2]
    observed: dict[str, datetime] = {}

    assert audit._sftp_controlled_row_semantics(
        table_name="deposit_access_links",
        row=active_link,
        row_sha256=audit._sha(active_link),
        primary_key_sha256=audit._sha([SFTP_LINK_ID]),
        ledger=ledger,
        stage="active",
        observed_timestamps=observed,
    )
    for row in active_audits:
        assert audit._sftp_controlled_row_semantics(
            table_name="audit_logs",
            row=row,
            row_sha256=audit._sha(row),
            primary_key_sha256=audit._sha([row["id"]]),
            ledger=ledger,
            stage="active",
            observed_timestamps=observed,
        )
    audit._validate_sftp_observed_timestamps(observed, stage="active")


def test_sftp_semantics_rejects_forged_inactive_reason_before_hashing() -> None:
    forged = _sftp_audit_rows()[-1]
    forged["details"] = {**forged["details"], "reason": "bad_password"}
    ledger = audit._sftp_ledger_contract(
        _sftp_ledger(), candidate_sha=SHA, deployment_id=DEPLOYMENT_ID
    )

    assert not audit._sftp_controlled_row_semantics(
        table_name="audit_logs",
        row=forged,
        row_sha256=audit._sha(forged),
        primary_key_sha256=audit._sha([forged["id"]]),
        ledger=ledger,
        stage="revoked",
        observed_timestamps={},
    )


def test_sftp_compare_cli_emits_one_bounded_canonical_content_free_receipt(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline, post, final, ledger = _sftp_fixtures()
    paths = {}
    for name, payload in (
        ("baseline", baseline),
        ("post", post),
        ("final", final),
        ("ledger", ledger),
    ):
        path = tmp_path / f"{name}.json"
        path.write_bytes(audit._json_bytes(payload) + b"\n")
        if name == "ledger":
            path.chmod(0o600)
        paths[name] = path

    code = audit.main(
        [
            "compare-sftp-canary",
            "--sha",
            SHA,
            "--deployment-id",
            DEPLOYMENT_ID,
            "--baseline",
            str(paths["baseline"]),
            "--post-canary",
            str(paths["post"]),
            "--final",
            str(paths["final"]),
            "--sftp-ledger",
            str(paths["ledger"]),
        ]
    )

    assert code == 0
    output = capsys.readouterr().out.encode()
    assert len(output) <= audit.MAX_SFTP_RECEIPT_BYTES
    parsed = json.loads(output)
    assert output == audit._canonical_sftp_receipt(parsed)
    assert parsed["result"] == "passed"
    assert SFTP_ACCESS_ID.encode() not in output


def test_sftp_snapshot_cli_requires_and_passes_a_strict_stage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ledger_path = tmp_path / "sftp-ledger.json"
    ledger_path.write_bytes(audit._json_bytes(_sftp_ledger()) + b"\n")
    ledger_path.chmod(0o600)
    captured: dict[str, Any] = {}

    def fake_build_inventory(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"result": "passed", "content_serialized": False}

    monkeypatch.setattr(audit, "build_inventory", fake_build_inventory)
    code = audit.main(
        [
            "snapshot",
            "--sha",
            SHA,
            "--deployment-id",
            DEPLOYMENT_ID,
            "--sftp-ledger",
            str(ledger_path),
            "--sftp-stage",
            "active",
        ]
    )

    assert code == 0
    assert captured["sftp_ledger"] == _sftp_ledger()
    assert captured["sftp_stage"] == "active"
    assert json.loads(capsys.readouterr().out)["content_serialized"] is False


def test_sftp_private_ledger_reader_rejects_world_readable_and_symlinked_files(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_bytes(audit._json_bytes(_sftp_ledger()) + b"\n")
    ledger_path.chmod(0o644)
    with pytest.raises(audit.PostCanaryDatabaseError, match="private"):
        audit._read_private_sftp_ledger(str(ledger_path))

    ledger_path.chmod(0o600)
    symlink = tmp_path / "ledger-link.json"
    symlink.symlink_to(ledger_path)
    with pytest.raises(audit.PostCanaryDatabaseError, match="unavailable"):
        audit._read_private_sftp_ledger(str(symlink))


def test_sftp_private_ledger_reader_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_bytes(b'{"schema_version":1,"schema_version":1}\n')
    ledger_path.chmod(0o600)

    with pytest.raises(audit.PostCanaryDatabaseError, match="duplicate"):
        audit._read_private_sftp_ledger(str(ledger_path))


def test_collector_source_has_no_per_table_row_inventory() -> None:
    source = Path(audit.__file__).read_text(encoding="utf-8")

    assert "rows: list[" not in source
    assert "seen_primary_keys" not in source
    assert "stream_results=True" in source
    assert '"rows": rows' not in source
