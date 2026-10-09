# Luma : implémentation, essais et activation restante

État du **9 octobre 2026**. Les quatre compléments produit génériques sont
implémentés et testés localement. Dans `agentium-showcase`, les datasets ont
été importés, sept versions de modèles sont prêtes et des prédictions ont
réellement été exécutées par les API d'Agentium. **Le nouveau Flow et la release
Work restent préparés, sans activation.**

La [preuve JSON compacte](fixtures/showcase_learning/live_evidence_2026-10-09.json)
conserve les IDs, états, métriques retenues et résultats des appels. Elle est
extraite des réponses de la session, sans secrets, aperçu de dossiers, courbes
complètes ni artefacts ML. Les chiffres ci-dessous portent sur des **données
synthétiques de démonstration**, pas sur une activité commerciale réelle.

## Capacités produit livrées

| Complément générique | Résultat utilisable dans une configuration Work | Documentation |
| --- | --- | --- |
| Contrat de prédiction | Cible, type de prédiction, classe positive, unité, bandes, version et provenance configurables ; validation du modèle attendu. | [Contrat de prédiction](../../work-prediction-contract.md) |
| Séries temporelles | Lecture bornée d'un dataset produit par l'action publiée, graphique historique/prévision et intervalle, états vide/refusé/partiel et provenance. | [Séries temporelles Work](../../agentium-work-timeseries.md) |
| Organisation MLOps | Distinction Systems métier/opérations modèle, navigation modèle → Flows consommateurs publiés ; aucun propriétaire exclusif ou coût réattribué par inférence. | [Portefeuille Model Operations](../../agentium-model-operations-portfolio.md) |
| Catalogue MLOps | Capability universelle `model_operations`, découverte et inspection des deux Skills de surveillance/réentraînement, curation et garde humaine conservées. | [Catalogue et réconciliation](../../agentium-model-operations-catalog.md) |

La navigation des pages déclarées dans la release est également réutilisable
par les hôtes Work spécialisés. Le studio des réclamations peut ainsi rejoindre
les pages **Charge** et **Amélioration**, avec des liens et titres issus de la
configuration publiée.

## Données réellement préparées

Le [générateur et ses contrôles](fixtures/showcase_learning/README.md) produisent
une histoire commune, bornée au **9 octobre 2026 à 00:00 UTC** :

- **4 573 lignes d'apprentissage** après exclusion des résultats qui n'étaient
  pas encore disponibles à la coupure chronologique ; six variables initiales
  pour le modèle SLA, langue réservée aux comparaisons de groupes.
- **1 433 dossiers de test chronologique** tenus à part, distincts des dossiers
  de présentation et du benchmark humain.
- **420 jours de volume quotidien**, jusqu'au 8 octobre inclus, cohérents avec
  les dossiers synthétiques.
- **480 messages FR/EN non étiquetés**, importés et prêts pour un futur parcours
  LLM → revue humaine → apprentissage. Aucune revue n'est présumée.

Les datasets prêts sont :

| Usage | ID | Version / lignes |
| --- | --- | --- |
| Apprentissage SLA retenu | `e1141f15-820e-46e5-87f8-9c6f3dc9a430` | v2 / 4 573 |
| Durée de résolution | `4b75d695-63d0-448b-8ec2-663aa2567681` | v1 / 4 573 |
| Segmentation numérique | `b2280d68-9fb2-43e9-abbf-7e51b2126cca` | v1 / 4 573 |
| Volume quotidien | `1268f620-0608-4a56-b095-0143e6e213e4` | v1 / 420 |
| Messages à qualifier | `a58c4067-1eea-48d3-bcda-e8340fcef74e` | v1 / 480 |

Le dataset SLA **v2** est celui utilisé par les deux nouveaux modèles : neuf
colonnes, sans `resolution_hours`. La première version importée est conservée
comme historique, mais ne sert pas à ces fits. Le manifeste des fixtures est
une preuve de génération ; les réponses API conservées dans l'inventaire sont
la preuve des imports.

## Modèles prêts et résultats observés

