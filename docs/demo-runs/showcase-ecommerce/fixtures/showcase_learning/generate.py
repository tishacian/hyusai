"""Reproducible synthetic Luma sources; no API calls, clocks or live writes.

Dates, outcomes and messages are fictional. Existing presentation and benchmark
fixtures are never read or changed. The explicit anchor is an exclusive as-of
boundary, not a claim that an experiment ran at that time.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_ANCHOR = date(2026, 10, 9)
SEED = 20261009
DAYS = 420
FEATURES = [
    "claim_reason",
    "paid_amount",
    "shipment_status",
    "already_refunded",
    "case_documents",
    "item_quantity",
]
NUMERIC_FEATURES = FEATURES[1:2] + FEATURES[3:]
LABELS = ["delivery_disputed", "parcel_lost", "refund_requested"]
FORBIDDEN_FEATURES = {
    "resolved_at",
    "resolution_hours",
    "resolution_over_72h",
    "synthetic_intent_reference",
    "label_available_at",
    "claim_id",
    "cohort",
}
PRESENTATION_IDS = ["RC-1042", "RC-1043", "RC-1044"]

# A separate wording bank in the chronological holdout prevents identical
# template sentences from becoming apparent evidence of text generalisation.
MESSAGES = {
    "train": {
        "fr": {
            "delivery_disputed": [
                "Le suivi dit livré mais je n'ai pas reçu {item}.",
                "Mon colis apparaît remis et pourtant je ne trouve pas {item} chez moi.",
                "Le transporteur indique une remise de {item} que je conteste.",
            ],
            "parcel_lost": [
                "Le transporteur ne retrouve plus {item}, pouvez-vous chercher le colis ?",
                "Le suivi de {item} est bloqué depuis {days} jours, le colis semble perdu.",
                "On m'annonce que le paquet contenant {item} a été égaré.",
            ],
            "refund_requested": [
                "Je voudrais savoir où en est le remboursement de {item}.",
                "Pouvez-vous vérifier le retour de paiement pour {item} ?",
                "J'ai demandé à être remboursé pour {item} et je souhaite un point.",
            ],
        },
        "en": {
            "delivery_disputed": [
                "Tracking says delivered but {item} has not reached me.",
                "The carrier marked {item} as handed over; I disagree with that delivery.",
                "I cannot find {item} although the parcel is shown as delivered.",
            ],
            "parcel_lost": [
                "The carrier cannot locate the parcel containing {item}.",
                "Tracking for {item} has not moved for {days} days and it may be lost.",
                "I was told that the package with {item} went missing in transit.",
            ],
            "refund_requested": [
                "Could you check the refund for {item}, please?",
                "I requested my money back for {item} and would like an update.",
                "Where are we with the return of payment for {item}?",
            ],
        },
    },
    "heldout": {
        "fr": {
            "delivery_disputed": [
                "D'après votre notification {item} est chez moi, mais personne ne l'a réceptionné.",
                "Pourquoi annoncer une livraison terminée pour {item} alors que ma boîte est vide ?",
            ],
            "parcel_lost": [
                "Votre service de transport a perdu la trace de {item} dans son réseau.",
                "Aucune étape nouvelle pour {item} depuis {days} jours ; pouvez-vous lancer une recherche ?",
            ],
            "refund_requested": [
                "J'attends le crédit bancaire correspondant à {item} : quelle est la suite ?",
                "Merci de me renseigner sur la restitution du montant payé pour {item}.",
            ],
        },
        "en": {
            "delivery_disputed": [
                "Your notification claims {item} arrived, yet nobody at this address accepted it.",
                "Why is delivery complete for {item} when my mailbox is empty?",
            ],
            "parcel_lost": [
                "The shipping company has lost track of {item} somewhere in its network.",
                "No new scan for {item} in {days} days; please start a parcel search.",
            ],
            "refund_requested": [
                "When should the bank credit for {item} reach my account?",
                "Please update me on returning the amount I paid for {item}.",
            ],
        },
    },
}
ITEMS = {
    "fr": [
        "la lampe",
        "le tapis",
        "le vase",
        "le plaid",
        "la housse",
        "le miroir",
        "la corbeille",
        "la nappe",
    ],
    "en": [
        "the lamp",
        "the rug",
        "the vase",
        "the blanket",
        "the cover",
        "the mirror",
        "the basket",
        "the tablecloth",
    ],
}
COLOURS = {
    "fr": ["beige", "bleu", "vert", "gris"],
    "en": ["beige", "blue", "green", "grey"],
}


def utc(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def cohort_for(day: date, anchor: date) -> str:
    age = (anchor - day).days
    if age > 120:
        return "train"
    if age > 110:
        return "embargo"
    if age > 30:
        return "heldout"
    if age > 10:
        return "feedback"
    return "recent"


def campaign_day(day: date, anchor: date) -> int | None:
    offset = (day - (anchor - timedelta(days=396))).days
    if offset < 0:
        return None
    phase = offset % 56
    return phase if phase < 14 else None


def initial_message(rng: random.Random, cohort: str, language: str, reason: str) -> str:
    bank = "heldout" if cohort == "heldout" else "train"
    message = rng.choice(MESSAGES[bank][language][reason]).format(
        item=rng.choice(ITEMS[language]), days=rng.randrange(3, 12)
    )
    # Customer details available at intake, not outcome or synthetic identifiers.
    if language == "fr":
        detail = f" Modèle {rng.choice(COLOURS[language])}, commandé le {rng.randrange(1, 29)}."
        return (
            rng.choice(["Bonjour. ", "Bonsoir. ", "Bonjour à l'équipe. "])
            + message
            + detail
        )
    detail = f" {rng.choice(COLOURS[language]).capitalize()} model, ordered on day {rng.randrange(1, 29)}."
    return (
        rng.choice(["Hello. ", "Good morning. ", "Hi support team. "])
        + message
        + detail
    )


def build(anchor: date = DEFAULT_ANCHOR, seed: int = SEED) -> dict[str, list[dict]]:
    rng = random.Random(seed)
    cases, outcomes, volumes = [], [], []
    cutoff = utc(anchor)
    train_cutoff = utc(anchor - timedelta(days=120))
    for index in range(DAYS):
        day = anchor - timedelta(days=DAYS - index)
        phase = campaign_day(day, anchor)
        promo = 12 * math.sin(math.pi * (phase + 0.5) / 14) if phase is not None else 0
        weekday = [1.28, 1.17, 1.08, 1.0, 0.95, 0.64, 0.57][day.weekday()]
        count = max(3, round((13 + index * 0.01 + promo) * weekday + rng.gauss(0, 2)))
        volumes.append(
            {
                "observed_at": iso(utc(day)),
                "series_id": "luma_sav",
                "claim_count": count,
                "campaign_active": int(phase is not None),
                "data_kind": "synthetic_demo",
            }
        )
        for number in range(count):
            opened = utc(day) + timedelta(seconds=rng.randrange(86400))
            cohort = cohort_for(day, anchor)
            reason = rng.choices(LABELS, [47, 33, 20])[0]
            amount = round(math.exp(rng.uniform(math.log(18), math.log(450))), 2)
            shipment = rng.choices(["delivered", "lost", "in_transit"], [68, 7, 25])[0]
            if reason == "parcel_lost":
                shipment = rng.choices(["lost", "in_transit"], [75, 25])[0]
            refunded = int(reason == "refund_requested" and rng.random() < 0.65)
            documents = rng.randrange(5)
            quantity = rng.choices([1, 2, 3, 4], [63, 23, 10, 4])[0]
            language = rng.choices(["fr", "en"], [72, 28])[0]
            logit = (
                -2.7
                + 2.6 * (reason == "delivery_disputed")
                + 0.5 * (reason == "parcel_lost")
                + 0.003 * amount
                + 1.1 * (shipment == "in_transit")
                + 0.8 * (documents < 2)
                + 0.4 * (quantity > 2)
                - 2.1 * refunded
                + 0.3 * (phase is not None)
            )
            late = rng.random() < 1 / (1 + math.exp(-logit))
            hours = round(rng.uniform(74, 160) if late else rng.uniform(6, 68), 3)
            resolved = opened + timedelta(hours=hours)
            suffix = f"{day:%Y%m%d}-{number + 1:03d}"
            case = {
                "claim_id": f"SYN-LUMA-{suffix}",
                "order_id": f"SYN-ORDER-{suffix}",
                "shipment_id": f"SYN-SHIP-{suffix}",
                "opened_at": iso(opened),
                "snapshot_at": iso(opened),
                "cohort": cohort,
                "claim_reason": reason,
                "paid_amount": amount,
                "shipment_status": shipment,
                "already_refunded": refunded,
                "case_documents": documents,
                "item_quantity": quantity,
                "language": language,
                "initial_message": initial_message(rng, cohort, language, reason),
                "campaign_active": int(phase is not None),
                "data_kind": "synthetic_demo",
            }
            cases.append(case)
            # Never manufacture future actuals; the generator knows them but
            # deliberately does not publish them before the as-of boundary.
            if resolved < cutoff:
                outcomes.append(
                    {
                        "claim_id": case["claim_id"],
                        "resolved_at": iso(resolved),
                        "label_available_at": iso(resolved),
                        "resolution_hours": hours,
                        "resolution_over_72h": int(late),
                        "synthetic_intent_reference": reason,
                        "data_kind": "synthetic_demo",
                        "review_status": "not_human_reviewed",
                    }
                )

    by_id = {row["claim_id"]: row for row in outcomes}
    supervised = {}
    for cohort in ("train", "heldout"):
        rows = []
        for case in cases:
            outcome = by_id.get(case["claim_id"])
            if case["cohort"] != cohort or outcome is None:
                continue
            if cohort == "train" and outcome["label_available_at"] >= iso(train_cutoff):
                continue  # Purge training labels that were unavailable at its cutoff.
            rows.append(
                {
                    "claim_id": case["claim_id"],
                    **{key: case[key] for key in FEATURES},
                    "language": case["language"],
                    "resolution_over_72h": outcome["resolution_over_72h"],
                    "resolution_hours": outcome["resolution_hours"],
                }
            )
        supervised[f"sla_{cohort}.csv"] = rows

    # Small, balanced cohort with no reference labels sent to the LLM. Keep it
    # separate from the heldout wording/date range. Real review remains pending.
    eligible_ids = {row["claim_id"] for row in supervised["sla_train.csv"]}
    review = []
    for reason in LABELS:
        for language in ("fr", "en"):
            group = [
                row
                for row in cases
                if row["claim_id"] in eligible_ids
                and row["claim_reason"] == reason
                and row["language"] == language
            ]
            rng.shuffle(group)
            review.extend(
                {key: row[key] for key in ("claim_id", "language", "initial_message")}
                for row in group[:80]
            )
    rng.shuffle(review)
    regression = [
        {key: value for key, value in row.items() if key != "resolution_over_72h"}
        for row in supervised["sla_train.csv"]
    ]
    segmentation = [
        {key: row[key] for key in ("claim_id", *NUMERIC_FEATURES)}
        for row in supervised["sla_train.csv"]
    ]
    supervised["sla_train.csv"] = [
        {key: value for key, value in row.items() if key != "resolution_hours"}
        for row in supervised["sla_train.csv"]
    ]
    return {
        "cases.csv": cases,
        "outcomes.csv": outcomes,
        "daily_volume.csv": volumes,
        **supervised,
        "regression_train.csv": regression,
        "segmentation_numeric.csv": segmentation,
        "text_for_review.csv": review,
    }


def validate(data: dict[str, list[dict]], anchor: date) -> dict:
    cases, outcomes, volumes = (
        data["cases.csv"],
        data["outcomes.csv"],
        data["daily_volume.csv"],
    )
    ids = {row["claim_id"] for row in cases}
    assert len(ids) == len(cases) and not ids.intersection(PRESENTATION_IDS)
    assert len({row["claim_id"] for row in outcomes}) == len(outcomes)
    by_id = {row["claim_id"]: row for row in cases}
    by_outcome = {row["claim_id"]: row for row in outcomes}
    assert not FORBIDDEN_FEATURES.intersection(FEATURES)
    assert not (FORBIDDEN_FEATURES - {"claim_id", "cohort"}).intersection(cases[0])
    counted = Counter(row["opened_at"][:10] for row in cases)
    assert len(volumes) == DAYS
    for index, volume in enumerate(volumes):
        expected = anchor - timedelta(days=DAYS - index)
        assert volume["observed_at"] == iso(utc(expected))
        assert volume["claim_count"] == counted[expected.isoformat()]
    for row in outcomes:
        assert row["claim_id"] in ids and row["review_status"] == "not_human_reviewed"
        opened = datetime.fromisoformat(by_id[row["claim_id"]]["opened_at"])
        closed = datetime.fromisoformat(row["resolved_at"])
        assert opened < closed < utc(anchor)
        assert (
            abs((closed - opened).total_seconds() / 3600 - row["resolution_hours"])
            < 1e-6
        )
        assert row["resolution_over_72h"] == int(row["resolution_hours"] > 72)
    train = data["sla_train.csv"]
    heldout = data["sla_heldout.csv"]
    train_ids = {row["claim_id"] for row in train}
    heldout_ids = {row["claim_id"] for row in heldout}
    assert not train_ids.intersection(heldout_ids)
    assert all(
        by_outcome[key]["label_available_at"] < iso(utc(anchor - timedelta(days=120)))
        for key in train_ids
    )
    assert max(by_id[key]["opened_at"] for key in train_ids) < min(
        by_id[key]["opened_at"] for key in heldout_ids
    )
    train_text = {
        row["initial_message"] for row in cases if row["claim_id"] in train_ids
    }
    heldout_text = {
        row["initial_message"] for row in cases if row["claim_id"] in heldout_ids
    }
    assert not train_text.intersection(heldout_text)
    assert len(data["text_for_review.csv"]) == 480
    assert {row["claim_id"] for row in data["text_for_review.csv"]}.issubset(train_ids)
    assert set(data["text_for_review.csv"][0]) == {
        "claim_id",
        "language",
        "initial_message",
    }
    assert "resolution_hours" not in train[0]
    assert "resolution_over_72h" not in data["regression_train.csv"][0]
    assert set(data["segmentation_numeric.csv"][0]) == {"claim_id", *NUMERIC_FEATURES}
    counts = Counter(row["resolution_over_72h"] for row in train)
    # Conservative floor under the product's stratified 25% test and 20%
    # calibration-of-training splits; it is eligibility, not a fitted result.
    estimated_calibration = {
        str(label): math.floor(count * 0.75 * 0.2) - 2
        for label, count in counts.items()
    }
    assert len(counts) == 2 and min(estimated_calibration.values()) >= 20
    assert sum(estimated_calibration.values()) >= 200
    return {
        "checks": [
            "source_keys_unique",
            "presentation_excluded",
            "outcomes_separate",
            "no_future_outcomes",
            "chronological_embargo",
            "train_labels_known_at_cutoff",
            "heldout_text_distinct",
            "review_input_unlabeled",
            "daily_counts_match_cases",
            "regular_daily_grid",
            "calibration_eligible",
        ],
        "rows_by_cohort": dict(Counter(row["cohort"] for row in cases)),
        "train_class_counts": {
            str(label): count for label, count in sorted(counts.items())
        },
        "calibration_conservative_minimum_by_class": estimated_calibration,
        "unresolved_at_anchor": len(cases) - len(outcomes),
    }


def documents(anchor: date) -> dict[str, str]:
    start, end = anchor - timedelta(days=4), anchor + timedelta(days=9)
    return {
        "campaign-plan.md": f"""# Luma — campagne Maison d'automne

