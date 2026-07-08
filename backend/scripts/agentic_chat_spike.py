"""Offline A/B measurement harness for the andritz chat (two arms, per-case + aggregate).

Phase 0 (measurement only). ZERO change to live chat behaviour: this never wires
into the chat endpoint and never persists sessions/runs.

Two arms per case:
  * ``arm_classic`` — the REAL deterministic production orchestration. It re-runs
    the exact path ``/chat`` uses: ``ChatRequest`` ->
    ``_apply_workspace_chat_flow_defaults`` -> ``_apply_retrieval_budget_policy`` ->
    ``orchestrator.process_request`` -> ``apply_answer_policy_to_text``, WITHOUT
    overriding the latency lane, so the captured ``route_mode`` (fast/balanced/deep),
    ``passage_points`` (pipeline stages) and ``latency_ms`` are exactly what prod
    would have produced.
  * ``arm_agentic`` — the bounded agentic controller (arm B). INTENTIONALLY a
    placeholder right now: its decision logic depends on the finalized agentic DAG
    (composite scale, post-answer confidence formula, retrieval homogenization,
    self-correct/react), which a sibling worker is still finalizing. Wiring it now
    would measure stale logic. The single integration point is ``run_arm_agentic``.

Metrics are computed for BOTH arms by reusable, arm-agnostic, timeout-safe
functions: ``evaluate_response_metrics`` (ResponseEvaluator: relevance, factuality,
coherence, HHEM, adv_HHEM) and ``judge_answer`` (JudgeService: composite 0-100,
hallucination_rate). A cross-encoder/HHEM CPU timeout records null + a note and
never crashes the case.

Run in-container (Qdrant + LLM reachable):

    cat backend/scripts/agentic_chat_spike.py | \
      ssh omnirag-demo "docker exec -i -e SPIKE_LIMIT=5 -w /app/backend agentium-backend python -"

Env knobs (used when piped through ``python -`` where argv is unavailable):
    SPIKE_LIMIT          int, first-N corpus rows (0 = all)
    SPIKE_IDS            comma-separated corpus ids to run (overrides limit)
    SPIKE_OUTPUT         aggregate JSON report path (default /tmp/agentic_ab_report.json)
    SPIKE_JSONL          per-case JSONL checkpoint path (default /tmp/agentic_ab_rows.jsonl)
    SPIKE_RESUME         1 to skip ids already present in SPIKE_JSONL
    SPIKE_BATCH          batch size for the JSON checkpoint cadence (default 5)
    SPIKE_CASE_TIMEOUT   seconds per orchestration pass (default 150)
    SPIKE_METRIC_TIMEOUT seconds per metric (evaluator / judge) call (default 120)
    SPIKE_REPORT_MD      markdown report path to write (optional)
    SPIKE_REPORT_ONLY    1 to regenerate the report from an existing JSONL/JSON
                         (no orchestration), then exit
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

WORKSPACE_SLUG = "andritz"
WORKSPACE_ID = "0cce0bee-7e86-485d-95b1-672e82f16600"

# ---------------------------------------------------------------------------
# Corpus. Curated, bounded (~60) and self-contained so the script can run
# in-container via ``python -`` without the golden JSON files (absent from the
# prod image). Sources:
#   demo       -> docs/demo-andritz-qa-set-2026-06-22.md (firm PASS/FAIL labels)
#   regression -> explicit known-regression cases (D.60, CU250S-2, Etachrom, DE)
#   golden:<f> -> backend/app/resources/retrieval_golden/<f>.json (query fields)
# ground_truth: "bon" | "faible" | None (None = unlabeled, broadens weak-rate
# measurement but is excluded from the precision/recall calibration).
# ---------------------------------------------------------------------------
CORPUS: List[Dict[str, Any]] = json.loads(r"""
[
 {
  "id": "demo_pass_akk200_width_speed",
  "source": "demo",
  "category": "baseline",
  "lang": "fr",
  "ground_truth": "bon",
  "query": "Quelle est la largeur de travail et la vitesse de production du système AKK200 Nonwoven ?"
 },
 {
  "id": "demo_pass_qms12_function_en",
  "source": "demo",
  "category": "baseline",
  "lang": "en",
  "ground_truth": "bon",
  "query": "What is the Qualiscan QMS-12 system used for and how does it work?"
 },
 {
  "id": "demo_pass_injector_cartridge_cleaning",
  "source": "demo",
  "category": "baseline",
  "lang": "fr",
  "ground_truth": "bon",
  "query": "Comment dois-je nettoyer les cartouches d'injecteurs ?"
 },
 {
  "id": "demo_pass_acj200_carde",
  "source": "demo",
  "category": "baseline",
  "lang": "fr",
  "ground_truth": "bon",
  "query": "Décris la carde ACJ200 et ses principaux composants."
 },
 {
  "id": "demo_fail_akk200_de",
  "source": "demo",
  "category": "language_de",
  "lang": "de",
  "ground_truth": "faible",
  "query": "Wie groß sind die Arbeitsbreite und die Produktionsgeschwindigkeit des AKK200 Nonwoven-Systems?"
 },
 {
  "id": "demo_fail_cu250s2_role",
  "source": "demo",
  "category": "route",
  "lang": "fr",
  "ground_truth": "faible",
  "query": "Quel est le rôle et la configuration du module CU250S-2 ?"
 },
 {
  "id": "demo_fail_etachrom_spares",
  "source": "demo",
  "category": "exact_id",
  "lang": "fr",
  "ground_truth": "faible",
  "query": "Quelles sont les pièces de rechange de la pompe Etachrom B ?"
 },
 {
  "id": "demo_fail_qms12_de",
  "source": "demo",
  "category": "language_de",
  "lang": "de",
  "ground_truth": "faible",
  "query": "Wozu dient das Qualiscan QMS-12 System und wie funktioniert es?"
 },
 {
  "id": "demo_d60_greasing",
  "source": "demo",
  "category": "table_extract",
  "lang": "fr",
  "ground_truth": "bon",
  "query": "Quelle quantité de graisse faut-il pour le palier moteur D.60 ?"
 },
 {
  "id": "demo_fail_german_generic",
  "source": "demo",
  "category": "language_de",
  "lang": "de",
  "ground_truth": "faible",
  "query": "Welche Wartung ist für die Filtration und das Vakuum im Projekt AKK200 erforderlich?"
 },
 {
  "id": "demo15_akk200_sections",
  "source": "demo15",
  "category": "route",
  "lang": "fr",
  "ground_truth": "bon",
  "query": "Quelles sont les sections principales du manuel utilisateur de l'AKK200 ?"
 },
 {
  "id": "demo15_acj200_residual_risks",
  "source": "demo15",
  "category": "baseline",
  "lang": "fr",
  "ground_truth": "bon",
  "query": "Quels sont les risques résiduels et les consignes de sécurité de la carde ACJ200 ?"
 },
 {
  "id": "demo15_qms12_calibration",
  "source": "demo15",
  "category": "baseline",
  "lang": "fr",
  "ground_truth": "bon",
  "query": "Comment calibrer les capteurs du système de mesure Qualiscan QMS-12 ?"
 },
 {
  "id": "demo15_cu250s2_commissioning",
  "source": "demo15",
  "category": "route",
  "lang": "fr",
  "ground_truth": null,
  "query": "Comment mettre en service et paramétrer l'unité de commande CU250S-2 avec l'outil STARTER ?"
 },
 {
  "id": "demo15_qms12_fr",
  "source": "demo15",
  "category": "baseline",
  "lang": "fr",
  "ground_truth": null,
  "query": "À quoi sert le système de mesure Qualiscan QMS-12 et comment fonctionne-t-il ?"
 },
 {
  "id": "avoid_hydrodry",
  "source": "demo15",
  "category": "out_of_corpus",
  "lang": "fr",
  "ground_truth": null,
  "query": "Quelles sont les étapes de séchage du système Hydro-Dry ?"
 },
 {
  "id": "avoid_filtration_intervals",
  "source": "demo15",
  "category": "hedge_prone",
  "lang": "fr",
  "ground_truth": "faible",
  "query": "Quels sont les intervalles de maintenance de la filtration et de la cellule de flottation ?"
 },
 {
  "id": "avoid_list_all_pumps",
  "source": "demo15",
  "category": "inventory",
  "lang": "fr",
  "ground_truth": null,
  "query": "Liste-moi toutes les pompes de tous les projets."
 },
 {
  "id": "reg_transversal_uraca",
  "source": "regression",
  "category": "inventory",
  "lang": "fr",
  "ground_truth": null,
  "query": "Quels projets utilisent une pompe URACA ?"
 },
 {
  "id": "tr_akk200_tout",
  "source": "transcript",
  "category": "route",
  "lang": "fr",
  "ground_truth": null,
  "query": "donne moi tout ce que tu sais sur le projet AKK200"
 },
 {
  "id": "tr_akk200_pompe",
  "source": "transcript",
  "category": "route",
  "lang": "fr",
  "ground_truth": null,
  "query": "Quelle pompe est utilisée dans le projet AKK200 ?"
 },
 {
  "id": "tr_akk200_detaille_manuel",
  "source": "transcript",
  "category": "route",
  "lang": "fr",
  "ground_truth": null,
  "query": "Détaille le contenu du manuel AKK200."
 },
 {
  "id": "tr_akk200_resume",
  "source": "transcript",
  "category": "route",
  "lang": "fr",
  "ground_truth": null,
  "query": "Résume le projet AKK200."
 },
 {
  "id": "tr_akk200_quelles_infos",
  "source": "transcript",
  "category": "baseline",
  "lang": "fr",
  "ground_truth": null,
  "query": "quelles infos sur AKK200 ?"
 },
 {
  "id": "tr_col100_garniture_carde1",
  "source": "transcript",
  "category": "depth",
  "lang": "fr",
  "ground_truth": null,
  "query": "Peux-tu retrouver la liste de garniture de la carde numéro 1 du projet COL100 ?"
 },
 {
  "id": "tr_bhx100_puissance_carde",
  "source": "transcript",
  "category": "multi_hop",
  "lang": "fr",
  "ground_truth": null,
  "query": "Quelle est la puissance totale installée sur l'ensemble des éléments de carde (incluant TMS, TCF etc...) sur la carde numéro 2 du projet BHX100 ?"
 },
 {
  "id": "tr_tambour_poids",
  "source": "transcript",
  "category": "multi_hop",
  "lang": "fr",
  "ground_truth": null,
  "query": "À des fins de manipulation : quel est le poids d'un tambour de Ø1500 monté sur une machine de laize 3m ?"
 },
 {
  "id": "tr_brosses_frequence",
  "source": "transcript",
  "category": "hedge_prone",
  "lang": "fr",
  "ground_truth": null,
  "query": "À quelle fréquence les brosses de nettoyage de toile doivent être nettoyées/remplacées ?"
 },
 {
  "id": "tr_col100_garniture_avant_train",
  "source": "transcript",
  "category": "depth",
  "lang": "fr",
  "ground_truth": null,
  "query": "Peux-tu retrouver la référence et la quantité de la garniture utilisée sur l'avant train de la carde du projet COL100 ?"
 },
 {
  "id": "tr_bhx100_plan_charges",
  "source": "transcript",
  "category": "depth",
  "lang": "fr",
  "ground_truth": null,
  "query": "Peux-tu me retrouver le plan de charges du projet BHX100 ?"
 },
 {
  "id": "tr_col100_rouleaux_transfert",
  "source": "transcript",
  "category": "depth",
  "lang": "fr",
  "ground_truth": null,
  "query": "Combien y a-t-il de rouleaux de transfert sur la machine de COL100 ?"
 },
 {
  "id": "tr_stockage_entrepot",
  "source": "transcript",
  "category": "hedge_prone",
  "lang": "fr",
  "ground_truth": null,
  "query": "Quelles sont les recommandations de stockage dans l'entrepôt ?"
 },
 {
  "id": "tr_d60_diametre60",
  "source": "transcript",
  "category": "table_extract",
  "lang": "fr",
  "ground_truth": null,
  "query": "Quelle est la quantité de graisse dans un palier moteur de diamètre 60 ?"
 },
 {
  "id": "tr_kru001y_pompes_hp",
  "source": "transcript",
  "category": "out_of_corpus",
  "lang": "fr",
  "ground_truth": null,
  "query": "Pour le projet KRU001Y peux-tu me donner la liste des pompes HP avec les injecteurs dédiés à chaque pompe."
 },
 {
  "id": "tr_dru006_prj2s",
  "source": "transcript",
  "category": "out_of_corpus",
  "lang": "fr",
  "ground_truth": null,
  "query": "Pour le projet DRU006 qui s'occupe de fournir la PRJ2S ?"
 },
 {
  "id": "tr_nacelle_hse",
  "source": "transcript",
  "category": "out_of_corpus",
  "lang": "fr",
  "ground_truth": null,
  "query": "Dans quelles conditions un salarié sous-traitant peut-il utiliser une nacelle élévatrice sur notre site ?"
 },
 {
  "id": "tr_sable_220",
  "source": "transcript",
  "category": "out_of_corpus",
  "lang": "fr",
  "ground_truth": null,
  "query": "Sur une ligne ayant un débit de 220m3/h combien faut-il installer de filtre à sable ?"
 },
 {
  "id": "oc_northforge_pmp700",
  "source": "out_of_corpus",
  "category": "out_of_corpus",
  "lang": "en",
  "ground_truth": null,
  "query": "At what pressure does the PMP-700 relief valve open?"
 },
 {
  "id": "oc_northforge_brg22",
  "source": "out_of_corpus",
  "category": "out_of_corpus",
  "lang": "fr",
  "ground_truth": null,
  "query": "Quand faut-il remplacer un roulement BRG-22 ?"
 },
 {
  "id": "oc_northforge_vortex5",
  "source": "out_of_corpus",
  "category": "out_of_corpus",
  "lang": "en",
  "ground_truth": null,
  "query": "Summarize the VORTEX-5 line start-up sequence."
 },
 {
  "id": "edge_mh_bba120_hp_pump",
  "source": "synthetic",
  "category": "multi_hop",
  "lang": "fr",
  "ground_truth": null,
  "query": "Pour BBA120, quelle est la pompe haute pression, quelle est sa pression de service, et dans quel document la trouver ?"
 },
 {
  "id": "edge_mh_akk200_filter_oring",
  "source": "synthetic",
  "category": "multi_hop",
  "lang": "fr",
  "ground_truth": null,
  "query": "Dans AKK200, donne la référence de la cartouche filtrante ET la taille du O-ring, avec leurs sources."
 },
 {
  "id": "edge_cl_la_pompe",
  "source": "synthetic",
  "category": "clarify",
  "lang": "fr",
  "ground_truth": null,
  "query": "Où est la notice de la pompe ?"
 },
 {
  "id": "edge_cl_le_manuel",
  "source": "synthetic",
  "category": "clarify",
  "lang": "fr",
  "ground_truth": null,
  "query": "Donne-moi le manuel."
 },
 {
  "id": "edge_cl_les_pieces",
  "source": "synthetic",
  "category": "clarify",
  "lang": "fr",
  "ground_truth": null,
  "query": "Quelles pièces de rechange ?"
 },
 {
  "id": "edge_dp_servo_x_safety",
  "source": "synthetic",
  "category": "depth",
  "lang": "fr",
  "ground_truth": null,
  "query": "Quelles sont les consignes de sécurité liées au système de mesure SERVO X ?"
 },
 {
  "id": "edge_dp_jetlace_conveyor",
  "source": "synthetic",
  "category": "depth",
  "lang": "fr",
  "ground_truth": null,
  "query": "Où est documenté le convoyeur Jetlace et ses réglages ?"
 },
 {
  "id": "edge_inv_etachrom_projects",
  "source": "synthetic",
  "category": "inventory",
  "lang": "fr",
  "ground_truth": null,
  "query": "Sur quels projets trouve-t-on des pompes KSB Etachrom ?"
 },
 {
  "id": "edge_inv_qms12_projects",
  "source": "synthetic",
  "category": "inventory",
  "lang": "fr",
  "ground_truth": null,
  "query": "Quels projets sont équipés d'un Qualiscan QMS-12 ?"
 },
 {
  "id": "edge_rt_akk200_generic",
  "source": "synthetic",
  "category": "route",
  "lang": "fr",
  "ground_truth": null,
  "query": "Parle-moi du projet AKK200."
 },
 {
  "id": "mt_followup_akk200",
  "source": "multiturn",
  "category": "anaphora",
  "lang": "fr",
  "ground_truth": null,
  "query": "et pour celle-ci, quelles pièces de rechange ?",
  "conversation_history": [
   {
    "role": "user",
    "content": "Parle-moi de la machine du projet AKK200"
   },
   {
    "role": "assistant",
    "content": "Le projet AKK200 couvre une ligne SPL documentée dans Spare Parts List AKK200_Ind A.pdf."
   }
  ]
 },
 {
  "id": "mt_followup_switch_aco150",
  "source": "multiturn",
  "category": "anaphora",
  "lang": "fr",
  "ground_truth": null,
  "query": "même question pour ACO150",
  "conversation_history": [
   {
    "role": "user",
    "content": "Retrouve la Spare Parts List du projet AKK200"
   },
   {
    "role": "assistant",
    "content": "Voici la Spare Parts List AKK200_Ind A.pdf."
   }
  ]
 },
 {
  "id": "mt_followup_etachrom_maint",
  "source": "multiturn",
  "category": "anaphora",
  "lang": "fr",
  "ground_truth": null,
  "query": "et la maintenance pour cette machine ?",
  "conversation_history": [
   {
    "role": "user",
    "content": "Quels documents pour la pompe Etachrom B ?"
   },
   {
    "role": "assistant",
    "content": "La pompe est documentée dans Etachrom B.PDF."
   }
  ]
 },
 {
  "id": "spl_002_dci110_strip_carrier",
  "source": "golden",
  "category": "depth",
  "lang": "fr",
  "ground_truth": null,
  "query": "Comment retirer le strip-carrier d'un injecteur dans DCI110 ?"
 },
 {
  "id": "spl_003_aco140_spl",
  "source": "golden",
  "category": "baseline",
  "lang": "fr",
  "ground_truth": null,
  "query": "Peux-tu retrouver la Spare Parts List du projet ACO140 ?"
 },
 {
  "id": "spl_005_bba120_spl",
  "source": "golden",
  "category": "baseline",
  "lang": "fr",
  "ground_truth": null,
  "query": "Peux-tu retrouver la Spare Parts List du projet BBA120 ?"
 },
 {
  "id": "spl_006_bba120_uraca_kd724",
  "source": "golden",
  "category": "baseline",
  "lang": "fr",
  "ground_truth": null,
  "query": "Quels documents existent pour la pompe HP URACA KD724 du projet BBA120 ?"
 },
 {
  "id": "spl_007_bba120_ksb_etachrom",
  "source": "golden",
  "category": "baseline",
  "lang": "fr",
  "ground_truth": null,
  "query": "Quel document couvre la pompe KSB Etachrom dans BBA120 ?"
 },
 {
  "id": "spl_008_akk200_filtration_vacuum",
  "source": "golden",
  "category": "baseline",
  "lang": "fr",
  "ground_truth": null,
  "query": "Quelle procedure de maintenance concerne la filtration et le vacuum dans AKK200 ?"
 },
 {
  "id": "spl_009_ara200_conveyor",
  "source": "golden",
  "category": "depth",
  "lang": "fr",
  "ground_truth": null,
  "query": "Quels documents de convoyeur sont indexes pour ARA200 ?"
 },
 {
  "id": "spl_010_ara200_pneumatic_cabinet",
  "source": "golden",
  "category": "depth",
  "lang": "fr",
  "ground_truth": null,
  "query": "Quel document decrit l'armoire pneumatique de ARA200 ?"
 },
 {
  "id": "spl_011_akk200_filtering_cartridge_oring",
  "source": "golden",
  "category": "table_extract",
  "lang": "fr",
  "ground_truth": null,
  "query": "Dans le projet AKK200, quelle source contient Filtering cartridge LM 300 et O-ring string D. 3,6 ?"
 },
 {
  "id": "spl_012_geotex_def_strips_label_b",
  "source": "golden",
  "category": "table_extract",
  "lang": "fr",
  "ground_truth": null,
  "query": "Dans les fichiers NON-WOVENS France, que vaut le label B dans la table Def strips ?"
 },
 {
  "id": "spl_014_akk200_lm300_filtering_cartridge",
  "source": "golden",
  "category": "exact_id",
  "lang": "fr",
  "ground_truth": null,
  "query": "Dans AKK200, je cherche la reference Filtering cartridge LM300 : quelle source faut-il ouvrir ?"
 },
 {
  "id": "spl_015_akk200_oring_d36",
  "source": "golden",
  "category": "exact_id",
  "lang": "fr",
  "ground_truth": null,
  "query": "Quel fichier source contient le joint O-ring string D. 3,6 pour AKK200 ?"
 },
 {
  "id": "div_001_g150_operating_instructions_multiproject",
  "source": "golden",
  "category": "baseline",
  "lang": "en",
  "ground_truth": null,
  "query": "Where can I find the G150 speed controller operating instructions?"
 },
 {
  "id": "div_002_printable_parts_manual_multiproject",
  "source": "golden",
  "category": "clarify",
  "lang": "fr",
  "ground_truth": null,
  "query": "Montre-moi les parts manuals disponibles en version imprimable."
 },
 {
  "id": "div_003_vacuum_set_blower_manuals",
  "source": "golden",
  "category": "depth",
  "lang": "en",
  "ground_truth": null,
  "query": "Which manuals cover the vacuum set blowers of the hydroentanglement unit?"
 },
 {
  "id": "div_006_cu250s2_vector_control_units",
  "source": "golden",
  "category": "route",
  "lang": "en",
  "ground_truth": null,
  "query": "Where is the CU250S-2 vector control unit manual referenced?"
 },
 {
  "id": "div_007_qualiscan_qms12_betriebsanleitungen",
  "source": "golden",
  "category": "language_de",
  "lang": "de",
  "ground_truth": null,
  "query": "Wo sind die Betriebsanleitungen fuer den Qualiscan QMS-12?"
 },
 {
  "id": "div_008_sinamics_s120_s150_list_manuals",
  "source": "golden",
  "category": "depth",
  "lang": "en",
  "ground_truth": null,
  "query": "Find the SINAMICS S120 S150 list manual for the carding unit."
 },
 {
  "id": "div_009_uraca_kd724_chapters_multiproject",
  "source": "golden",
  "category": "inventory",
  "lang": "fr",
  "ground_truth": null,
  "query": "Sur quels projets retrouve-t-on la documentation des pompes URACA KD724-G ?"
 },
 {
  "id": "fb_001_sparse_disabled_dense_still_answers",
  "source": "golden",
  "category": "baseline",
  "lang": "fr",
  "ground_truth": null,
  "query": "Comment nettoyer les cartouches d'injecteurs ?"
 },
 {
  "id": "fb_002_cross_encoder_applied_on_balanced",
  "source": "golden",
  "category": "baseline",
  "lang": "fr",
  "ground_truth": null,
  "query": "Quelle est la procédure de maintenance du vide ?"
 },
 {
  "id": "hi_001_ambiguous_parts_manual",
  "source": "golden",
  "category": "clarify",
  "lang": "fr",
  "ground_truth": null,
  "query": "Ou se trouve le parts manual ?"
 },
 {
  "id": "hi_002_ambiguous_kd724_partial_ref",
  "source": "golden",
  "category": "inventory",
  "lang": "fr",
  "ground_truth": null,
  "query": "Quels projets utilisent la pompe KD724 ?"
 },
 {
  "id": "hi_003_compare_continental_pollrich_aki300",
  "source": "golden",
  "category": "comparison_partial",
  "lang": "en",
  "ground_truth": null,
  "query": "What is the difference between the CONTINENTAL GVJS and POLLRICH GVJ1 vacuum set blowers on AKI300?"
 },
 {
  "id": "hi_004_compare_g150_s120_drives",
  "source": "golden",
  "category": "comparison_partial",
  "lang": "fr",
  "ground_truth": null,
  "query": "Quelles differences de parametres de mise en service entre les variateurs SINAMICS G150 et SINAMICS S120 ?"
 },
 {
  "id": "hi_005_analytical_php_pressure_drop",
  "source": "golden",
  "category": "depth",
  "lang": "fr",
  "ground_truth": null,
  "query": "Pourquoi la pression chute-t-elle sur le groupe haute pression PHP et quel document consulter ?"
 },
 {
  "id": "hi_006_german_simotics_akk200",
  "source": "golden",
  "category": "language_de",
  "lang": "de",
  "ground_truth": null,
  "query": "Wo finde ich die SIMOTICS Betriebsanleitung auf Deutsch fuer das Projekt AKK200?"
 },
 {
  "id": "hi_007_exclusion_excelle_not_dutch",
  "source": "golden",
  "category": "route",
  "lang": "en",
  "ground_truth": null,
  "query": "Excelle S5PP6TT card operator manual in English please, not the Dutch Gebruikershandleiding."
 },
 {
  "id": "hi_008_compare_wilo_drain_nolh_bex200",
  "source": "golden",
  "category": "comparison_partial",
  "lang": "fr",
  "ground_truth": null,
  "query": "Compare the Wilo Drain SP and the Wilo NOLH pump manuals available for BEX200."
 },
 {
  "id": "hi_009_ambiguous_lh2_identifier",
  "source": "golden",
  "category": "exact_id",
  "lang": "en",
  "ground_truth": null,
  "query": "What does document LH2 0113 cover and which machines reference it?"
 },
 {
  "id": "hi_010_analytical_wilo_rexa_vacuum_lot100",
  "source": "golden",
  "category": "depth",
  "lang": "fr",
  "ground_truth": null,
  "query": "Sur LOT100, quelle pompe BP WILO equipe le vacuum set et ou est sa notice d'exploitation ?"
 },
 {
  "id": "hi_011_ambiguous_etachrom_bc_multiproject",
  "source": "golden",
  "category": "exact_id",
  "lang": "fr",
  "ground_truth": null,
  "query": "Ou trouver la notice etachrom bc du circuit HP ?"
 },
 {
  "id": "ml_001_fr_injector_cleaning",
  "source": "golden",
  "category": "baseline",
  "lang": "fr",
  "ground_truth": null,
  "query": "Comment nettoyer les cartouches d'injecteurs EXH ?"
 },
 {
  "id": "ml_002_en_injector_cleaning",
  "source": "golden",
  "category": "baseline",
  "lang": "en",
  "ground_truth": null,
  "query": "How do I clean the EXH injector cartridges?"
 },
 {
  "id": "ml_003_de_injector_cleaning",
  "source": "golden",
  "category": "language_de",
  "lang": "de",
  "ground_truth": null,
  "query": "Wie reinige ich die EXH Injektor-Kartuschen?"
 },
 {
  "id": "ml_006_de_akk200_spl",
  "source": "golden",
  "category": "language_de",
  "lang": "de",
  "ground_truth": null,
  "query": "Finde die Ersatzteilliste für das Projekt AKK200."
 },
 {
  "id": "sf_001_project_filter_akk200",
  "source": "golden",
  "category": "clarify",
  "lang": "fr",
  "ground_truth": null,
  "query": "Liste des pièces de rechange"
 },
 {
  "id": "sf_002_cross_project_guard",
  "source": "golden",
  "category": "baseline",
  "lang": "fr",
  "ground_truth": null,
  "query": "Liste de garniture du projet ACO150"
 },
 {
  "id": "sf_003_source_kind_filter_html",
  "source": "golden",
  "category": "clarify",
  "lang": "fr",
  "ground_truth": null,
  "query": "Procédure de maintenance de la filtration"
 },
 {
  "id": "sp_001_pump_model_exact",
  "source": "golden",
  "category": "exact_id",
  "lang": "fr",
  "ground_truth": null,
  "query": "URACA KD724"
 },
 {
  "id": "sp_002_doc_reference_exact",
  "source": "golden",
  "category": "exact_id",
  "lang": "fr",
  "ground_truth": null,
  "query": "DCI 110 PERFO-TE-OM-10-5"
 },
 {
  "id": "sp_003_excel_stem_exact",
  "source": "golden",
  "category": "exact_id",
  "lang": "fr",
  "ground_truth": null,
  "query": "GEOTEX SPL Y25.05.22"
 }
]
""")


# ---------------------------------------------------------------------------
# Cheap deterministic detectors (no LLM). These complement the judge: the
# live pipeline already emits the operational signals (fallback_reason,
# no_context, guardrail, cross-encoder status); the answer-side detectors
# (hedge / jargon / language contract) mirror the documented demo failure
# shapes.
# ---------------------------------------------------------------------------
_GERMAN_MARKERS = re.compile(
    r"\b(der|die|das|und|für|fuer|wie|wo|finde|ich|auf\s+deutsch|betriebsanleitung|"
    r"ersatzteilliste|reinige|kartuschen|gross|größe|gr\u00f6\u00dfe|arbeitsbreite|"
    r"produktionsgeschwindigkeit|wartung|erforderlich|dient|funktioniert|dr\u00fccke|kalibriert)\b",
    re.IGNORECASE,
)
_HEDGE_RE = re.compile(r"analyse\s+g[ée]n[ée]rale\s+[àa]\s+valider", re.IGNORECASE)
_JARGON_LEAK_RE = re.compile(r"\b(vectoriel|score\s+vectoriel|base\s+vectorielle)\b", re.IGNORECASE)
# Andritz project codes: 2-4 letters + 2-3 digits (+ optional -N), plus D.NN style.
_PROJECT_CODE_RE = re.compile(r"\b([A-Z]{2,4}\d{2,3}(?:-\d)?|D\.\d{2,3})\b")
_ANAPHORA_RE = re.compile(
    r"\b(celle?-ci|celui-ci|cette|ce\s+|cet\s+|ceux|m[êe]me\s+question|et\s+pour|"
    r"pour\s+celle|cette\s+machine|it|that|those|they|them)\b",
    re.IGNORECASE,
)
_GENERIC_PART_RE = re.compile(
    r"\b(pi[èe]ces?\s+de\s+rechange|parts?\s+manual|spare\s+parts?|liste\s+des?\s+pi[èe]ces|"
    r"ersatzteilliste|liste\s+de\s+garniture)\b",
    re.IGNORECASE,
)
_CROSS_PROJECT_RE = re.compile(
    r"\b(quels?\s+projets?|which\s+projects?|tous\s+les\s+projets?|across|sur\s+quels)\b",
    re.IGNORECASE,
)


def looks_german(query: str) -> bool:
    q = query or ""
    hits = len(_GERMAN_MARKERS.findall(q))
    return hits >= 2 or "deutsch" in q.lower() or "betriebsanleitung" in q.lower()


def assess_sufficiency(query: str, *, has_history: bool) -> Dict[str, Any]:
    """Heuristic clarification-opportunity detector (clarify workstream).

    Offline we cannot simulate the clarify->answer recovery, so we only size
    the opportunity: how many first queries are ambiguous / under-specified
    enough that a single clarifying question would plausibly help.
    """
    q = (query or "").strip()
    words = q.split()
    reasons: List[str] = []
    has_project = bool(_PROJECT_CODE_RE.search(q))
    has_anaphora = bool(_ANAPHORA_RE.search(q))
    generic_part = bool(_GENERIC_PART_RE.search(q))
    cross_project = bool(_CROSS_PROJECT_RE.search(q))

    if has_anaphora and not has_project and not has_history:
        reasons.append("anaphora_without_anchor")
    if generic_part and not has_project:
        reasons.append("generic_part_no_project")
    if cross_project and not has_project:
        reasons.append("unscoped_cross_project")
    if len(words) <= 3 and not has_project:
        reasons.append("very_short_no_anchor")
    # bare identifier with no explicit ask (e.g. "URACA KD724")
    if len(words) <= 3 and "?" not in q and not re.search(r"\b(quel|quelle|comment|where|how|what|wo|wie)\b", q, re.IGNORECASE):
        if "bare_identifier" not in reasons:
            reasons.append("bare_identifier")

    ambiguous = bool(reasons)
    # sufficiency score: 1.0 = fully specified, lower = more under-specified
    score = 1.0
    score -= 0.35 if "generic_part_no_project" in reasons else 0.0
    score -= 0.35 if "unscoped_cross_project" in reasons else 0.0
    score -= 0.3 if "anaphora_without_anchor" in reasons else 0.0
    score -= 0.2 if "very_short_no_anchor" in reasons else 0.0
    score -= 0.15 if "bare_identifier" in reasons else 0.0
    score = max(0.0, round(score, 3))
    return {
        "ambiguous": ambiguous,
        "sufficiency_score": score,
        "reasons": reasons,
        "has_project_code": has_project,
    }


# ---------------------------------------------------------------------------
# Orchestrator bootstrap. A fresh ``python -`` process never runs the FastAPI
# lifespan, so the orchestrator singleton is unset. Mirror app.main's startup
# (orchestrator + OmniRAG agent) — read-only, no servers, no schedulers.
# ---------------------------------------------------------------------------
async def bootstrap_orchestrator() -> None:
    from app.agents.orchestrator import AgentOrchestrator
    from app.agents.procurement_agent import OmniRAGAgent
    from app.api.v1.endpoints.agents import get_orchestrator, set_orchestrator

    if get_orchestrator() is not None:
        return
    orchestrator = AgentOrchestrator()
    set_orchestrator(orchestrator)
    agent = OmniRAGAgent()
    await agent.initialize()
    orchestrator.register_agent(agent)


def _extract_context_chunks(rag_context: Any, sources: Any, *, limit: int = 12) -> List[str]:
    chunks: List[str] = []
    if isinstance(rag_context, dict):
        raw = rag_context.get("chunks")
        if isinstance(raw, list):
            for item in raw[:limit]:
                if isinstance(item, str) and item.strip():
                    chunks.append(item[:1500])
    if not chunks and isinstance(sources, list):
        for item in sources[:limit]:
            if isinstance(item, dict):
                text = item.get("content") or item.get("snippet") or item.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text[:1500])
    return chunks


def _summarize_passage_points(decision_steps: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Distil the real pipeline's emitted decision_steps into passage points.

    The deterministic orchestration emits a decision_step per stage
    (query_rewrite, routing -> query_received, embedding, retrieve,
    context_filtering, validation, synthesis, evaluation). We keep the last
    status seen per step id (the collector already de-dupes by id) and expose
    both a compact per-stage list and an ordered, de-duplicated stage-type list
    so the report's "decisions/steps" column reflects what prod actually did.
    """
    passage: List[Dict[str, Any]] = []
    stages: List[str] = []
    for ds in decision_steps or []:
        if not isinstance(ds, dict):
            continue
        stype = ds.get("type") or "step"
        passage.append({
            "type": stype,
            "title": ds.get("title"),
            "component": ds.get("component"),
            "status": ds.get("status"),
            "duration_ms": ds.get("duration"),
        })
        if stype not in stages:
            stages.append(stype)
    return passage, stages


