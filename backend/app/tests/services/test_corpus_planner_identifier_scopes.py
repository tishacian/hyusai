from __future__ import annotations

from app.models.workspace import Workspace
from app.services.knowledge_collections import create_collection, upsert_collection_source
from app.services.rag.corpus_planner import _source_lookup_terms, plan_corpus

# Production shape of andritz-notices-techniques-spl-pilot: large enough for the
# dense guardrail and the bounded DB-side targeting to be the planner path.
_PILOT_DOCUMENT_COUNT = 6_000
_PILOT_CHUNK_COUNT = 60_000


def _pilot_collection(db_session, *, workspace_id: str, name: str, filenames: tuple[str, ...]):
    workspace = Workspace(id=workspace_id, name=name, slug=workspace_id)
    db_session.add(workspace)
    db_session.flush()
    collection = create_collection(db_session, workspace=workspace, name=name)
    for filename in filenames:
        upsert_collection_source(
            db_session,
            collection=collection,
            filename=filename,
            status="ready",
            chunk_count=150,
        )
    collection.status = "ready"
    collection.document_count = _PILOT_DOCUMENT_COUNT
    collection.chunk_count = _PILOT_CHUNK_COUNT
    db_session.commit()
    return workspace, collection


def _pilot_profile(workspace, collection) -> dict:
    return {
        "collection": collection.slug,
        "collections": [collection.slug],
        "workspace_id": workspace.id,
        "latency_profile": "fast",
        "rag_mode": "auto",
    }


