# Chat recherche — A/B agentique vs déterministe (mesure offline)

> **VERDICT v2 (base ÉQUITABLE, post-fix retrieval — 2026-06-26).** Run propre **95/95, 0 erreur quota**, sur le DAG agentique réparé (retrieval câblé `workspace_slug`, parité de recall, routage inventaire→deep, verdict recalibré ; migrations 049/050). **La contamination du v1 est levée** : l'écart composite passe de **−5.9 (v1 contaminé, bras B sans retrieval)** à **−1.43** (A 92.2 vs B 90.8) → l'agentique est **quasi à parité de qualité**, pas en échec.
>
> **Mais il ne se justifie pas encore** : **+6.1 s** de latence (27.6 s vs 21.5 s), **win/tie/loss = 26 / 21 / 48** (il perd plus qu'il ne gagne), et seuls 2 leviers gagnent vraiment (`inventory` +1.8, `table_extract` +3.0). `self_correct` ne sur-déclenche plus (**0 %**), le routage `deep` fonctionne (B deep=28 vs A deep=9), 4 `aborted_latency` (4.2 %).
>
> ✅ **Signal hallucination QUALIFIÉ** (voir § « Qualification du signal hallucination ») : le `hallucination_rate` jugé B = 0.372 vs A = 0.097 est **~76 % un artefact du juge**, pas une vraie hallucination. Cause prouvée dans le code : `JudgeService` **n'injecte jamais le texte des chunks** dans son prompt (juste un booléen `has_context`) → il marque « unsupported » tout fait spécifique non-devinable par GPT-4o, **même verbatim dans un chunk remonté** ; plus B est précis/étayé, plus il est pénalisé (ce n'est **PAS** le format de citation `[n]`). Cross-check robuste : HHEM/factuality (grounding réel) donnent B **aussi/plus** ancré que A (ΔHHEM +0.010, Δfact +0.021). **hallucination_rate B corrigée ≈ 0.163** (borne haute ; ~0.10-0.13 après audit verbatim) → **quasi-parité** avec A (0.097). Le résidu de vraie hallu se concentre sur `multi_hop` (cas à retrieval dégradé).
>
> **Conclusion (consolidée, hallucination qualifiée)** : sur base équitable, l'agentique est **quasi-parité qualité** (composite −1.4 ; hallucination corrigée ~0.16 ≈ A), **plus lent** (+6.1 s), **sans gain net** → **pas de bascule justifiée en l'état**, mais **pas disqualifié**. Les seuls leviers réellement gagnants sont `inventory` (+1.8) et `table_extract` (+3.0). Pour faire gagner l'agentique : cibler ces niches + réduire la latence (les 3 évaluateurs `fork.self_eval` en parallèle / gating), et — orthogonal — corriger le juge (injecter le texte des chunks) ou prendre **HHEM** comme métrique d'hallucination de référence.
>
> ⚠ La section « Lecture » plus bas est un **template auto-généré** : ses phrases sur « self_correct sur-déclenche / quasi-systématique » sont **périmées** ici (self_correct = 0 %). Se fier à ce bandeau.

_Workspace_: `andritz` · _cas_: **95** · _arm B mesurés_: **95** · _erreurs_: 0

> **Arm A** = orchestration **déterministe de production** (`/chat`). **Arm B** = **vrai DAG agentique** (System « Andritz Chat Agentic », `variant=chat_agentic_thinking_v1`) exécuté de bout en bout par `execute_run_dag()` — 100 % fidèle, pas un mirroir. Les deux arms sont notés par les **mêmes** fonctions (`score_both_metrics`).

## Méthodologie

- **Arm A (déterministe).** `faithful_chat(mode=None)` rejoue le chemin exact de `/chat` (`_apply_workspace_chat_flow_defaults` → `_apply_retrieval_budget_policy` → `AgentOrchestrator.process_request` → `apply_answer_policy_to_text`), sans override de lane : `route_mode` = profil déterministe choisi par prod.
- **Arm B (DAG réel).** Par cas : création d'un `Run(system=Andritz Chat Agentic, input={query,history}, trigger=ab_spike)` puis `await execute_run_dag(run_id)`. La **trace** est reconstruite depuis `Run.checkpoints` (les `node_end` portent `chosen_branch` des décisions `route_mode`/`verdict`/`egress_gate`/`deliver` + `latency_ms`/`status` par nœud) et `SkillInvocations` (plan→action/mode, self_correct→action_taken, response_eval→composite interne, retrieval→context). `answer` = `Run.output_ref` (sink), fallback invocation. États terminaux explicites : `completed` / `hitl_pending` (→ `hitl_flagged`) / `aborted_latency` (valve membrane `max_latency_ms`, `hard_abort` — vraie issue prod, comptée) / `failed`.
- **Métriques identiques (2 arms).** `evaluate_response_metrics` → ResponseEvaluator (relevance, factuality, coherence, HHEM, adv_HHEM) ; `judge_answer` → JudgeService (composite 0-100, hallucination_rate). Timeout-safe (null + `_note`, jamais de crash). NB : le **composite des colonnes** vient du JudgeService (parité A/B) ; le DAG utilise en interne un composite distinct (ResponseEvaluator ×100) pour son verdict — voir Lecture.

## Détail par cas (classic vs agentic, lignes adjacentes)