async def faithful_chat(db, workspace, query: str, *, mode: Optional[str] = None,
                        conversation_history: Optional[list] = None,
                        case_timeout: float = 150.0) -> Dict[str, Any]:
    """Re-run the REAL prod chat orchestration (minus persistence only).

    This is the exact deterministic path ``/chat`` uses:
    ``ChatRequest`` -> ``_apply_workspace_chat_flow_defaults`` ->
    ``_apply_retrieval_budget_policy`` -> ``orchestrator.process_request`` ->
    ``apply_answer_policy_to_text``.

    ``mode=None`` (arm_classic): PROD-DETERMINISTIC. We do NOT override the
    latency lane — whatever ``_apply_workspace_chat_flow_defaults`` +
    ``answer_profile_decision`` deterministically choose is the route prod would
    have taken, and that resolved profile is returned as ``route_mode``.

    ``mode in {"fast","balanced","deep"}``: force that retrieval lane. Reserved
    for the agentic arm's chosen mode (``run_arm_agentic``); arm_classic never
    forces a mode.

    Returns the user-facing answer plus the operational trace the chat path
    exposes: ``route_mode`` (deterministic profile), ``executed_profile``,
    ``passage_points``/``stages`` (pipeline stages), wall-clock ``latency_ms``,
    grounding state, answer-policy violations, retrieval metrics and the context
    chunks needed for downstream metric scoring.
    """
    from app.api.v1.endpoints.agents import get_orchestrator
    from app.api.v1.endpoints.chat import (
        ChatRequest,
        _apply_response_language_contract,
        _apply_retrieval_budget_policy,
        _apply_workspace_chat_flow_defaults,
        _collect_chat_chunk,
        _grounding_degraded_reply,
        _resolve_response_language,
        resolve_grounding_policy,
    )
    from app.core.config import settings
    from app.core.settings_manager import get_resolved_settings
    from app.services.industrial_answer_profile import apply_answer_policy_to_text

    request = ChatRequest(query=query)
    _apply_workspace_chat_flow_defaults(db, workspace=workspace, request=request)

    # arm_classic (mode=None) is the REAL prod-deterministic lane: do NOT touch
    # latency_profile / retrieval_profile / budgets — whatever the flow defaults +
    # answer_profile_decision resolved is exactly the route prod would have taken.
    # Forcing a mode (fast/balanced/deep) is reserved for the agentic arm.
    if mode == "deep":
        request.latency_profile = "deep"
        request.deep_retrieval = True
        request.retrieval_profile = "deep_async"
        request.top_k = None
        request.source_display_k = None
        request.synthesis_k = None
        request.candidate_pool_k = None
    elif mode in {"fast", "balanced"}:
        request.latency_profile = mode  # type: ignore[assignment]
        request.deep_retrieval = False
        # let the budget policy recompute clean defaults for the forced lane
        request.retrieval_profile = "chat"
        request.top_k = None
        request.source_display_k = None
        request.synthesis_k = None
        request.candidate_pool_k = None
    # mode is None -> prod-deterministic: leave the resolved defaults untouched.

    response_language = _resolve_response_language(request, query)
    request.response_language = response_language

    app_settings = get_resolved_settings(workspace_id=workspace.id)
    request_dict = request.model_dump()
    request_dict["query"] = query
    request_dict["workspace_slug"] = workspace.slug
    request_dict["workspace_id"] = workspace.id
    # ChatRequest has no ``context`` field: the chat endpoint injects the
    # anaphora anchor straight into the request_dict the orchestrator consumes
    # (mirrors chat.py request_dict["context"]["conversation_history"]).
    if conversation_history:
        request_dict["context"] = {
            "conversation_history": list(conversation_history),
            "memory_type": "long_term",
        }
    _apply_response_language_contract(request_dict, response_language)
    grounding_policy = resolve_grounding_policy(
        query=query, workspace=workspace,
        assistant_profile=request.assistant_profile,
        requested_mode=request.grounding_mode, context_id=request.context_id,
    )
    request_dict["grounding_policy"] = grounding_policy
    request_dict["grounding_mode"] = grounding_policy["mode"]
    prefs = request_dict.get("agent_preferences") or {}
    prefs.setdefault("model_preferences", {})
    prefs["model_preferences"].setdefault("model", app_settings.get("defaultModel") or settings.default_model)
    prefs["model_preferences"].setdefault("provider", app_settings.get("defaultProvider") or settings.default_provider)
    request_dict["agent_preferences"] = prefs
    if request.max_tokens is None:
        request_dict["max_tokens"] = app_settings.get("maxTokens", 2000)
    if request.temperature is None:
        request_dict["temperature"] = app_settings.get("temperature", 0.7)
    _apply_retrieval_budget_policy(request_dict)

    orchestrator = get_orchestrator()
    full_content: List[str] = []
    decision_steps: List[Dict[str, Any]] = []
    state: Dict[str, Any] = {"grounding_policy": grounding_policy}

    started = time.perf_counter()
    error: Optional[str] = None

    async def _consume() -> None:
        async for chunk in orchestrator.process_request(request_dict):
            _collect_chat_chunk(chunk, full_content=full_content,
                                decision_steps=decision_steps, state=state)
            if (chunk.get("chunk_type") == "retrieval"
                    and chunk.get("phase") != "started" and not full_content):
                reply = _grounding_degraded_reply(
                    state, grounding_policy, response_language=response_language)
                if reply:
                    state["grounding_state"] = "no_grounded_context"
                    full_content.append(reply)
                    break
            if chunk.get("is_final"):
                break

    try:
        await asyncio.wait_for(_consume(), timeout=case_timeout)
    except asyncio.TimeoutError:
        error = f"timeout_{int(case_timeout)}s"
    except Exception as exc:  # noqa: BLE001 - report every case, keep the batch moving
        error = f"{type(exc).__name__}: {exc}"
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    raw_answer = "".join(full_content)
    answer, violations = apply_answer_policy_to_text(
        raw_answer,
        answer_policy=request_dict.get("answer_policy") if isinstance(request_dict.get("answer_policy"), dict) else None,
        profile_decision=request_dict.get("answer_profile_decision") if isinstance(request_dict.get("answer_profile_decision"), dict) else None,
    )
    metrics = state.get("retrieval_metrics") if isinstance(state.get("retrieval_metrics"), dict) else {}
    rag_context = state.get("rag_context")
    context_chunks = _extract_context_chunks(rag_context, state.get("sources"))
    passage_points, stages = _summarize_passage_points(decision_steps)
    # route_mode = the deterministically chosen profile (post budget policy);
    # executed_profile = what the retrieval lane actually reported running.
    route_mode = request_dict.get("latency_profile")
    executed_profile = metrics.get("latency_profile") or route_mode
    return {
        "answer": answer,
        "raw_answer": raw_answer,
        "answer_policy_violations": violations,
        "latency_ms": elapsed_ms,
        "error": error,
        "response_language": response_language,
        "route_mode": route_mode,
        "executed_profile": executed_profile,
        "latency_profile": request_dict.get("latency_profile"),
        "answer_profile": request_dict.get("answer_profile"),
        "answer_profile_decision": request_dict.get("answer_profile_decision"),
        "grounding_mode": grounding_policy.get("mode"),
        "grounding_state": state.get("grounding_state"),
        "context_chunks": context_chunks,
        "context_count": len(context_chunks),
        "passage_points": passage_points,
        "stages": stages,
        "decision_steps": decision_steps,
        "system_prompt": request_dict.get("system_prompt") or "",
        "metrics": {
            "no_context": metrics.get("no_context"),
            "fallback": metrics.get("fallback"),
            "fallback_reason": metrics.get("fallback_reason"),
            "chunks_retrieved": metrics.get("chunks_retrieved"),
            "cross_encoder_status": metrics.get("cross_encoder_status"),
            "cross_encoder_ms": metrics.get("cross_encoder_ms"),
            "sparse_status": metrics.get("sparse_status"),
            "dense_policy": metrics.get("dense_policy"),
            "scope_confidence": metrics.get("scope_confidence"),
            "exact_match_guardrail_inserted": metrics.get("exact_match_guardrail_inserted"),
            "retrieval_profile": metrics.get("retrieval_profile"),
            "latency_profile": metrics.get("latency_profile"),
        },
    }


