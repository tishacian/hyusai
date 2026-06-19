"""Tests for exhaustive cross-project enumeration via the project_code facet."""
import pytest

from app.services.rag import project_inventory as pi


class _FakeHit:
    def __init__(self, value, count):
        self.value = value
        self.count = count


class _FakeFacetResponse:
    def __init__(self, hits):
        self.hits = hits


class _FakeQdrantClient:
    """Minimal Qdrant client double recording facet calls by term tuple."""

    def __init__(self, mapping, *, exists=True):
        # mapping: tuple(terms) -> list[(project_code, count)]
        self._mapping = mapping
        self._exists = exists
        self.facet_calls: list[tuple[str, ...]] = []

    def collection_exists(self, name):  # noqa: ARG002 - signature parity only.
        return self._exists

    def facet(self, *, collection_name, key, facet_filter, limit, exact):  # noqa: ARG002
        assert key == "project_code"
        terms = tuple(condition.match.text for condition in facet_filter.must)
        self.facet_calls.append(terms)
        hits = self._mapping.get(terms, [])
        return _FakeFacetResponse([_FakeHit(code, count) for code, count in hits])


class _FakeDB:
    def __init__(self, client, collection_name):
        self.client = client
        self.collection_name = collection_name


def _patch_factory(monkeypatch, db_by_slug):
    def fake_get_db(collection_name="documents", db_type="qdrant", workspace_slug=None):
        scoped = f"{workspace_slug}__{collection_name}" if workspace_slug else collection_name
        db = db_by_slug.get(collection_name)
        if db is None:
            raise AssertionError(f"unexpected collection {collection_name}")
        db.collection_name = scoped
        return db

    monkeypatch.setattr(pi.VectorDBFactory, "get_db", staticmethod(fake_get_db))


# --- discriminating-term extraction -----------------------------------------

@pytest.mark.parametrize(
    "query,expected",
    [
        ("donne moi les projets avec une pompe uraca", ["uraca"]),
        ("quels projets utilisent une pompe URACA", ["uraca"]),
        ("donne-moi les projets équipés d'une pompe Uraca", ["uraca"]),
        ("les projets qui ont une pompe Uraca KD724", ["uraca", "kd724"]),
        ("dans quels projets retrouve-t-on un sécheur", []),  # generic only -> no term
    ],
)
def test_extract_inventory_terms_keeps_only_salient_equipment(query, expected):
    assert pi.extract_inventory_terms(query) == expected


def test_query_targets_projects():
    assert pi.query_targets_projects("donne moi les projets avec une pompe uraca") is True
    assert pi.query_targets_projects("quels projets utilisent une pompe URACA") is True
    # Equipment-only inventory must NOT take the project facet path.
    assert pi.query_targets_projects("Liste toutes les pompes Uraca") is False


# --- facet aggregation branch -----------------------------------------------

def test_build_project_inventory_aggregates_facet(monkeypatch):
    client = _FakeQdrantClient(
        {("uraca",): [("BHX100", 3390), ("AKI500", 1326), ("BIO100", 951)]}
    )
    _patch_factory(monkeypatch, {"notices": _FakeDB(client, "notices")})

    result = pi.build_project_inventory(
        {
            "vector_db": "qdrant",
            "workspace_slug": "andritz",
            "collections": ["notices"],
        },
        "donne moi les projets avec une pompe uraca",
    )

    assert result is not None
    assert result["terms"] == ["uraca"]
    assert result["total_projects"] == 3
    # Sorted by chunk_count desc -> BHX100 first (matches the diagnosis).
    assert result["projects"][0] == {"project_code": "BHX100", "chunk_count": 3390}
    assert [p["project_code"] for p in result["projects"]] == ["BHX100", "AKI500", "BIO100"]
    assert client.facet_calls == [("uraca",)]


def test_build_project_inventory_merges_across_collections(monkeypatch):
    client_a = _FakeQdrantClient({("uraca",): [("BHX100", 100), ("AKI500", 50)]})
    client_b = _FakeQdrantClient({("uraca",): [("BHX100", 5), ("ZZZ999", 7)]})
    _patch_factory(
        monkeypatch,
        {"notices": _FakeDB(client_a, "notices"), "deposit": _FakeDB(client_b, "deposit")},
    )

    result = pi.build_project_inventory(
        {
            "vector_db": "qdrant",
            "workspace_slug": "andritz",
            "collections": ["notices", "deposit"],
        },
        "quels projets utilisent une pompe uraca",
    )

    assert result["total_projects"] == 3
    counts = {p["project_code"]: p["chunk_count"] for p in result["projects"]}
    assert counts == {"BHX100": 105, "AKI500": 50, "ZZZ999": 7}
    assert result["collections_faceted"] == 2


