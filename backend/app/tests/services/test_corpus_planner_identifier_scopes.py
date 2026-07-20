from __future__ import annotations

from app.models.workspace import Workspace
from app.services.knowledge_collections import create_collection, upsert_collection_source
from app.services.rag.corpus_planner import _source_lookup_terms, plan_corpus


def test_source_lookup_terms_keep_identifiers_and_drop_generic_or_measurement_noise():
    assert _source_lookup_terms([], "Que dit la notice TTN17829J ?") == {"ttn17829j"}
    assert _source_lookup_terms([], "Que dit le manuel TTN17829J ?") == {"ttn17829j"}
    assert _source_lookup_terms([], "10000 rpm") == set()
    assert _source_lookup_terms([], "notice 12345") == {"12345"}

    # Explicit project scopes are injected before query-term filtering. This
    # helper must not silently discard one even if the free-text query resembles
    # a measurement; project identity remains owned by project_references.
    assert _source_lookup_terms(["10000"], "10000 rpm") == {"10000"}


def test_large_corpus_keeps_document_identifiers_separate_from_project_identity(db_session):
    workspace = Workspace(
        id="ws-identifier-scope",
        name="Identifier scope",
        slug="identifier-scope",
    )
    db_session.add(workspace)
    db_session.flush()
    collection = create_collection(
        db_session,
        workspace=workspace,
        name="Dense technical notices",
    )

    # Reproduce the production failure: more than the SQL targeting cap sort
    # before the Needlepunch logical name and contain generic operator-manual
    # vocabulary plus ``10000`` as a substring of a longer industrial number.
    for index in range(205):
        upsert_collection_source(
            db_session,
            collection=collection,
            filename=(
                f"A__legacy_{index:03d}__561000000xx001_"
                "Operator_manual_notice_operation.pdf"
            ),
            status="ready",
            chunk_count=1,
            source_metadata={"project_code": "BAO100"},
        )

    ttn_filename = (
        "needlepunch__61035__TTN17829J_Operation_and_maintenance_manual_"
        "Needle_Punch_A50R.pdf"
    )
    v_filename = "needlepunch__61035__V10234_variant.pdf"
    numeric_part_filename = "needlepunch__61035__notice_part_12345.pdf"
    for filename in (ttn_filename, v_filename, numeric_part_filename):
        upsert_collection_source(
            db_session,
            collection=collection,
            filename=filename,
            status="ready",
            chunk_count=3,
            source_metadata={"project_code": "61035"},
        )

    collection.status = "ready"
    collection.document_count = 6_000
    collection.chunk_count = 60_000
    db_session.commit()

    profile = {
        "collection": collection.slug,
        "collections": [collection.slug],
        "workspace_id": workspace.id,
        "latency_profile": "fast",
        "rag_mode": "auto",
    }

    ttn_plan = plan_corpus(
        db=db_session,
        profile=profile,
        query="Que dit la notice TTN17829J ?",
    )
    assert ttn_plan.filters == {"document_filename": [ttn_filename]}
    assert "project_code" not in ttn_plan.filters

    measurement_plan = plan_corpus(
        db=db_session,
        profile=profile,
        query="10000 rpm",
    )
    assert "document_filename" not in measurement_plan.filters
    assert "project_code" not in measurement_plan.filters

    variant_plan = plan_corpus(
        db=db_session,
        profile=profile,
        query="variante V10234",
    )
    assert variant_plan.filters == {"document_filename": [v_filename]}
    assert "project_code" not in variant_plan.filters

    numeric_part_plan = plan_corpus(
        db=db_session,
        profile=profile,
        query="notice 12345",
    )
    assert numeric_part_plan.filters == {"document_filename": [numeric_part_filename]}
    assert "project_code" not in numeric_part_plan.filters
