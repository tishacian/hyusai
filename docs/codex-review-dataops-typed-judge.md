# Revue Codex — `codex/dataops-typed-judge` (`45ccc915`)

Revue du 13 octobre 2026, à traiter sur cette branche. Ce document est la liste de corrections. Il ne remplace pas `docs/agentium-dataops-plan.md`.

## Règles pour l'agent

- La spécification est le plan **tel qu'il est sur `demo/agentic` (`ad10dbc2`)**, identique à `docs/dataops-plan-databricks`. Ne pas le réécrire pour qu'il décrive le code.
- Le commit `45ccc915` remplace les §0 à §4 du plan et pose la règle « en cas de différence, le code gagne ». C'est un défaut. Restaure le fichier depuis `ad10dbc2` :

  ```bash
  git checkout ad10dbc2 -- docs/agentium-dataops-plan.md
  ```

  Les écarts entre le code et ce plan restent des écarts. On les consigne dans ce document, pas dans le plan.
- Ne pas fusionner vers `demo/agentic`. Ne pas déployer. Ne pas lancer `terraform apply`. Ne pas imprimer de secrets.
- Un correctif est fini seulement quand le test cité passe, sur cette branche, et qu'il passe aussi la comparaison avec `ad10dbc2` quand c'est demandé.
- Le parent de `45ccc915` a le même arbre que la prod `ad10dbc2`. Tout test vert sur `ad10dbc2` et rouge ici est introduit par la branche.

## Verdict

Non fusionnable en l'état.

La sécurité tient : HANA S0, liste blanche des formules, sels de hachage, isolation par workspace, aucune fuite de secret dans le commit. Le reste ne passe ni la suite, ni le plan, ni un déploiement.

Vérifié en faisant tourner les tests, pas d'après le message de commit :

| Contrôle | Résultat sur `45ccc915` |
|---|---|
| Tests infra | 2 échecs, 902 réussites |
| Suite backend complète | 11 échecs, 8 413 réussites |
| Conformité | OK |
| `npm run test:unit` (frontend-ng) | 2 165 / 2 165 |
| `check-k8s-scaffold.sh` | Échec ici, succès sur `ad10dbc2` |
| Helm lint + template (5 fichiers de valeurs) | OK |

Les 13 échecs (2 infra + 11 suite) passent tous sur `ad10dbc2`. Aucun n'est un test ML instable. L'affirmation du commit (« un échec de catalogue ML préexistant ») ne se reproduit pas : les 100 tests ML et catalogue passent sur `ad10dbc2`. Le seul échec de catalogue ici est `test_surface_catalog`, vert sur la base.

Le venv partagé n'a pas `sqlglot`, `deltalake`, `arro3-core`. Sans eux, `import app.main` plante, parce que `compiler.py` importe `sqlglot` au chargement. `deprecated` (dépendance de deltalake) n'est pas épinglé.

## Conformité au plan

