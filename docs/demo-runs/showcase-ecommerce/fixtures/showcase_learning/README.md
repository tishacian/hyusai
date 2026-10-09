# Luma — historique, textes et charge pour le showcase

Ce pack prépare les données du [parcours commun](../../SHOWCASE-EVOLUTION-2026-10-09.md).
Il ne modifie ni PostgreSQL, ni un System, ni un modèle. **Tout est synthétique** :
les clôtures et les motifs sont générés, aucune revue humaine n'est attestée.
Les IDs, dates et preuves des dossiers de présentation `RC-1042/1043/1044` ainsi
que les fixtures du benchmark sont conservés et exclus de ce nouvel historique.

## Générer et vérifier

Depuis la racine du dépôt, sans dépendance Python supplémentaire :

```bash
python3 docs/demo-runs/showcase-ecommerce/fixtures/showcase_learning/generate.py
python3 -m unittest discover -s docs/demo-runs/showcase-ecommerce/fixtures/showcase_learning -p 'test_*.py'
```

Le générateur utilise explicitement la borne **2026-10-09 à 00:00 UTC**, graine
`20261009`. Les derniers volumes complets datent donc du 8 octobre. `--anchor`
et `--seed` permettent une nouvelle édition ; ils ne lisent jamais l'horloge.
Une nouvelle date constitue un **nouveau scénario**, pas de nouvelles observations
de la session précédente. Ne pas régénérer/réimporter silencieusement un dataset
déjà utilisé par un modèle ou une prévision.

Les CSV volumineux restent dans `generated/`, ignoré par Git. Le générateur, les
recettes et [le manifeste de référence](manifest.reference.json) sont versionnés.
`generated/manifest.json` fournit les SHA-256, schémas, effectifs et contrôles du
pack effectivement créé ; comparer ses empreintes au manifeste avant l'import.
Ce manifeste constitue une preuve de génération locale, pas un reçu d'import.

## Sources et vues dérivées

| Fichier généré | Lignes de référence | Utilisation et restrictions |
| --- | ---: | --- |
| `cases.csv` | 6 782 | Source initiale des dossiers : identifiants synthétiques, ouverture, snapshot à l'ouverture, six variables SLA, langue, message initial, campagne et cohorte. Aucun résultat de clôture. |
| `outcomes.csv` | 6 708 | Résultats disponibles avant la borne : clôture, durée, cible SLA, motif de génération et statut `not_human_reviewed`. Jointure par `claim_id`. Ne jamais l'utiliser comme matrice de features. |
| `daily_volume.csv` | 420 | Une observation quotidienne continue et une seule série `luma_sav`. Chaque volume compte exactement les cas de la même date UTC dans `cases.csv`. |
| `sla_train.csv` | 4 573 | Projection d'apprentissage purgée : six features, `language` pour les comparaisons de groupes, ID de traçabilité et cible SLA. |
| `sla_heldout.csv` | 1 433 | Test chronologique tenu à part. Les deux résultats sont conservés pour évaluer classification/régression ; aucun réentraînement ni tuning dessus. |
| `regression_train.csv` | 4 573 | Même cohorte purgée ; seule cible `resolution_hours`. Ce délai calendaire n'est pas du temps de travail humain. |
| `segmentation_numeric.csv` | 4 573 | ID et quatre variables numériques initiales, sans cible. Quatre groupes proposés comme point de départ, à interpréter après fit. |
| `text_for_review.csv` | 480 | 80 messages par motif/langue, uniquement train ; ID, langue, message, **aucun label**. Source du parcours LLM → revue humaine → distillation. |

Les trois premiers fichiers sont les sources communes. Les projections sont
des exports de commodité, pas huit sources métier différentes. Dans DataOps,
recréer les projections à partir des sources avec `sql_transform_v1` pour
conserver le lignage natif. Ne pas importer une nouvelle copie pour chaque modèle.

Le générateur produit aussi `campaign-plan.md` et `capacity-policy.md`, à ingérer
dans une collection de contexte commune au System. Ils expliquent une campagne
de 14 jours répétée toutes les huit semaines, avec la période courante du
5 au 18 octobre pour l'ancrage de référence. L'agent peut citer ces documents ;
la comparaison initiale des modèles de volume ne les consomme pas.

## Dictionnaire et disponibilité des variables

