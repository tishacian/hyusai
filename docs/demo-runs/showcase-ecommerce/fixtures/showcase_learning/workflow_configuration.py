"""Author Luma configuration using native Flow and certified Work components.

Pure construction only: publication, confirmation policy and CAS belong to the
product's activation workflow. The input Flow must already contain the shared
PostgreSQL/DataOps/SLA lane; this adds a separate forecast ingress to that System.
"""

from __future__ import annotations

import copy
import re

FORECAST_BINDING = "showcase.claims.forecast"
FORECAST_INGRESS = "source.forecast"
FORECAST_NODE = "forecast.predict"
TIMELINE_NODE = "forecast.timeline"
TIMELINE_SQL = """WITH history AS (
  SELECT cast(observed_at AS TIMESTAMPTZ) AS timestamp,
         cast(claim_count AS DOUBLE) AS actual
  FROM input_1
  ORDER BY timestamp DESC
  LIMIT 42
), timeline AS (
  SELECT timestamp, 'Luma SAV' AS series, actual,
         cast(NULL AS DOUBLE) AS pred,
         cast(NULL AS DOUBLE) AS lower_bound,
         cast(NULL AS DOUBLE) AS upper_bound
  FROM history
  UNION ALL
  SELECT cast(timestamp AS TIMESTAMPTZ), 'Luma SAV' AS series,
         cast(NULL AS DOUBLE), cast(pred AS DOUBLE),
         cast(lower_bound AS DOUBLE), cast(upper_bound AS DOUBLE)
  FROM input_2
)
SELECT timestamp, series, actual, pred, lower_bound, upper_bound
FROM timeline ORDER BY timestamp
"""


def _task(node_id, label, skill, params, *, inputs_map=None, x=420):
    return {
        "id": node_id,
        "kind": "task",
        "type": "skill",
        "label": label,
        "position": {"x": x, "y": 820},
        "config": {
            "skill_slug": skill,
            "params": params,
            "inputs_map": inputs_map or {},
            "on_error": "fail",
        },
    }


def _identifier(value, name):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", value
    ):
        raise ValueError(f"LUMA_CONFIGURATION_{name.upper()}_INVALID")
    return value


