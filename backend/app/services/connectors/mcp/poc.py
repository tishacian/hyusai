"""Deterministic PR→PO helpers used by python_recipe nodes and tests.

The walker has a ``loop`` kind, but it only invokes one skill per item — it
cannot nest budget → decision → HITL. v1 therefore processes **one PR per
scheduled tick**: list, then select the pinned or first remaining approved PR.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping


def _row_pr_id(row: Mapping[str, Any]) -> str:
    return str(row.get("pr_id") or row.get("PurchaseRequisition") or "").strip()


def _row_material_group(row: Mapping[str, Any]) -> str:
    return str(row.get("MaterialGroup") or row.get("pr_type") or row.get("type") or "").strip()


def _row_supplier(row: Mapping[str, Any]) -> str:
    return str(row.get("supplier") or row.get("Supplier") or "").strip()


def _row_format(row: Mapping[str, Any]) -> str:
    return str(
        row.get("format") or row.get("PurchaseOrderType") or row.get("PaymentTerms") or ""
    ).strip()


def select_next_pr(payload: Mapping[str, Any]) -> dict[str, Any]:
    prs = payload.get("prs")
    rows = [dict(item) for item in prs] if isinstance(prs, list) else []
    pin = str(payload.get("pr_id") or "").strip()
    chosen = None
    if pin:
        chosen = next((row for row in rows if _row_pr_id(row) == pin), None)
    if chosen is None and rows:
        chosen = rows[0]
    if not isinstance(chosen, dict):
        return {
            "pr_id": "",
            "pr": None,
            "pr_type": "",
            "MaterialGroup": "",
            "PurchaseRequisitionItem": "",
            "empty": True,
            "prs": rows,
        }
    pr_id = _row_pr_id(chosen)
    material_group = _row_material_group(chosen)
    return {
        "pr_id": pr_id,
        "pr": chosen,
        "pr_type": str(chosen.get("pr_type") or chosen.get("type") or chosen.get("PurchaseRequisitionType") or ""),
        "MaterialGroup": material_group,
        "PurchaseRequisitionItem": str(chosen.get("PurchaseRequisitionItem") or "10"),
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
    suppliers = Counter(_row_supplier(row) for row in rows if _row_supplier(row))
    supplier = suppliers.most_common(1)[0][0] if suppliers else ""
    formats = Counter(
        _row_format(row)
        for row in rows
        if _row_supplier(row) == supplier and _row_format(row)
    )
    shared_format = formats.most_common(1)[0][0] if formats else ""
    pr = payload.get("pr") if isinstance(payload.get("pr"), Mapping) else {}
    pr_id = str(payload.get("pr_id") or pr.get("pr_id") or pr.get("PurchaseRequisition") or "")
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


FORMAT_REQUIREMENTS = "tabulate>=0.9.0"

FORMAT_TEST_INPUT = (
    '{"pr":{"pr_id":"PR-4402","title":"Laptop replacements","amount":12000,'
    '"currency":"QAR"},"pr_id":"PR-4402","supplier":"ACME","format":"XML",'
    '"vote_count":2,"proposed_po":{"pr_id":"PR-4402","supplier":"ACME",'
    '"format":"XML"},"summary_prompt":"Summarise this purchase-requisition '
    'justification in two short sentences.","justification":"Finance laptops '
    'are past refresh."}'
)


def format_dossier(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Mirror of FORMAT_CODE for in-process walker tests.

    The live node imports ``tabulate`` from the managed venv. This helper
    keeps the same keys so the DAG can walk without that package in pytest.
    """

    pr = payload.get("pr") if isinstance(payload.get("pr"), Mapping) else {}
    supplier = str(payload.get("supplier") or "")
    order_format = str(payload.get("format") or "")
    vote_count = payload.get("vote_count") or 0
    pr_id = str(payload.get("pr_id") or pr.get("pr_id") or "")
    rows = [
        ("PR", pr_id),
        ("Title", str(pr.get("title") or pr.get("PurReqnDescription") or pr.get("PurchaseRequisitionItemText") or "")),
        ("Supplier", supplier),
        ("Order type", order_format),
        ("Votes", vote_count),
        ("Amount", pr.get("amount") or pr.get("TotalNetAmount") or ""),
        ("Currency", pr.get("currency") or "QAR"),
    ]
    version = ""
    try:
        from tabulate import tabulate as _tabulate
        import tabulate as tabulate_mod

        table = _tabulate(rows, headers=["Field", "Value"], tablefmt="github")
        version = str(getattr(tabulate_mod, "__version__", "") or "")
    except ImportError:
        table = "| Field | Value |\n| --- | --- |\n" + "\n".join(
            f"| {field} | {value} |" for field, value in rows
        )
    return {
        "formatted": table,
        "recipe_package": "tabulate",
        "recipe_package_version": version,
        "supplier": supplier,
        "format": order_format,
        "vote_count": vote_count,
        "pr_id": pr_id,
        "pr": dict(pr) if pr else {},
        "proposed_po": (
            dict(payload.get("proposed_po"))
            if isinstance(payload.get("proposed_po"), Mapping)
            else {}
        ),
        "summary_prompt": str(payload.get("summary_prompt") or ""),
        "justification": str(payload.get("justification") or ""),
    }


