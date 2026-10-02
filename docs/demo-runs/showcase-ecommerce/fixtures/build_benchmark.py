"""Build ten matched pairs, independent of scene cases; never seed times/costs.

Pairs use distinct case identities, alternate AB/BA and include all three scene
classes plus missing delivery evidence. The missing class has no invented proof.
"""
import copy
import hashlib
import json
from pathlib import Path
from build import DDL, ROOT, insert_rows, source_text, write_pdf


def main():
    original = json.loads((ROOT / "fixture_spec.json").read_text())
    tables = {t: [] for t in ("customers", "orders", "order_items", "shipments", "refunds", "claims", "document_refs")}
    pairs, documents = [], []
    folder = ROOT / "benchmark"; folder.mkdir(exist_ok=True)
    (folder / "documents").mkdir(exist_ok=True); (folder / "source-texts").mkdir(exist_ok=True)
    for pair_no in range(1, 11):
        kind = (pair_no - 1) % 4
        base_no = (1042, 1043, 1044, 1042)[kind]
        pair = {"pair_id": f"P{pair_no:02}", "first_condition": "manual" if pair_no % 2 else "assisted"}
        for variant, condition in enumerate(("manual", "assisted")):
            n = 5000 + (pair_no - 1) * 2 + variant + 1
            old_order, new_order = f"LM-{base_no}", f"LM-{n}"
            old_customer = next(r["customer_id"] for r in original["orders"] if r["order_id"] == old_order)
            replace = {old_order: new_order, str(base_no): str(n), old_customer: f"C-B{n}"}
            def clone(value):
                if not isinstance(value, str): return value
                for before, after in replace.items(): value = value.replace(before, after)
                return value
            for table in tables:
                if table == "document_refs": continue
                selected = [r for r in original[table] if r.get("order_id") == old_order or (table == "customers" and r["customer_id"] == old_customer)]
                for row in selected:
                    copied = {k: clone(v) for k, v in row.items()}
                    if table == "customers": copied["display_name"] = f"Client fictif B{n}"
                    tables[table].append(copied)
            required = ["refund-policy-v2"]
            for row in original["documents"]:
                if row["order_id"] != old_order or (kind == 3 and row["type"] == "delivery_receipt"): continue
                copied = {k: clone(v) for k, v in row.items()}
                copied["paragraphs"] = [clone(v) for v in row["paragraphs"]]
                path = folder / "documents" / copied["filename"]
                write_pdf(copied, path)
                (folder / "source-texts" / f"{copied['reference']}.md").write_text(source_text(copied))
                sha = hashlib.sha256(path.read_bytes()).hexdigest()
                documents.append({"reference": copied["reference"], "filename": copied["filename"], "sha256": sha})
                tables["document_refs"].append({"document_key": copied["reference"], "source_filename": copied["filename"], "document_type": copied["type"], "version": copied["version"], "effective_from": copied["effective_from"], "is_current": True, "order_id": new_order, "sha256": sha, "knowledge_source_id": None})
                if copied["type"] in {"delivery_receipt", "carrier_loss_confirmation", "refund_receipt"}: required.append(copied["reference"])
            pair[condition + "_claim_id"] = f"RC-{n}"
            # Oracle names are condition-specific; do not expose them to operators.
            pair[condition + "_expected"] = {"action": ("carrier_investigation", "refund", "close_duplicate", "request_information")[kind], "amount": "49.90" if kind == 1 else "0", "references": required}
        pairs.append(pair)
    sql = "-- Additional synthetic benchmark cases. Load base seed first.\nBEGIN;\n"
    for table, rows in tables.items(): sql += insert_rows(table, rows)
    (folder / "seed.sql").write_text(sql + "\nCOMMIT;\n")
    (folder / "manifest.json").write_text(json.dumps({"evidence_kind": "synthetic_demo_benchmark", "documents": documents}, ensure_ascii=False, indent=2) + "\n")
    (folder / "protocol.json").write_text(json.dumps({"version": "showcase-ecommerce-roi-v1", "hourly_eur": "40.00", "hourly_nature": "declared_demo_assumption", "pairs": pairs, "allocation": None}, ensure_ascii=False, indent=2) + "\n")
    print(f"Prepared {len(pairs)} pairs and {len(documents)} original PDFs; no measurements or DB connection.")


if __name__ == "__main__": main()