| Colonne | Sens / rôle |
| --- | --- |
| `claim_id`, `order_id`, `shipment_id` | Clés fictives `SYN-*`, cohérentes uniquement dans ce pack ; aucun lien implicite vers une commande PostgreSQL existante. Jamais des features. |
| `opened_at`, `snapshot_at` | ISO UTC ; le snapshot correspond à l'ouverture. Les faits initiaux ne sont pas mis à jour avec des preuves trouvées plus tard. |
| `claim_reason` | Motif déclaré à l'ouverture : `delivery_disputed`, `parcel_lost`, `refund_requested`. Utilisable pour le modèle SLA ; exclu du modèle de texte dont il serait une réponse déguisée. |
| `paid_amount` | Montant payé fictif en EUR, strictement positif. |
| `shipment_status` | État connu à l'ouverture : `delivered`, `lost`, `in_transit`. |
| `already_refunded` | 0/1 : remboursement **déjà existant à l'ouverture**, jamais l'action produite par l'enquête actuelle. |
| `case_documents` | Nombre de pièces déjà disponibles à l'ouverture, 0–4. |
| `item_quantity` | Quantité initiale, 1–4. |
| `language`, `initial_message` | `fr`/`en`, texte fictif initial ; aucun résultat de l'enquête. La classification texte utilise uniquement `initial_message`. |
| `campaign_active` | Contexte commercial connu ; fourni pour une expérience classique future. Exclu de la comparaison initiale et des six features SLA compatibles. |
| `cohort` | Partition temporelle, jamais une feature. |
| `resolved_at`, `label_available_at` | Clôture et disponibilité du label simulées ; absentes des cas non clôturés à la borne. |
| `resolution_hours` | `(resolved_at - opened_at)` en heures calendaires ; cible de régression uniquement. |
| `resolution_over_72h` | 0/1 dérivé du délai strictement supérieur à 72 h, cible SLA uniquement. Ce n'est pas la décision de remboursement. |
| `synthetic_intent_reference` | Motif ayant guidé la génération ; référence synthétique pour audit, jamais label humain ni entrée du LLM. |
| `review_status`, `data_kind` | `not_human_reviewed`, `synthetic_demo` : provenance, jamais predictors. |
| `observed_at`, `series_id`, `claim_count` | Date UTC du volume, série constante, nombre de réclamations synthétiques. Aucun revenu ni volume de commandes implicite. |

### Splits et fuite de cible

L'historique couvre 420 jours. Les 300 premiers jours constituent le train ;
10 jours d'embargo séparent ensuite 80 jours de heldout, 20 jours de feedback
et 10 jours récents. Dans le train, les clôtures non disponibles à sa propre
borne, **11 juin 2026 à 00:00 UTC**, sont purgées : 4 624 cas initiaux donnent
4 573 lignes éligibles. Au total, 74 clôtures postérieures à la borne d'octobre
ne sont pas exportées. Le jeu heldout utilise aussi des formulations différentes.

Le produit réalise son split interne aléatoire stratifié sur la seule cohorte
train. Avec 25 % de test interne puis 20 % de calibration sur le train restant,
les deux classes dépassent largement les minima de 200 lignes au total et
20 par classe (bornes conservatrices : 379 et 302). **L'éligibilité ne prouve pas
qu'une calibration a été exécutée** : vérifier les métriques et avertissements
du fit. Le heldout chronologique externe reste indépendant des métriques
internes affichées par Model Center.

Le modèle SLA sélectionne explicitement les six colonnes de `FEATURES` dans
[generate.py](generate.py). Le modèle de durée utilise les mêmes colonnes.
KMeans reçoit `paid_amount`, `already_refunded`, `case_documents`, `item_quantity`.
Aucun identifiant, résultat, langue de regroupement, cohorte ou date de clôture
n'est sélectionné implicitement.

## Recette produit et API

Toutes les requêtes sont authentifiées et portent le workspace voulu via
`X-Workspace-Slug`. Les routes ci-dessous sont relatives à `/api/v1`.
Ne conserver aucun token ou mot de passe dans les fichiers ou le manifeste.

1. **Importer les sources dans Data Center** ou via `POST /datasets/upload`,
   multipart `file`, `name`, `description`. Relever le `dataset.id`, sa version,
   son hash et attendre `status=ready` avec `GET /datasets/{id}`. Décrire chaque
   import comme synthétique, ancré et non revu. Vérifier lignes/colonnes avec
   `GET /datasets/{id}/preview`. Pour démarrer sans créer de pipeline annexe,
   les exports d'entraînement peuvent être importés directement ; ils n'auront
   alors que le lignage d'upload, pas un Run DataOps inventé.