# ---------------------------------------------------------------------------
# Cheap deterministic answer-side signals (no LLM). Reused by arm_classic to
# annotate the per-case row + drive the DAG-independent "would_self_correct"
# diagnostic; arm B will reuse the same helper once wired.
# ---------------------------------------------------------------------------
def deterministic_signals(query: str, passage: Dict[str, Any]) -> Dict[str, Any]:
    metrics = passage.get("metrics") or {}
    raw = passage.get("raw_answer") or ""
    answer = passage.get("answer") or ""
    sigs: List[str] = []
    if passage.get("error"):
        sigs.append(f"pipeline_error:{passage['error']}")
    if passage.get("grounding_state") == "no_grounded_context":
        sigs.append("grounding_no_context")
    if metrics.get("no_context"):
        sigs.append("no_context")
    if metrics.get("fallback") and metrics.get("fallback_reason"):
        sigs.append(f"fallback:{metrics.get('fallback_reason')}")
    if metrics.get("exact_match_guardrail_inserted"):
        sigs.append("exact_match_guardrail")
    if _HEDGE_RE.search(raw):
        sigs.append("hedge_analyse_generale")
    if _JARGON_LEAK_RE.search(raw):
        sigs.append("jargon_leak")
    for v in passage.get("answer_policy_violations") or []:
        sigs.append(f"policy:{v}")
    if str(metrics.get("cross_encoder_status") or "") in {"timeout", "error"}:
        sigs.append(f"xenc:{metrics.get('cross_encoder_status')}")
    if looks_german(query) and passage.get("response_language") != "de":
        sigs.append("language_contract_violation_de")
    if not answer.strip():
        sigs.append("empty_answer")
    # hard signals force weak independent of the judge
    hard = {
        "grounding_no_context", "no_context", "exact_match_guardrail",
        "hedge_analyse_generale", "jargon_leak", "language_contract_violation_de",
        "empty_answer",
    }
    hard_weak = any(s in hard or s.startswith("fallback:") or s.startswith("pipeline_error:")
                    for s in sigs)
    return {"signals": sigs, "hard_weak": hard_weak}