DÉMONSTRATION SYNTHÉTIQUE — aucune campagne commerciale réelle.
Version 1. Référence LUMA-CAMPAIGN-{anchor.isoformat()}. Date d'ancrage UTC : {anchor}.

La campagne fictive couvre le {start} au {end}, inclus. Les promotions similaires
de l'historique suivent un cycle de 56 jours et durent 14 jours. La série comprend
des volumes de réclamations, pas des commandes ni du chiffre d'affaires.

Au {anchor}, les derniers volumes complets disponibles sont ceux de la veille.
Le pic est volontairement construit dans les données synthétiques ; il n'est pas
une découverte commerciale ni une garantie que chaque modèle le prédit bien.

La campagne augmente les sollicitations concernant les articles de décoration.
Le responsable SAV consulte une prévision à 28 jours et sa bande d'incertitude
avant d'ajuster la capacité. Comparer le naïf saisonnier, le modèle classique et
Chronos sur les mêmes dates et les mêmes observations.

Cette note fournit un contexte à l'agent via Document Center/OmniRAG. Le protocole
de comparaison initial n'envoie ni cette note ni campaign_active aux modèles :
ils utilisent l'historique des volumes. Chronos ne reçoit pas de covariable.
Une variante classique enrichie du calendrier commercial constitue une autre
expérience, avec ses entrées futures connues et sa comparaison explicitement nommées.

