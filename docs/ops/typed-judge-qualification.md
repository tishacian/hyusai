# Juge typé : vision et qualification humaine

État actif au 13 octobre 2026 : le protocole et ses contrôles sont implémentés,
mais aucun fournisseur ni corpus métier réel n'est qualifié ici. **Gemini via
OpenRouter sera raccordé et qualifié plus tard. La narration est laissée de
côté et inactive** (`narration_enabled=false`, parcours en brouillon). Ce runbook
décrit une procédure de qualification future ; il ne demande aucune activation
immédiate. Voir le [plan autonome du juge](../agentium-typed-judge-plan.md).

`evaluate_v2` pose des questions statiques typées (`boolean`, `choice`,
`multi_choice`, `score`, `probability`) à la route de modèle gouvernée. Il conserve
les abstentions, les citations vérifiées, les mesures du fournisseur et une
évaluation canonique `EvaluationScore`. `evaluate_v1` reste une version distincte.
Un score de qualité, une probabilité demandée au modèle et la confiance dans une
réponse sont trois données différentes. La confiance vaut `null` en l'absence
d'un profil qualifié applicable. La disposition du juge reste `review` : la
publication appartient au moteur de promesse de service et à sa décision humaine.

Les tests du dépôt remplacent le transport du fournisseur. Ils prouvent la
construction des requêtes OpenAI/Azure et les refus d'accès ; ils ne qualifient
aucun fournisseur, aucun tarif ni aucun corpus client réel. Le parcours suivant
exige des documents, deux annotateurs indépendants (et un troisième en cas de
désaccord) et une connexion réellement configurée. Les chemins OpenAI/Azure
testés ne démontrent pas la compatibilité ou la qualification Gemini/OpenRouter.

## Preuves A1 et découpage

Chaque unité est un actif immuable autorisé du workspace. Son manifeste porte
`source`, `language` (ex. `en-fr`), `task` (`j2450_translation` ou `typed_questions`)
et `document_family`. Une famille réunit toutes les pages, révisions et dérivés
d'un même document. Une répartition aléatoire des pages d'un même document entre
apprentissage et test est interdite.

Une preuve image est déclarée ainsi dans le manifeste A1 :

```json
{
  "objects": [{"key": "workspaces/WS/doc/page.png", "sha256": "SHA256", "size_bytes": 12345}],
  "evidence": [{"id": "page-1", "kind": "image", "sha256": "SHA256", "mime_type": "image/png", "locator": {"object_key": "workspaces/WS/doc/page.png"}}]
}
```

L'entrée du juge contient uniquement `id`, `kind`, `sha256` et l'`asset_ref`
complet (workspace, actif, version et digest). Le résolveur serveur vérifie les
droits natifs, le manifeste, les octets et le format réel, puis envoie les octets
par contenu image inline. Il n'accepte aucune URL fournie par le Run. PNG, JPEG
et WebP fixes sont autorisés ; les animations et dépassements de taille/pixels
sont refusés avant l'appel. La citation image contient le hash, une description
visible et une région `[gauche, haut, droite, bas]` normalisée, ou `null` pour
l'image entière. Les citations texte gardent leurs offsets et leur extrait exact.

Pour la cible documentaire différée de 500 pages et environ 500 images, découper
les questions en unités bornées lors de sa reprise. Aucun tel lot réel n'est
qualifié par ce travail. La couverture d'une réponse ne concerne que ses preuves
déclarées. Le lot doit rapprocher l'inventaire attendu des unités effectivement examinées ;
un échantillon ne prouve pas la couverture intégrale des défauts critiques. Le
scoring de 2 à 3 millions de lignes reste déterministe : aucun appel LLM par ligne.

## Qualifier une route vision

L'API est `/api/v1/typed-calibration`, derrière le même accès workspace et le
même drapeau `service_contracts` que les actifs A1. La création et la qualification
des routes et corpus sont réservées aux administrateurs du workspace.

Les valeurs `provider` ci-dessous décrivent le contrat actuellement implémenté.
Le futur raccordement Gemini/OpenRouter devra d'abord être intégré au Model Plane
et à ses contrôles de transport ; il ne suffit pas de renommer une route existante
ou de réutiliser une attestation issue d'un transport simulé.

1. Configurer le modèle via le Model Plane existant, avec son endpoint, son
   déploiement et ses identifiants. `POST /vision-routes` reçoit `logical_key`,
   `provider` (`openai` ou `azure_openai`), `model`, `returned_model` attendu et les
   cinq limites explicites `max_images`, `max_image_bytes`, `max_total_bytes`,
   `max_image_tokens`, `max_pixels`. La création calcule le digest de connexion
   côté serveur, ne fait aucun appel et retourne `qualified: false`.