| id | category | query | arm | route/mode | decisions/steps | latency_ms | composite | halluc_rate | hhem | factuality | coherence |
|---|---|---|---|---|---|---|---|---|---|---|---|
| demo_pass_akk200_width_speed | baseline | Quelle est la largeur de travail et la vite… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 14135 | 97.5 | 0.000 | 0.197 | 0.569 | 0.509 |
| demo_pass_akk200_width_speed | baseline | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 23068 | 96.7 | 0.667 | 0.204 | 0.562 | 0.497 |
| demo_pass_qms12_function_en | baseline | What is the Qualiscan QMS-12 system used fo… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 21328 | 95.8 | 0.000 | 0.287 | 0.847 | 0.428 |
| demo_pass_qms12_function_en | baseline | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 23438 | 96.2 | 0.000 | 0.296 | 0.868 | 0.455 |
| demo_pass_injector_cartridge_clea… | baseline | Comment dois-je nettoyer les cartouches d'i… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 19138 | 95.8 | 0.000 | 0.233 | 0.761 | 0.442 |
| demo_pass_injector_cartridge_clea… | baseline | ⤷ | agentic | fast | plan:reject_oos/fast → route:fast → verdict:strong → egress:ok → deliver:deliver | 22758 | 90.0 | 0.571 | 0.218 | 0.696 | 0.571 |
| demo_pass_acj200_carde | baseline | Décris la carde ACJ200 et ses principaux co… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 75934 | 95.4 | 0.000 | 0.250 | 0.684 | 0.636 |
| demo_pass_acj200_carde | baseline | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver | 33259 | 95.8 | 0.000 | 0.278 | 0.696 | 0.440 |
| demo_fail_akk200_de | language_de | Wie groß sind die Arbeitsbreite und die Pro… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 13557 | 96.7 | 0.333 | 0.229 | 0.662 | 0.408 |
| demo_fail_akk200_de | language_de | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 18757 | 97.9 | 0.000 | 0.224 | 0.648 | 0.481 |
| demo_fail_cu250s2_role | route | Quel est le rôle et la configuration du mod… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 18623 | 96.7 | 0.000 | 0.260 | 0.644 | 0.450 |
| demo_fail_cu250s2_role | route | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 23881 | 92.5 | 0.143 | 0.249 | 0.649 | 0.370 |
| demo_fail_etachrom_spares | exact_id | Quelles sont les pièces de rechange de la p… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 24513 | 98.3 | 0.000 | 0.230 | 0.727 | 0.386 |
| demo_fail_etachrom_spares | exact_id | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver | 31389 | 87.9 | 0.000 | 0.259 | 0.648 | 0.527 |
| demo_fail_qms12_de | language_de | Wozu dient das Qualiscan QMS-12 System und … | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 17385 | 94.6 | 0.000 | 0.270 | 0.705 | 0.382 |
| demo_fail_qms12_de | language_de | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 22732 | 96.2 | 0.000 | 0.314 | 0.859 | 0.489 |
| demo_d60_greasing | table_extract | Quelle quantité de graisse faut-il pour le … | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 11060 | 96.2 | 0.000 | 0.329 | 0.753 | 0.830 |
| demo_d60_greasing | table_extract | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 17833 | 95.8 | 0.250 | 0.340 | 0.773 | 0.618 |
| demo_fail_german_generic | language_de | Welche Wartung ist für die Filtration und d… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 23831 | 96.7 | 0.000 | 0.259 | 0.714 | 0.458 |
| demo_fail_german_generic | language_de | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 31109 | 95.8 | 0.000 | 0.273 | 0.728 | 0.432 |
| demo15_akk200_sections | route | Quelles sont les sections principales du ma… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 18494 | 87.1 | 0.000 | 0.171 | 0.487 | 0.504 |
| demo15_akk200_sections | route | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 25890 | 94.2 | 0.000 | 0.211 | 0.552 | 0.584 |
| demo15_acj200_residual_risks | baseline | Quels sont les risques résiduels et les con… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 32083 | 97.1 | 0.000 | 0.349 | 0.796 | 0.573 |
| demo15_acj200_residual_risks | baseline | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 28132 | 91.7 | 0.000 | 0.331 | 0.757 | 0.468 |
| demo15_qms12_calibration | baseline | Comment calibrer les capteurs du système de… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 28044 | 95.8 | 0.000 | 0.330 | 0.828 | 0.490 |
| demo15_qms12_calibration | baseline | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 42272 | 92.9 | 0.500 | 0.282 | 0.696 | 0.446 |
| demo15_cu250s2_commissioning | route | Comment mettre en service et paramétrer l'u… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 29781 | 95.4 | 0.000 | 0.323 | 0.792 | 0.451 |
| demo15_cu250s2_commissioning | route | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 37415 | 94.2 | 0.000 | 0.276 | 0.706 | 0.465 |
| demo15_qms12_fr | baseline | À quoi sert le système de mesure Qualiscan … | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 19317 | 95.8 | 0.000 | 0.244 | 0.848 | 0.492 |
| demo15_qms12_fr | baseline | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 28689 | 95.8 | 0.167 | 0.259 | 0.862 | 0.357 |
| avoid_hydrodry | out_of_corpus | Quelles sont les étapes de séchage du systè… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 25327 | 95.4 | 0.000 | 0.297 | 0.690 | 0.537 |
| avoid_hydrodry | out_of_corpus | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 21953 | 96.2 | 0.000 | 0.304 | 0.718 | 0.494 |
| avoid_filtration_intervals | hedge_prone | Quels sont les intervalles de maintenance d… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 33040 | 90.0 | 0.200 | 0.148 | 0.451 | 0.294 |
| avoid_filtration_intervals | hedge_prone | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 30224 | 90.4 | 0.000 | 0.161 | 0.480 | 0.540 |
| avoid_list_all_pumps | inventory | Liste-moi toutes les pompes de tous les pro… | classic | deep | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 25350 | 86.2 | 0.000 | 0.243 | 0.591 | 0.524 |
| avoid_list_all_pumps | inventory | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver | 27491 | 95.8 | 0.000 | 0.307 | 0.726 | 0.382 |
| reg_transversal_uraca | inventory | Quels projets utilisent une pompe URACA ? | classic | deep | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 27958 | 85.8 | 0.000 | 0.275 | 0.648 | 0.456 |
| reg_transversal_uraca | inventory | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver | 26303 | 91.2 | 1.000 | 0.249 | 0.709 | 0.444 |
| tr_akk200_tout | route | donne moi tout ce que tu sais sur le projet… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 51755 | 94.6 | 0.000 | 0.196 | 0.540 | 0.433 |
| tr_akk200_tout | route | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver | 30910 | 89.6 | 0.429 | 0.197 | 0.625 | 0.380 |
| tr_akk200_pompe | route | Quelle pompe est utilisée dans le projet AK… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 15336 | 97.5 | 0.000 | 0.217 | 0.602 | 1.000 |
| tr_akk200_pompe | route | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 35576 | 95.8 | 0.000 | 0.245 | 0.640 | 0.539 |
| tr_akk200_detaille_manuel | route | Détaille le contenu du manuel AKK200. | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 48960 | 92.5 | 0.000 | 0.242 | 0.590 | 0.503 |
| tr_akk200_detaille_manuel | route | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver | 41897 | 88.8 | 1.000 | 0.236 | 0.619 | 0.379 |
| tr_akk200_resume | route | Résume le projet AKK200. | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 35079 | 91.7 | 0.000 | 0.184 | 0.532 | 0.394 |
| tr_akk200_resume | route | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 27476 | 86.2 | 1.000 | 0.167 | 0.509 | 0.493 |
| tr_akk200_quelles_infos | baseline | quelles infos sur AKK200 ? | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 21194 | 90.8 | 0.000 | 0.190 | 0.538 | 0.433 |
| tr_akk200_quelles_infos | baseline | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 22727 | 90.4 | 1.000 | 0.187 | 0.530 | 0.422 |
| tr_col100_garniture_carde1 | depth | Peux-tu retrouver la liste de garniture de … | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 11005 | 87.1 | 0.333 | 0.241 | 0.601 | 0.469 |
| tr_col100_garniture_carde1 | depth | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver | 23503 | 81.2 | 0.200 | 0.319 | 0.733 | 0.622 |
| tr_bhx100_puissance_carde | multi_hop | Quelle est la puissance totale installée su… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 21371 | 91.2 | 0.000 | 0.166 | 0.482 | 0.376 |
| tr_bhx100_puissance_carde | multi_hop | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver | 33285 | 86.2 | 0.000 | 0.196 | 0.524 | 0.397 |
| tr_tambour_poids | multi_hop | À des fins de manipulation : quel est le po… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 27544 | 96.2 | 0.000 | 0.293 | 0.678 | 0.588 |
| tr_tambour_poids | multi_hop | ⤷ | agentic | balanced | plan:reject_oos/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 28598 | 86.7 | 1.000 | 0.307 | 0.682 | 0.565 |
| tr_brosses_frequence | hedge_prone | À quelle fréquence les brosses de nettoyage… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 25710 | 91.2 | 0.000 | 0.203 | 0.560 | 0.537 |
| tr_brosses_frequence | hedge_prone | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 35852 | 76.2 | 0.000 | 0.265 | 0.664 | 0.440 |
| tr_col100_garniture_avant_train | depth | Peux-tu retrouver la référence et la quanti… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 11782 | 83.8 | 0.000 | 0.214 | 0.539 | 0.485 |
| tr_col100_garniture_avant_train | depth | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver | 22400 | 89.6 | 0.000 | 0.207 | 0.534 | 0.633 |
| tr_bhx100_plan_charges | depth | Peux-tu me retrouver le plan de charges du … | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 14484 | 89.6 | 0.000 | 0.145 | 0.606 | 0.433 |
| tr_bhx100_plan_charges | depth | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 21420 | 81.2 | 0.000 | 0.177 | 0.613 | 0.490 |
| tr_col100_rouleaux_transfert | depth | Combien y a-t-il de rouleaux de transfert s… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 16803 | 82.1 | 0.000 | 0.125 | 0.462 | 0.547 |
| tr_col100_rouleaux_transfert | depth | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 20735 | 92.5 | 0.333 | 0.134 | 0.479 | 0.471 |
| tr_stockage_entrepot | hedge_prone | Quelles sont les recommandations de stockag… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 18126 | 95.8 | 0.000 | 0.325 | 0.820 | 0.485 |
| tr_stockage_entrepot | hedge_prone | ⤷ | agentic | balanced | plan:reject_oos/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 23589 | 97.1 | 0.000 | 0.288 | 0.791 | 0.508 |
| tr_d60_diametre60 | table_extract | Quelle est la quantité de graisse dans un p… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 23751 | 91.2 | 0.000 | 0.297 | 0.683 | 0.434 |
| tr_d60_diametre60 | table_extract | ⤷ | agentic | balanced | plan:reject_oos/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 32571 | 87.5 | 0.400 | 0.308 | 0.719 | 0.555 |
| tr_kru001y_pompes_hp | out_of_corpus | Pour le projet KRU001Y peux-tu me donner la… | classic | deep | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 35766 | 82.9 | 0.167 | 0.204 | 0.562 | 0.616 |
| tr_kru001y_pompes_hp | out_of_corpus | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver | 42597 | 81.2 | 0.000 | 0.252 | 0.706 | 0.533 |
| tr_dru006_prj2s | out_of_corpus | Pour le projet DRU006 qui s'occupe de fourn… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 17403 | 78.8 | 0.333 | 0.179 | 0.498 | 0.445 |
| tr_dru006_prj2s | out_of_corpus | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver | 26027 | 80.0 | 0.500 | 0.195 | 0.527 | 0.462 |
| tr_nacelle_hse | out_of_corpus | Dans quelles conditions un salarié sous-tra… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 28922 | 94.6 | 0.000 | 0.113 | 0.389 | 0.535 |
| tr_nacelle_hse | out_of_corpus | ⤷ | agentic | balanced | plan:reject_oos/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 21436 | 90.8 | 0.000 | 0.093 | 0.360 | 0.384 |
| tr_sable_220 | out_of_corpus | Sur une ligne ayant un débit de 220m3/h com… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 25119 | 87.5 | 0.333 | 0.256 | 0.662 | 0.396 |
| tr_sable_220 | out_of_corpus | ⤷ | agentic | balanced | plan:reject_oos/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 28437 | 86.7 | 0.000 | 0.252 | 0.661 | 0.459 |
| oc_northforge_pmp700 | out_of_corpus | At what pressure does the PMP-700 relief va… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 12396 | 85.8 | 1.000 | 0.144 | 0.417 | 0.444 |
| oc_northforge_pmp700 | out_of_corpus | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 14639 | 86.2 | 0.000 | 0.117 | 0.397 | 0.462 |
| oc_northforge_brg22 | out_of_corpus | Quand faut-il remplacer un roulement BRG-22… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 24715 | 94.6 | 0.000 | 0.310 | 0.770 | 0.460 |
| oc_northforge_brg22 | out_of_corpus | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 25457 | 89.6 | 0.000 | 0.294 | 0.803 | 0.568 |
| oc_northforge_vortex5 | out_of_corpus | Summarize the VORTEX-5 line start-up sequen… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 16457 | 80.0 | 0.667 | 0.258 | 0.613 | 0.404 |
| oc_northforge_vortex5 | out_of_corpus | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 19024 | 96.7 | 0.000 | 0.289 | 0.724 | 0.500 |
| edge_mh_bba120_hp_pump | multi_hop | Pour BBA120, quelle est la pompe haute pres… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 22873 | 97.9 | 0.000 | 0.216 | 0.625 | 0.630 |
| edge_mh_bba120_hp_pump | multi_hop | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver | 25719 | 91.7 | 1.000 | 0.178 | 0.639 | 0.324 |
| edge_mh_akk200_filter_oring | multi_hop | Dans AKK200, donne la référence de la carto… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 24611 | 84.2 | 0.250 | 0.227 | 0.542 | 0.296 |
| edge_mh_akk200_filter_oring | multi_hop | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver | 29347 | 93.8 | 1.000 | 0.162 | 0.440 | 0.447 |
| edge_cl_la_pompe | clarify | Où est la notice de la pompe ? | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 10383 | 81.7 | 0.333 | 0.321 | 0.767 | 1.000 |
| edge_cl_la_pompe | clarify | ⤷ | agentic | balanced | plan:reject_oos/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 21206 | 92.1 | 0.000 | 0.318 | 0.747 | 0.456 |
| edge_cl_le_manuel | clarify | Donne-moi le manuel. | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 13548 | 94.2 | 0.000 | 0.312 | 0.726 | 0.604 |
| edge_cl_le_manuel | clarify | ⤷ | agentic | balanced | plan:reject_oos/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 16781 | 89.2 | 0.000 | 0.322 | 0.743 | 0.503 |
| edge_cl_les_pieces | clarify | Quelles pièces de rechange ? | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 20116 | 93.3 | 0.000 | 0.365 | 0.827 | 0.489 |
| edge_cl_les_pieces | clarify | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 32377 | 95.8 | 0.000 | 0.379 | 0.830 | 0.555 |
| edge_dp_servo_x_safety | depth | Quelles sont les consignes de sécurité liée… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 18502 | 96.2 | 0.000 | 0.343 | 0.779 | 0.513 |
| edge_dp_servo_x_safety | depth | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 23636 | 95.8 | 0.000 | 0.318 | 0.707 | 0.540 |
| edge_dp_jetlace_conveyor | depth | Où est documenté le convoyeur Jetlace et se… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 12621 | 97.1 | 0.000 | 0.263 | 0.652 | 0.558 |
| edge_dp_jetlace_conveyor | depth | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 22308 | 95.8 | 0.000 | 0.296 | 0.711 | 0.410 |
| edge_inv_etachrom_projects | inventory | Sur quels projets trouve-t-on des pompes KS… | classic | deep | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 18538 | 95.4 | 0.000 | 0.248 | 0.575 | 0.280 |
| edge_inv_etachrom_projects | inventory | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver | 25645 | 95.0 | 0.333 | 0.289 | 0.696 | 0.843 |
| edge_inv_qms12_projects | inventory | Quels projets sont équipés d'un Qualiscan Q… | classic | deep | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 20950 | 95.8 | 0.000 | 0.238 | 0.584 | 0.574 |
| edge_inv_qms12_projects | inventory | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver | 25549 | 93.8 | 1.000 | 0.302 | 0.784 | 0.758 |
| edge_rt_akk200_generic | route | Parle-moi du projet AKK200. | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 32173 | 94.6 | 0.000 | 0.203 | 0.565 | 0.369 |
| edge_rt_akk200_generic | route | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 32453 | 72.9 | 1.000 | 0.184 | 0.531 | 0.511 |
| mt_followup_akk200 | anaphora | et pour celle-ci, quelles pièces de rechang… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 19613 | 95.8 | 0.000 | 0.234 | 0.748 | 0.318 |
| mt_followup_akk200 | anaphora | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 28097 | 87.1 | 0.000 | 0.395 | 0.853 | 0.569 |
| mt_followup_switch_aco150 | anaphora | même question pour ACO150 | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 9758 | 94.2 | 0.000 | 0.175 | 0.502 | 1.000 |
| mt_followup_switch_aco150 | anaphora | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 18054 | 92.1 | 0.000 | 0.292 | 0.744 | 0.451 |
| mt_followup_etachrom_maint | anaphora | et la maintenance pour cette machine ? | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 26385 | 92.1 | 0.125 | 0.249 | 0.623 | 0.512 |
| mt_followup_etachrom_maint | anaphora | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 30348 | 95.4 | 0.000 | 0.266 | 0.654 | 0.488 |
| spl_002_dci110_strip_carrier | depth | Comment retirer le strip-carrier d'un injec… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 18611 | 90.0 | 0.500 | 0.224 | 0.573 | 0.407 |
| spl_002_dci110_strip_carrier | depth | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 21265 | 80.4 | 1.000 | 0.225 | 0.590 | 0.528 |
| spl_003_aco140_spl | baseline | Peux-tu retrouver la Spare Parts List du pr… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 18063 | 96.2 | 0.000 | 0.205 | 0.549 | 1.000 |
| spl_003_aco140_spl | baseline | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver | 31077 | 97.1 | 0.000 | 0.263 | 0.662 | 0.476 |
| spl_005_bba120_spl | baseline | Peux-tu retrouver la Spare Parts List du pr… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 22700 | 95.8 | 0.000 | 0.263 | 0.739 | 0.462 |
| spl_005_bba120_spl | baseline | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver | 39756 | 97.1 | 0.000 | 0.325 | 0.715 | 0.330 |
| spl_006_bba120_uraca_kd724 | baseline | Quels documents existent pour la pompe HP U… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 23400 | 95.8 | 0.000 | 0.254 | 0.706 | 0.530 |
| spl_006_bba120_uraca_kd724 | baseline | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver | 29812 | 96.7 | 0.000 | 0.334 | 0.759 | 0.573 |
| spl_007_bba120_ksb_etachrom | baseline | Quel document couvre la pompe KSB Etachrom … | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 17102 | 85.4 | 0.000 | 0.167 | 0.484 | 0.557 |
| spl_007_bba120_ksb_etachrom | baseline | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver | 28778 | 86.7 | 1.000 | 0.207 | 0.565 | 0.454 |
| spl_008_akk200_filtration_vacuum | baseline | Quelle procedure de maintenance concerne la… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 24889 | 91.2 | 0.000 | 0.197 | 0.529 | 0.671 |
| spl_008_akk200_filtration_vacuum | baseline | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver → [aborted_latency] | 46893 | 96.7 | 0.000 | 0.261 | 0.666 | 0.594 |
| spl_009_ara200_conveyor | depth | Quels documents de convoyeur sont indexes p… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 15304 | 97.5 | 0.000 | 0.271 | 0.636 | 0.495 |
| spl_009_ara200_conveyor | depth | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver | 24893 | 92.1 | 0.000 | 0.285 | 0.686 | 0.403 |
| spl_010_ara200_pneumatic_cabinet | depth | Quel document decrit l'armoire pneumatique … | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 16864 | 69.6 | 1.000 | 0.189 | 0.504 | 0.528 |
| spl_010_ara200_pneumatic_cabinet | depth | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 21700 | 89.6 | 0.000 | 0.215 | 0.539 | 0.477 |
| spl_011_akk200_filtering_cartridg… | table_extract | Dans le projet AKK200, quelle source contie… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 22183 | 97.1 | 0.000 | 0.257 | 0.715 | 0.424 |
| spl_011_akk200_filtering_cartridg… | table_extract | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver → [aborted_latency] | 51127 | 96.7 | 0.000 | 0.205 | 0.627 | 0.518 |
| spl_012_geotex_def_strips_label_b | table_extract | Dans les fichiers NON-WOVENS France, que va… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 10352 | 76.2 | 1.000 | 0.058 | 0.283 | 1.000 |
| spl_012_geotex_def_strips_label_b | table_extract | ⤷ | agentic | balanced | plan:reject_oos/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 20148 | 92.5 | 1.000 | 0.204 | 0.579 | 1.000 |
| spl_014_akk200_lm300_filtering_ca… | exact_id | Dans AKK200, je cherche la reference Filter… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 23297 | 96.2 | 0.000 | 0.254 | 0.686 | 0.470 |
| spl_014_akk200_lm300_filtering_ca… | exact_id | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 31346 | 97.5 | 0.000 | 0.202 | 0.580 | 0.471 |
| spl_015_akk200_oring_d36 | exact_id | Quel fichier source contient le joint O-rin… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 19131 | 92.1 | 0.000 | 0.145 | 0.505 | 1.000 |
| spl_015_akk200_oring_d36 | exact_id | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 28360 | 91.7 | 0.000 | 0.184 | 0.537 | 0.297 |
| div_001_g150_operating_instructio… | baseline | Where can I find the G150 speed controller … | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 11488 | 95.8 | 0.000 | 0.330 | 0.757 | 0.736 |
| div_001_g150_operating_instructio… | baseline | ⤷ | agentic | balanced | plan:reject_oos/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 21110 | 92.9 | 1.000 | 0.276 | 0.664 | 0.734 |
| div_002_printable_parts_manual_mu… | clarify | Montre-moi les parts manuals disponibles en… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 11763 | 91.2 | 0.000 | 0.271 | 0.679 | 0.426 |
| div_002_printable_parts_manual_mu… | clarify | ⤷ | agentic | balanced | plan:reject_oos/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 19773 | 90.0 | 1.000 | 0.262 | 0.635 | 0.420 |
| div_003_vacuum_set_blower_manuals | depth | Which manuals cover the vacuum set blowers … | classic | deep | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 24113 | 96.7 | 0.000 | 0.318 | 0.724 | 0.764 |
| div_003_vacuum_set_blower_manuals | depth | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 26716 | 90.0 | 1.000 | 0.278 | 0.675 | 0.519 |
| div_006_cu250s2_vector_control_un… | route | Where is the CU250S-2 vector control unit m… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 16362 | 95.8 | 0.000 | 0.246 | 0.708 | 0.454 |
| div_006_cu250s2_vector_control_un… | route | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 24637 | 94.2 | 1.000 | 0.188 | 0.521 | 0.374 |
| div_007_qualiscan_qms12_betriebsa… | language_de | Wo sind die Betriebsanleitungen fuer den Qu… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 23002 | 95.8 | 0.000 | 0.363 | 0.851 | 0.440 |
| div_007_qualiscan_qms12_betriebsa… | language_de | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 25431 | 96.2 | 0.333 | 0.342 | 0.825 | 0.492 |
| div_008_sinamics_s120_s150_list_m… | depth | Find the SINAMICS S120 S150 list manual for… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 19439 | 95.8 | 0.000 | 0.310 | 0.807 | 0.424 |
| div_008_sinamics_s120_s150_list_m… | depth | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 26464 | 94.6 | 0.429 | 0.281 | 0.763 | 0.562 |
| div_009_uraca_kd724_chapters_mult… | inventory | Sur quels projets retrouve-t-on la document… | classic | deep | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 21304 | 96.2 | 0.000 | 0.203 | 0.518 | 0.449 |
| div_009_uraca_kd724_chapters_mult… | inventory | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver | 28953 | 94.2 | 1.000 | 0.225 | 0.621 | 0.771 |
| fb_001_sparse_disabled_dense_stil… | baseline | Comment nettoyer les cartouches d'injecteur… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 22758 | 90.8 | 0.400 | 0.220 | 0.650 | 0.453 |
| fb_001_sparse_disabled_dense_stil… | baseline | ⤷ | agentic | balanced | plan:reject_oos/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 31962 | 88.8 | 0.857 | 0.229 | 0.704 | 0.528 |
| fb_002_cross_encoder_applied_on_b… | baseline | Quelle est la procédure de maintenance du v… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 21370 | 92.5 | 0.000 | 0.268 | 0.640 | 0.511 |
| fb_002_cross_encoder_applied_on_b… | baseline | ⤷ | agentic | balanced | plan:reject_oos/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 24954 | 81.7 | 1.000 | 0.180 | 0.504 | 0.427 |
| hi_001_ambiguous_parts_manual | clarify | Ou se trouve le parts manual ? | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 14592 | 95.8 | 0.000 | 0.249 | 0.633 | 0.380 |
| hi_001_ambiguous_parts_manual | clarify | ⤷ | agentic | balanced | plan:reject_oos/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 15916 | 94.6 | 0.000 | 0.227 | 0.615 | 0.532 |
| hi_002_ambiguous_kd724_partial_ref | inventory | Quels projets utilisent la pompe KD724 ? | classic | deep | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 23527 | 93.8 | 0.000 | 0.229 | 0.579 | 0.331 |
| hi_002_ambiguous_kd724_partial_ref | inventory | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver | 21260 | 93.8 | 1.000 | 0.234 | 0.716 | 0.291 |
| hi_003_compare_continental_pollri… | comparison_partial | What is the difference between the CONTINEN… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 26880 | 87.1 | 0.500 | 0.143 | 0.460 | 0.360 |
| hi_003_compare_continental_pollri… | comparison_partial | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 36450 | 91.2 | 1.000 | 0.152 | 0.486 | 0.376 |
| hi_004_compare_g150_s120_drives | comparison_partial | Quelles differences de parametres de mise e… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 21213 | 91.7 | 0.000 | 0.364 | 0.803 | 0.453 |
| hi_004_compare_g150_s120_drives | comparison_partial | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 26440 | 93.8 | 0.400 | 0.328 | 0.730 | 0.473 |
| hi_005_analytical_php_pressure_dr… | depth | Pourquoi la pression chute-t-elle sur le gr… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 16882 | 95.4 | 0.000 | 0.325 | 0.720 | 0.513 |
| hi_005_analytical_php_pressure_dr… | depth | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 26001 | 96.7 | 0.000 | 0.309 | 0.735 | 0.412 |
| hi_006_german_simotics_akk200 | language_de | Wo finde ich die SIMOTICS Betriebsanleitung… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 16030 | 91.7 | 0.000 | 0.167 | 0.485 | 0.418 |
| hi_006_german_simotics_akk200 | language_de | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 24702 | 66.2 | 1.000 | 0.185 | 0.529 | 0.470 |
| hi_007_exclusion_excelle_not_dutch | route | Excelle S5PP6TT card operator manual in Eng… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 18166 | 86.2 | 0.333 | 0.189 | 0.599 | 0.522 |
| hi_007_exclusion_excelle_not_dutch | route | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 25633 | 74.6 | 1.000 | 0.243 | 0.597 | 0.496 |
| hi_008_compare_wilo_drain_nolh_be… | comparison_partial | Compare the Wilo Drain SP and the Wilo NOLH… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 25209 | 87.9 | 0.000 | 0.183 | 0.519 | 0.412 |
| hi_008_compare_wilo_drain_nolh_be… | comparison_partial | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver → [aborted_latency] | 45604 | 79.6 | 0.000 | 0.115 | 0.393 | 0.470 |
| hi_009_ambiguous_lh2_identifier | exact_id | What does document LH2 0113 cover and which… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 16424 | 96.7 | 0.000 | 0.197 | 0.641 | 0.529 |
| hi_009_ambiguous_lh2_identifier | exact_id | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 27135 | 86.7 | 1.000 | 0.207 | 0.637 | 0.389 |
| hi_010_analytical_wilo_rexa_vacuu… | depth | Sur LOT100, quelle pompe BP WILO equipe le … | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 24670 | 86.2 | 0.000 | 0.135 | 0.461 | 0.483 |
| hi_010_analytical_wilo_rexa_vacuu… | depth | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver | 33543 | 92.5 | 0.800 | 0.220 | 0.608 | 0.409 |
| hi_011_ambiguous_etachrom_bc_mult… | exact_id | Ou trouver la notice etachrom bc du circuit… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 12475 | 91.7 | 0.000 | 0.165 | 0.535 | 0.543 |
| hi_011_ambiguous_etachrom_bc_mult… | exact_id | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 17046 | 91.7 | 1.000 | 0.162 | 0.524 | 0.480 |
| ml_001_fr_injector_cleaning | baseline | Comment nettoyer les cartouches d'injecteur… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 18327 | 95.8 | 0.000 | 0.262 | 0.821 | 0.392 |
| ml_001_fr_injector_cleaning | baseline | ⤷ | agentic | balanced | plan:reject_oos/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 33307 | 93.3 | 0.200 | 0.202 | 0.626 | 0.468 |
| ml_002_en_injector_cleaning | baseline | How do I clean the EXH injector cartridges? | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 20253 | 95.8 | 0.000 | 0.269 | 0.807 | 0.366 |
| ml_002_en_injector_cleaning | baseline | ⤷ | agentic | balanced | plan:reject_oos/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 26063 | 97.1 | 0.000 | 0.278 | 0.816 | 0.476 |
| ml_003_de_injector_cleaning | language_de | Wie reinige ich die EXH Injektor-Kartuschen? | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 14797 | 95.8 | 0.000 | 0.374 | 0.808 | 0.539 |
| ml_003_de_injector_cleaning | language_de | ⤷ | agentic | balanced | plan:reject_oos/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 19300 | 95.4 | 0.000 | 0.400 | 0.856 | 0.487 |
| ml_006_de_akk200_spl | language_de | Finde die Ersatzteilliste für das Projekt A… | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 15011 | 87.5 | 1.000 | 0.168 | 0.579 | 0.728 |
| ml_006_de_akk200_spl | language_de | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver | 28245 | 97.1 | 0.250 | 0.236 | 0.841 | 0.459 |
| sf_001_project_filter_akk200 | clarify | Liste des pièces de rechange | classic | deep | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 26574 | 95.0 | 0.000 | 0.353 | 0.788 | 0.485 |
| sf_001_project_filter_akk200 | clarify | ⤷ | agentic | deep | plan:clarify/deep → route:deep → verdict:strong → egress:ok → deliver:clarify → [aborted_latency] | 45789 | 93.8 | 0.000 | 0.291 | 0.681 | 1.000 |
| sf_002_cross_project_guard | baseline | Liste de garniture du projet ACO150 | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 14639 | 90.8 | 0.250 | 0.169 | 0.519 | 0.592 |
| sf_002_cross_project_guard | baseline | ⤷ | agentic | deep | plan:answer/deep → route:deep → verdict:strong → egress:ok → deliver:deliver | 21697 | 77.9 | 0.750 | 0.247 | 0.775 | 0.476 |
| sf_003_source_kind_filter_html | clarify | Procédure de maintenance de la filtration | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 31783 | 95.8 | 0.000 | 0.292 | 0.704 | 0.432 |
| sf_003_source_kind_filter_html | clarify | ⤷ | agentic | balanced | plan:reject_oos/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 43914 | 94.6 | 0.000 | 0.240 | 0.658 | 0.440 |
| sp_001_pump_model_exact | exact_id | URACA KD724 | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 17766 | 90.0 | 0.200 | 0.174 | 0.526 | 0.286 |
| sp_001_pump_model_exact | exact_id | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 25961 | 80.0 | 1.000 | 0.192 | 0.552 | 0.517 |
| sp_002_doc_reference_exact | exact_id | DCI 110 PERFO-TE-OM-10-5 | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 12343 | 93.8 | 0.000 | 0.247 | 0.605 | 0.526 |
| sp_002_doc_reference_exact | exact_id | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 21337 | 90.0 | 1.000 | 0.300 | 0.707 | 0.434 |
| sp_003_excel_stem_exact | exact_id | GEOTEX SPL Y25.05.22 | classic | balanced | query_rewrite → routing → query_received → embedding → retrieve → context_filtering → validation → synthesis → evaluation | 15389 | 96.7 | 0.000 | 0.244 | 0.665 | 0.682 |
| sp_003_excel_stem_exact | exact_id | ⤷ | agentic | balanced | plan:answer/balanced → route:balanced → verdict:strong → egress:ok → deliver:deliver | 25323 | 87.9 | 0.857 | 0.246 | 0.600 | 0.433 |