Les dossiers RC-1042, RC-1043 et RC-1044 conservent leurs dates, commandes et preuves
d'origine. Ils illustrent les décisions SAV ; ils n'appartiennent pas à cet
historique d'apprentissage ni à sa série de volumes.
""",
        "capacity-policy.md": f"""# Luma — revue de charge et de capacité SAV

DÉMONSTRATION SYNTHÉTIQUE — convention de présentation, pas une politique réelle.
Version 1. Référence LUMA-CAPACITY-{anchor.isoformat()}. Ancrage UTC : {anchor}.

Le responsable examine chaque matin la file, la charge prévisionnelle et ses
incertitudes. Une hausse prévue déclenche une revue de planning et de priorités,
jamais une modification automatique d'effectif ou de remboursement.

Le score SLA estime une clôture après 72 heures calendaires. La durée de résolution
comprend des attentes transporteur/client : elle ne mesure pas le travail humain.
La priorité ne modifie ni les preuves requises ni la validation financière.

Pour comparer des scénarios de capacité, les conventions approuvées sont :
8 minutes de traitement manuel, 2 minutes de validation humaine assistée,
40 euros par heure chargée et 0,50 euro de budget complet par dossier.
Les coûts d'appels, infrastructure, licence et intégration amortie sont inclus
dans cette hypothèse de budget ; ne pas les ajouter deux fois.