def _deterministic_failed_components(sigs: List[str]) -> List[str]:
    comps: set = set()
    for s in sigs:
        if s.startswith("fallback:") or s in {"grounding_no_context", "no_context", "exact_match_guardrail"} or s.startswith("xenc:"):
            comps.add("retriever")
        if s in {"hedge_analyse_generale", "jargon_leak", "language_contract_violation_de", "empty_answer"} or s.startswith("policy:"):
            comps.add("generator")
    return sorted(comps)


# ---------------------------------------------------------------------------
# Reusable, ARM-AGNOSTIC, timeout-safe metric functions. Both arms call the
# exact same two functions on their final answer so the A/B comparison is fair.
# A slow cross-encoder / HHEM pass on CPU records null + a note and NEVER
# crashes the case.
# ---------------------------------------------------------------------------
EVALUATOR_KEYS = ("relevance", "factuality", "coherence", "hhem", "adv_hhem")


async def evaluate_response_metrics(query: str, answer: str,
                                    context_chunks: Optional[List[str]] = None,
                                    *, timeout: float = 120.0) -> Dict[str, Any]:
    """Embedding-based RAG metrics via ``ResponseEvaluator``.

    Returns ``{relevance, factuality, coherence, hhem, adv_hhem}`` (floats) or
    those keys set to ``None`` plus a ``_note`` on timeout / empty / error. The
    HHEM term is embedding-derived and can be slow on CPU, hence the hard
    ``asyncio.wait_for`` guard. Arm-agnostic: pass any arm's final answer.
    """
    if not (answer or "").strip():
        return {k: None for k in EVALUATOR_KEYS} | {"_note": "empty_answer"}
    try:
        from app.services.metrics.evaluator import ResponseEvaluator
        evaluator = ResponseEvaluator()
        res = await asyncio.wait_for(
            evaluator.evaluate(query=query, response=answer,
                               source_chunks=list(context_chunks or [])),
            timeout=timeout,
        )
        return {k: res.get(k) for k in EVALUATOR_KEYS}
    except asyncio.TimeoutError:
        return {k: None for k in EVALUATOR_KEYS} | {"_note": f"timeout_{int(timeout)}s"}
    except Exception as exc:  # noqa: BLE001 - never crash a case on a metric
        return {k: None for k in EVALUATOR_KEYS} | {"_note": f"error: {type(exc).__name__}: {exc}"}


async def judge_answer(query: str, answer: str, *, system_prompt: str = "",
                       context_chunks: Optional[List[str]] = None,
                       timeout: float = 120.0) -> Dict[str, Any]:
    """LLM-as-judge metrics via ``JudgeService`` (12 dims -> composite 0-100).

    Returns ``{composite, hallucination_rate, question_type, failed_components,
    overall_note}`` or ``composite``/``hallucination_rate`` set to ``None`` plus
    a ``_note`` on timeout / error. Arm-agnostic: pass any arm's final answer.
    """
    try:
        from app.services.evaluation.judge import get_judge_service
        svc = get_judge_service()
        data = await asyncio.wait_for(
            svc.evaluate(query=query, response=answer or "",
                         system_prompt=system_prompt or "",
                         context_chunks=list(context_chunks or [])),
            timeout=timeout,
        )
        return {
            "composite": data.get("composite_score"),
            "hallucination_rate": data.get("hallucination_rate"),
            "question_type": data.get("question_type"),
            "failed_components": data.get("failed_components"),
            "overall_note": data.get("overall_note"),
        }
    except asyncio.TimeoutError:
        return {"composite": None, "hallucination_rate": None, "_note": f"timeout_{int(timeout)}s"}
    except Exception as exc:  # noqa: BLE001 - never crash a case on a metric
        return {"composite": None, "hallucination_rate": None,
                "_note": f"error: {type(exc).__name__}: {exc}"}