## Agrégat par levier (`category`) — A (classic) vs B (agentic)

| category | n | A comp | B comp | Δcomp | A halluc | B halluc | A lat | B lat | Δlat | self_correct |
|---|---|---|---|---|---|---|---|---|---|---|
| anaphora | 3 | 94.0 | 91.5 | -2.5 | 0.042 | 0.000 | 18585 | 25500 | +6914 | 0/3 |
| baseline | 19 | 94.2 | 92.4 | -1.8 | 0.034 | 0.406 | 23482 | 29461 | +5978 | 0/19 |
| clarify | 7 | 92.4 | 92.9 | +0.4 | 0.048 | 0.143 | 18394 | 27965 | +9571 | 0/7 |
| comparison_partial | 3 | 88.9 | 88.2 | -0.7 | 0.167 | 0.467 | 24434 | 36165 | +11731 | 0/3 |
| depth | 13 | 89.8 | 90.2 | +0.4 | 0.141 | 0.289 | 17006 | 24199 | +7193 | 0/13 |
| exact_id | 8 | 94.4 | 89.2 | -5.3 | 0.025 | 0.607 | 17667 | 25987 | +8320 | 0/8 |
| hedge_prone | 3 | 92.3 | 87.9 | -4.4 | 0.067 | 0.000 | 25625 | 29888 | +4263 | 0/3 |
| inventory | 6 | 92.2 | 94.0 | +1.8 | 0.000 | 0.722 | 22938 | 25867 | +2929 | 0/6 |
| language_de | 7 | 94.1 | 92.1 | -2.0 | 0.190 | 0.226 | 17659 | 24325 | +6666 | 0/7 |
| multi_hop | 4 | 92.4 | 89.6 | -2.8 | 0.062 | 0.750 | 24100 | 29237 | +5138 | 0/4 |
| out_of_corpus | 8 | 87.5 | 88.4 | +1.0 | 0.312 | 0.062 | 23263 | 24946 | +1683 | 0/8 |
| route | 10 | 93.2 | 88.3 | -4.9 | 0.033 | 0.557 | 28473 | 30577 | +2104 | 0/10 |
| table_extract | 4 | 90.2 | 93.1 | +3.0 | 0.250 | 0.412 | 16836 | 30420 | +13583 | 0/4 |