2. **Matérialiser les projections avec DataOps** lorsque le lignage doit être
   montré. `POST /datasets/sql-preview` valide la requête, mais ne crée pas un
   dataset. Le Skill `sql_transform_v1` effectue la transformation persistante,
   avec `sources=[{"view":"cases","dataset_id":"…"},{"view":"outcomes","dataset_id":"…"}]`
   et un `output_name`. Exemple de projection SLA de référence :

   ```sql
   SELECT c.claim_id, c.claim_reason, c.paid_amount, c.shipment_status,
          c.already_refunded, c.case_documents, c.item_quantity, c.language,
          o.resolution_over_72h
   FROM cases AS c JOIN outcomes AS o ON c.claim_id = o.claim_id
   WHERE c.cohort = 'train'
     AND cast(o.label_available_at AS TIMESTAMPTZ) < TIMESTAMPTZ '2026-06-11T00:00:00Z'
   ORDER BY c.claim_id
   ```

   Pour la régression, remplacer uniquement la cible par `o.resolution_hours`.
   Pour une autre date d'ancrage, utiliser la borne du manifeste correspondant.
3. **Préparer les demandes d'entraînement** avec [model_requests.py](model_requests.py).
   La CLI accepte les quatre IDs de datasets SLA/volume/régression/segmentation
   et le nom exact de la lignée SLA existante (`--sla-model-name`). `--anchor`
   doit correspondre au manifeste des datasets importés. Elle émet des
   objets `plan`/`train` distincts : `/plan` refuse `name`, `description`,
   `test_size` et `cross_validation`. Les comparaisons de modèle exigent une
   même lignée et des versions compatibles ; ne pas créer un System par modèle.
4. **Valider puis entraîner les seules recettes retenues** : `POST /ml-models/plan`,
   vérifier `refusal=null`, `plan.features`, famille et avertissements ; puis
   `POST /ml-models` avec le corps `train`. Attendre la fin avec
   `GET /ml-models/{id}`. Le plan est une prévalidation, pas un fit ni une preuve
   de qualité. Conserver IDs, versions, dataset parent, configuration, métriques,
   avertissements et temps mesuré. Inspecter chaque nouvelle version avant
   une éventuelle promotion explicite via `POST /ml-models/{id}/champion`.
5. **Relier le modèle au Flow commun et à Work**, en épinglant une version pour
   la recette. La classification SLA conserve les six entrées PostgreSQL
   existantes. Les bandes de priorité Work sont un choix métier distinct du
   seuil Youden/F1 ; vérifier la classe positive, les unités et les deux réglages.
6. **Importer les deux notes dans Document Center** :
   `POST /documents/collections/{collection_id}/documents` multipart `files`.
   Attendre les jobs d'ingestion puis une collection prête ; attacher la
   collection aux sources du même System. Conserver le hash et la version des
   notes. Elles complètent les politiques existantes et ne les remplacent pas.

### Prévision : même historique et émission réelle

Les trois recettes volume partagent `observed_at`, `claim_count`, fréquence `D`,
horizon **28 jours**, trois fenêtres de backtest et intervalle 80 %. La série est
unique ; les colonnes `series_id`, `campaign_active`, `data_kind` ne sont pas
des features implicites. Le naïf saisonnier est la baseline, le classique utilise
des retards 1/2/7/14/28/56, Chronos ses poids figés. Aucun n'a accès au calendrier
de campagne dans cette première comparaison. Conserver les mêmes dates de
coupure ; un meilleur score n'est jamais garanti par le pack.

`POST /ml-models/{id}/forecast` accepte par exemple
`{"inputs":[],"params":{"horizon":28,"interval_level":0.8},"version":1}`.
Choisir la version réellement créée, ne pas reprendre `1` à l'aveugle. Une
prévision émise le 9 octobre dans l'après-midi peut déjà contenir un premier
point au 9 octobre à 00:00 : ce point ne sera pas une prévision antérieure à
sa date cible pour le monitoring. L'horizon 28 permet de conserver plus de
20 points futurs éligibles, à condition d'émettre à temps et d'attendre leurs
observations. Work peut montrer 42 jours d'historique puis ces 28 prévisions.

Le Skill `ml_forecast_v1` matérialise un dataset pour le Flow ; utiliser son
mapping de colonnes effectif pour la courbe Work, pas des lignes copiées d'un
backtest. Associer plus tard un dataset d'observations avec
`POST /ml-models/{id}/monitoring/actuals` et
`{"dataset_id":"…","follow_latest":false}`. **Ce pack ne contient aucun
volume futur et ne fabrique aucun reçu d'émission antérieur.** Les métriques de
backtest restent distinctes du suivi de prévisions émises.

### Configuration du Flow commun et des pages Work

[workflow_configuration.py](workflow_configuration.py) expose le constructeur
pur `build_configuration(flow, pages, forecast_model_id, forecast_model_slug,
forecast_model_version, history_dataset_id, sla_contract, models=None)`.
`flow` doit être le Flow **déjà composé** avec la préparation PostgreSQL et le
scoring SLA. `pages` doit provenir de `work_pages()` et conserver les composants
`investigation` et `queue_refresh` de la page `dossier`.