def test_build_project_inventory_and_then_single_term_fallback(monkeypatch):
    # AND of both terms returns nothing (a model number that is not a single
    # full-text token); the brand alone still answers.
    client = _FakeQdrantClient(
        {
            ("uraca", "kd724"): [],
            ("uraca",): [("BHX100", 42)],
            ("kd724",): [],
        }
    )
    _patch_factory(monkeypatch, {"notices": _FakeDB(client, "notices")})

    result = pi.build_project_inventory(
        {"vector_db": "qdrant", "workspace_slug": "andritz", "collections": ["notices"]},
        "les projets avec une pompe uraca kd724",
    )

    assert result is not None
    assert [p["project_code"] for p in result["projects"]] == ["BHX100"]
    assert ("uraca", "kd724") in client.facet_calls  # AND attempted first


def test_build_project_inventory_returns_none_without_discriminating_term(monkeypatch):
    _patch_factory(monkeypatch, {"notices": _FakeDB(_FakeQdrantClient({}), "notices")})
    assert (
        pi.build_project_inventory(
            {"vector_db": "qdrant", "workspace_slug": "andritz", "collections": ["notices"]},
            "donne moi les projets",
        )
        is None
    )


def test_build_project_inventory_skips_non_qdrant_backend():
    assert (
        pi.build_project_inventory(
            {"vector_db": "faiss", "workspace_slug": "andritz", "collections": ["notices"]},
            "donne moi les projets avec une pompe uraca",
        )
        is None
    )


def test_build_project_inventory_none_when_facet_empty(monkeypatch):
    client = _FakeQdrantClient({("uraca",): []})
    _patch_factory(monkeypatch, {"notices": _FakeDB(client, "notices")})
    assert (
        pi.build_project_inventory(
            {"vector_db": "qdrant", "workspace_slug": "andritz", "collections": ["notices"]},
            "donne moi les projets avec une pompe uraca",
        )
        is None
    )


def test_build_project_inventory_survives_facet_error(monkeypatch):
    class _BoomClient(_FakeQdrantClient):
        def facet(self, **kwargs):  # noqa: ARG002
            raise RuntimeError("facet unsupported")

    _patch_factory(monkeypatch, {"notices": _FakeDB(_BoomClient({}), "notices")})
    # A Qdrant error must degrade to None (deep-retrieval fallback), not raise.
    assert (
        pi.build_project_inventory(
            {"vector_db": "qdrant", "workspace_slug": "andritz", "collections": ["notices"]},
            "donne moi les projets avec une pompe uraca",
        )
        is None
    )


# --- gating in the retrieval layer ------------------------------------------

def test_should_build_project_inventory_gating():
    from app.services.rag.context import _should_build_project_inventory

    transversal = {
        "answer_profile": "transversal_inventory",
        "answer_profile_decision": {
            "profile": "transversal_inventory",
            "requires_exhaustive_retrieval": True,
        },
    }
    assert (
        _should_build_project_inventory(transversal, "donne moi les projets avec une pompe uraca")
        is True
    )
    # Transversal but equipment-only (no project enumeration) -> no facet.
    assert _should_build_project_inventory(transversal, "liste toutes les pompes uraca") is False
    # A precise single-project fact question must never trigger the facet.
    precise = {
        "answer_profile": "precise_fact",
        "answer_profile_decision": {"profile": "precise_fact"},
    }
    assert (
        _should_build_project_inventory(precise, "quelle pompe est utilisée dans le projet AKK200 ?")
        is False
    )


# --- answer-context injection -----------------------------------------------

def test_inventory_block_reaches_answer_context():
    from app.agents.procurement_agent import _format_project_inventory_block

    block = _format_project_inventory_block(
        {
            "terms": ["uraca"],
            "total_projects": 3,
            "projects": [
                {"project_code": "BHX100", "chunk_count": 3390},
                {"project_code": "AKI500", "chunk_count": 1326},
                {"project_code": "BIO100", "chunk_count": 951},
            ],
        }
    )
    assert "couverture exhaustive" in block
    assert "3 projet(s) au total" in block
    assert "BHX100 (3390)" in block
    assert "AKI500 (1326)" in block
    assert "BIO100 (951)" in block
    # No facet aggregation -> no block (regular deep path, no regression).
    assert _format_project_inventory_block(None) == ""
    assert _format_project_inventory_block({"projects": []}) == ""
