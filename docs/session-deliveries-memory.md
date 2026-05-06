# Mémoire de session — livraisons E1.5, E2, E5, E7-lite, Showcase

Document de rattachement : il résume ce qui a été livré dans la ligne de développement
« boucle d’évaluation actionnable → preuves → vitrine », sans remplacer le plan détaillé
dans [`vague-e-plan.md`](./vague-e-plan.md) ni la norme sémantique dans
[`mental-model.md`](./mental-model.md).

## E1 → E1.5 (boucle « game changer »)

**Constat.** E1 « scoring post-run + seuils + UI » était techniquement clos, mais le
cockpit restait passif : peu d’impact opérationnel sans signal humain, remédiation et
apprentissage déterministe.

**Décomposition livrée (E1.5.1 → E1.5.5).**

| Sous-lot | Thème | Livrables clés |
| -------- | ----- | -------------- |
| **E1.5.1** | Feedback persistant | Table `evaluation_feedback`, enregistrement au accept/reject Hypervisor, `GET /evaluation/feedback`, audit |
| **E1.5.2** | Remédiation | `parent_run_id`, `replay_overrides`, `POST /runs/{id}/replay`, `GET /runs/{id}/replays`, bouton RE-RUN (review queue) |
| **E1.5.3** | Analytics RAG | `question_type`, `failed_components`, `topic` sur scores, taxonomie type Giskard, `GET /evaluation/component-health` + `/taxonomy`, UI Quality / filtre composant |
| **E1.5.4** | Adoption | Preset d’évaluation auto-onboardé (`enabled`, `composite_min` migration), opt-out explicite |
| **E1.5.5** | Déterminisme + suggestions | `canonical_answers`, court-circuit chat avant orchestrateur, suggestions actives (LLM + fallback), **APPLY** → replay avec overrides |

**Migrations Alembic de référence :** `016` → `020` (voir noms exacts dans `backend/alembic/versions/`).

**Mental model produit :** System → Run → Evaluation → Decision → Action (fermeture de boucle
documentée dans [`showcase-demo-walkthrough.md`](./showcase-demo-walkthrough.md)).

## E2 — Playwright E2E

**Objectif.** Preuves automatisées sur VM (stack Keycloak + app) pour les flux critiques.

**Livrables.** `@playwright/test`, config `workers: 1`, fixtures auth/API/PDF dynamiques,
scénarios : auth, chat drop-and-ask, HITL (système créé par API), debug step/continue,
réponse canonique déterministe. Voir `frontend-ng/e2e/README.md`.

## E5 — Recommandations proactives

**Objectif.** Sortir les signaux agrégés d’évaluation du seul tableau de bord pour créer des
`Decision(kind=recommendation)` idempotentes (empreinte dans la rationale).

**Livrables.** `recommendations.proactive_service`, `POST /hypervisor/recommendations/generate`,
bouton **SCAN** Hypervisor, tests services + smoke VM.

## E7-lite — checkpoint déploiement / smoke Vague E

**Objectif.** Valider HEAD déployé : migrations jusqu’à `020_canonical_answers`, santé API,
Playwright 7/7, smoke Vague D inchangé côté attentes, frontend build + Nginx sur VM.

**Périmètre explicite.** « E7-full » optionnel si l’on exige un script `smoke_vague_e.sh` dédié
et CI post-déploiement automatisée (`vague-e-plan.md`).

## Showcase workspace

**Objectif.** Tenant `agentium-showcase` cohérent, peuplé, réinitialisable, pour démo par
persona (executive, ops, governance, builder).

**Livrables.** `backend/scripts/seed_showcase_workspace.py` (idempotent avec `--reset`),
`backend/scripts/smoke_showcase_workspace.py`, documentation
[`showcase-workspace.md`](./showcase-workspace.md),
[`showcase-demo-walkthrough.md`](./showcase-demo-walkthrough.md),
[`showcase-gaps.md`](./showcase-gaps.md). Propriétaire showcase cible :
`thibaud.ishacian@datategy.net` (voir options `--owner-email` du seed).

## Documents compagnons (ne pas dupliquer)

| Document | Rôle |
| -------- | ---- |
| [`vague-e-plan.md`](./vague-e-plan.md) | Plan E, journal, détail technique et statuts |
| [`mental-model.md`](./mental-model.md) | Entités canoniques et sémantique produit |
| [`showcase-workspace.md`](./showcase-workspace.md) | Contenu seed, commandes, personas |
| [`production-demo-map.md`](./production-demo-map.md) | Cartographie env, parcours, limites, preuves |

---

_Dernière mise à jour : avril 2026 (alignée sur la branche `demo/agentic` et les livraisons décrites dans `vague-e-plan.md`)._
