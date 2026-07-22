# Cartographie production / démo Agentium

Ce document décrit **ce qui est disponible** sur l’environnement de référence démo,
**comment le prouver**, les **parcours** recommandés et les **limites** connues. Il complète
[`demo-scope.md`](./demo-scope.md) (positionnement générique) et
[`showcase-workspace.md`](./showcase-workspace.md) (tenant vitrine).

---

## 1. Environnement de référence

| Élément | Démo typique | Note |
| ------- | ------------- | ---- |
| **URL app** | `https://agentium.papai.ai` (exemple VM / démo) | Remplacer par l’URL réelle du déploiement. |
| **Auth** | Keycloak (realm client, client confidentiel backend) | E2 et smoke utilisent des comptes de test dédiés. |
| **Backend** | FastAPI `/api/v1/*` | Santé : `/`, `/openapi.json`. |
| **Données** | Postgres + migrations Alembic jusqu’à **020** (canonical answers) | Vérifier `alembic current` après déploiement. |

---

## 2. Ce qui est « disponible » (fonctionnel E1.5 / E5 / showcase)

Les capacités ci-dessous sont **câblées** backend + UI (ou endpoint seul pour API-first),
avec traçabilité audit là où prévu.

| Capacité | Indication produit | Preuve rapide |
| -------- | ------------------ | ------------- |
| Scoring post-run + presets | Quality, presets `/presets/evaluation` | Runs avec `evaluation_scores`, seuils modifiables |
| Review queue | Steering, filtre composant | File d’attente + RE-RUN + APPLY |
| Feedback humain | Accept/reject sur décisions review | Table / liste feedback + audit |
| Replay / lineage | Run detail, replays | `parent_run_id`, historique replays |
| Santé composants RAG | Dashboard qualité | `GET /evaluation/component-health` |
| Réponses canoniques | Chat bypass + page gouvernance | `GET/POST/DELETE /evaluation/canonical-answers` |
| Recommandations proactives | Hypervisor **SCAN** | `POST /hypervisor/recommendations/generate` |
| Audit | Governance | `GET` audit avec `{ logs, total }` |
| Connecteur SharePoint (fondation) | UI `/connectors/sharepoint` | Jobs / audits ; démo showcase voir bannière guest-link |

**Gaps documentés** (non bloquants démo selon contexte) : [`showcase-gaps.md`](./showcase-gaps.md).

---

## 3. Parcours (preuves humaines)

### 3.1 Parcours scripté vitrine

Suivre [`showcase-demo-walkthrough.md`](./showcase-demo-walkthrough.md) sur le workspace
`agentium-showcase` (seed idempotent, sans reset destructif).

### 3.2 Parcours automatisés

| Preuve | Commande / lieu | Attendu |
| ------ | ----------------- | ------- |
| **Smoke API showcase** | `python -m scripts.smoke_showcase_workspace` (voir [`showcase-workspace.md`](./showcase-workspace.md)) | Tous les checks PASS (login, systems, runs, recommandations, etc.) |
| **E2E Playwright** | `frontend-ng`, `npx playwright test` sur VM Node ≥ 18 | 7 tests / 5 flux (voir `e2e/README.md`) |
| **Smoke Vague D** | Script shell historique (`SMOKE_RUN_SSE=0` etc.) | 28 PASS attendus (inchangé selon plan E7-lite) |
| **Tests unitaires backend** | `pytest` dans venv | Suite services / modèles alignée CI |

### 3.3 Parcours « compliance »

- Export ou consultation **audit** avec filtres.
- Démontrer **canonical answer** : même question → même réponse, `hit_count` qui augmente.
- Montrer **idempotence** des recommandations : double **SCAN** ne duplique pas les décisions (empreinte).

---

## 4. Limites (à dire en démo)

- **Orchestrateur** : certaines routes exigent un orchestrateur initialisé ; le hit **canonical** est conçu pour court-circuiter avant l’orchestrateur (comportement voulu pour déterminisme).
- **Ingest RAG** : le seed peut utiliser `--skip-ingest` ; sans index vectoriel, le RAG peut être dégradé alors que la **story** évaluation / décision reste valide.
- **SharePoint guest** : démo peut être simulée (job showcase) sans sync réelle OAuth complète (**E4.3**).
- **E0 sécurité** : rotation secrets / DKIM / coffre — voir [`vague-e-plan.md`](./vague-e-plan.md) ; condition d’**ouverture client** réelle.

---

## 5. Carte des documents de vérité

| Besoin | Document |
| ------ | --------- |
| Plan de release et journal E | [`vague-e-plan.md`](./vague-e-plan.md) |
| Sémantique produit complète | [`mental-model.md`](./mental-model.md) |
| Identité courte | [`agentium-identity-card.md`](./agentium-identity-card.md) |
| Mémoire livraisons session | [`session-deliveries-memory.md`](./session-deliveries-memory.md) |
| Démo « for dummies » | [`showcase-demo-walkthrough.md`](./showcase-demo-walkthrough.md) |

---

_Mise à jour indicative : avril 2026._