def build_configuration(
    flow,
    pages,
    forecast_model_id,
    forecast_model_slug,
    forecast_model_version,
    history_dataset_id,
    sla_contract,
    models=None,
):
    """Return the reviewed configuration accepted by composition activation.

    ``pages`` is the document returned by ``work_pages()``. ``models`` is an
    optional list of {id, label_fr, label_en, description_fr, description_en};
    only actual supplied IDs produce links. The prediction agent may insert a
    certified prediction card into the preserved dossier after this function.
    The caller must create the returned binding with confirmation_policy=confirm.
    """
    _identifier(forecast_model_id, "forecast_model_id")
    _identifier(forecast_model_slug, "forecast_model_slug")
    _identifier(history_dataset_id, "history_dataset_id")
    if type(forecast_model_version) is not int or forecast_model_version < 1:
        raise ValueError("LUMA_CONFIGURATION_FORECAST_VERSION_INVALID")
    if not isinstance(sla_contract, dict) or not sla_contract.get("model_id"):
        raise ValueError("LUMA_CONFIGURATION_SLA_CONTRACT_REQUIRED")
    graph, document = copy.deepcopy(flow), copy.deepcopy(pages)
    node_ids = {node["id"] for node in graph["nodes"]}
    if {FORECAST_INGRESS, FORECAST_NODE, TIMELINE_NODE, "sink.forecast"} & node_ids:
        raise ValueError("LUMA_CONFIGURATION_FORECAST_ALREADY_INSTALLED")
    if not {"source.request", "source.queue", "sav.score"} <= node_ids:
        raise ValueError("LUMA_CONFIGURATION_COMPOSED_FLOW_REQUIRED")
    if {"charge", "amelioration"} & {page["id"] for page in document["pages"]}:
        raise ValueError("LUMA_CONFIGURATION_PAGES_ALREADY_INSTALLED")
    dossier = next(
        (page for page in document["pages"] if page["id"] == "dossier"), None
    )
    if dossier is None or not {"investigation", "queue_refresh"} <= {
        node["id"] for node in dossier["components"]
    }:
        raise ValueError("LUMA_CONFIGURATION_COMPOSED_WORK_REQUIRED")
    graph["nodes"].extend(
        [
            {
                "id": FORECAST_INGRESS,
                "type": "source",
                "kind": "source",
                "label": "Prévoir la charge SAV",
                "position": {"x": 80, "y": 820},
                "config": {
                    "ingress_kind": "manual",
                    "input_schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {},
                    },
                },
            },
            _task(
                FORECAST_NODE,
                "Prévoir les 28 prochains jours",
                "ml_forecast_v1",
                {
                    "model_id": forecast_model_id,
                    "model_slug": forecast_model_slug,
                    "pinned_version": forecast_model_version,
                    "horizon": 28,
                    "interval_level": 0.8,
                    "output_name": "Luma — Prévision de charge SAV",
                },
            ),
            _task(
                TIMELINE_NODE,
                "Assembler historique et prévision",
                "sql_transform_v1",
                {
                    "sql": TIMELINE_SQL,
                    "output_name": "Luma — Charge passée et prévisionnelle",
                    "sources": [{"view": "history", "dataset_id": history_dataset_id}],
                },
                inputs_map={
                    "dataset_id": {
                        "node_id": FORECAST_NODE,
                        "path": ["dataset_id"],
                        "required": True,
                    }
                },
                x=740,
            ),
            {
                "id": "sink.forecast",
                "type": "sink",
                "kind": "sink",
                "label": "Charge et capacité dans Work",
                "position": {"x": 1060, "y": 820},
            },
        ]
    )
    graph["edges"].extend(
        {"from": left, "to": right, "kind": "data"}
        for left, right in [
            (FORECAST_INGRESS, FORECAST_NODE),
            (FORECAST_NODE, TIMELINE_NODE),
            (TIMELINE_NODE, "sink.forecast"),
        ]
    )

    i18n = document.setdefault("i18n", {})
    for language in ("fr", "en"):
        i18n.setdefault(language, {})

    def text(key, fr, en):
        key = "luma_learning_" + key
        i18n["fr"][key], i18n["en"][key] = fr, en
        return {"$i18n": key, "fallback": fr}

    def callout(node_id, fr, en, href=None):
        props = {"body": text(node_id, fr, en), "density": "compact"}
        if href:
            props["href"] = href
        return {"id": node_id, "type": "callout", "props": props}

    dossier["components"].append(
        callout(
            "case_studio_link",
            "Ouvrir la file SAV et les preuves du dossier dans l'atelier métier.",
            "Open the service queue and case evidence in the case workspace.",
            "/work/reclamations/studio",
        )
    )
    charge = {
        "id": "charge",
        "title": text("charge_title", "Charge et capacité", "Workload and capacity"),
        "props": {"density": "compact"},
        "components": [
            {
                "id": "charge_header",
                "type": "header",
                "props": {
                    "title": text(
                        "charge_header",
                        "Anticiper la charge SAV",
                        "Anticipate service workload",
                    ),
                    "description": text(
                        "charge_description",
                        "42 jours d'historique et 28 jours de prévision, avec incertitude. Données synthétiques.",
                        "42 days of history and a 28-day forecast, with uncertainty. Synthetic data.",
                    ),
                },
            },
            {
                "id": "forecast_refresh",
                "type": "action_button",
                "props": {
                    "bindingKey": FORECAST_BINDING,
                    "input": {},
                    "density": "compact",
                    "label": text(
                        "forecast_refresh",
                        "Actualiser la prévision",
                        "Refresh forecast",
                    ),
                },
            },
            {
                "id": "forecast_state",
                "type": "runtime_status",
                "props": {"sourceComponentId": "forecast_refresh"},
            },
            {
                "id": "forecast_chart",
                "type": "chart",
                "props": {
                    "kind": "timeseries",
                    "title": text(
                        "forecast_chart", "Réclamations par jour", "Claims per day"
                    ),
                    "unit": text("forecast_unit", "dossiers/jour", "cases/day"),
                    "mapping": {
                        "time": "timestamp",
                        "value": "pred",
                        "actual": "actual",
                        "lower": "lower_bound",
                        "upper": "upper_bound",
                        "series": "series",
                    },
                    "datasetSource": {
                        "source": "run-output",
                        "selector": "dataset_id",
                        "componentId": "forecast_refresh",
                    },
                },
            },
            callout(
                "forecast_capacity",
                "Utiliser cette prévision pour revoir le planning et les priorités. La bande traduit une incertitude ; elle ne garantit pas le volume futur.",
                "Use this forecast to review staffing and priorities. The band expresses uncertainty; it does not guarantee future volume.",
            ),
            callout(
                "forecast_model",
                f"Ouvrir le modèle de prévision et ses backtests · version {forecast_model_version}.",
                f"Open the forecast model and its backtests · version {forecast_model_version}.",
                f"/models/{forecast_model_id}",
            ),
        ],
    }
    improvement = {
        "id": "amelioration",
        "title": text("improvement_title", "Amélioration", "Improvement"),
        "props": {"density": "compact"},
        "components": [
            {
                "id": "improvement_header",
                "type": "header",
                "props": {
                    "title": text(
                        "improvement_header",
                        "Améliorer avec des preuves",
                        "Improve with evidence",
                    ),
                    "description": text(
                        "improvement_description",
                        "Comparer les modèles, revoir les labels et décider avant de changer la version utilisée.",
                        "Compare models, review labels and decide before changing the version in use.",
                    ),
                },
            },
            callout(
                "improvement_evidence",
                "Les historiques et résultats de clôture sont synthétiques. Les scores de test et les temps techniques ne prouvent ni une qualité en production ni un ROI réalisé.",
                "Histories and closure outcomes are synthetic. Test scores and technical timings establish neither production quality nor realised ROI.",
            ),
            callout(
                "improvement_review",
                "Qualification des messages FR/EN : étiquetage proposé, puis revue humaine de toute la cohorte avant distillation. La revue reste requise ; aucun label généré n'est présenté comme validé.",
                "FR/EN message classification: proposed labels, then human review of the full cohort before distillation. Review is still required; generated labels are not presented as approved.",
            ),
        ],
    }
    references = [
        {
            "id": sla_contract["model_id"],
            "label_fr": "Modèle de priorité SLA",
            "label_en": "SLA priority model",
        },
        *(models or []),
    ]
    seen = set()
    for index, model in enumerate(references):
        model_id = _identifier(model.get("id"), "linked_model_id")
        if model_id in seen:
            continue
        seen.add(model_id)
        fr = str(model.get("label_fr") or model.get("name") or "Modèle")
        en = str(model.get("label_en") or model.get("name") or "Model")
        if model.get("description_fr"):
            fr += " — " + str(model["description_fr"])
        if model.get("description_en"):
            en += " — " + str(model["description_en"])
        improvement["components"].append(
            callout(f"improvement_model_{index}", fr, en, f"/models/{model_id}")
        )
    document["pages"].extend([charge, improvement])
    return {
        "flow_definition": graph,
        "pages": document,
        "bindings": [{"binding_key": FORECAST_BINDING, "ingress_id": FORECAST_INGRESS}],
    }
