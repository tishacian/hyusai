"""Reproducible synthetic history; outcomes never enter the model features."""

import csv
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
FEATURES = [
    "claim_reason",
    "paid_amount",
    "shipment_status",
    "already_refunded",
    "case_documents",
    "item_quantity",
]


def history():
    rng = random.Random(20261006)
    rows = []
    for index in range(1200):
        reason = rng.choices(
            ["delivery_disputed", "parcel_lost", "refund_requested"], [45, 35, 20]
        )[0]
        amount = round(math.exp(rng.uniform(math.log(15), math.log(500))), 2)
        shipment = rng.choices(["delivered", "lost", "in_transit"], [65, 10, 25])[0]
        if reason == "parcel_lost":
            shipment = rng.choices(["lost", "in_transit"], [80, 20])[0]
        refunded = int(reason == "refund_requested" and rng.random() < 0.75)
        documents, quantity = (
            rng.randrange(5),
            rng.choices([1, 2, 3, 4], [65, 20, 10, 5])[0],
        )
        logit = (
            -2.4
            + 2.7 * (reason == "delivery_disputed")
            + 0.45 * (reason == "parcel_lost")
            + 0.003 * amount
            + 1.2 * (shipment == "in_transit")
            + 0.8 * (documents < 2)
            + 0.45 * (quantity > 2)
            - 2.2 * refunded
        )
        late = rng.random() < 1 / (1 + math.exp(-logit))
        hours = rng.uniform(73, 168) if late else rng.uniform(6, 65)
        opened = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(
            hours=rng.randrange(5700)
        )
        rows.append(
            {
                "claim_id": f"HIST-LUMA-{index + 1:05d}",
                "opened_at": opened.isoformat(),
                "resolved_at": (opened + timedelta(hours=hours)).isoformat(),
                "claim_reason": f" {reason.upper()} " if index % 19 == 0 else reason,
                "paid_amount": amount,
                "shipment_status": shipment,
                "already_refunded": refunded,
                "case_documents": documents,
                "item_quantity": quantity,
                "evidence_kind": "synthetic_demo",
            }
        )
    # Known, visible quality issues: duplicate source records and invalid outcomes.
    rows.extend(dict(row) for row in rows[:24])
    for index in range(12):
        row = dict(rows[index + 40], claim_id=f"HIST-LUMA-INVALID-{index + 1:02d}")
        row["resolved_at"] = "" if index % 2 else row["opened_at"]
        rows.append(row)
    rng.shuffle(rows)
    return rows


if __name__ == "__main__":
    rows = history()
    with (ROOT / "luma_sav_history_synthetic.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