Sept versions sont prêtes dans Model Center, réparties sur six lignées.
Les métriques du tableau sont les résultats de test interne ou de backtest
calculés à l'entraînement ; le test chronologique externe SLA suit séparément.

| Modèle | ID | Résultat retenu |
| --- | --- | --- |
| SLA calibré v1 | `17331ddf-7811-42e1-8e0f-c8dc75dd3541` | AUC interne 0,820671 ; calibration sigmoid sur 686 lignes ; seuil Youden 0,486915. |
| Challenger SLA v2 | `0c93ef17-3241-43bd-93dc-cc0d9c5524e1` | AUC interne 0,820925 ; cinq essais de tuning, trois folds, budget 60 s ; non promu. |
| Volume naïf saisonnier | `afa061f3-a36d-4e75-901f-85df6a7a22f0` | MAE 3,976 dossiers/jour ; MASE 0,9383. |
| Volume classique | `b79ed3b2-3f2e-411a-a2e4-14aeaa78699b` | MAE 2,189 dossiers/jour ; MASE 0,5162. |
| Volume Chronos | `ec5436b1-8233-4e06-9912-5bc9956c96f3` | MAE 1,712 dossiers/jour ; MASE 0,4005 ; modèle de fondation figé. |
| Durée calendaire de résolution | `e7429b0c-98cd-4fe0-85d8-f57ca661fb1b` | R² 0,2717 ; MAE 29,73 h ; intervalles conformes configurés. |
| Quatre segments numériques | `513f0c17-baef-4a67-95da-7453d9593f14` | Silhouette 0,3277 ; stabilité ARI moyenne 0,5935. |

Les trois modèles de volume utilisent 420 jours et trois fenêtres de backtest
de 28 jours, soit 84 points. Leurs résultats permettent une comparaison sur
ce scénario synthétique. La durée calendaire ne mesure pas le travail humain ;
les segments restent exploratoires et ne donnent aucun droit de remboursement.

### Test externe SLA et décision de version

Les deux versions ont répondu sur les **mêmes 1 433 dossiers réservés**, via
**30 appels réussis**, quinze par version, avec au plus 100 lignes par appel
(dernier lot : 33). Cela représente 2 866 lignes scorées. Les premières
requêtes trop volumineuses ont reçu **HTTP 422 avant prédiction** ; elles ne
sont pas comptées comme exécutions réussies.

| Version | AUC externe | Brier | F1 au seuil servi |
| --- | ---: | ---: | ---: |
| v1 | 0,8216039 | 0,1708562 | 0,7401575 |
| v2 | 0,8219026 | 0,1707639 | 0,7433881 |

L'écart d'AUC est d'environ **0,00030**. Aucun test d'incertitude ou résultat
métier ne démontre une amélioration significative. Le plan de démo conserve
**v1 épinglée** ; v2 reste un challenger à examiner. Les journaux techniques de
ces appels ne constituent ni une revue humaine des labels ni des dossiers
traités par le System métier.

### Essais de prévision

- **Chronos : HTTP 200**, 28 points du 9 octobre au 5 novembre 2026, intervalle
  demandé à 80 %, durée technique rapportée 1 833,2 ms. Prédiction journalisée
  `f3259a13-5cf4-456a-bfc6-5a7f01d1a672`.
- **Classique : HTTP 504**, `ML_FORECAST_TIMEOUT` après 30 secondes. Le modèle
  reste `ready`, mais cet essai de serving n'est pas validé ; le délai reste
  à diagnostiquer. Un entraînement réussi ne prouve pas un appel de prévision
  réussi.

Aucune observation future n'a été attachée pour fabriquer une couverture ou
un résultat de monitoring. Les intervalles et les erreurs du backtest ne sont
pas des mesures de performance future.

## Configuration prête, activation restante

Le [plan versionné](fixtures/showcase_learning/live_learning_plan.json) et sa
[revue locale](fixtures/showcase_learning/live_learning_plan.review.json)
préparent **24 nodes, 25 edges et trois entrées** sur le System métier Luma
existant : enquêter, recalculer la file, prévoir la charge. Les pages Work sont
`dossier`, `charge`, `amelioration`. Le Flow et les pages passent les validations
locales ; cette preuve n'est pas un reçu de publication.