Ces conventions produisent une capacité valorisée projetée, pas une économie
réalisée. Le volume mensuel n'est pas fixé. Les temps humains doivent être mesurés
dans une expérience dédiée. Les coûts incomplets restent inconnus.

Une action proposée conserve le dossier, la version du modèle et les pièces
consultées. Toute décision financière reste humaine et les reçus sont simulés.
Les documents existants de remboursement et d'enquête restent les références
applicables ; cette consigne de planning ne les remplace pas.
""",
    }


def write_pack(output: Path, anchor: date, seed: int = SEED) -> dict:
    data = build(anchor, seed)
    validation = validate(data, anchor)
    output.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, rows in data.items():
        path = output / name
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=list(rows[0]), lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(rows)
        payload = path.read_bytes()
        files[name] = {
            "rows": len(rows),
            "columns": list(rows[0]),
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    for name, content in documents(anchor).items():
        (output / name).write_text(content, encoding="utf-8")
        payload = (output / name).read_bytes()
        files[name] = {
            "kind": "document",
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    manifest = {
        "schema_version": 1,
        "generator_version": 1,
        "seed": seed,
        "anchor_exclusive_utc": iso(utc(anchor)),
        "data_kind": "synthetic_demo",
        "human_review": "not_performed",
        "live_import": "not_performed",
        "presentation_ids_reserved": PRESENTATION_IDS,
        "history_days": DAYS,
        "train_label_cutoff_exclusive_utc": iso(utc(anchor - timedelta(days=120))),
        "model_features": {
            "sla": FEATURES,
            "text": ["initial_message"],
            "clustering": NUMERIC_FEATURES,
        },
        "files": files,
        "validation": validation,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--anchor",
        type=date.fromisoformat,
        default=DEFAULT_ANCHOR,
        help="Exclusive as-of date in UTC; never defaults to today's clock",
    )
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--output", type=Path, default=ROOT / "generated")
    args = parser.parse_args()
    manifest = write_pack(args.output, args.anchor, args.seed)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "files": {
                    name: value.get("rows", "document")
                    for name, value in manifest["files"].items()
                },
                "validation": manifest["validation"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
