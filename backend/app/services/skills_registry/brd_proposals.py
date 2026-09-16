"""Server-owned proposal snapshots; mappings never imply successful tests."""
from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models.brd_proposal import BrdProposal
from app.services.flow_contracts import canonical_sha256


def coverage(extraction, mappings, *, node_ids, case_ids):
    """Use source positions, not potentially duplicate BRD reference labels."""
    sources = {
        (item["table"], item["row"]): item
        for item in extraction.get("provenance", [])
        if item["section"] in {"functional requirements", "business rules", "prohibitions", "decisions"}
    }
    selected = {}
    for mapping in mappings:
        key = (mapping["table"], mapping["row"])
        if key not in sources or key in selected:
            raise HTTPException(422, "Unknown or duplicate BRD source mapping")
        if not set(mapping["node_ids"]).issubset(node_ids):
            raise HTTPException(422, "A requirement maps to an unknown operation")
        if not set(mapping["case_ids"]).issubset(case_ids):
            raise HTTPException(422, "A requirement maps to an unknown test case")
        selected[key] = mapping
    result = []
    for key, source in sources.items():
        mapping = selected.get(key, {})
        nodes, cases = mapping.get("node_ids", []), mapping.get("case_ids", [])
        result.append({
            **source, "node_ids": nodes, "case_ids": cases,
            "status": "proposed" if nodes and cases else "uncovered",
            "reason": mapping.get("reason", ""),
            "test_verdict": "not_run",
        })
    return result


def retain_proposal(db, *, document, user, request_key, proposal):
    snapshot = {**deepcopy(proposal), "document_id": document.id, "document_sha256": document.sha256}
    digest = canonical_sha256(snapshot)
    query = db.query(BrdProposal).filter_by(
        workspace_id=document.workspace_id, created_by_user_id=user.id, request_key=request_key
    )
    def replay(row):
        if row.sha256 != digest:
            raise HTTPException(409, "Request key already used for a different BRD proposal")
        return row
    previous = query.first()
    if previous:
        return replay(previous)
    row = BrdProposal(
        workspace_id=document.workspace_id, document_id=document.id,
        created_by_user_id=user.id, request_key=request_key, sha256=digest,
        proposal=snapshot,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        previous = query.first()
        if previous is None:
            raise
        return replay(previous)
    db.commit()
    return row


def proposal_payload(row):
    return {"id": row.id, "sha256": row.sha256, "status": row.status,
            "system_id": row.system_id, "proposal": deepcopy(row.proposal)}