2. Exécuter une vérification réelle et autorisée du fournisseur configuré, avec
   une image de contrôle et une question dont la réponse dépend de ses pixels.
   Inspecter la trace et la réponse. Déposer dans A1 une trace expurgée des
   identifiants et des octets sensibles inutiles, avec ses objets vérifiés et le
   manifeste ci-dessous. Le hash de l'image doit être celui qui a été transmis.
3. Appeler `POST /vision-routes/{asset_id}/qualify` avec
   `{"verification_ref": ASSET_REF_TRACE, "note": "Compte rendu précis de la vérification humaine"}`.
   Le serveur enregistre l'identité authentifiée de l'administrateur et la méthode
   `human_verified_transport_trace`. Cette attestation qualifie le transport,
   pas la qualité J2450. Elle ne prétend pas être un probe automatisé.

```json
{
  "type": "vision_transport_verification",
  "route_digest": "DIGEST_DE_LA_ROUTE",
  "provider_response_model": "REVISION_REELLEMENT_RETOURNEE",
  "observed_transport": "inline_image",
  "reviewed_image_sha256": "SHA256_DE_L_IMAGE_TRANSMISE",
  "passed": true,
  "objects": [{"key": "workspaces/WS/traces/transport.json", "sha256": "SHA256_TRACE", "size_bytes": 12345}]
}
```

Les plafonds absolus sont 16 images par requête, 8 Mo par image, 32 Mo au total,
40 millions de pixels par image et 100 000 tokens réservés par image. La route
qualifiée doit fixer des valeurs adaptées et généralement inférieures. Changer
provider, modèle, endpoint, version API ou origine des identifiants invalide le
digest de connexion. Un `returned_model` différent échoue après l'appel et garde
son coût mesuré. Une identité de modèle absente dans la réponse du fournisseur
est inconnue : le nom configuré ne la remplace pas pour qualifier la vision ou
le corpus. Une qualification Work générique ne qualifie pas la vision.

## Constituer et annoter le corpus

`POST /corpora` fige `logical_key`, `rubric_id`, `rubric_version`, `questions`,
`model: {provider, model, returned_model}`, `context: {source, language, task}`,
`units` et `policy`. Chaque unité est
`{key, document_family, partition: dev|calibration|test, asset_ref}`. Limite :
1 000 unités. Les familles et empreintes de contenu sont disjointes entre
partitions. Une famille déjà exposée comme test ne peut pas être réutilisée dans
un nouveau corpus : un changement de seuil ou de rubrique exige un nouveau test.

Pour J2450, la rubrique doit comporter une question `choice` ou `multi_choice`
avec exactement `WT`, `SE`, `OM`, `SA`, `SP`, `PE`, `ME`. Exemple de question :
« Quelles catégories d'erreur J2450 sont présentes dans cette traduction,
comparée au segment source et à ses références autorisées ? ». `multi_choice`
accepte `[]` lorsqu'aucune erreur n'est observée ; l'abstention est distincte.
J2450 qualifie ici des erreurs de traduction. Il ne sert pas de métrique générale
de qualité d'une narration ni de score SAE pondéré inventé.

Le responsable renseigne avant tout résultat :

- `min_calibration_units`, `min_test_units`, `min_calibration_families`,
  `min_test_families` (au moins deux familles indépendantes par partition) ;
- `critical_labels` par question, `min_critical_positives`, `min_precision`,
  `min_recall`, `max_critical_miss_rate`, `min_coverage`, `min_confidence_lower` ;
- `max_brier` et `max_ece`, explicitement `null` si non applicables ; pour une
  question de probabilité, fournir des plafonds numériques et des événements
  observés. Une question `score` exige `numeric_tolerances` pour l'accord humain.

Ces seuils n'ont pas de valeur métier par défaut. Le protocole initial de
qualification exige un critère critique catégoriel ; les scores et probabilités
peuvent compléter cette rubrique. Un profil de probabilité seul ne produit pas
de borne de confiance sur la justesse d'une réponse.

Deux humains distincts appellent chacun
`POST /corpora/{id}/annotations` avant le passage du juge sur calibration/test :

```json
{
  "unit_key": "manuel-17-segment-3",
  "values": {"categories": ["OM"]},
  "outcomes": {},
  "note": "Comparaison du segment source et de sa traduction : avertissement omis.",
  "adjudication": false
}
```

Le serveur prend l'identité de la session ; aucun `reviewer_user_id` n'est
accepté. Les annotations sont immuables. Une divergence exige un troisième
humain avec `adjudication: true`. Une référence humaine `null` reste inconnue et
bloque la qualification. Organiser la revue en aveugle : ne pas partager les
réponses du juge avec les annotateurs. Le serveur vérifie l'ordre de création
des annotations et des évaluations ; il ne peut pas observer des échanges hors
plateforme. Les types A1 `typed_calibration_*` sont réservés au workflow et chaque
annotation porte en plus une provenance serveur vérifiée.

