"""Compose the reviewed Luma configuration; this helper makes no live writes."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def forecast_node(graph):
    nodes = [node for node in graph["nodes"] if node.get("id") == "forecast.predict"]
    if len(nodes) != 1:
        raise ValueError("FORECAST_NODE_REQUIRED")
    node = nodes[0]
    if (node.get("config") or {}).get("skill_slug") != "ml_forecast_v1":
        raise ValueError("FORECAST_BINDING_CHANGED")
    if not isinstance(node["config"].get("params"), dict):
        raise ValueError("FORECAST_PARAMETERS_REQUIRED")
    return node


def apply_forecast(graph, params, *, expected_params):
    result = copy.deepcopy(graph)
    node = forecast_node(result)
    if node["config"]["params"] != expected_params:
        raise ValueError("FORECAST_PARAMETERS_CHANGED")
    node["config"]["params"] = copy.deepcopy(params)
    node["label"] = (
        f"Prévoir la charge SAV · modèle classique v{params['pinned_version']}"
    )
    return result


def apply_pages(pages, *, forecast, challenger, champion):
    result = copy.deepcopy(pages)
    labels = {
        "luma_learning_charge_description": (
            "Historique synthétique arrêté au 8 octobre 2026 ; prévision du 9 octobre au 5 novembre, avec intervalle à 80 %.",
            "Synthetic history through 8 October 2026; forecast for 9 October–5 November, with an 80% interval.",
        ),
        "luma_learning_forecast_model": (
            "Prévision classique · version 2 — consulter les backtests et la référence saisonnière.",
            "Classical forecast · version 2 — inspect backtests and the seasonal baseline.",
        ),
        "luma_learning_improvement_model_0": (
            "Modèle de priorité SLA en service · version 5",
            "Serving SLA priority model · version 5",
        ),
        "luma_learning_improvement_model_2": (
            "Challenger explicable · forêt aléatoire v6 — comparer et explorer TreeSHAP avant toute promotion.",
            "Explainable challenger · RandomForest v6 — compare and explore TreeSHAP before any promotion.",
        ),
        "luma_learning_improvement_model_6": (
            "Charge SAV · modèle classique v2 — utilisé par la prévision de cette application.",
            "SAV workload · classical model v2 — used by this application's forecast.",
        ),
        "luma_learning_improvement_model_7": (
            "Historique · Chronos v1 — ancien artefact non appelable, remplacé dans cette application.",
            "History · Chronos v1 — legacy artifact cannot be called; replaced in this application.",
        ),
    }
    links = {
        "forecast_model": forecast,
        "improvement_model_0": champion,
        "improvement_model_2": challenger,
        "improvement_model_6": forecast,
    }
    seen = set()
    for page in result["pages"]:
        for component in page.get("components", []):
            props = component.get("props", {})
            if component["id"] in links:
                props["href"] = "/models/" + links[component["id"]]
                seen.add(component["id"])
            for field in ("body", "description"):
                text = props.get(field)
                if isinstance(text, dict) and text.get("$i18n") in labels:
                    text["fallback"] = labels[text["$i18n"]][0]
    if seen != set(links):
        raise ValueError("EXPECTED_WORK_COMPONENTS_MISSING")
    for key, (fr, en) in labels.items():
        result["i18n"]["fr"][key] = fr
        result["i18n"]["en"][key] = en
    return result


def compose(snapshot_dir, forecast_params, challenger_id):
    from app.services.chains.dag_validator import validate_flow
    from app.services.experience.lifecycle import validate_pages_document
    from app.services.run_engine.execution_contract import canonical_flow_sha256

    planner = module("luma_judge_plan", HERE / "build_plan.py")
    prep = module(
        "luma_visual_prep", HERE.parent / "showcase_visual_prep/configuration.py"
    )
    settings = json.loads((HERE / "judge_settings.json").read_text())
    settings["tariff"]["reference"] = (
        "https://developers.openai.com/api/docs/models/gpt-5 "
        "(checked 2026-10-19; standard input, cache discount excluded)"
    )
    plan, review = planner.build_plan(snapshot_dir, settings)
    forecast_before = copy.deepcopy(
        forecast_node(plan["publication_candidate"])["config"]["params"]
    )
    if (
        forecast_node(plan["preserved_draft_candidate"])["config"]["params"]
        != forecast_before
    ):
        raise ValueError("FORECAST_DRAFT_PARAMETERS_DIVERGED")
    before_draft_issues = {
        str(issue)
        for issue in validate_flow(plan["backup"]["flow_draft"]["flow_definition"])
    }
    for key in ("publication_candidate", "preserved_draft_candidate"):
        plan[key] = apply_forecast(
            prep.build_flow(plan[key]), forecast_params, expected_params=forecast_before
        )
        issues = validate_flow(plan[key])
        errors = [
            issue
            for issue in issues
            if issue.level == "error"
            and not (
                key == "preserved_draft_candidate" and str(issue) in before_draft_issues
            )
        ]
        if errors:
            raise ValueError(f"INVALID_COMPOSED_FLOW: {errors}")
        review[key + "_warnings"] = [
            str(issue) for issue in issues if issue.level != "error"
        ]
        if key == "preserved_draft_candidate":
            review["preserved_preexisting_draft_issues"] = [
                str(issue) for issue in issues if str(issue) in before_draft_issues
            ]
    for key in ("work_pages", "preserved_work_draft_pages"):
        plan[key] = apply_pages(
            plan[key],
            forecast=forecast_params["model_id"],
            challenger=challenger_id,
            champion=plan["sla_inference_proof"]["model_id"],
        )
        validate_pages_document(plan[key])
    target = canonical_flow_sha256(plan["publication_candidate"])
    plan["target_flow_sha256"] = target
    plan["triage_after_publication"]["scoring_flow_sha256"] = target
    templates = plan["request_templates"]
    templates["flow_draft_save"]["flow_definition"] = plan["publication_candidate"]
    templates["flow_draft_restore"]["flow_definition"] = plan[
        "preserved_draft_candidate"
    ]
    templates["work_draft_save"]["pages"] = plan["work_pages"]
    templates["work_draft_restore"]["pages"] = plan["preserved_work_draft_pages"]
    templates["flow_publish"]["message"] = (
        "Préparation visuelle, revue qualité et entrées événementielles ; "
        "prévision classique qualifiée, SLA v5 et brouillon utilisateur conservés."
    )
    templates["work_release"]["notes"] = (
        "Parcours SAV : préparation visuelle, Judge et événements ; prévision "
        "classique v2 et accès au challenger explicable v6, sans changer le champion SLA."
    )
    review.update(
        target_flow_sha256=target,
        configuration_sha256=planner.digest(plan),
        nodes=len(plan["publication_candidate"]["nodes"]),
        edges=len(plan["publication_candidate"]["edges"]),
        visual_preparation=True,
        forecast_model_id=forecast_params["model_id"],
        forecast_version=forecast_params["pinned_version"],
        challenger_model_id=challenger_id,
        shadow_activated=False,
    )
    return plan, review


if __name__ == "__main__":
    snapshots, forecast_path, challenger, output = sys.argv[1:]
    output = Path(output)
    if output.exists() or output.with_suffix(".review.json").exists():
        raise SystemExit("Use a fresh output path")
    plan, review = compose(
        Path(snapshots), json.loads(Path(forecast_path).read_text()), challenger
    )
    output.write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    output.with_suffix(".review.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2)
    )
    print(json.dumps(review, ensure_ascii=False, indent=2))
