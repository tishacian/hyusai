"""Document-family facets belong to the tenant that has those documents.

The built-in facets describe one customer's corpus: spare-parts lists,
injector notices, pump and conveyor manuals, pneumatic cabinets, with French
and English trigger words such as "joint", "pompe", "cartouche". They applied
to every workspace, so unrelated vocabulary activated them, expanded queries
with parts terms and boosted parts-shaped documents.
"""

from __future__ import annotations

from app.services.rag.project_references import bind_project_reference_scheme
from app.services.rag.retrieval_policy import RetrievalPolicy, SourceFamilyRule
from app.services.rag.source_facets import (
    active_source_family_facets,
    expanded_terms_for_query,
    source_family_facets,
)

UNRELATED_QUERIES = [
    "congé joint parental",
    "la pompe à chaleur du bureau",
    "remplacer la cartouche de l'imprimante",
]


def test_a_third_tenant_gets_none_of_the_built_in_facets():
    with bind_project_reference_scheme(""):
        assert source_family_facets() == ()
        for query in UNRELATED_QUERIES:
            assert active_source_family_facets(query) == ()
            assert expanded_terms_for_query(query) == ()


def test_the_andritz_tenant_keeps_its_facets():
    with bind_project_reference_scheme("andritz"):
        keys = {facet.key for facet in source_family_facets()}
        assert "spare_parts_list" in keys
        assert {f.key for f in active_source_family_facets("la Spare Parts List ACO150")} >= {
            "spare_parts_list"
        }


def test_a_third_tenant_still_gets_the_facets_its_own_guide_declares():
    """The guide policy is the mechanism meant for this, and it is kept."""

    policy = RetrievalPolicy(
        source_family_rules=(
            SourceFamilyRule(when_terms=("contrat", "avenant"), source_families=("contract_amendment",)),
        ),
    )
    with bind_project_reference_scheme(""):
        keys = {facet.key for facet in source_family_facets(policy)}
        assert keys == {"contract_amendment"}
        active = active_source_family_facets("quel avenant au contrat de bail ?", policy)
        assert [facet.key for facet in active] == ["contract_amendment"]