## Mesurer puis qualifier

Exécuter le vrai juge sans `profile_ref`, sur les questions et les preuves exactes
de chaque unité. Garder `subject_ref = unit.key`. Attacher son identifiant canonique
via `POST /corpora/{id}/predictions` :
`{"unit_key": "manuel-17-segment-3", "evaluation_id": "UUID_EVALUATION"}`.
Le serveur n'accepte ni réponses fournies dans le corps HTTP, ni auto-évaluation,
ni seconde tentative sélectionnée après une première réponse défavorable. Les
révisions du modèle, le hash des questions, le contexte et l'actif sont vérifiés.

`GET /corpora/{id}/report` donne les raisons de refus et les métriques séparées
calibration/test : précision, rappel, défauts critiques manqués, couverture avec
dénominateur attendu, unités manquantes, Brier/ECE des probabilités observées et
bornes de confiance par famille. Une abstention compte comme un défaut critique
manqué quand la référence en contient un. Les mesures sans observations valent
`null`. Toutes les unités attendues doivent avoir références et prédictions.

La confiance est la borne inférieure de Wilson à 95 % de l'événement « toutes les
réponses requises de cette famille sont correctes ». Les réponses d'une même
famille ne sont pas comptées comme des observations indépendantes. Cette borne
empirique conservatrice, globale à la population déclarée, n'est ni une
probabilité produite par le LLM ni une garantie individuelle. Le test indépendant
mesure aussi Brier/ECE de cette borne figée ; ces indicateurs doivent être lus
avec la taille du test et les seuils métier du rapport. Les seuils Brier/ECE du
contrat initial portent sur les questions de probabilité, pas sur une garantie
automatique de calibration de toutes les questions catégorielles.

`POST /corpora/{id}/qualify` crée un profil A1 immuable uniquement si tous les
critères préalablement fixés passent. Le profil lie rubrique, modèle retourné,
source, langue, tâche, annotations, prédictions et rapport. Un changement de
liaison, une révocation, un résultat incomplet ou l'absence de profil remet la
confiance à `null` ; aucun seuil de publication n'est abaissé pour compenser.

## Branchement Flow, budget et reprise

La configuration publiée `node.config.typed_evaluation` conserve les questions,
budgets et tarif. `profile_ref` et `vision_route_ref` sont des références A1 ; le
wrapper les retire avant `TypedEvaluationInput.model_validate`, puis appelle :

```python
prepared = prepare_typed_judge_context(
    payload, server_ctx, profile_ref=profile_ref, vision_route_ref=vision_route_ref
)
result = await typed_evaluate(payload, prepared)
```

Le contexte applicatif contient un vrai `workspace_id`, `run_id`, utilisateur
autorisé, `_model_execution` et `_model_policy_check`. Le helper installe les
résolveurs A1 et déduit le contexte source/langue/tâche des preuves autorisées.
Ces champs privés ne doivent jamais être recopiés depuis l'entrée libre d'un Run.

`batch_key` est stable pour la fenêtre de service et `request_key` pour l'unité.
Les réservations d'appels, tokens et coûts sont persistées dans `WorkspaceJob` ;
une reprise ne remet pas le compteur à zéro. Le verrou de production existant
borne la concurrence par workspace. Le budget de lot, les limites par unité et
les limites de route se cumulent. Les tokens image sont réservés avant appel au
plafond déclaré ; l'usage fourni remplace cette réserve lorsqu'il est mesuré.
Pour un Run rattaché à une promesse de service, le
[budget partagé de fenêtre](service-window-budget.md) cumule en plus les appels
du juge avec les autres étapes déclarées, y compris entre plusieurs tentatives.
Le ledger sait inclure l'adaptateur de narration, mais celui-ci reste inactif
dans le périmètre courant ; les exemples de lot mixte ne l'activent pas.
Sans usage fournisseur, le coût réel reste `null` et la réservation demeure
engagée. Un timeout ne déclenche ni repli automatique ni double appel aveugle.
Un usage mesuré supérieur à la réserve conserve la dépense réelle et échoue
avec `JUDGE_MEASURED_BUDGET_EXCEEDED` si le plafond du lot est dépassé.
Les images inline et identifiants ne figurent pas dans l'évaluation persistée.

Validation locale :

```bash
cd backend
../.venv/bin/python -m pytest -q app/tests/services/test_typed_judge.py app/tests/services/test_typed_vision.py app/tests/services/test_typed_calibration.py app/tests/services/test_model_execution.py
```