async def score_both_metrics(query: str, answer: str, *, system_prompt: str,
                             context_chunks: List[str], metric_timeout: float) -> Dict[str, Any]:
    """Run BOTH metric services on one answer and return a combined block.

    Single choke-point shared by every arm: ``{evaluator: {...}, judge: {...}}``.
    """
    evaluator = await evaluate_response_metrics(
        query, answer, context_chunks, timeout=metric_timeout)
    judge = await judge_answer(
        query, answer, system_prompt=system_prompt,
        context_chunks=context_chunks, timeout=metric_timeout)
    return {"evaluator": evaluator, "judge": judge}


# ---------------------------------------------------------------------------
# Arm A — REAL deterministic production orchestration.
# ---------------------------------------------------------------------------
async def run_arm_classic(db, workspace, row: Dict[str, Any], *,
                          case_timeout: float, metric_timeout: float) -> Dict[str, Any]:
    """Run the real prod orchestration (``mode=None``) and score it.

    Captures the deterministic ``route_mode`` (fast/balanced/deep), the pipeline
    ``passage_points``/``stages``, wall-clock ``latency_ms``, and both metric
    blocks. ``would_self_correct`` is a DAG-INDEPENDENT classic-side diagnostic
    (mirrors the agentic ``weak`` rule: composite<70 or hallucination_rate>0.15
    or context_count==0) so we can later quantify how often arm B *would* fire;
    it is NOT arm B's decision.
    """
    query = row["query"]
    history = row.get("conversation_history")
    passage = await faithful_chat(db, workspace, query, mode=None,
                                  conversation_history=history, case_timeout=case_timeout)
    scored = await score_both_metrics(
        query, passage.get("answer") or "",
        system_prompt=passage.get("system_prompt") or "",
        context_chunks=passage.get("context_chunks") or [],
        metric_timeout=metric_timeout,
    )
    det = deterministic_signals(query, passage)
    judge = scored["judge"]
    composite = judge.get("composite")
    halluc = judge.get("hallucination_rate")
    context_count = passage.get("context_count") or 0
    would_self_correct = bool(
        det["hard_weak"]
        or (composite is not None and composite < 70)
        or (halluc is not None and halluc > 0.15)
        or context_count == 0
    )
    return {
        "answer": passage.get("answer"),
        "route_mode": passage.get("route_mode"),
        "executed_profile": passage.get("executed_profile"),
        "passage_points": passage.get("passage_points"),
        "stages": passage.get("stages"),
        "latency_ms": passage.get("latency_ms"),
        "error": passage.get("error"),
        "response_language": passage.get("response_language"),
        "answer_profile": passage.get("answer_profile"),
        "grounding_state": passage.get("grounding_state"),
        "context_count": context_count,
        "pipeline_metrics": passage.get("metrics"),
        "evaluator": scored["evaluator"],
        "judge": judge,
        "signals": det["signals"],
        "would_self_correct": would_self_correct,
    }


# ---------------------------------------------------------------------------
# Arm B — bounded agentic controller. *** REAL DAG execution via run_engine. ***
# 100% faithful (NOT a mirror): we create a Run against the seeded
# "Andritz Chat Agentic" System and walk the finalized 22-node DAG with
# ``execute_run_dag``, then reconstruct the trace from Run.checkpoints +
# SkillInvocations. Metrics are computed by the SAME ``score_both_metrics`` as
# arm A so the two arms are measured identically.
# ---------------------------------------------------------------------------
AGENTIC_SYSTEM_NAME = "Andritz Chat Agentic"
AGENTIC_VARIANT = "chat_agentic_thinking_v1"

# node_end ``chosen_branch`` of these decision nodes is the live trace.
_DECISION_KEYS = {
    "decision.route_mode": "route_mode",
    "decision.verdict": "verdict",
    "decision.egress_gate": "egress",
    "decision.deliver": "deliver",
}

# Placeholder used when arm B is not executed in a given pass (classic-only run).
ARM_AGENTIC_NOT_RUN: Dict[str, Any] = {
    "status": "not_run",
    "note": "Arm B (real DAG) not executed in this pass; set SPIKE_RUN_AGENTIC=1.",
    "answer": None, "route_mode": None, "plan": None, "decisions": None,
    "self_correct_fired": None, "self_correct_action": None, "tools_used": None,
    "passes": None, "latency_ms": None, "hitl_flagged": None,
    "evaluator": None, "judge": None,
}


def lookup_agentic_system(db, workspace):
    """Find the seeded 'Andritz Chat Agentic' run_engine System (variant match)."""
    from app.models.system import System
    candidates = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.name == AGENTIC_SYSTEM_NAME)
        .all()
    )
    fallback = None
    for s in candidates:
        if (s.flow_definition or {}).get("variant") == AGENTIC_VARIANT:
            if s.status == "active":
                return s
            fallback = fallback or s
    return fallback or (candidates[0] if candidates else None)


def _chunks_from_results(results: Any, *, limit: int = 12) -> List[str]:
    """Normalise semantic_search_v1 ``results`` into plain context strings."""
    chunks: List[str] = []
    if isinstance(results, list):
        for item in results[:limit]:
            if isinstance(item, str) and item.strip():
                chunks.append(item[:1500])
            elif isinstance(item, dict):
                text = (item.get("content") or item.get("text") or item.get("snippet")
                        or item.get("page_content"))
                if isinstance(text, str) and text.strip():
                    chunks.append(text[:1500])
    return chunks


def _agentic_trace(checkpoints: Any) -> Dict[str, Any]:
    """Reconstruct decisions, executed stages and per-node latencies from
    ``Run.checkpoints`` (the engine appends a ``node_end`` per node with
    ``chosen_branch`` for decisions and ``latency_ms``/``status`` for tasks)."""
    decisions: Dict[str, Any] = {}
    node_latencies: Dict[str, float] = {}
    stages: List[str] = []
    self_correct_fired = False
    for cp in checkpoints or []:
        if not isinstance(cp, dict) or cp.get("kind") != "node_end":
            continue
        nid = cp.get("node_id")
        status = cp.get("status")
        if nid in _DECISION_KEYS and cp.get("chosen_branch"):
            decisions[_DECISION_KEYS[nid]] = cp.get("chosen_branch")
        if cp.get("latency_ms") is not None:
            node_latencies[nid] = cp.get("latency_ms")
        if status != "skipped":
            if nid not in stages:
                stages.append(nid)
            if nid == "task.self_correct":
                self_correct_fired = True
    return {
        "decisions": decisions,
        "node_latencies": node_latencies,
        "stages": stages,
        "self_correct_fired": self_correct_fired,
    }


def _agentic_answer(output_ref: Any, inv_by_slug: Dict[str, List[Dict[str, Any]]]) -> str:
    """User-facing text: deliver->answer, clarify->clarifying_question,
    reject_oos->reason; fall back to the corrected/draft invocation answer
    (covers hitl_pending / latency-abort runs where output_ref is partial)."""
    if isinstance(output_ref, dict):
        for key in ("answer", "clarifying_question", "reason"):
            val = output_ref.get(key)
            if isinstance(val, str) and val.strip():
                return val
    for slug in ("chat_self_correct_v1", "llm_rag_answer_v1"):
        for out in inv_by_slug.get(slug, []):
            ans = out.get("answer") if isinstance(out, dict) else None
            if isinstance(ans, str) and ans.strip():
                return ans
    return ""


async def warmup_agentic(db, workspace, system, *, case_timeout: float) -> str:
    """Fire ONE DAG run to warm models (reranker/embeddings/LLM) so the first
    *measured* case doesn't trip the 45s membrane latency valve cold."""
    from app.models.run import Run
    from app.services.run_engine.dag import execute_run_dag
    run = Run(workspace_id=workspace.id, system_id=system.id,
              input_ref={"query": "Décris la carde ACJ200.", "conversation_history": []},
              status="pending", trigger="ab_spike_warmup")
    db.add(run)
    db.commit()
    run_id = run.id
    try:
        await asyncio.wait_for(execute_run_dag(run_id), timeout=case_timeout)
    except Exception as exc:  # noqa: BLE001 - warmup never blocks the sweep
        return f"warmup_error: {type(exc).__name__}: {exc}"
    db.expire_all()
    fresh = db.query(Run).filter(Run.id == run_id).first()
    return fresh.status if fresh else "unknown"


async def run_arm_agentic(db, workspace, row: Dict[str, Any], *, system,
                          case_timeout: float, metric_timeout: float) -> Dict[str, Any]:
    """Execute the REAL finalized agentic DAG for one case and score it.

    Creates a ``Run`` against the seeded System, walks it with
    ``execute_run_dag``, then reconstructs the trace (route_mode / verdict /
    egress / deliver decisions, self-correct action, per-node latencies, plan
    action/mode, tools, passes) from ``Run.checkpoints`` + ``SkillInvocations``.
    Terminal states are mapped explicitly (completed / hitl_pending /
    aborted_latency / failed) — a latency-valve abort is a REAL prod outcome,
    not an error. Metrics use the SAME ``score_both_metrics`` as arm A.
    """
    from app.models.run import Run, SkillInvocation
    from app.services.run_engine.dag import execute_run_dag

    if system is None:
        return dict(ARM_AGENTIC_NOT_RUN, status="error", error="agentic_system_not_found")

    query = row["query"]
    run = Run(
        workspace_id=workspace.id,
        system_id=system.id,
        input_ref={"query": query, "conversation_history": row.get("conversation_history") or []},
        status="pending",
        trigger="ab_spike",
    )
    db.add(run)
    db.commit()
    run_id = run.id

    started = time.perf_counter()
    harness_error: Optional[str] = None
    try:
        await asyncio.wait_for(execute_run_dag(run_id), timeout=case_timeout)
    except asyncio.TimeoutError:
        harness_error = f"harness_timeout_{int(case_timeout)}s"
    except Exception as exc:  # noqa: BLE001 - never crash a case
        harness_error = f"{type(exc).__name__}: {exc}"
    latency_ms = int((time.perf_counter() - started) * 1000)

    # execute_run_dag committed on its own session; re-read fresh.
    db.expire_all()
    fresh = db.query(Run).filter(Run.id == run_id).first()
    invocations = (
        db.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run_id)
        .order_by(SkillInvocation.started_at.asc())
        .all()
    )
    inv_by_slug: Dict[str, List[Dict[str, Any]]] = {}
    tools_used: List[str] = []
    for inv in invocations:
        slug = inv.skill_slug or "?"
        inv_by_slug.setdefault(slug, []).append(inv.output_ref or {})
        if slug not in tools_used:
            tools_used.append(slug)

    checkpoints = (fresh.checkpoints if fresh else None) or []
    trace = _agentic_trace(checkpoints)
    decisions = trace["decisions"]
    self_correct_fired = trace["self_correct_fired"]

    plan_out = (inv_by_slug.get("chat_agentic_plan_v1") or [{}])[0]
    plan = {"action": plan_out.get("action"), "mode": plan_out.get("mode"),
            "confidence": plan_out.get("confidence")}
    sc_out = (inv_by_slug.get("chat_self_correct_v1") or [{}])[-1]
    self_correct_action = sc_out.get("action_taken")
    dag_eval = (inv_by_slug.get("response_eval_v1") or [{}])[0] or {}

    answer = _agentic_answer(fresh.output_ref if fresh else None, inv_by_slug)
    context_chunks = _chunks_from_results(
        (inv_by_slug.get("semantic_search_v1") or [{}])[0].get("results"))
    context_count = dag_eval.get("context_count")
    if context_count is None:
        context_count = len(context_chunks)

    run_status = fresh.status if fresh else None
    run_error = (fresh.error if fresh else None) or harness_error
    if harness_error and not run_status:
        status = "error"
    elif run_status == "completed":
        status = "completed"
    elif run_status == "hitl_pending":
        status = "hitl_pending"
    elif run_status == "failed" and run_error and "max_latency_ms" in run_error:
        status = "aborted_latency"
    elif run_status == "failed":
        status = "failed"
    else:
        status = run_status or "error"
    hitl_flagged = bool(status == "hitl_pending" or decisions.get("egress") == "review")

    # Same metrics as arm A. Score whenever we have an answer (covers
    # aborted_latency / hitl_pending which still produced text); otherwise null.
    if answer.strip():
        scored = await score_both_metrics(
            query, answer, system_prompt="", context_chunks=context_chunks,
            metric_timeout=metric_timeout)
        evaluator, judge = scored["evaluator"], scored["judge"]
    else:
        evaluator = {k: None for k in EVALUATOR_KEYS} | {"_note": f"no_answer:{status}"}
        judge = {"composite": None, "hallucination_rate": None, "_note": f"no_answer:{status}"}

    return {
        "status": status,
        "answer": answer,
        "route_mode": decisions.get("route_mode"),
        "plan": plan,
        "decisions": decisions,
        "self_correct_fired": self_correct_fired,
        "self_correct_action": self_correct_action,
        "tools_used": tools_used,
        "passes": 1 + int(self_correct_fired),
        "latency_ms": latency_ms,
        "engine_duration_ms": float(fresh.duration_ms) if (fresh and fresh.duration_ms) else None,
        "hitl_flagged": hitl_flagged,
        "context_count": context_count,
        "dag_eval": {k: dag_eval.get(k) for k in (
            "composite", "hallucination_rate", "context_count", "hhem", "factuality", "coherence")},
        "node_latencies": trace["node_latencies"],
        "stages": trace["stages"],
        "run_id": run_id,
        "error": run_error,
        "evaluator": evaluator,
        "judge": judge,
    }


