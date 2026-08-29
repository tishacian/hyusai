"""Deterministic PR→PO helpers used by python_recipe nodes and tests.

The walker has a ``loop`` kind, but it only invokes one skill per item — it
cannot nest budget → decision → HITL. v1 therefore processes **one PR per
scheduled tick**: list, then select the pinned or first remaining approved PR.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping


def select_next_pr(payload: Mapping[str, Any]) -> dict[str, Any]:
    prs = payload.get("prs")
    rows = [dict(item) for item in prs] if isinstance(prs, list) else []
    pin = str(payload.get("pr_id") or "").strip()
    chosen = None
    if pin:
        chosen = next((row for row in rows if str(row.get("pr_id") or "") == pin), None)
    if chosen is None and rows:
        chosen = rows[0]
    if not isinstance(chosen, dict):
        return {"pr_id": "", "pr": None, "pr_type": "", "empty": True, "prs": rows}
    pr_type = str(chosen.get("pr_type") or chosen.get("type") or "")
    return {
        "pr_id": str(chosen.get("pr_id") or ""),
        "pr": chosen,
        "pr_type": pr_type,
        "empty": False,
        "prs": rows,
    }


def majority_supplier_format(payload: Mapping[str, Any]) -> dict[str, Any]:
    pos = payload.get("pos")
    rows = [dict(item) for item in pos] if isinstance(pos, list) else []
    if not rows:
        return {
            "supplier": "",
            "format": "",
            "vote_count": 0,
            "pos": rows,
            "proposed_po": {},
        }
    suppliers = Counter(str(row.get("supplier") or "") for row in rows if row.get("supplier"))
    supplier = suppliers.most_common(1)[0][0] if suppliers else ""
    formats = Counter(
        str(row.get("format") or "")
        for row in rows
        if str(row.get("supplier") or "") == supplier and row.get("format")
    )
    shared_format = formats.most_common(1)[0][0] if formats else ""
    pr = payload.get("pr") if isinstance(payload.get("pr"), Mapping) else {}
    pr_id = str(payload.get("pr_id") or pr.get("pr_id") or "")
    proposed = {
        "pr_id": pr_id,
        "supplier": supplier,
        "format": shared_format,
        "amount": pr.get("amount"),
        "currency": pr.get("currency") or "QAR",
        "pr_type": str(payload.get("pr_type") or pr.get("pr_type") or pr.get("type") or ""),
    }
    justification = str(payload.get("justification") or "")
    summary_prompt = (
        "Summarise this purchase-requisition justification in two short sentences. "
        "Do not decide to reject or approve. Do not invent a supplier.\n\n"
        f"{justification}"
    )
    return {
        "supplier": supplier,
        "format": shared_format,
        "vote_count": suppliers.get(supplier, 0),
        "pos": rows,
        "proposed_po": proposed,
        "summary_prompt": summary_prompt,
        "pr_id": pr_id,
        "pr": dict(pr) if pr else {},
        "justification": justification,
    }


SELECT_PR_CODE = '''"""Pick the next approved PR for this scheduled tick."""

def main(inputs):
    prs = list(inputs.get("prs") or [])
    pin = str(inputs.get("pr_id") or "").strip()
    chosen = None
    if pin:
        for row in prs:
            if isinstance(row, dict) and str(row.get("pr_id") or "") == pin:
                chosen = row
                break
    if chosen is None and prs:
        chosen = prs[0] if isinstance(prs[0], dict) else None
    if not isinstance(chosen, dict):
        return {"pr_id": "", "pr": None, "pr_type": "", "empty": True, "prs": prs}
    return {
        "pr_id": str(chosen.get("pr_id") or ""),
        "pr": chosen,
        "pr_type": str(chosen.get("pr_type") or chosen.get("type") or ""),
        "empty": False,
        "prs": prs,
    }
'''

MAJORITY_CODE = '''"""Majority supplier and shared format from HIKMA POs of the same type."""

from collections import Counter

def main(inputs):
    pos = [row for row in (inputs.get("pos") or []) if isinstance(row, dict)]
    if not pos:
        return {
            "supplier": "",
            "format": "",
            "vote_count": 0,
            "pos": pos,
            "proposed_po": {},
            "summary_prompt": "",
            "pr_id": str(inputs.get("pr_id") or ""),
            "pr": inputs.get("pr") if isinstance(inputs.get("pr"), dict) else {},
            "justification": str(inputs.get("justification") or ""),
        }
    suppliers = Counter(str(row.get("supplier") or "") for row in pos if row.get("supplier"))
    supplier = suppliers.most_common(1)[0][0] if suppliers else ""
    formats = Counter(
        str(row.get("format") or "")
        for row in pos
        if str(row.get("supplier") or "") == supplier and row.get("format")
    )
    shared = formats.most_common(1)[0][0] if formats else ""
    pr = inputs.get("pr") if isinstance(inputs.get("pr"), dict) else {}
    pr_id = str(inputs.get("pr_id") or pr.get("pr_id") or "")
    justification = str(inputs.get("justification") or "")
    return {
        "supplier": supplier,
        "format": shared,
        "vote_count": suppliers.get(supplier, 0),
        "pos": pos,
        "proposed_po": {
            "pr_id": pr_id,
            "supplier": supplier,
            "format": shared,
            "amount": pr.get("amount"),
            "currency": pr.get("currency") or "QAR",
            "pr_type": str(inputs.get("pr_type") or pr.get("pr_type") or pr.get("type") or ""),
        },
        "summary_prompt": (
            "Summarise this purchase-requisition justification in two short sentences. "
            "Do not decide to reject or approve. Do not invent a supplier.\\n\\n"
            + justification
        ),
        "pr_id": pr_id,
        "pr": pr,
        "justification": justification,
    }
'''