Fait et conforme : S0 (écritures HANA admin + drapeau, Skill en lecture seule, plus de mot de passe plateforme, TLS vérifié, codes d'erreur fermés, garde SSRF en mode `report`), D0 (SQL sur la file `dataops`, `PDEATHSIG`, `placement` dans `_PUBLIC_LINEAGE_KEYS`), cœur D3 (une table Delta par version, drapeau `dataops_write_delta_enabled` à faux par défaut).

Écarts à garder visibles, pas à effacer en éditant le plan :

| Lot | Constat |
|---|---|
| D0 #1 | `check-k8s-scaffold.sh` attend `cpu,recipes,dataops` sur le worker unique. Le chart rend `cpu,recipes` et `worker.yaml` refuse `dataops` (Deployment séparé). Le script échoue. `docs/ops/agentium-kubernetes.md` dit encore `cpu,recipes`. |
| D1a | Le contrat de spec s'écarte du §5 : pas de `id` / `enabled` / `comment`, 100 étapes au lieu de 200, regex de port `{0,63}` au lieu de `{0,30}`. Le compilateur émet des f-strings, pas des arbres sqlglot. `QUALIFY` est utilisé (`compiler.py`, `steps.py`) alors que le plan veut des formes portables. `sort` n'a pas le départage `__row_fp`. |
| D1a formules | `strftime`, `date_trunc`, `strpos`, `regexp_matches` sont dans la liste blanche et toujours refusées : sqlglot les renomme. |
| D1a types | `preview.py` type via `schema_json.dtype`. Le §7 l'interdit : le type vient du pied de page Parquet. |
| D1b | Pas de validateur `data_prep_issues` à la publication. `/dataops/catalog`, `/compile`, `/preview` ignorent `dataops_enabled`. |
| D2 | Marqué implémenté dans le plan réécrit. En code : un formulaire générique (`data-prep-editor.component.ts`, 72 lignes). Pas de palette, pas d'ateliers, pas d'e2e. |
| D3 | `materialize` réécrit chaque table Delta en un seul Parquet. Pas de téléchargement `/datasets/{id}/download`, pas de purge MinIO. |
| D4 à D7, I1, I2 | Absents. Le plan réécrit les passe en « différés ». |
| Hors plan | Assets gouvernés, promesses de service, juge typé, calibration, narration, scoring (~9 000 lignes), migration 126, 32 endpoints. `narration.py` (738 lignes) et le skill `narration_run_v1` sont livrés alors que la narration est dite différée. |

`docs/agentium-typed-judge-plan.md` décrit le code livré. Ce n'est pas un plan antérieur. Ne pas le présenter comme la spécification d'origine.

## Bloquant

### 1. Remettre le plan d'origine

`git checkout ad10dbc2 -- docs/agentium-dataops-plan.md`, puis vérifier que le fichier est identique à `ad10dbc2` (`git diff ad10dbc2 -- docs/agentium-dataops-plan.md` vide). Ne pas réintroduire la règle « le code gagne ». Ne pas recréer les lots R0, C0, A1, P1, M1, J, W1, N1 dans ce plan.

### 2. Rendre la suite verte

Chaque ligne est un échec introduit par la branche.

| Test | Correction |
|---|---|
| `test_demo_constraints_cover_declared_requirements[giskard]`, `test_giskard_venv_only_overrides_what_giskard_pins_differently` | Épingler `sqlglot`, `deltalake`, `arro3-core` et `deprecated` dans `constraints-demo-giskard.txt` et `constraints-demo-app.txt`. |
| `test_surface_catalog.py::test_endpoint_catalog_covers_the_real_api_router` | Déclarer les 32 endpoints (dataops, service-contracts, typed-calibration) dans le catalogue de surface. |
| `test_public_bench.py::test_migration_125_extends_the_single_head` | Le faire suivre la tête réelle (`126_service_contracts`). L'identifiant fait 21 caractères, `down_revision` est `125_retrieval_bench_runs` : c'est bon, le test doit suivre. |
| `test_ecommerce_composition.py` (2 tests) | Les nœuds SQL font un `send_task` vers RabbitMQ (`skills.py`, file `dataops`) et obtiennent `Connection refused`. Adapter les tests au mode eager, comme les autres skills. |
| `test_dataops_preparation.py::test_delta_legacy_reader_and_atomic_split`, `test_dataops_published_pipeline.py`, `test_stream_score_worker.py` (2) | `storage.py` : `DeltaTable.file_uris()` renvoie des chemins réels, `delta_root` ne l'est pas. `relative_to` casse quand le répertoire temporaire est un lien (`/var` → `/private/var` sur macOS). Résoudre `delta_root` avant la comparaison. |
| `test_dataops_showcase.py::test_benchmark_uses_real_preparation_and_native_model` | Même correction de chemin. Le prélèvement RSS renvoie 0 hors Linux : marquer le test Linux-only. |

Critère : la suite infra et la suite complète n'ont plus aucun échec introduit par la branche. Relancer un échec seul ne suffit pas s'il reste rouge dans la suite.

### 3. Aligner le contrôle Kubernetes

`check-k8s-scaffold.sh` doit accepter le worker `cpu,recipes` **et** le Deployment `dataops` séparé. Il doit continuer à échouer si `dataops` est ajouté aux files du worker unique. Mettre `docs/ops/agentium-kubernetes.md` au même endroit. Critère : `ops/scripts/check-k8s-scaffold.sh` passe sur cette branche et passe encore sur `ad10dbc2`.

### 4. Mesurer les images avant tout changement de budget

Estimation, pas une construction : deltalake pèse ~52 Mo sur les roues Linux, ~56 Mo avec les autres paquets. Les quatre images installent `requirements.txt`.

| Image | Taille actuelle / budget | Estimation |
|---|---|---|
| backend | 1 356 / 1 400 Mo | ~1 410, au-dessus |
| worker | 1 709 / 1 760 Mo | ~1 765, au-dessus |
| ml-ts | 1 172 / 1 240 Mo | ~1 228, dans le budget |

Construire les images et mesurer avec `scripts/agentium-image-budget.sh`. Si un budget saute, le relever explicitement dans les notes de version, ou alléger les dépendances. Ne pas désactiver le contrôle.

### 5. Ne pas déployer HANA Showcase en l'état

`agentium-showcase` est le seul workspace HANA. Il a un mot de passe stocké, `encrypt=true`, et ni `ssl_validate_certificate` ni `demo_mode`. Avant, le code forçait `sslValidateCertificate=False` et repliait sur des données de démo. Ici, le certificat est obligatoire et le repli est supprimé : la démo répondrait `HANA_CONNECTION_FAILED`.

Ne pas choisir à la place de l'utilisateur entre valider le certificat, poser `demo_mode`, ou une exception TLS. Laisser le durcissement. Documenter le blocage dans la réponse de lot. Retirer `HANA_CONNECTOR_PASSWORD` du bundle n'est à faire qu'au déploiement, pas dans ce correctif : la clé est ignorée par le nouveau code, `HANA_CONNECTOR_FERNET_KEY` sert encore.

## Important

6. **Timeout RabbitMQ.** `consumer_timeout` est à 20 min (`compose.agentium.yml`), sous le défaut de 30 min de RabbitMQ 4.1. `task_acks_late` est global, `subflow_parent_resume` a une limite de 1 830 s, et des tâches d'évaluation n'ont pas de limite. Le mettre au moins au-dessus de la plus longue tâche `acks_late` (≥ 31 min), ou retirer la surcharge. `up` ne recrée pas RabbitMQ : l'écrire dans la doc.

7. **Drapeaux.** Faire respecter `dataops_enabled` sur `/dataops/catalog`, `/compile`, `/preview`. Faire respecter `service_contracts_enabled` sur les routes et sur les entrées de navigation « Data preparation » et « Service deliveries » (`navigation.catalog.ts`). Aujourd'hui elles s'affichent alors que la fonctionnalité répond 404.

8. **Préparation.**
   - Rendre réellement utilisables `strftime`, `date_trunc`, `strpos`, `regexp_matches`, ou les retirer de la liste blanche.
   - Typer depuis le pied de page Parquet, pas depuis `schema_json.dtype`.
   - Ajouter le validateur de publication `data_prep_issues`.
   - Ajouter un corpus golden `tests/dataops/golden/`, au moins 3 cas par étape.

9. **Contrats de service.** `publish_window` repasse le `lease_token` lu en base (`service_contracts.py`) : le contrôle de bail est vide. Exiger le bail ou la barrière de l'appelant. Le downgrade de la migration 126 efface contrats et reçus sans garde : suivre le modèle de la migration 108.

10. **Dump.** Le dump d'avant migration recopie des préfixes de workspace entiers, et un échec est fatal (ce n'était plus le cas). `andritz` a 150 Go de collections de connaissances et 0 dataset, pour 129 Go libres sur `/` de la VM. Borner le périmètre (workspaces qui ont des `asset_versions`, ou exclure `knowledge-collections` tant qu'aucun asset ne les référence) et ajouter un contrôle d'espace disque avant la copie. `test_data_plane_dump.py` a été inversé pour accepter cette copie : le test doit décrire le nouveau périmètre borné, pas « on copie tout ».

11. **Narration.** Tant que N1 n'est pas décidé : retirer `narration.py` du chemin actif et ne pas semer `narration_run_v1`, ou les garder derrière un drapeau désactivé par défaut et absents du catalogue tant que le drapeau est faux.

## Souhaitable

12. Annuler le bruit `Optional` → `X | None` et le reformatage des entrées non touchées dans `skills.py`, `dag.py`, `seed.py`. Découper `steps.py` (~995 lignes) et `typed_judge.py` (~1 015). Corriger la docstring de `dataops_runner.py` (elle dit que les entrées sont lues à la demande ; le code fait `CREATE TEMP TABLE … AS SELECT *`). Retirer `QUALIFY`. Ajouter `__row_fp` au `sort`. Ajouter `prep` à `_PUBLIC_LINEAGE_KEYS`.

## Déploiement, pour mémoire

À ne pas exécuter dans ce lot. Utile pour ne pas casser la prod plus tard.

- Les nœuds `_sql_transform_v1` partent toujours sur la file `dataops`. Sans le worker, chaque nœud SQL de Nawa et Showcase attend jusqu'au timeout. Le worker `agentium-worker-dataops` (4 Go, 2 CPU, concurrence 1) suit le modèle de `agentium-worker-recipes`.
- Aucune variable nouvelle n'est obligatoire : tout est désactivé par défaut. Clés optionnelles : `DATAOPS_ENABLED`, `DATAOPS_WRITE_DELTA_ENABLED`, `DATAOPS_*`, `CELERY_DATAOPS_QUEUE`, `ML_SCORE_STREAMING_ENABLED`, `ML_SCORE_STREAMING_MAX_ROWS`, `SERVICE_CONTRACTS_ENABLED`, `NARRATION_*`, `HANA_WRITES_ENABLED`, `HANA_NETWORK_POLICY_MODE`, `HANA_ALLOWED_HOSTS`, `HANA_ALLOWED_CIDRS`, `HANA_ALLOW_INSECURE_TLS`, `HANA_INSECURE_TLS_ALLOWED_HOSTS`, `AGENTIUM_DATAOPS_MEMORY`, `AGENTIUM_DATAOPS_CPUS`, `AGENTIUM_DATAOPS_CONCURRENCY`.
- La migration 126 est additive. Les noms de tâches Celery existants ne changent pas. Trois tâches nouvelles, toutes avec `queue=dataops` : `agentium.dataops_sql_execute`, `dataops_prepare`, `dataops_score`.
- Trois skills nouveaux (`data_prep_v1`, `evaluate_v2`, `narration_run_v1`) feront diverger `catalog-check` jusqu'à `catalog-apply`.
- `agentium-vm-build.sh` ne construit que depuis `demo/agentic`. Cette branche doit être fusionnée avant toute construction.

## Sécurité déjà vérifiée, à ne pas défaire

- Compilateur de préparation : identifiants quotés, littéraux échappés, paramètres numériques bornés. Les sondes `$dp_salt_0`, `$1`, `getvariable`, sous-requêtes, `read_csv`, `COLUMNS()`, `nextval` sont refusées.
- Runner SQL : `enable_external_access=false`, `lock_configuration`, limites mémoire / CPU / fichiers, `PDEATHSIG`. Le runner ne se connecte pas à la base.
- Aperçus : DuckDB scellé, timeout, plafond de 16 Mo. Ils contournent aujourd'hui `dataops_enabled` (point 7).
- HANA : codes fermés, TLS par défaut, exception TLS seulement avec drapeau global et hôte exact, DNS épinglé, `SET TRANSACTION READ ONLY`.
- Juge : preuves citées comme données non fiables, pas d'outils, schéma strict, citations et images revérifiées, pas de repli, disposition toujours `review`. Pas de masquage PII avant l'envoi au modèle : ça repose sur la politique de route du Model Plane. Ne pas le présenter comme un masquage.
- `publish_window` : le trou de bail est le point 9, pas un acquis.

## Hors périmètre de preuve

Pas vérifié : `alembic upgrade` / `downgrade` sur un vrai PostgreSQL, une construction d'image, `build:prod`, un HANA réel, une qualification S3/PG, le benchmark de 3 millions de lignes annoncé en 271 s. Ne pas réaffirmer ces preuves tant qu'elles n'ont pas été refaites.