## Synthèse A/B globale

- **composite** — A: 92.2 · B: 90.8 · **Δ moyen: -1.43** (B−A, sur 95 cas appariés)
- **win/tie/loss (agentic, seuil ±1 pt composite)**: **26 / 21 / 48**
- **hallucination_rate** — A: 0.097 · B: 0.372 · **Δ moyen: +0.275**
- **latence** — A: 21464 ms · B: 27601 ms · **Δ moyen: +6137 ms**
- **route changée vs classic**: 22 (23.2%) — A routes {balanced=86, deep=9} · B routes {balanced=66, deep=28, fast=1}
- **self_correct déclenché**: 0 (0.0%)
- **aborted_latency (valve membrane)**: 4 (4.2%)
- **hitl_flagged**: 0 (0.0%)
- **arm B statuts**: {aborted_latency=4, completed=91}

## Lecture (template auto-généré — certaines phrases périmées, voir bandeau VERDICT v2)

**Où l'agentique gagne sa latence.**
- `table_extract` : composite +3.0 pour +13583 ms — le surcoût de latence achète de la qualité (le verdict→self_correct ou la route plus profonde paie).
- `inventory` : composite +1.8 pour +2929 ms — le surcoût de latence achète de la qualité (le verdict→self_correct ou la route plus profonde paie).

