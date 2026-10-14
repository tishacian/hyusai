# Amendements demandés au plan DataOps et état de la branche

Ce document accompagne le [plan DataOps d’origine](agentium-dataops-plan.md),
restauré à l’identique de `ad10dbc2`. Il consigne les demandes de cette conversation
et les écarts de l’implémentation initiale `45ccc915`, puis les travaux de reprise.
Le code n’est pas une autorité qui
permet de redéfinir après coup un critère de recette.

## Origine des amendements

Dans cette conversation, l’utilisateur a demandé, avant l’implémentation :

- finir la restructuration puis S0 et la reprise de D0 sur les nouveaux packages ;
- conserver le moteur de préparation, le Flow, son interface et le stockage en parts ;
- ajouter une promesse de service par System, des actifs documentaires/référentiels
  versionnés et un juge typé, avec une approbation humaine gouvernée ;
- repousser Kubernetes éphémère, Spark, D6 et la plupart des connecteurs jusqu’à
  un besoin et un volume mesurés ; conserver Helm pour le déploiement permanent ;
- utiliser le workspace Showcase sans exiger de client pilote, avec un scoring
  de 2 à 3 millions de lignes par jour et plusieurs centaines de pages/images ;
- laisser ensuite narration de côté ; Gemini via OpenRouter sera raccordé plus tard.
- le 14 octobre, faire des connecteurs (D7) une vitrine face aux catalogues de Sim,
  n8n, Dataiku et papAI, avec une solidité comparable au dépôt SFTP ; voir le
  [complément D7](agentium-dataops-connectors.md).

Ces demandes expliquent les extensions au périmètre du document d’origine. Elles
ne prouvent ni leur complétude ni leur conformité : leur recette est distincte.
Les décisions D-1 à D-25 et les règles de fusion restent dans le plan d’origine.
Aucune fusion, modification de VM ou activation de service n’est autorisée par
ce document.

## Plans et contrats distincts

- [Juge typé](agentium-typed-judge-plan.md) : contrat proposé, état du code et
  critères de qualification ; ce document a été écrit pendant l’implémentation,
  pas avant elle. Aucun fournisseur ni corpus réel n’est qualifié.
- [Actifs et promesses](ops/service-contracts.md) et
  [budgets](ops/service-window-budget.md) : contrat de la nouvelle extension,
  incluant responsable, fraîcheur, complétude, revue et reçu vérifiable.
- [Scoring Showcase](agentium-showcase-scoring-contract.md) : recette visée et
  destination Work, qui ne vaut pas intégration à un système client externe.
- [Narration](agentium-showcase-narration-contract.md) : brouillon différé,
  sans activation ni promesse de livraison dans le lot actif.
- [Complément D7](agentium-dataops-connectors.md) : catalogue de connecteurs
  certifiés, en deux catalogues (données, outils) et en vagues C0 à C7. Proposé,
  non implémenté.

## Écarts constatés, à fermer par des preuves

La [revue de la branche](codex-review-dataops-typed-judge.md) conserve les constats
sur `45ccc915`. Son historique ne doit pas être réécrit pour effacer les erreurs.

| Domaine | État et critère restant |
|---|---|
| R0/S0/D0 | Structure reprise et garde-fous en code ; le déploiement, son build-info, HANA vivant et la révocation du token Docker Hub de papAI ne sont pas attestés par les tests locaux. |
| D1a | Reprise : 46 contrats d’étapes fermés, 74 fonctions, typage physique, formules restreintes, sélecteurs et corpus golden indépendant. La couverture des cas métier et toutes les recettes du plan ne sont pas acquises par cette seule couverture du catalogue. |
| D1b | API/Flow repris pour la configuration canonique, sources épinglées, schémas par étape, aperçu récursif, compteurs et profil sur échantillon. Rattrapage des anciens échantillons par tâche DataOps et cache d’aperçu livrés avec tests ciblés. Hook Helm de réconciliation ajouté et testé au rendu ; aucune exécution sur cluster n’est attestée. |
| D2 | Palette des sept opérations, ateliers dédiés, éditeur de formules, historique et conversion SQL livrés. Recettes navigateur mockées FR/EN et suites existantes passées ; elles ne constituent pas une recette contre un backend déployé. |
| D3 | Lecteurs natifs multi-parts, profil borné, téléchargement en flux, retraite sans suppression et purge par identité distincte livrés. Le commit natif delta-rs remplace le journal maison : parts écrites puis commit0 natif sans réencodage, conformément à D-21/§29.3. MinIO réel local et une sortie synthétique de plus de 3 Gio qualifiés avec réservoir final, sous cgroup client 4 Gio/2 CPU. Spark/Unity et la migration d’un bucket de production ne sont pas qualifiés. |
| Actifs/promesses/juge | Extension demandée, implémentée sur la branche et soumise à la revue ; aucun statut de production ni qualification fournisseur ne découle du nombre de tests. |
| Narration | Différée. Catalogue masqué, runtime fermé et absence de seed de parcours tant que le drapeau est désactivé. |
| D4/D5/D6/I1/I2 | Différés par demande explicite ; leur absence reste visible dans le plan d’origine et n’est pas présentée comme une implémentation. |
| D7 | Repriorisé le 14 octobre et précisé par le [complément D7](agentium-dataops-connectors.md). Rien n’est implémenté à ce stade. |