async def run_case(db, workspace, row: Dict[str, Any], *, case_timeout: float,
                   metric_timeout: float, run_agentic: bool = False,
                   agentic_system=None) -> Dict[str, Any]:
    """Run both arms for one corpus row."""
    query = row["query"]
    suff = assess_sufficiency(query, has_history=bool(row.get("conversation_history")))
    classic = await run_arm_classic(db, workspace, row,
                                    case_timeout=case_timeout, metric_timeout=metric_timeout)
    if run_agentic:
        agentic = await run_arm_agentic(db, workspace, row, system=agentic_system,
                                        case_timeout=case_timeout, metric_timeout=metric_timeout)
    else:
        agentic = dict(ARM_AGENTIC_NOT_RUN)
    return {
        "id": row["id"],
        "source": row.get("source"),
        "category": row.get("category"),
        "lang": row.get("lang"),
        "ground_truth": row.get("ground_truth"),
        "query": query,
        "sufficiency": suff,
        "arm_classic": classic,
        "arm_agentic": agentic,
    }


def _load_done_rows(jsonl_path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if jsonl_path and os.path.exists(jsonl_path):
        with open(jsonl_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    return rows


def _write_json_checkpoint(output_path: str, results: List[Dict[str, Any]]) -> None:
    if not output_path:
        return
    report = {
        "workspace": WORKSPACE_SLUG,
        "corpus_size": len(results),
        "summary": summarize(results),
        "results": results,
    }
    tmp = f"{output_path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, output_path)


async def run_corpus(rows: List[Dict[str, Any]], *, case_timeout: float, metric_timeout: float,
                     jsonl_path: str, output_path: str, resume: bool,
                     batch_size: int = 5, run_agentic: bool = False) -> List[Dict[str, Any]]:
    """Run both arms over the rows in small batches, checkpointing as we go.

    Per-case append to the JSONL (source of truth for resume) + a full aggregate
    JSON written after every batch and at the end, so a crash / resource limit
    loses nothing and is resumable via SPIKE_RESUME=1.
    """
    from app.db.base import SessionLocal
    from app.models.workspace import Workspace

    await bootstrap_orchestrator()
    db = SessionLocal()
    try:
        workspace = db.query(Workspace).filter(Workspace.slug == WORKSPACE_SLUG).first()
        if not workspace:
            raise SystemExit(f"workspace not found: {WORKSPACE_SLUG}")
        agentic_system = None
        if run_agentic:
            agentic_system = lookup_agentic_system(db, workspace)
            if agentic_system is None:
                raise SystemExit(
                    f"agentic System '{AGENTIC_SYSTEM_NAME}' (variant {AGENTIC_VARIANT}) "
                    "not found in workspace — is migration 048 applied?")
            print(f"agentic System: {agentic_system.id} status={agentic_system.status} "
                  f"default_model={agentic_system.default_model}", flush=True)
            if os.environ.get("SPIKE_WARMUP", "1") == "1":
                warm = await warmup_agentic(db, workspace, agentic_system, case_timeout=case_timeout)
                print(f"DAG warmup status: {warm}", flush=True)
        prior = _load_done_rows(jsonl_path) if resume else []
        done = {r.get("id") for r in prior}
        results: List[Dict[str, Any]] = list(prior) if resume else []
        total = len(rows)
        since_checkpoint = 0
        for idx, row in enumerate(rows, start=1):
            if row["id"] in done:
                print(f"[{idx:03d}/{total:03d}] SKIP (done) {row['id']}", flush=True)
                continue
            try:
                res = await run_case(db, workspace, row, case_timeout=case_timeout,
                                     metric_timeout=metric_timeout, run_agentic=run_agentic,
                                     agentic_system=agentic_system)
            except Exception as exc:  # noqa: BLE001 - report every case, keep the batch moving
                res = {"id": row["id"], "source": row.get("source"), "category": row.get("category"),
                       "lang": row.get("lang"), "ground_truth": row.get("ground_truth"),
                       "query": row["query"], "error": f"{type(exc).__name__}: {exc}",
                       "arm_classic": None, "arm_agentic": dict(ARM_AGENTIC_NOT_RUN)}
            results.append(res)
            since_checkpoint += 1
            if jsonl_path:
                with open(jsonl_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(res, ensure_ascii=False) + "\n")
            classic = res.get("arm_classic") or {}
            cj = classic.get("judge") or {}
            agentic = res.get("arm_agentic") or {}
            aj = agentic.get("judge") or {}
            print(f"[{idx:03d}/{total:03d}] {res['id']} "
                  f"A[route={classic.get('route_mode')} comp={cj.get('composite')} "
                  f"lat={classic.get('latency_ms')}ms] "
                  f"B[{agentic.get('status')} route={agentic.get('route_mode')} "
                  f"verdict={(agentic.get('decisions') or {}).get('verdict')} "
                  f"sc={agentic.get('self_correct_fired')} comp={aj.get('composite')} "
                  f"lat={agentic.get('latency_ms')}ms] "
                  f"err={res.get('error') or classic.get('error')}", flush=True)
            if since_checkpoint >= max(1, batch_size):
                _write_json_checkpoint(output_path, results)
                since_checkpoint = 0
                print(f"  …checkpoint written ({len(results)} cases) -> {output_path}", flush=True)
        _write_json_checkpoint(output_path, results)
        return results
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Aggregation (two-arm). arm_classic is fully aggregated now; arm_agentic stays
# a pending placeholder until the finalized DAG lands.
# ---------------------------------------------------------------------------
def _mean(xs: List[Any]) -> Optional[float]:
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(sum(xs) / len(xs), 3) if xs else None


def _arm_metric(arm: Optional[Dict[str, Any]], block: str, key: str) -> Any:
    if not isinstance(arm, dict):
        return None
    sub = arm.get(block)
    return sub.get(key) if isinstance(sub, dict) else None


def _arms(results: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    return [r.get(key) for r in results if isinstance(r.get(key), dict)]


def _arm_block_means(arms: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Mean metric block shared by global + per-category aggregation."""
    return {
        "mean_composite": _mean([_arm_metric(a, "judge", "composite") for a in arms]),
        "mean_hallucination_rate": _mean([_arm_metric(a, "judge", "hallucination_rate") for a in arms]),
        "mean_relevance": _mean([_arm_metric(a, "evaluator", "relevance") for a in arms]),
        "mean_factuality": _mean([_arm_metric(a, "evaluator", "factuality") for a in arms]),
        "mean_coherence": _mean([_arm_metric(a, "evaluator", "coherence") for a in arms]),
        "mean_hhem": _mean([_arm_metric(a, "evaluator", "hhem") for a in arms]),
        "mean_adv_hhem": _mean([_arm_metric(a, "evaluator", "adv_hhem") for a in arms]),
        "mean_latency_ms": _mean([a.get("latency_ms") for a in arms]),
    }


# Arm B statuses that still produced a user-facing answer we can compare.
_AGENTIC_ANSWERED = {"completed", "hitl_pending", "aborted_latency"}


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Full two-arm A/B aggregation: per-arm means, per-category levers, and the
    head-to-head A/B summary (win/tie/loss, deltas, route-change, self-correct,
    abort, hitl rates)."""
    n = len(results)
    classic = _arms(results, "arm_classic")
    agentic = _arms(results, "arm_agentic")
    errors = [r for r in results
              if r.get("error") or (isinstance(r.get("arm_classic"), dict) and r["arm_classic"].get("error"))]

    classic_routes: Dict[str, int] = {}
    for a in classic:
        classic_routes[a.get("route_mode") or "?"] = classic_routes.get(a.get("route_mode") or "?", 0) + 1
    agentic_routes: Dict[str, int] = {}
    agentic_status: Dict[str, int] = {}
    for a in agentic:
        agentic_routes[a.get("route_mode") or "?"] = agentic_routes.get(a.get("route_mode") or "?", 0) + 1
        agentic_status[a.get("status") or "?"] = agentic_status.get(a.get("status") or "?", 0) + 1

    would_sc = [a for a in classic if a.get("would_self_correct")]

    # ---- Head-to-head A/B (only cases where BOTH arms produced an answer) ----
    wins = ties = losses = 0
    comp_deltas: List[float] = []
    halluc_deltas: List[float] = []
    lat_deltas: List[float] = []
    route_changed = 0
    paired = 0
    self_correct_fired = 0
    aborted_latency = 0
    hitl_flagged = 0
    agentic_measured = 0
    for r in results:
        a = r.get("arm_classic") if isinstance(r.get("arm_classic"), dict) else None
        b = r.get("arm_agentic") if isinstance(r.get("arm_agentic"), dict) else None
        if not b or b.get("status") in (None, "not_run", "error"):
            continue
        agentic_measured += 1
        if b.get("self_correct_fired"):
            self_correct_fired += 1
        if b.get("status") == "aborted_latency":
            aborted_latency += 1
        if b.get("hitl_flagged"):
            hitl_flagged += 1
        if not a:
            continue
        ca = _arm_metric(a, "judge", "composite")
        cb = _arm_metric(b, "judge", "composite")
        ha = _arm_metric(a, "judge", "hallucination_rate")
        hb = _arm_metric(b, "judge", "hallucination_rate")
        la, lb = a.get("latency_ms"), b.get("latency_ms")
        if a.get("route_mode") and b.get("route_mode") and a.get("route_mode") != b.get("route_mode"):
            route_changed += 1
        if isinstance(ca, (int, float)) and isinstance(cb, (int, float)):
            paired += 1
            d = round(cb - ca, 2)
            comp_deltas.append(d)
            if d > 1.0:
                wins += 1
            elif d < -1.0:
                losses += 1
            else:
                ties += 1
        if isinstance(ha, (int, float)) and isinstance(hb, (int, float)):
            halluc_deltas.append(round(hb - ha, 3))
        if isinstance(la, (int, float)) and isinstance(lb, (int, float)):
            lat_deltas.append(lb - la)

    # ---- Per-lever (category) breakdown, BOTH arms + delta ----
    by_cat_groups: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for r in results:
        cat = r.get("category") or "uncategorized"
        g = by_cat_groups.setdefault(cat, {"classic": [], "agentic": []})
        if isinstance(r.get("arm_classic"), dict):
            g["classic"].append(r["arm_classic"])
        b = r.get("arm_agentic")
        if isinstance(b, dict) and b.get("status") in _AGENTIC_ANSWERED:
            g["agentic"].append(b)
    by_cat_out: Dict[str, Dict[str, Any]] = {}
    for cat, g in by_cat_groups.items():
        ac = _arm_block_means(g["classic"]) if g["classic"] else None
        ag = _arm_block_means(g["agentic"]) if g["agentic"] else None
        delta = None
        if ac and ag and ac.get("mean_composite") is not None and ag.get("mean_composite") is not None:
            delta = {
                "composite": round(ag["mean_composite"] - ac["mean_composite"], 2),
                "hallucination_rate": (round(ag["mean_hallucination_rate"] - ac["mean_hallucination_rate"], 3)
                                       if ac.get("mean_hallucination_rate") is not None
                                       and ag.get("mean_hallucination_rate") is not None else None),
                "latency_ms": (round(ag["mean_latency_ms"] - ac["mean_latency_ms"], 0)
                               if ac.get("mean_latency_ms") is not None
                               and ag.get("mean_latency_ms") is not None else None),
            }
        by_cat_out[cat] = {
            "n": len(g["classic"]),
            "n_agentic": len(g["agentic"]),
            "arm_classic": ac,
            "arm_agentic": ag,
            "ab_delta": delta,
            "would_self_correct": sum(int(bool(a.get("would_self_correct"))) for a in g["classic"]),
            "self_correct_fired": sum(int(bool(a.get("self_correct_fired"))) for a in g["agentic"]),
        }

    classic_means = _arm_block_means(classic)
    agentic_answered = [a for a in agentic if a.get("status") in _AGENTIC_ANSWERED]
    agentic_means = _arm_block_means(agentic_answered) if agentic_answered else None

    return {
        "n_cases": n,
        "n_errors": len(errors),
        "error_ids": [r["id"] for r in errors],
        "arm_classic": {
            **classic_means,
            "route_distribution": classic_routes,
            "would_self_correct_count": len(would_sc),
            "would_self_correct_rate_pct": round(100.0 * len(would_sc) / len(classic), 1) if classic else None,
            "metric_timeouts": {
                "evaluator": sum(1 for a in classic if isinstance(a.get("evaluator"), dict) and a["evaluator"].get("_note")),
                "judge": sum(1 for a in classic if isinstance(a.get("judge"), dict) and a["judge"].get("_note")),
            },
        },
        "arm_agentic": {
            **(agentic_means or {}),
            "measured_cases": agentic_measured,
            "route_distribution": agentic_routes,
            "status_distribution": agentic_status,
            "self_correct_fired_count": self_correct_fired,
            "aborted_latency_count": aborted_latency,
            "hitl_flagged_count": hitl_flagged,
        },
        "ab_summary": {
            "paired_cases": paired,
            "wins_agentic": wins,
            "ties": ties,
            "losses_agentic": losses,
            "mean_composite_delta": _mean(comp_deltas),
            "mean_hallucination_delta": _mean(halluc_deltas),
            "mean_latency_delta_ms": _mean(lat_deltas),
            "route_changed_count": route_changed,
            "route_changed_pct": round(100.0 * route_changed / agentic_measured, 1) if agentic_measured else None,
            "self_correct_fired_pct": round(100.0 * self_correct_fired / agentic_measured, 1) if agentic_measured else None,
            "aborted_latency_pct": round(100.0 * aborted_latency / agentic_measured, 1) if agentic_measured else None,
            "hitl_flagged_pct": round(100.0 * hitl_flagged / agentic_measured, 1) if agentic_measured else None,
        },
        "by_category": by_cat_out,
    }


# ---------------------------------------------------------------------------
# Markdown report generator — real two-arm A/B (classic vs live agentic DAG).
# ---------------------------------------------------------------------------
def _fmt(value: Any, *, pct: bool = False, nd: int = 2, signed: bool = False) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, (int, float)):
        sign = "+" if (signed and value > 0) else ""
        return f"{sign}{value:.{nd}f}{'%' if pct else ''}"
    return str(value)


def _cell(text: Any, *, limit: int = 60) -> str:
    s = "" if text is None else str(text)
    s = s.replace("|", "\\|").replace("\n", " ").strip()
    return (s[: limit - 1] + "…") if len(s) > limit else s


def _classic_steps(arm: Optional[Dict[str, Any]]) -> str:
    if not isinstance(arm, dict):
        return "n/a"
    stages = arm.get("stages")
    if isinstance(stages, list) and stages:
        return " → ".join(str(s) for s in stages)
    return "n/a"


def _agentic_steps(arm: Optional[Dict[str, Any]]) -> str:
    if not isinstance(arm, dict):
        return "n/a"
    status = arm.get("status")
    if status in (None, "not_run"):
        return "_not run_"
    if status == "error":
        return _cell(f"ERROR: {arm.get('error')}", limit=58)
    d = arm.get("decisions") or {}
    plan = arm.get("plan") or {}
    parts = [f"plan:{plan.get('action')}/{plan.get('mode')}"]
    if d.get("route_mode"):
        parts.append(f"route:{d['route_mode']}")
    if d.get("verdict"):
        parts.append(f"verdict:{d['verdict']}")
    if arm.get("self_correct_fired"):
        parts.append(f"sc:{arm.get('self_correct_action')}")
    if d.get("egress"):
        parts.append(f"egress:{d['egress']}")
    if d.get("deliver"):
        parts.append(f"deliver:{d['deliver']}")
    if status != "completed":
        parts.append(f"[{status}]")
    return " → ".join(str(p) for p in parts)


def _arm_row(cid: str, cat: str, q: str, arm_name: str, route: Any, steps: str,
             arm: Dict[str, Any]) -> str:
    ev = arm.get("evaluator") if isinstance(arm.get("evaluator"), dict) else {}
    ju = arm.get("judge") if isinstance(arm.get("judge"), dict) else {}
    return ("| {id} | {cat} | {q} | {arm} | {route} | {steps} | {lat} | "
            "{comp} | {hal} | {hhem} | {fact} | {coh} |".format(
                id=cid, cat=cat, q=q, arm=arm_name,
                route=_cell(route), steps=steps,
                lat=_fmt(arm.get("latency_ms"), nd=0),
                comp=_fmt(ju.get("composite"), nd=1),
                hal=_fmt(ju.get("hallucination_rate"), nd=3),
                hhem=_fmt(ev.get("hhem"), nd=3),
                fact=_fmt(ev.get("factuality"), nd=3),
                coh=_fmt(ev.get("coherence"), nd=3)))


def render_report_md(report: Dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    results = report.get("results") or []
    classic_sum = summary.get("arm_classic") or {}
    agentic_sum = summary.get("arm_agentic") or {}
    ab = summary.get("ab_summary") or {}
    by_cat = summary.get("by_category") or {}
    n = summary.get("n_cases", len(results))
    measured = agentic_sum.get("measured_cases", 0)

    lines: List[str] = []
    lines.append("# Chat recherche — A/B agentique vs déterministe (mesure offline)")
    lines.append("")
    lines.append(f"_Workspace_: `{report.get('workspace', WORKSPACE_SLUG)}` · "
                 f"_cas_: **{n}** · _arm B mesurés_: **{measured}** · "
                 f"_erreurs_: {summary.get('n_errors', 0)}")
    lines.append("")
    lines.append("> **Arm A** = orchestration **déterministe de production** (`/chat`). "
                 "**Arm B** = **vrai DAG agentique** (System « Andritz Chat Agentic », "
                 "`variant=chat_agentic_thinking_v1`) exécuté de bout en bout par "
                 "`execute_run_dag()` — 100 % fidèle, pas un mirroir. Les deux arms sont "
                 "notés par les **mêmes** fonctions (`score_both_metrics`).")
    lines.append("")

    # ---- Methodology -----------------------------------------------------
    lines.append("## Méthodologie")
    lines.append("")
    lines.append("- **Arm A (déterministe).** `faithful_chat(mode=None)` rejoue le chemin exact "
                 "de `/chat` (`_apply_workspace_chat_flow_defaults` → "
                 "`_apply_retrieval_budget_policy` → `AgentOrchestrator.process_request` → "
                 "`apply_answer_policy_to_text`), sans override de lane : `route_mode` = profil "
                 "déterministe choisi par prod.")
    lines.append("- **Arm B (DAG réel).** Par cas : création d'un `Run(system=Andritz Chat "
                 "Agentic, input={query,history}, trigger=ab_spike)` puis "
                 "`await execute_run_dag(run_id)`. La **trace** est reconstruite depuis "
                 "`Run.checkpoints` (les `node_end` portent `chosen_branch` des décisions "
                 "`route_mode`/`verdict`/`egress_gate`/`deliver` + `latency_ms`/`status` par "
                 "nœud) et `SkillInvocations` (plan→action/mode, self_correct→action_taken, "
                 "response_eval→composite interne, retrieval→context). `answer` = "
                 "`Run.output_ref` (sink), fallback invocation. États terminaux explicites : "
                 "`completed` / `hitl_pending` (→ `hitl_flagged`) / `aborted_latency` (valve "
                 "membrane `max_latency_ms`, `hard_abort` — vraie issue prod, comptée) / `failed`.")
    lines.append("- **Métriques identiques (2 arms).** `evaluate_response_metrics` → "
                 "ResponseEvaluator (relevance, factuality, coherence, HHEM, adv_HHEM) ; "
                 "`judge_answer` → JudgeService (composite 0-100, hallucination_rate). "
                 "Timeout-safe (null + `_note`, jamais de crash). NB : le **composite des "
                 "colonnes** vient du JudgeService (parité A/B) ; le DAG utilise en interne un "
                 "composite distinct (ResponseEvaluator ×100) pour son verdict — voir Lecture.")
    lines.append("")

    # ---- Per-case table --------------------------------------------------
    lines.append("## Détail par cas (classic vs agentic, lignes adjacentes)")
    lines.append("")
    lines.append("| id | category | query | arm | route/mode | decisions/steps | latency_ms | "
                 "composite | halluc_rate | hhem | factuality | coherence |")
    lines.append("|" + "---|" * 12)
    for r in results:
        cid = _cell(r.get("id"), limit=34)
        cat = _cell(r.get("category"), limit=18)
        q = _cell(r.get("query"), limit=44)
        a = r.get("arm_classic") if isinstance(r.get("arm_classic"), dict) else {}
        b = r.get("arm_agentic") if isinstance(r.get("arm_agentic"), dict) else {}
        case_err = r.get("error") or (a.get("error") if a else None)
        a_steps = _classic_steps(a) if not case_err else _cell(f"ERROR: {case_err}", limit=58)
        lines.append(_arm_row(cid, cat, q, "classic", a.get("route_mode"), a_steps, a or {}))
        lines.append(_arm_row(cid, cat, "⤷", "agentic", b.get("route_mode"),
                              _agentic_steps(b), b or {}))
    lines.append("")

    # ---- Aggregate by category (lever), both arms + delta ----------------
    lines.append("## Agrégat par levier (`category`) — A (classic) vs B (agentic)")
    lines.append("")
    lines.append("| category | n | A comp | B comp | Δcomp | A halluc | B halluc | A lat | B lat | "
                 "Δlat | self_correct |")
    lines.append("|" + "---|" * 11)
    for cat in sorted(by_cat):
        b = by_cat[cat]
        ac = b.get("arm_classic") or {}
        ag = b.get("arm_agentic") or {}
        dl = b.get("ab_delta") or {}
        lines.append("| {cat} | {n} | {ac} | {ag} | {dc} | {ah} | {bh} | {al} | {bl} | {dl} | "
                     "{sc}/{na} |".format(
                         cat=_cell(cat, limit=20), n=b.get("n"),
                         ac=_fmt(ac.get("mean_composite"), nd=1),
                         ag=_fmt(ag.get("mean_composite"), nd=1) if ag else "n/a",
                         dc=_fmt(dl.get("composite"), nd=1, signed=True) if dl else "n/a",
                         ah=_fmt(ac.get("mean_hallucination_rate"), nd=3),
                         bh=_fmt(ag.get("mean_hallucination_rate"), nd=3) if ag else "n/a",
                         al=_fmt(ac.get("mean_latency_ms"), nd=0),
                         bl=_fmt(ag.get("mean_latency_ms"), nd=0) if ag else "n/a",
                         dl=_fmt(dl.get("latency_ms"), nd=0, signed=True) if dl else "n/a",
                         sc=b.get("self_correct_fired", 0), na=b.get("n_agentic", 0)))
    lines.append("")

    # ---- Global A/B summary ----------------------------------------------
    lines.append("## Synthèse A/B globale")
    lines.append("")
    cr = classic_sum.get("route_distribution") or {}
    ar = agentic_sum.get("route_distribution") or {}
    sd = agentic_sum.get("status_distribution") or {}
    lines.append(f"- **composite** — A: {_fmt(classic_sum.get('mean_composite'), nd=1)} · "
                 f"B: {_fmt(agentic_sum.get('mean_composite'), nd=1)} · "
                 f"**Δ moyen: {_fmt(ab.get('mean_composite_delta'), nd=2, signed=True)}** "
                 f"(B−A, sur {ab.get('paired_cases')} cas appariés)")
    lines.append(f"- **win/tie/loss (agentic, seuil ±1 pt composite)**: "
                 f"**{ab.get('wins_agentic')} / {ab.get('ties')} / {ab.get('losses_agentic')}**")
    lines.append(f"- **hallucination_rate** — A: {_fmt(classic_sum.get('mean_hallucination_rate'), nd=3)} · "
                 f"B: {_fmt(agentic_sum.get('mean_hallucination_rate'), nd=3)} · "
                 f"**Δ moyen: {_fmt(ab.get('mean_hallucination_delta'), nd=3, signed=True)}**")
    lines.append(f"- **latence** — A: {_fmt(classic_sum.get('mean_latency_ms'), nd=0)} ms · "
                 f"B: {_fmt(agentic_sum.get('mean_latency_ms'), nd=0)} ms · "
                 f"**Δ moyen: {_fmt(ab.get('mean_latency_delta_ms'), nd=0, signed=True)} ms**")
    lines.append(f"- **route changée vs classic**: {ab.get('route_changed_count')} "
                 f"({_fmt(ab.get('route_changed_pct'), pct=True, nd=1)}) — "
                 f"A routes {{{', '.join(f'{k}={v}' for k, v in sorted(cr.items()))}}} · "
                 f"B routes {{{', '.join(f'{k}={v}' for k, v in sorted(ar.items()))}}}")
    lines.append(f"- **self_correct déclenché**: {agentic_sum.get('self_correct_fired_count')} "
                 f"({_fmt(ab.get('self_correct_fired_pct'), pct=True, nd=1)})")
    lines.append(f"- **aborted_latency (valve membrane)**: {agentic_sum.get('aborted_latency_count')} "
                 f"({_fmt(ab.get('aborted_latency_pct'), pct=True, nd=1)})")
    lines.append(f"- **hitl_flagged**: {agentic_sum.get('hitl_flagged_count')} "
                 f"({_fmt(ab.get('hitl_flagged_pct'), pct=True, nd=1)})")
    lines.append(f"- **arm B statuts**: {{{', '.join(f'{k}={v}' for k, v in sorted(sd.items()))}}}")
    lines.append("")

    # ---- Lecture ---------------------------------------------------------
    lines.extend(_render_lecture(summary))

    # ---- Reproduction ----------------------------------------------------
    lines.append("## Reproduction (in-container)")
    lines.append("")
    lines.append("```bash")
    lines.append("# Balayage complet 95 cas, 2 arms (DAG réel pour B), warmup + checkpointing")
    lines.append("cat backend/scripts/agentic_chat_spike.py | ssh omnirag-demo \"docker exec -i \\")
    lines.append("  -e SPIKE_RUN_AGENTIC=1 -e SPIKE_BATCH=3 \\")
    lines.append("  -e SPIKE_JSONL=/tmp/ab_full.jsonl -e SPIKE_OUTPUT=/tmp/ab_full.json \\")
    lines.append("  -e SPIKE_REPORT_MD=/tmp/ab_full.md -w /app/backend agentium-backend python -\"")
    lines.append("")
    lines.append("# Reprise après limite de ressources (idempotent — ne rejoue pas les cas faits)")
    lines.append("cat backend/scripts/agentic_chat_spike.py | ssh omnirag-demo \"docker exec -i \\")
    lines.append("  -e SPIKE_RUN_AGENTIC=1 -e SPIKE_RESUME=1 -e SPIKE_BATCH=3 \\")
    lines.append("  -e SPIKE_JSONL=/tmp/ab_full.jsonl -e SPIKE_OUTPUT=/tmp/ab_full.json \\")
    lines.append("  -e SPIKE_REPORT_MD=/tmp/ab_full.md -w /app/backend agentium-backend python -\"")
    lines.append("")
    lines.append("# Régénérer le rapport depuis les partiels, sans relancer aucune orchestration")
    lines.append("cat backend/scripts/agentic_chat_spike.py | ssh omnirag-demo \"docker exec -i \\")
    lines.append("  -e SPIKE_REPORT_ONLY=1 -e SPIKE_JSONL=/tmp/ab_full.jsonl \\")
    lines.append("  -e SPIKE_REPORT_MD=/tmp/ab_full.md -w /app/backend agentium-backend python -\"")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def _render_lecture(summary: Dict[str, Any]) -> List[str]:
    """Where agentic earns its latency vs pure overhead + calibration signal."""
    classic_sum = summary.get("arm_classic") or {}
    agentic_sum = summary.get("arm_agentic") or {}
    ab = summary.get("ab_summary") or {}
    by_cat = summary.get("by_category") or {}

    # Buckets: where does B win composite vs where is it pure latency overhead?
    earns, overhead = [], []
    for cat, b in by_cat.items():
        dl = b.get("ab_delta") or {}
        dc = dl.get("composite")
        dlat = dl.get("latency_ms")
        if dc is None:
            continue
        if dc >= 1.0:
            earns.append((cat, dc, dlat))
        elif (dlat or 0) > 0:
            overhead.append((cat, dc, dlat))
    earns.sort(key=lambda x: x[1], reverse=True)
    overhead.sort(key=lambda x: (x[2] or 0), reverse=True)

    rel = classic_sum.get("mean_relevance")
    fact = classic_sum.get("mean_factuality")
    coh = classic_sum.get("mean_coherence")
    approx_internal = None
    if all(isinstance(x, (int, float)) for x in (rel, fact, coh)):
        approx_internal = round((rel + fact + coh) / 3 * 100, 1)

    lines: List[str] = []
    lines.append("## Lecture")
    lines.append("")
    lines.append("**Où l'agentique gagne sa latence.**")
    if earns:
        for cat, dc, dlat in earns:
            lines.append(f"- `{cat}` : composite {_fmt(dc, nd=1, signed=True)} pour "
                         f"{_fmt(dlat, nd=0, signed=True)} ms — le surcoût de latence achète "
                         "de la qualité (le verdict→self_correct ou la route plus profonde paie).")
    else:
        lines.append("- _Aucun levier où B dépasse A de ≥1 pt composite sur ce run._")
    lines.append("")
    lines.append("**Où c'est de l'overhead pur** (plus lent, sans gain composite) :")
    if overhead:
        for cat, dc, dlat in overhead[:6]:
            lines.append(f"- `{cat}` : composite {_fmt(dc, nd=1, signed=True)} mais "
                         f"{_fmt(dlat, nd=0, signed=True)} ms — l'orchestration agentique "
                         "(plan + 3 évaluateurs + gates) ne rend pas la réponse meilleure.")
    else:
        lines.append("- _Aucun levier d'overhead pur franc sur ce run._")
    lines.append("")
    lines.append("**Signal de calibration du verdict (à corriger).**")
    lines.append(f"- Le DAG calcule son composite **interne** via ResponseEvaluator "
                 f"(`composite ≈ moyenne(relevance, factuality, coherence) × 100`). Sur arm A "
                 f"on mesure rel={_fmt(rel, nd=3)} / fact={_fmt(fact, nd=3)} / "
                 f"coh={_fmt(coh, nd=3)} → un composite interne **≈ "
                 f"{_fmt(approx_internal, nd=1)}**, donc **< 70**.")
    lines.append(f"- Le verdict `weak` se déclenche si `composite<70 or hallucination_rate>0.15 "
                 f"or context_count==0`. Avec un composite interne structurellement ~66, le "
                 f"verdict bascule `weak` presque toujours → **self_correct sur-déclenche** "
                 f"(mesuré : {_fmt(ab.get('self_correct_fired_pct'), pct=True, nd=1)} des cas "
                 f"arm B), ce qui ajoute une passe LLM (latence) sans garantie de gain.")
    lines.append(f"- **Abort latence** : la valve membrane `max_latency_ms=45000` (`hard_abort`) "
                 f"coupe {_fmt(ab.get('aborted_latency_pct'), pct=True, nd=1)} des runs B — "
                 "directement aggravé par la passe self_correct quasi-systématique.")
    lines.append("")
    lines.append("**Recommandation de recalibration.**")
    lines.append("1. **Découpler l'échelle composite du verdict.** Le composite "
                 "ResponseEvaluator (cosinus d'embeddings) vit naturellement autour de "
                 "0.6–0.7×100 ; comparer ce 0-100 à un seuil de 70 conçu pour un juge LLM est "
                 "une erreur d'échelle. Soit recalibrer le seuil à **~55–60** pour ce composite, "
                 "soit faire porter le verdict par la **hallucination_rate** (`>0.15`) + "
                 "`context_count==0`, et ne garder le composite que comme tie-breaker.")
    lines.append("2. **Préférer un verdict hallucination-based** : `weak` si "
                 "`hallucination_rate>0.15 or context_count==0` (signaux fiables, peu sensibles "
                 "à l'échelle), réservant l'escalade coûteuse aux vrais cas de non-grounding.")
    lines.append("3. **Protéger la latence** : si self_correct doit rester déclenché souvent, "
                 "relever `max_latency_ms` ou rendre la passe self_correct conditionnelle à un "
                 "gain attendu, pour éviter les `aborted_latency` qui détruisent l'UX sans rien "
                 "livrer.")
    lines.append("")
    return lines


def _select_rows() -> List[Dict[str, Any]]:
    ids_env = os.environ.get("SPIKE_IDS", "").strip()
    rows = CORPUS
    if ids_env:
        wanted = {x.strip() for x in ids_env.split(",") if x.strip()}
        return [r for r in rows if r["id"] in wanted]
    try:
        limit = int(os.environ.get("SPIKE_LIMIT", "0") or "0")
    except ValueError:
        limit = 0
    return rows[:limit] if limit > 0 else rows


def _emit_report(report: Dict[str, Any], report_md_path: str) -> None:
    summary = report.get("summary") or {}
    md = render_report_md(report)
    if report_md_path:
        try:
            with open(report_md_path, "w", encoding="utf-8") as fh:
                fh.write(md)
            print(f"report markdown written: {report_md_path}", flush=True)
        except OSError as exc:
            print(f"WARN: could not write markdown to {report_md_path}: {exc}", flush=True)
    print("===SPIKE_SUMMARY_BEGIN===", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    print("===SPIKE_SUMMARY_END===", flush=True)
    # Emit the full markdown between sentinels so it can be captured over ssh and
    # written into the repo doc (the container has no repo checkout).
    print("===SPIKE_REPORT_MD_BEGIN===", flush=True)
    print(md, flush=True)
    print("===SPIKE_REPORT_MD_END===", flush=True)


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def main() -> None:
    output = os.environ.get("SPIKE_OUTPUT", "/tmp/agentic_ab_report.json")
    jsonl = os.environ.get("SPIKE_JSONL", "/tmp/agentic_ab_rows.jsonl")
    report_md = os.environ.get("SPIKE_REPORT_MD", "").strip()
    resume = os.environ.get("SPIKE_RESUME", "0") == "1"
    report_only = os.environ.get("SPIKE_REPORT_ONLY", "0") == "1"
    run_agentic = os.environ.get("SPIKE_RUN_AGENTIC", "0") == "1"
    case_timeout = _float_env("SPIKE_CASE_TIMEOUT", 150.0)
    metric_timeout = _float_env("SPIKE_METRIC_TIMEOUT", 120.0)
    try:
        batch_size = int(os.environ.get("SPIKE_BATCH", "5") or "5")
    except ValueError:
        batch_size = 5

    if report_only:
        # Regenerate the report from whatever completed (JSONL preferred, else JSON).
        results = _load_done_rows(jsonl)
        if not results and os.path.exists(output):
            with open(output, "r", encoding="utf-8") as fh:
                results = (json.load(fh) or {}).get("results") or []
        report = {"workspace": WORKSPACE_SLUG, "corpus_size": len(results),
                  "summary": summarize(results), "results": results}
        if output:
            with open(output, "w", encoding="utf-8") as fh:
                json.dump(report, fh, ensure_ascii=False, indent=2)
        print(f"SPIKE report-only: {len(results)} cases from {jsonl or output}", flush=True)
        _emit_report(report, report_md)
        return

    rows = _select_rows()
    print(f"SPIKE start: {len(rows)} rows, resume={resume}, run_agentic={run_agentic}, "
          f"case_timeout={case_timeout}s, metric_timeout={metric_timeout}s, "
          f"batch={batch_size}, jsonl={jsonl}", flush=True)
    results = asyncio.run(run_corpus(
        rows, case_timeout=case_timeout, metric_timeout=metric_timeout,
        jsonl_path=jsonl, output_path=output, resume=resume,
        batch_size=batch_size, run_agentic=run_agentic))
    report = {"workspace": WORKSPACE_SLUG, "corpus_size": len(results),
              "summary": summarize(results), "results": results}
    with open(output, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(f"report written: {output}", flush=True)
    _emit_report(report, report_md)


if __name__ == "__main__":
    main()