**Où c'est de l'overhead pur** (plus lent, sans gain composite) :
- `comparison_partial` : composite -0.7 mais +11731 ms — l'orchestration agentique (plan + 3 évaluateurs + gates) ne rend pas la réponse meilleure.
- `clarify` : composite +0.4 mais +9571 ms — l'orchestration agentique (plan + 3 évaluateurs + gates) ne rend pas la réponse meilleure.
- `exact_id` : composite -5.3 mais +8320 ms — l'orchestration agentique (plan + 3 évaluateurs + gates) ne rend pas la réponse meilleure.
- `depth` : composite +0.4 mais +7193 ms — l'orchestration agentique (plan + 3 évaluateurs + gates) ne rend pas la réponse meilleure.
- `anaphora` : composite -2.5 mais +6914 ms — l'orchestration agentique (plan + 3 évaluateurs + gates) ne rend pas la réponse meilleure.
- `language_de` : composite -2.0 mais +6666 ms — l'orchestration agentique (plan + 3 évaluateurs + gates) ne rend pas la réponse meilleure.

**Signal de calibration du verdict (à corriger).**
- Le DAG calcule son composite **interne** via ResponseEvaluator (`composite ≈ moyenne(relevance, factuality, coherence) × 100`). Sur arm A on mesure rel=0.717 / fact=0.635 / coh=0.516 → un composite interne **≈ 62.3**, donc **< 70**.
- Le verdict `weak` se déclenche si `composite<70 or hallucination_rate>0.15 or context_count==0`. Avec un composite interne structurellement ~66, le verdict bascule `weak` presque toujours → **self_correct sur-déclenche** (mesuré : 0.0% des cas arm B), ce qui ajoute une passe LLM (latence) sans garantie de gain.
- **Abort latence** : la valve membrane `max_latency_ms=45000` (`hard_abort`) coupe 4.2% des runs B — directement aggravé par la passe self_correct quasi-systématique.