SELECT_PR_CODE = '''"""Pick the next approved PR for this scheduled tick."""

def _pr_id(row):
    return str((row or {}).get("pr_id") or (row or {}).get("PurchaseRequisition") or "").strip()

def main(inputs):
    prs = list(inputs.get("prs") or [])
    pin = str(inputs.get("pr_id") or "").strip()
    chosen = None
    if pin:
        for row in prs:
            if isinstance(row, dict) and _pr_id(row) == pin:
                chosen = row
                break
    if chosen is None and prs:
        chosen = prs[0] if isinstance(prs[0], dict) else None
    if not isinstance(chosen, dict):
        return {"pr_id": "", "pr": None, "pr_type": "", "MaterialGroup": "", "PurchaseRequisitionItem": "", "empty": True, "prs": prs}
    return {
        "pr_id": _pr_id(chosen),
        "pr": chosen,
        "pr_type": str(chosen.get("pr_type") or chosen.get("type") or chosen.get("PurchaseRequisitionType") or ""),
        "MaterialGroup": str(chosen.get("MaterialGroup") or chosen.get("pr_type") or chosen.get("type") or ""),
        "PurchaseRequisitionItem": str(chosen.get("PurchaseRequisitionItem") or "10"),
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
    def _supplier(row):
        return str(row.get("supplier") or row.get("Supplier") or "").strip()
    def _fmt(row):
        return str(row.get("format") or row.get("PurchaseOrderType") or row.get("PaymentTerms") or "").strip()
    suppliers = Counter(_supplier(row) for row in pos if _supplier(row))
    supplier = suppliers.most_common(1)[0][0] if suppliers else ""
    formats = Counter(
        _fmt(row)
        for row in pos
        if _supplier(row) == supplier and _fmt(row)
    )
    shared = formats.most_common(1)[0][0] if formats else ""
    pr = inputs.get("pr") if isinstance(inputs.get("pr"), dict) else {}
    pr_id = str(inputs.get("pr_id") or pr.get("pr_id") or pr.get("PurchaseRequisition") or "")
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

FORMAT_CODE = '''"""Format the compiled PR-to-PO dossier. Requires tabulate in the managed env."""

import tabulate
from tabulate import tabulate as render_table


def main(inputs):
    pr = inputs.get("pr") if isinstance(inputs.get("pr"), dict) else {}
    supplier = str(inputs.get("supplier") or "")
    order_format = str(inputs.get("format") or "")
    vote_count = inputs.get("vote_count") or 0
    pr_id = str(inputs.get("pr_id") or pr.get("pr_id") or "")
    rows = [
        ["PR", pr_id],
        ["Title", str(pr.get("title") or pr.get("PurReqnDescription") or pr.get("PurchaseRequisitionItemText") or "")],
        ["Supplier", supplier],
        ["Order type", order_format],
        ["Votes", vote_count],
        ["Amount", pr.get("amount") or pr.get("TotalNetAmount") or ""],
        ["Currency", pr.get("currency") or "QAR"],
    ]
    return {
        "formatted": render_table(rows, headers=["Field", "Value"], tablefmt="github"),
        "recipe_package": "tabulate",
        "recipe_package_version": str(getattr(tabulate, "__version__", "") or ""),
        "supplier": supplier,
        "format": order_format,
        "vote_count": vote_count,
        "pr_id": pr_id,
        "pr": pr,
        "proposed_po": inputs.get("proposed_po") if isinstance(inputs.get("proposed_po"), dict) else {},
        "summary_prompt": str(inputs.get("summary_prompt") or ""),
        "justification": str(inputs.get("justification") or ""),
    }
'''