Les suites ciblées du premier lot ne remplaçaient pas une suite complète. Les
rapports de tests, les comparaisons avec la base et les constructions d’images
sont consignés dans le suivi de correction de la revue. Une allocation texte
excessive a également démontré que la limite DuckDB ne suffisait pas à protéger
l'API : `940bc43b` déplace le calcul d'aperçu dans un processus soumis à une
limite système stricte, avec une recette distincte de refus et de terminaison.
Les mesures du premier lot restent historiques. La reprise possède désormais
ses propres preuves de suite complète, de stockage MinIO sous cgroup et de
construction d'images, avec leurs révisions et limites de périmètre. Sur
`bd724044`, les **8 864 tests réussis et 145 ignorés** ne ferment pas tous les
critères du plan. Les mesures OCI finales donnent **3 567 Mio pour le backend**
et **4 676 Mio pour le worker**, comparables à la comptabilité Docker classique ;
ces valeurs dépassaient les plafonds numériques de 1 400 et 1 760 Mio alors en
vigueur.
Le relevé VM du 14 octobre établit toutefois une comptabilité différente avec
Docker 29/containerd : les images de production mesurent 1 356 et 1 709 Mio ;
les candidates y étaient absentes et leur budget **non qualifié**. Les tailles
OCI décompressées ne permettent donc pas de conclure à un dépassement sur la VM.
La [réconciliation des mesures](dataops-release-blockers-2026-10-14.md) fait foi
sur ce point. Un relevé VM ultérieur, transmis par l'utilisateur pour `6dcb0d48`,
mesure 1 412 Mio pour le backend et 1 765 Mio pour le worker : dépassements de
12 et 5 Mio. Après explication de cet écart, l'utilisateur autorise les plafonds
**1 480 / 1 850 Mio**, environ 5 % au-dessus des tailles mesurées. Les autres
plafonds restent inchangés, dont ml-ts à 1 240 Mio pour une mesure de 1 229 Mio.
Les défauts du build VM et les notes de livraison sont actualisés dans `cd015ed6`.
L'utilisateur confirme ensuite le recontrôle VM des images `6dcb0d48` existantes
avec ces plafonds : **code de sortie 0**. Le blocage de budget est levé pour ce
périmètre, sur la foi de ce compte rendu, sans nouveau bundle SSH brut. Aucune
bascule de conteneur ni activation HANA n'est effectuée. Voir le suivi pour le
benchmark et ses limites.

Le 14 octobre, l'utilisateur choisit la démonstration explicite pour HANA
Showcase : `demo_mode=true`, chiffrement et vérification TLS conservés, écritures
désactivées. La décision est prise et le contrôle de budget est passé ; son
activation et sa recette restent à effectuer lors de la livraison.
Le formulaire conserve désormais ces
paramètres, et le test de connexion reste un test HANA réel. La
[recette locale](evidence/hana-showcase-demo-2026-10-14/README.md) ne vaut pas une
activation sur la VM ni une qualification de l'instance SAP.

Le [suivi des corrections](codex-review-dataops-typed-judge-followup.md) consigne
les tests réellement exécutés et les qualifications encore bloquées.

## Références après la restructuration

Les numéros de ligne du plan original sont historiques. Cette table actualise
les points d'entrée sans modifier la spécification ; les noms de fonctions
restent préférables aux numéros de ligne.

| Référence historique | Chemin actuel, relatif à la racine du dépôt |
|---|---|
| `wrappers.py`, fonctions et `_REGISTRY` | `backend/app/services/skills_registry/wrappers/skills.py` et `wrappers/registry.py` |
| `dag.py`, fusion et configuration du graphe | `backend/app/services/run_engine/dag.py` ; `_merge_predecessor_outputs`, `_GRAPH_OWNED_BLOCKS` |
| `execution_contract.py` | `backend/app/services/run_engine/execution_contract.py` ; la compilation publiée est dans `backend/app/services/flow_contracts.py` |
| `dag_validator.py`, `data_prep_issues` | `backend/app/services/chains/dag_validator.py` et `backend/app/services/dataops/flow.py` |
| HANA | `backend/app/api/v1/endpoints/hana.py`, `backend/app/services/connectors/hana/service.py` et `network_policy.py` |
| Spec, compilation, runner DataOps | `backend/app/schemas/data_prep.py`, `backend/app/services/dataops/{compiler,steps,operations,preparation,sql_execution}.py`, `backend/app/resources/dataops_runner.py` ; tâches dans `backend/app/workers/tasks.py` |
| Dataset, `RecipeExecution`, stockage | `backend/app/models/{tabular,recipe}.py`, `backend/app/services/tabular_datasets.py` et `backend/app/services/dataops/storage.py` |
| Migration des actifs/promesses | `backend/alembic/versions/126_service_contracts.py` après `125_retrieval_bench_runs` ; elle ne remplace pas la migration future `compute_runs` de D4 |
| Déploiement et worker permanent | `scripts/agentium-vm-deploy.sh`, `ops/helm/agentium/templates/{worker-dataops,dataops-watchdog}.yaml`, `ops/scripts/check-k8s-scaffold.sh` |

Le découpage de modules prévu par D1a reste une cible ; tous les noms du plan ne
correspondent pas à un module livré. Le nouveau Job Helm `catalog-reconcile.yaml`
lance la réconciliation après `migrate.yaml` (poids 10 après 5). Le rendu est
vérifié ; son exécution en déploiement reste à qualifier.

Le [guide de préparation](agentium-dataops-guide.md), le
[runbook de stockage](agentium-dataops-storage.md) et les
[preuves de reprise](evidence/dataops-completion-2026-10-13/) décrivent ces ajouts
sans modifier les critères du plan ni les constats historiques de la revue.