**Recommandation de recalibration.**
1. **Découpler l'échelle composite du verdict.** Le composite ResponseEvaluator (cosinus d'embeddings) vit naturellement autour de 0.6–0.7×100 ; comparer ce 0-100 à un seuil de 70 conçu pour un juge LLM est une erreur d'échelle. Soit recalibrer le seuil à **~55–60** pour ce composite, soit faire porter le verdict par la **hallucination_rate** (`>0.15`) + `context_count==0`, et ne garder le composite que comme tie-breaker.
2. **Préférer un verdict hallucination-based** : `weak` si `hallucination_rate>0.15 or context_count==0` (signaux fiables, peu sensibles à l'échelle), réservant l'escalade coûteuse aux vrais cas de non-grounding.
3. **Protéger la latence** : si self_correct doit rester déclenché souvent, relever `max_latency_ms` ou rendre la passe self_correct conditionnelle à un gain attendu, pour éviter les `aborted_latency` qui détruisent l'UX sans rien livrer.

## Qualification du signal hallucination

> **TL;DR.** Le `hallucination_rate` jugé B = **0.372** est **majoritairement un artefact du juge LLM** (≈ **76 %** de l'écart B−A), pas une vraie hallucination. Le juge audite les claims **sans jamais recevoir le texte du contexte** (il ne voit qu'un booléen `has_context: yes/no`) → il pénalise tout fait spécifique qu'il ne peut pas deviner par son prior, **même verbatim dans un chunk remonté**. Mesuré par le grounding réel (HHEM, embeddings sur chunks réels), **B est à parité voire légèrement mieux ancré que A** (ΔHHEM +0.010, Δfact +0.021). **hallucination_rate B corrigée ≈ 0.163** (borne haute conservatrice ; audit verbatim → plutôt ~0.10–0.13) vs A 0.097. **Le verdict v2 (quasi-parité, plus lent, sans gain net) tient ; l'hallucination ne disqualifie pas l'agentique.**

### (a) Mécanisme exact du `hallucination_rate` (juge)

`JudgeService.evaluate` (`backend/app/services/evaluation/judge.py`) : GPT-4o extrait 3–8 *claims* atomiques de la réponse et étiquette chacun `supported`/`unsupported`, puis

```python
supported = sum(1 for c in claims if c.get("supported"))
unsupported = len(claims) - supported
hallucination_rate = unsupported / max(1, len(claims))
```

**Le piège est dans le prompt** (`JUDGE_PROMPT`) : le contexte n'y entre **que** via une ligne `Retrieved context available: {has_context}` où `has_context = "yes" if context_chunks else "no"` (judge.py). **Le texte des chunks n'est jamais injecté dans le prompt du juge.** L'instruction « label each as supported/unsupported based on the retrieved context » est donc **inopérante** : le juge ne dispose que de la question + son **prior** (connaissance GPT-4o). Sur un corpus industriel spécialisé (réf. de pièces, codes projet, cotes, couples de serrage, noms de fichiers), tout fait précis non-devinable par GPT-4o est marqué `unsupported`, **y compris lorsqu'il est verbatim dans un chunk effectivement remonté**.

Corollaire : **plus une réponse est précise et étayée, plus elle est pénalisée**. Le bras B (deep/agentique) produit des réponses plus complètes et plus spécifiques → plus de claims « non vérifiables par le prior » → `hallucination_rate` mécaniquement gonflée. **Ce n'est PAS un problème de format de citation `[n]`** : le prompt du juge ne lit aucune citation. C'est une **absence totale de contexte côté juge**.

À l'opposé, **HHEM/factuality** (`ResponseEvaluator`, `backend/app/services/metrics/evaluator.py`) comparent l'embedding de la réponse aux embeddings des **chunks réellement remontés** (`factuality = max cos(réponse, chunk)`, `hhem = mf/(1+mf)` avec `mf = mean_sim·factuality`). C'est une mesure de **grounding réel**, insensible au prior du juge **et** au format de citation.

### (b) Corrélation juge-halluc vs HHEM / factuality (95 cas)

| Relation | Coefficient (Pearson) | Lecture |
|---|---|---|
| `corr(B.halluc, B.HHEM)` | **−0.317** | faible — halluc-juge ≈ décorrélé du grounding |
| `corr(B.halluc, B.factuality)` | **−0.292** | idem |
| `corr(Δhalluc, ΔHHEM)` (apparié B−A) | **−0.196** | quasi-nul |
| `corr(Δhalluc, Δfactuality)` (apparié B−A) | **−0.144** | quasi-nul |
| Moyennes appariées | **Δhalluc = +0.275**, **ΔHHEM = +0.010**, **Δfact = +0.021** | B **aussi/plus** ancré que A, mais +0.275 d'halluc-juge |

Si `halluc`-juge mesurait du vrai non-grounding, on attendrait une corrélation **fortement négative** avec HHEM. Elle est faible (−0.31), et **en apparié les deux signaux pointent en sens opposés** : B est en moyenne légèrement *mieux* ancré que A (ΔHHEM/Δfact > 0) alors que le juge lui inflige +0.275 d'hallucination.

**Inversion révélatrice** (cf. agrégat par catégorie) : là où une *vraie* hallucination se manifesterait — `out_of_corpus` (pas de grounding disponible) — **B halluc = 0.062 < A = 0.312** (B hedge/rejette mieux). Le pic de B est au contraire concentré sur les catégories à **faits spécifiques étayés** : `inventory` 0.722, `multi_hop` 0.750, `exact_id` 0.607, `route` 0.557. C'est la **signature d'un artefact de spécificité**, pas d'une fabrication.

### (c) Audit par cas (échantillon) — claim flaggé `unsupported` vs chunk réellement remonté

Aucune mention « étayé » sans extrait verbatim. (`A.halluc`/`B.halluc` = valeurs du juge, table « Détail par cas ».)

| id | catégorie | claim que le juge note `unsupported` | étayé par un chunk remonté ? (id + verbatim) | A.halluc | B.halluc | verdict |
|---|---|---|---|---|---|---|
| `reg_transversal_uraca` | inventory | « 133 projets utilisent URACA : BHX100, AKI500, BCX200… » | **OUI** — chunk `project_inventory_facet` (source autoritative) : « *projets utilisant uraca : 133 projet(s) au total : BHX100, AKI500, BCX200, BIO100, BCX300, ASY100…* » | 0.000 | 1.000 | **ARTEFACT** |
| `edge_inv_qms12_projects` | inventory | « 11 projets QMS-12 : BHX100, ASY200, THO200… » | **OUI** — chunk `project_inventory_facet` : « *projets utilisant qualiscan, qms12 : 11 projet(s) au total : BHX100, ASY200, THO200, NAT100, EXX200, THO300…* » | 0.000 | 1.000 | **ARTEFACT** |
| `hi_002_ambiguous_kd724_partial_ref` | inventory | « la pompe KD724 est utilisée dans 136 projets : BHX100, AKI500… » | **OUI** — chunk `project_inventory_facet` : « *projets utilisant kd724 : 136 projet(s) au total : BHX100, AKI500, BCX200, TEK100…* » | 0.000 | 1.000 | **ARTEFACT** |
| `sp_001_pump_model_exact` | exact_id | « Druckwächter Typ FF 4-12 AAG = 0,595 kg » ; « M24 = 250 Nm » ; « essai de pression dir. 97/23/EG » | **OUI** — chunk `bba5f45f…_chunk_15` : « *0740431 0,595 … Druckwächter Typ FF 4-12 AAG* » ; chunk `cedbce07…_chunk_18` : « *M 24 - 250 Nm M 30 - 500 Nm M 36 - 700 Nm M 42 - 1000 Nm M 48 - 1300 Nm* » ; chunk `e1c8e119…_chunk_9` : « *Pressure Equipment Directive 97/23/EG* » | 0.200 | 1.000 | **ARTEFACT** |
| `sp_002_doc_reference_exact` | exact_id | « immersion 24 h » ; « nettoyage 1×/semaine » ; « ≥ 2 campagnes/mois » | **OUI** — chunk `8da86a0b…_chunk_10` : « *leave it in the solution during 24 hours* » ; chunk `8da86a0b…_chunk_9` : « *Carry out a weekly preventive cleaning of the injector cartridges* » + « *Carry out at least 2 cleaning campaigns per month* » | 0.000 | 1.000 | **ARTEFACT** |
| `edge_mh_akk200_filter_oring` | multi_hop | « cartouche filtrante réf. = AKK 200 » ; « O-ring 70 × 2,5 mm » | **NON** — 1 seul chunk remonté = facette **méta** (« *Inventaire Knowledge collection. Total sources: 107355…* ») ; ni réf. cartouche ni cote O-ring. B a réutilisé le **code projet** comme réf. et inventé la cote. | 0.250 | 1.000 | **RÉEL** (retrieval dégradé + sur-affirmation) |

Note méthodo : sur le même `sp_002`, le classifieur embeddings (d) l'a rangé en « réel-probable » (Δfact −0.065) alors que l'audit verbatim prouve l'artefact. **Le classifieur sous-compte donc les artefacts** → la halluc B corrigée (d) est une **borne haute**.

### (d) Split artefact / réel par catégorie + `hallucination_rate` B corrigée

Méthode : un cas est *élevé* si `B.halluc ≥ 0.30` et `B.halluc − A.halluc ≥ 0.15`. Parmi ces cas, **artefact** si le grounding n'est pas matériellement pire (`ΔHHEM ≥ −0.03` ET `Δfact ≥ −0.03`), sinon **réel-probable**. `B corr` = on ramène les cas artefact à la valeur de A (baseline grounding-apparié), on garde B ailleurs.

| catégorie | n | A halluc | B halluc (brut) | **B halluc (corrigé)** | artefact | réel |
|---|---|---|---|---|---|---|
| anaphora | 3 | 0.042 | 0.000 | 0.000 | 0 | 0 |
| baseline | 19 | 0.034 | 0.406 | 0.215 | 5 | 4 |
| clarify | 7 | 0.048 | 0.143 | 0.143 | 0 | 1 |
| comparison_partial | 3 | 0.167 | 0.467 | 0.300 | 1 | 1 |
| depth | 13 | 0.141 | 0.289 | 0.164 | 3 | 2 |
| exact_id | 8 | 0.025 | 0.607 | **0.132** | 4 | 1 |
| hedge_prone | 3 | 0.067 | 0.000 | 0.000 | 0 | 0 |
| inventory | 6 | 0.000 | 0.722 | **0.000** | 5 | 0 |
| language_de | 7 | 0.190 | 0.226 | 0.036 | 2 | 0 |
| multi_hop | 4 | 0.062 | 0.750 | **0.500** | 1 | 2 |
| out_of_corpus | 8 | 0.312 | 0.062 | 0.042 | 1 | 0 |
| route | 10 | 0.033 | 0.557 | 0.248 | 4 | 2 |
| table_extract | 4 | 0.250 | 0.412 | 0.312 | 1 | 0 |
| **GLOBAL** | **95** | **0.097** | **0.372** | **0.163** | **27** | **13** |

- **Écart B−A brut = +0.275 ; corrigé = +0.066 → ≈ 76 % de l'écart est un artefact du juge.**
- `inventory` (0.722 → **0.000**) : les 6 cas « élevés » sont **tous** artefact ; chacun reprend verbatim une facette `project_inventory_facet` (source autoritative) — le grounding parfait est étiqueté 100 % hallucination.
- `exact_id` (0.607 → **0.132**) : transcription verbatim de listes de pièces / procédures.
- **Résidu réel** concentré sur `multi_hop` (corrigé 0.500) et quelques `baseline`/`depth`/`route` à **retrieval dégradé** (1 chunk méta remonté, B sur-affirme au lieu de hedger) — vrai point de vigilance, mais marginal (≈ 13 cas, souvent faible amplitude).

### (e) Implication sur le verdict A/B + recommandations

- **Le 0.372 est majoritairement un artefact.** Après retrait, **halluc B corrigée ≈ 0.163** (borne haute ; ~0.10–0.13 après audit verbatim) vs **A 0.097** → **quasi-parité**. Sur le grounding *réel* (HHEM, embeddings sur chunks remontés), **B est à parité, voire marginalement meilleur** que A. **L'agentique n'est PAS disqualifié sur l'axe hallucination.**
- **Le verdict v2 tient inchangé** : quasi-parité de qualité, **plus lent (+6.1 s)**, **sans gain net** (win/tie/loss 26/21/48), gains réels limités à `inventory`/`table_extract`. L'hallucination n'inverse rien — le frein reste la **latence sans bénéfice**, pas la fiabilité.
- **Recommandations (provider-neutres) :**
  1. **Faire de HHEM la métrique d'hallucination de référence** dans l'A/B (grounding par embeddings sur chunks réels, robuste au prior et au format de citation). Conserver `halluc`-juge en **signal secondaire**, jamais comme couperet seul.
  2. **Corriger le juge à la source** : injecter le **texte des chunks** dans `JUDGE_PROMPT` (ajouter un placeholder `{context}` et passer `context_chunks` au prompt, pas seulement au booléen `has_context`). Sans cela, sur tout corpus spécialisé, `halluc`-juge restera **structurellement biaisée contre les réponses les plus précises** — donc contre le bras agentique.
  3. **Le format de citation n'est PAS le levier** : le juge n'exploite pas les marqueurs `[n]` (le prompt ne les lit pas). Reformater les citations du skill `generate` n'améliorerait la note du juge **que si** le contexte lui est aussi fourni (rec. 2). Priorité = rec. 2.
  4. **Cibler le résidu réel** : les ~13 cas « réel-probable » sont surtout des échecs de **retrieval** (1 chunk méta remonté) suivis d'une **sur-affirmation** ; pertinent de durcir la règle de hedge/`reject` du bras B quand `context_count`/diversité de sources est faible (plutôt que d'inventer une réf. à partir du code projet, cf. `edge_mh_akk200_filter_oring`).