def test_source_lookup_terms_keep_identifiers_and_drop_generic_or_measurement_noise():
    assert _source_lookup_terms([], "Que dit la notice TTN17829J ?") == {"ttn17829j"}
    assert _source_lookup_terms([], "Que dit le manuel TTN17829J ?") == {"ttn17829j"}
    assert _source_lookup_terms([], "10000 rpm") == set()
    assert _source_lookup_terms([], "notice 12345") == {"12345"}
    # A line position is two characters, well under the >=5 filename signal,
    # yet it is the only token separating the J1 documents from every other
    # conveyor document of the deposit.
    assert "j1" in _source_lookup_terms([], "la toile du convoyeur j1")

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

    # A strong numeric project query must not turn an embedded substring in an
    # unrelated historical identifier into a filename scope.  Project 61001 is
    # deliberately absent from the ledger at this point: this is the promotion
    # canary state immediately before its first wave is indexed.
    false_61001_filenames = []
    for index in range(3):
        filename = f"A__legacy_BID6100194_{index}__technical_notice.pdf"
        false_61001_filenames.append(filename)
        upsert_collection_source(
            db_session,
            collection=collection,
            filename=filename,
            status="ready",
            chunk_count=2,
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

    unseen_project_plan = plan_corpus(
        db=db_session,
        profile=profile,
        query="Résume le projet 61001",
    )
    assert unseen_project_plan.filters == {"project_code": "61001"}
    assert "document_filename" not in unseen_project_plan.filters
    assert not any(
        filename in str(unseen_project_plan.filters)
        for filename in false_61001_filenames
    )

    numeric_summary_plan = plan_corpus(
        db=db_session,
        profile=profile,
        query="Résume le projet 61035 en citant précisément les documents utilisés.",
    )
    assert numeric_summary_plan.intent == "content_search"
    assert numeric_summary_plan.dense_policy != "catalogue_inventory"
    assert numeric_summary_plan.filters == {"project_code": ["61035"]}

    spl_summary_plan = plan_corpus(
        db=db_session,
        profile=profile,
        query="Peux-tu résumer le projet BAO100 avec les sources utilisées ?",
    )
    assert spl_summary_plan.intent == "content_search"
    assert spl_summary_plan.dense_policy != "catalogue_inventory"
    assert spl_summary_plan.filters == {"project_code": ["BAO100"]}

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


_BEX200_CONVEYOR = (
    "B__BEX200-RevB__BEX200-RevB__files__section_IV__Hydroentanglement-unit__"
    "sub-section_5__V.1.Conveyor__convoyeur-jetlace.pdf"
)
_CBX300_CONVEYOR = (
    "C__CBX300__CBX300__files__section_IV__Hydroentanglement-unit__"
    "sub-section_5__V.1.Conveyor__convoyeur-jetlace.pdf"
)
_ASY200_SPARE_PARTS = "A__Manual_ASY200__Manual_ASY200__Spare Parts List_ASY200.pdf"
_AVA200_PRINTABLE = "A__AVA200__AVA200__fichiers__printable version__AVA100 RUS.pdf"


def test_line_position_query_does_not_lock_scope_on_a_family_only_match(db_session):
    """Regression on "quelle est la référence de la toile du convoyeur J1".

    Every hydroentanglement unit of the deposit ships a conveyor section, so the
    conveyor family matches dozens of documents equally. That family hit alone
    used to be treated as a strong phrase match and pinned a hard
    document_filename allowlist on the first such section (a BEX200 one), while
    the belt reference actually lives in the AVA200/ASY200 spare-parts lists
    whose filenames advertise none of the query's words. J1 is a station, never
    a project code, so nothing else narrowed the scope back.
    """
    workspace, collection = _pilot_collection(
        db_session,
        workspace_id="ws-line-position-open",
        name="Andritz notices SPL pilot",
        filenames=(
            _BEX200_CONVEYOR,
            _CBX300_CONVEYOR,
            _AVA200_PRINTABLE,
            _ASY200_SPARE_PARTS,
        ),
    )

    plan = plan_corpus(
        db=db_session,
        profile=_pilot_profile(workspace, collection),
        query="quelle est la réference de la toile du convoyeur j1",
    )

    assert "document_filename" not in plan.filters
    assert "BEX200" not in str(plan.filters)
    # Open bounded retrieval plus queued deep refinement: the answer document is
    # reachable again instead of being excluded before retrieval runs.
    assert plan.dense_policy == "fast_sparse_direct"
    assert plan.deep_retrieval_recommended is True


def test_line_position_carried_by_a_filename_keeps_the_document_scope(db_session):
    """The counterpart: a station named in the path is a document-level signal.

    The station document sorts last alphabetically, so leading the allowlist can
    only come from the position bonus.
    """
    j1_conveyor = (
        "T__TNX100__TNX100__files__section_IV__Hydroentanglement-unit__"
        "sub-section_5__V.1.Conveyor J1__convoyeur-jetlace.pdf"
    )
    workspace, collection = _pilot_collection(
        db_session,
        workspace_id="ws-line-position-scoped",
        name="Andritz notices SPL pilot J1",
        filenames=(j1_conveyor, _BEX200_CONVEYOR, _CBX300_CONVEYOR),
    )

    plan = plan_corpus(
        db=db_session,
        profile=_pilot_profile(workspace, collection),
        query="quelle est la réference de la toile du convoyeur j1",
    )

    assert plan.dense_policy == "fast_scoped_dense"
    assert plan.filters["document_filename"][0] == j1_conveyor


def test_family_only_match_no_longer_narrows_the_scope_by_itself(db_session):
    """A conveyor hit is a family, a jetlace hit is a document.

    Both documents belong to the conveyor family, so before the fix both were
    treated as strong phrase matches and the scope collapsed onto them
    indiscriminately. Only the second carries a term of the question that is
    not the family name, and that is what a filename allowlist may key on.
    """
    generic_conveyor = "R__RCZ100__RCZ100__fichiers__users manual__520-convoyeur__conveyor.pdf"
    jetlace_conveyor = (
        "S__SBX400__SBX400__fichiers__users manual__520-convoyeur__conveyor-jetlace-gb b.pdf"
    )
    workspace, collection = _pilot_collection(
        db_session,
        workspace_id="ws-family-only",
        name="Andritz notices SPL pilot families",
        filenames=(generic_conveyor, jetlace_conveyor),
    )

    plan = plan_corpus(
        db=db_session,
        profile=_pilot_profile(workspace, collection),
        query="quelle est la procédure de nettoyage du convoyeur jetlace",
    )

    assert plan.filters == {"document_filename": [jetlace_conveyor]}


def test_session_anchor_returns_the_previous_station_document_to_the_scope(db_session):
    """Regression on the 01/09 "distance entre le C1 et le J1" replan.

    The same session had already answered a J1 question from the ACJ100
    hydroentanglement conveyor notice. Without session memory the follow-up
    carries only stop-words and two stations, so the planner rebuilds a scope
    from scratch and can land on an unrelated carding-servo folder. The
    previously successful document comes back as an extra candidate.
    """
    carding_servo = (
        "T__TNX100__TNX100__files__section_IV__Carding unit__AAT__"
        "03 - SERVO X 91405971__TTN16697J.pdf"
    )
    isojet_conveyor = (
        "A__ACJ100__ACJ100__files__section_iv__hydroentanglement-unit__"
        "sub-section_5__V.1.Conveyor J1.pdf"
    )
    workspace, collection = _pilot_collection(
        db_session,
        workspace_id="ws-session-anchor",
        name="Andritz notices SPL pilot anchors",
        filenames=(carding_servo, isojet_conveyor),
    )
    profile = _pilot_profile(workspace, collection)
    query = "quelle doit être la distance entre le C1 et le J1"

    unanchored_plan = plan_corpus(db=db_session, profile=profile, query=query)
    assert "document_filename" not in unanchored_plan.filters

    anchored_plan = plan_corpus(
        db=db_session,
        profile=profile,
        query=query,
        request={
            "context": {
                "salient_entities": {
                    "references": ["ACJ100"],
                    "positions": ["J1", "C1"],
                    "documents": ["V.1.Conveyor J1.pdf"],
                }
            }
        },
    )

    assert anchored_plan.filters == {"document_filename": [isojet_conveyor]}
    assert "TNX100" not in str(anchored_plan.filters)