Le chemin cible reste : **PostgreSQL → DataOps → ML → enquête agentique et
OmniRAG → validation humaine → reçu → Impact**, avec la prévision sur une entrée
séparée. Les opérations d'apprentissage gardent leur propre cadence.

Suivre le [runbook d'activation](fixtures/showcase_learning/ACTIVATION.md) après
déploiement opérateur : réconciliation du catalogue, contrôle des empreintes
courantes, revue du plan, application et vérification depuis Work. Le plan
conserve les autorités du Flow publié, du draft et de la release observés ;
il doit être recalculé si ces références ont changé. Un Flow inchangé est
refusé avant mutation ; ce chemin ne sert pas aux mises à jour app-only.

Restent à effectuer après publication : recette live depuis l'application,
import documentaire des nouveaux éléments de campagne/capacité, revue des
messages puis entraînement texte/distillation/MiniLM, configuration des
nouvelles politiques de monitoring et du shadow, collecte ultérieure des
observations éligibles. Aucun de ces résultats n'est annoncé comme acquis ici.
Les hypothèses financières restent explicites ; aucun ROI humain réalisé n'a
été mesuré par ces essais ML.

## Qualification de cette livraison

Première campagne sur les compléments locaux avant intégration du commit
distant `8ab77d7f` :

- Backend : **278 tests**, puis **33 smoke tests** après format/imports ;
  **13 tests composition**, **1 régression d'atomicité**, **12 tests fixtures**.
  Ces campagnes se recouvrent : ne pas additionner leurs nombres comme un
  inventaire de tests distincts.
- Frontend : **2 089/2 089 tests unitaires** sur la passe finale. La première
  passe était à 2 088/2 089 ; le token de taille de texte absent a été corrigé et les
  **11 tests de contraste** passent.
- Navigateur local strict, API simulées : **8 scénarios** sur desktop sombre FR,
  desktop clair EN et mobile 390 px ; navigation, clavier, erreurs, dataset
  vide/partiel, configuration Studio et contraste. Aucun problème Axe relevé
  sur les trois variantes runtime testées. Les captures ont été inspectées.
- Build optimisé de production : **réussi**, avec inlining des polices
  temporairement désactivé pour le proxy de l'environnement ; `angular.json`
  restauré ensuite.
- Ruff, format, conformité produit et détection de secrets passent sur les
  fichiers backend contrôlés. Les avertissements de tests connus concernent
  SQLAlchemy/MLflow et une coroutine d'évaluation non attendue dans les tests
  HITL.

Après intégration de `8ab77d7f`, les conflits de catalogue, de dictionnaire, de
liste de tests et de serving ont été résolus en conservant les fonctionnalités
Hugging Face et la provenance des prédictions Work. Nouvelle campagne :

- **2 104 tests unitaires frontend passent**, ainsi que i18n, chrome et liens.
- **180 tests backend passent** : 29 composition/catalogue/portefeuille et
  151 prédiction/provenance/triage/datasets/autorisation/migration de schéma.
- **12 tests HF optionnels restent ignorés** : six d'activation faute de runtime
  ONNX et six de migration d'artefacts faute de Sentence Transformers dans le
  venv local. La migration Alembic 123 est testée ; le chargement des artefacts
  dans les workers de production reste un contrôle de déploiement.
- **8 scénarios navigateur passent à nouveau** après intégration, avec API
  simulées. Build de production optimisé réussi dans les mêmes conditions de
  polices ; configuration restaurée. Tous les hooks appliqués aux fichiers de
  la livraison passent, sauf `pre-commit-update` volontairement exclu car il
  actualise les versions des outils.

Les appels API live prouvent les imports, entraînements et prédictions décrits.
La QA navigateur locale prouve le comportement des composants avec des réponses
contrôlées. **La recette visuelle et métier après publication reste à réaliser
sur `agentium.papai.ai`.**