> _Reproductibilité de cette section : analyse offline depuis la table « Détail par cas » (durable dans ce rapport) + relecture des `Run(trigger=ab_spike)` durables en DB (System `874211ee-1222-4815-acd6-e1e28ca037b1`) — `output_ref` (réponse), `SkillInvocation.semantic_search_v1` (chunks remontés) et `EvaluationScore.claim_audit` (claims étiquetés par le juge). Aucune ré-orchestration ; pas de dépendance à `/tmp` (purgé)._

## Reproduction (in-container)

```bash
# Balayage complet 95 cas, 2 arms (DAG réel pour B), warmup + checkpointing
cat backend/scripts/agentic_chat_spike.py | ssh omnirag-demo "docker exec -i \
  -e SPIKE_RUN_AGENTIC=1 -e SPIKE_BATCH=3 \
  -e SPIKE_JSONL=/tmp/ab_full.jsonl -e SPIKE_OUTPUT=/tmp/ab_full.json \
  -e SPIKE_REPORT_MD=/tmp/ab_full.md -w /app/backend agentium-backend python -"

# Reprise après limite de ressources (idempotent — ne rejoue pas les cas faits)
cat backend/scripts/agentic_chat_spike.py | ssh omnirag-demo "docker exec -i \
  -e SPIKE_RUN_AGENTIC=1 -e SPIKE_RESUME=1 -e SPIKE_BATCH=3 \
  -e SPIKE_JSONL=/tmp/ab_full.jsonl -e SPIKE_OUTPUT=/tmp/ab_full.json \
  -e SPIKE_REPORT_MD=/tmp/ab_full.md -w /app/backend agentium-backend python -"

# Régénérer le rapport depuis les partiels, sans relancer aucune orchestration
cat backend/scripts/agentic_chat_spike.py | ssh omnirag-demo "docker exec -i \
  -e SPIKE_REPORT_ONLY=1 -e SPIKE_JSONL=/tmp/ab_full.jsonl \
  -e SPIKE_REPORT_MD=/tmp/ab_full.md -w /app/backend agentium-backend python -"
```