Le résultat `{flow_definition, pages, bindings}` peut être placé dans
`plan.configuration` pour l'activation revue par empreinte. Il ajoute une entrée
indépendante au même System :

```text
source.forecast → forecast.predict → forecast.timeline → sink.forecast
                  ml_forecast_v1     sql_transform_v1
```

Le SQL épingle l'historique comme première source (`input_1`), reçoit le dataset
de prévision produit par le nœud précédent comme seconde (`input_2`) et publie
une table de 42 observations + 28 prévisions dans le **même Run**. Les valeurs
absentes restent nulles. La série commune est nommée « Luma SAV » ; ce mapping
convient au modèle `single` préparé ici, pas à un panel arbitraire.

La page « Charge et capacité » contient une action compacte, son état, une
courbe certifiée `timeseries` et un lien vers le modèle épinglé. Sa référence
de dataset vient exclusivement du Run de `forecast_refresh`, via
`datasetSource`; aucune `queryBinding` ni donnée de graphique statique n'est
ajoutée. Le binding `showcase.claims.forecast` doit être créé par l'activation
avec `confirmation_policy="confirm"`.

La page « Amélioration » rappelle les preuves synthétiques et la revue humaine
requise, puis ouvre les modèles réellement fournis. `models` accepte une liste
de `{id, label_fr, label_en, description_fr?, description_en?}` ; les IDs sont
validés avant de devenir des liens `/models/{id}`. La page dossier conserve les
actions existantes et reçoit un lien vers `/work/reclamations/studio`. La carte
de prédiction peut être ajoutée à cette page par la configuration de son
composant générique ; le constructeur ne fabrique pas de résultat de scoring.

Pour inclure la vraie validation produit et DuckDB dans les tests :

```bash
DATABASE_URL=sqlite:///:memory: PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s docs/demo-runs/showcase-ecommerce/fixtures/showcase_learning -p 'test_*.py'
```

Cette commande vérifie notamment `validate_flow`, `validate_pages_document`,
le SQL de transformation, la séparation des valeurs observées/prévues et
l'absence de mutation des pages/du Flow source. Elle ne publie aucune release.

### Texte : qualification puis revue humaine réelle

Utiliser `text_for_review.csv` avec `llm_label_dataset_v1` et :

- `text_columns=["initial_message"]`, `label_column="label"` ;
- `labels=["delivery_disputed","parcel_lost","refund_requested"]` ;
- consigne : livraison déclarée remise mais contestée → `delivery_disputed` ;
  perte/absence de trace en transit → `parcel_lost` ; demande sur le retour de
  paiement → `refund_requested`. Classer la demande, sans décider de sa validité
  ou promettre un remboursement ;
- `max_rows=480`, `batch_size=10`, budgets de tokens/coût et **tarifs du modèle
  explicitement renseignés**. Ils ne sont pas inventés par le générateur.

Le résultat LLM est non revu. Brancher la porte canonique
`prompt_kind="review_dataset_labels"`, passer `label.dataset_id`, puis
`review.dataset_id` à l'entraînement. Une personne doit relire toute la cohorte
et confirmer/corriger ; un script ne peut pas faire cette validation à sa place.
`reviewed_text_requests()` propose ensuite baseline MinHash et MiniLM sur
`initial_message` seul, mêmes lignes/split, sans CV/calibration/tuning pour MiniLM.
Les colonnes de référence dans `outcomes.csv` ne remplacent pas cette revue.
Le heldout de texte est obtenu depuis les cas `cohort='heldout'` et demande sa
propre évaluation ; les phrases distinctes restent synthétiques et simples.

### Feedback et Impact

La cohorte feedback contient 327 cas clôturés synthétiques séparés du train et
du heldout. Elle peut exercer le contrat technique de feedback via des appels
unitaires `POST /ml-models/{id}/predict`, puis `/feedback` avec le vrai
`prediction_id` et `label` correspondant. Le feedback actuel ne concerne que
la première ligne de chaque appel. Ne pas le présenter comme une observation
client réelle, une décision humaine ou un gain de précision assuré.

Les exécutions de préparation, fit et prédiction ont de vrais temps techniques.
Elles ne sont pas automatiquement des dossiers traités dans Work, ni du temps
humain économisé. Impact conserve le périmètre du System métier, les coûts
connus/inconnus et les hypothèses approuvées : 8 min / 2 min / 40 €/h /
0,50 € par dossier. Aucun volume mensuel n'est fixé par ces fixtures.
