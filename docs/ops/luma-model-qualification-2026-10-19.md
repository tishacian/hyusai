# Luma : qualification du modèle après activation du socle

## État observé

Le 19 octobre 2026, l'opérateur rapporte la révision
`a775f8569a02ed5a1c38890f01ee2e126cc46277` et la migration
`140_mlops_prod_explanations`. Une lecture authentifiée dans Showcase confirme
le journal, les séries, la lecture du Flow et ML Operations ouverts ; les
alertes restent fermées.

Le champion SLA v1 (`17331ddf-7811-42e1-8e0f-c8dc75dd3541`) n'est pas appelable.
Sa route runtime donne `reason: legacy_artifact`. Le refus ne vient pas du
modèle linéaire : le contrat d'artefact et les informations de runtime requis
manquent. Play explique l'indisponibilité et propose le réentraînement ; la
recherche contrefactuelle ne peut pas charger cette version non plus.

Un nouvel entraînement explicite de la même lignée a créé la v4
`7381b781-7e0a-4613-9cec-9614b87a0a5b`, avec les six variables conservées,
calibration sigmoid, test à 25 % et validation croisée à trois plis. Il est
passé à `training / saving`, sans publication de résultats utilisables, puis
le contrôleur l'a classé `failed / EXECUTION_WORKER_LOST`, confirmé par l'API
lors de la vérification finale. Cette version n'a pas été promue et Luma n'a
pas été réépinglé dessus.

## Défauts produit reproduits et corrigés

- Le rafraîchissement ORM de la finalisation ML effaçait les changements non
  encore enregistrés : statut final, artefact, métriques et runtime. Avec le
  contrôle d'exécution actif, un calcul terminé pouvait rester affiché en
  entraînement jusqu'à la réconciliation. Les tests vérifient maintenant
  l'état réellement relu en base, au-delà du statut retourné par la fonction.
- Le contrôle final lit l'autorité persistée sous verrou sans écraser le
  résultat candidat. Si annulation, échéance ou perte d'autorité interdisent
  la publication, les changements candidats sont abandonnés. L'alias champion
  du registre d'un entraînement n'est publié qu'après enregistrement de l'état
  `ready` ; les captures de référence et hooks de challenger suivent ce même
  état final.
- Le formulaire Réentraîner conserve désormais le nom exact de la lignée.
  Il transmet aussi les variables sauvegardées dès le premier précontrôle :
  une liste vide envoyée avant réception du schéma élargissait auparavant le
  plan aux autres colonnes.

Ces corrections sont génériques. Elles n'ajoutent aucun comportement réservé
à Luma et ne modifient aucune politique d'approbation.

## Validation de la correction

- 43 tests ciblés passent sur PostgreSQL 16, notamment la relecture du statut
  et des métadonnées enregistrées, les refus d'autorité et la publication
  tardive après échéance.
- Les cinq scénarios Playwright du parcours de disponibilité et réentraînement
  passent, ainsi que la vérification TypeScript, la compilation Angular et le
  contrôle de cohérence du chrome.
- Une relecture indépendante du dernier diff ne relève plus de point bloquant.
  Ces résultats valident le code ; ils ne remplacent pas un nouvel entraînement
  et une qualification sur le déploiement corrigé.

## Reprise opérateur

1. Déployer une révision contenant `34bc3ff6` (finalisation ML) et `d754a548`
   (réentraînement UI), avec les images cohérentes de la release.
   Le **worker général CPU qui exécute `agentium.ml_train`** doit
   être mis à jour, ainsi que l'API, le frontend, le beat et les composants de
   contrôle gérés par le script de déploiement. Mettre à jour seulement `ml-ts`
   ne corrige pas l'entraînement tabulaire. Conserver les profils déjà actifs.
2. Il n'y a **aucune migration nouvelle** pour ces correctifs et aucun nouveau
   drapeau à ouvrir. Le script `up` utilise `--no-build` : construire les images
   de la nouvelle révision selon la procédure de release avant de l'appeler.
3. Vérifier les révisions réellement chargées et la disponibilité des workers.
   Créer ensuite une nouvelle version par le parcours de réentraînement.
   Ne pas forcer la v4 à `ready` ni reconstruire son contrat par une écriture SQL.
4. Attendre sa fin, puis vérifier `serving.callable`, son contrat d'artefact,
   son runtime et une prédiction explicitement épinglée à la version retournée.
   Évaluer avant de demander sa promotion par le mécanisme de gouvernance.
5. Après qualification, mettre à jour les épingles de Luma : `sav.score`,
   contrat imbriqué du triage, contrat de prédiction Work et bindings de la
   nouvelle publication. Préserver les différences du draft utilisateur et
   utiliser les préconditions de publication/release. La promotion du champion
   ne modifie pas ces références explicites.
6. Configurer la surveillance de la nouvelle version, vérifier sa planification,
   puis désactiver celle de l'ancienne version sans supprimer son historique.
   Un shadow demande aussi un challenger compatible : les anciennes versions
   ne sont pas converties par cette opération.

## Corpus de qualification prêt, campagne encore à exécuter

Le corpus reproductible utilise l'ancre `2026-10-09` et la graine `20261009`
de `docs/demo-runs/showcase-ecommerce/fixtures/showcase_learning/generate.py`.
Les 4 573 lignes et labels du dataset d'apprentissage téléchargé par l'API
correspondent à cette référence. Les 64 dossiers sélectionnés dans la cohorte
feedback sont distincts de l'apprentissage et du heldout, par identifiant et
par combinaison des six variables. Ils portent 32 labels synthétiques de
chaque classe, choisis indépendamment des réponses du modèle.

La campagne doit conserver les entrées, utiliser les `prediction_id` et
`sample_id` réellement retournés et rattacher les issues synthétiques connues
à la version effectivement servie. Après au moins 50 échantillons admissibles,
l'analyse de production peut être lancée. Le sous-ensemble équilibré qualifie
le parcours technique ; il ne mesure ni une prévalence réelle, ni une qualité
revue par un humain, ni un ROI réalisé. Aucun label ne vient de la prédiction
elle-même et aucune mesure ne doit être antidatée.

Les snapshots et captures authentifiés restent hors du dépôt, dans le dossier
privé de recette. Les payloads préparatoires ciblant v4 ne doivent pas être
appliqués : reconstruire les références depuis la future version qualifiée.
