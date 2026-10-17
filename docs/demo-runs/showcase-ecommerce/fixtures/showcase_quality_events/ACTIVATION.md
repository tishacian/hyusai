# Étendre le parcours Luma avec qualité, événements et suivi du modèle

Configuration préparée le **17 octobre 2026**. Le [plan concret](reviewed_plan.json)
et sa [revue](reviewed_plan.review.json) portent `applied=false` et
`activation_ready=false`. **Ils ne sont pas un reçu d'activation.** Le candidat SLA
v3 est encore en entraînement dans le snapshot ; aucune inférence de qualification
n'est inventée. L'accès PostgreSQL était également indisponible pendant la lecture
live, et le site exécutait encore `f4329db3`.

## Parcours métier et limites

Le même System `f3ea83de-df89-45ec-8a85-c00d676b2713` comporte 27 nodes, 28 edges et
cinq entrées : dossier manuel, file manuelle, prévision manuelle, réclamation par
webhook signé et file planifiée. Les deux nouvelles entrées traversent la même
préparation PostgreSQL/DataOps et le même scoring. Le mapping publié
`runtime_contract.ecommerce_ingress_operations` choisit dossier ou file ; un
champ `operation` envoyé par le client ne peut pas élargir le périmètre lu.

La branche dossier devient : **faits → préparation → score SLA → enquête
documentaire → Judge → validation humaine → reçu simulé**. La branche de file
et la prévision ne créent pas de reçu. L'agent s'arrête pour demander des pièces
avant le Judge quand son enquête ne permet pas de proposer une résolution.

Le Judge utilise `evaluate_v2` et un snapshot A1 immuable des sorties du même Run :
proposition avec passages cités, recherche de politique et faits PostgreSQL.
Les cinq questions portent sur les preuves, la politique, le montant/doublon,
les contradictions et la gestion de l'incertitude/validation humaine. Elles
exigent des citations. Un résultat défavorable, partiel ou une abstention reste
visible pour la personne ; aucune réponse du Judge ne contourne la porte HITL.
Une erreur technique de capture ou d'appel arrête le Run avant l'action : corriger
la cause et reprendre une enquête contrôlée, sans fabriquer une revue réussie.

Le tarif déclaré est **OpenAI GPT-5, 1,25 USD / million de tokens entrants et
10 USD / million sortants**, contrôlé le 17 octobre sur la
[fiche officielle](https://developers.openai.com/api/docs/models/gpt-5).
La remise de cache n'est pas incluse dans cette estimation. Le budget est borné
à un appel, 10 000 tokens, 2 048 tokens de sortie, 0,05 USD, 45 secondes et
32 000 octets de prompt ; un dépassement doit être refusé. La route réellement
résolue doit correspondre au tarif, sans fallback silencieux. Aucun profil de
calibration ni qualification du fournisseur sur le corpus Luma n'est annoncé.
Le score de qualité ne constitue pas une confiance calibrée.

La boucle MLOps conserve les versions et leurs artefacts. Le modèle candidat
`cd2d0692-7586-4e19-b541-8363118e031c` v3 est **une épingle proposée**, pas une
promotion. Monitoring, shadow, feedback et proposition de réentraînement utilisent
les fonctions produit de Model Center, décrites dans le
[guide d'activation MLOps](../../../../agentium-mlops-activation.md).
Chronos reste hors du réentraînement automatique ; aucune observation future
ni clôture humaine n'est ajoutée pour alimenter artificiellement les courbes.

## Préparer un plan applicable

1. Déployer la livraison finale sur API, workers et frontend ; comparer leurs
   révisions et réconcilier le catalogue. Vérifier `evaluate_v2`, les sources
   webhook/schedule et le snapshot de preuves. La livraison précédente seule
   ne contient pas ce raccordement.
2. Rétablir la lecture PostgreSQL avec le compte limité déjà configuré. Vérifier
   un dossier et la file. Conserver les réglages TLS et les credentials existants.
3. Attendre le résultat réel du fit SLA v3. Inspecter son artefact/serving, puis
   effectuer une inférence **épinglée v3**, contrôler `served.model_id`,
   `served.version`, les colonnes, le label positif `1` et `prediction_id`.
   `status=ready` seul ne suffit pas. Ne pas promouvoir pour passer ce contrôle.
4. Faire de nouvelles lectures autorisées et enregistrer les snapshots suivants
   au format `{ "status": 200, "data": ... }` :

   | Fichier | Lecture |
   | --- | --- |
   | `flow-state.json` | `/systems/{system_id}/flow-state` |
   | `work-live.json` | `/work/reclamations` |
   | `experience.json` | `/experiences/4c93ae4b-f2de-438d-b781-bb69a4cb962c` |
   | `binding-investigate.json` | `/system-bindings/showcase.claims.investigate` |
   | `binding-queue.json` | `/system-bindings/showcase.claims.refresh_queue` |
   | `binding-forecast.json` | `/system-bindings/showcase.claims.forecast` |
   | `collections.json` | `/documents/collections` |
   | `model-sla.json` | `/ml-models/{candidate_id}` |
   | `model-sla-prediction.json` | réponse de l'inférence épinglée réellement exécutée |
   | `triage-settings.json` | projection `{triage: settings.ecommerce_claims.triage}` de la lecture workspace |

   Ne pas enregistrer les secrets, jetons, réponses d'authentification ou secret
   de création du webhook dans ce dossier. Le dernier fichier ne contient que
   la configuration métier, pas l'ensemble des réglages du workspace.
5. Revoir explicitement `judge_settings.json`, puis reconstruire sans le mode
   bloqué depuis la racine du dépôt :

   ```bash
   PYTHONPATH=backend .venv/bin/python \
     docs/demo-runs/showcase-ecommerce/fixtures/showcase_quality_events/build_plan.py \
     --snapshots /chemin/vers/snapshots-frais \
     --judge-settings docs/demo-runs/showcase-ecommerce/fixtures/showcase_quality_events/judge_settings.json \
     --output /tmp/luma-quality-events-plan.json
   ```

   Le constructeur refuse une route/un tarif/un budget incomplet, un modèle
   incompatible, une inférence absente ou provenant d'une autre version, une
   dérive des bindings/triage, une politique de contrôle de draft non publiée
   ou des modifications Work non revues. `--allow-blocked` produit uniquement
   un candidat annoté pour revue lorsque le serving ou son essai manque ; il
   ne permet pas l'activation. La revue hors ligne ne dispense pas des contrôles
   PostgreSQL, fournisseur, autorisations, catalogue et workers ci-dessus.

## Publier sans perdre le draft utilisateur

Ne pas rejouer `activate_ecommerce_composition` ni l'ancien plan du 9 octobre :
ils créent des bindings qui existent déjà et retirent les anciens Systems.
Ici aucun autre System métier n'est créé ou retiré.

L'état lu est publication v4 `0c18cb17-ee28-4cbc-acd8-aafb6bcce150`, hash
`fad0507f94c836d392a5822c81aed47e482329b5f240398661c72c12b7944556`, draft r23
`0b27d39d316cf1264186a00354a95217e8499562cbf330048293041e88e5c0c7`.
Le draft contient le node non publié `flow.mv95zi21.1` (Prepare).
`backup.flow_draft` conserve son contenu ; `preserved_draft_candidate` lui ajoute
la même extension sans le supprimer. Seul `publication_candidate`, construit
depuis la publication, est destiné à être publié.

Utiliser les endpoints produit ci-dessous avec la session autorisée de
l'opérateur, tous préfixés `/api/v1`. Les étapes de Flow/Work sont distinctes :
conserver chaque réponse et arrêter sur tout conflit. Garder les déclencheurs
en pause pendant l'intervention et éviter les éditions concurrentes.

1. Relire Flow, expérience, déploiement, bindings et triage ; comparer **toutes**
   les valeurs de `preconditions`. Archiver le plan et son empreinte de revue.
   Un écart nécessite une nouvelle construction/revue, pas un remplacement
   automatique de l'empreinte attendue.
2. `PUT /systems/{id}/flow-draft` avec
   `{flow_definition: plan.publication_candidate, expected_revision: plan.preconditions.draft_revision}`.
   Conserver la révision retournée. `GET /systems/{id}/flow-diff?base=published&target=draft`
   donne le diff et `target.execution_contract_sha256` à revoir : cinq entrées,
   Judge, modèle épinglé, droits, tarifs et porte humaine.
3. `POST /systems/{id}/flow/publish` avec `expected_draft_revision` retournée,
   `expected_published_version_id` du plan, `expected_execution_contract_sha256`
   du diff relu, `breaking_change_intent: "acknowledged"` et un message décrivant
   l'extension. Vérifier le `published.flow_sha256` contre `target_flow_sha256`.
   Ne pas publier une empreinte différente pour poursuivre la recette.
4. `PUT /systems/{id}/flow-draft` avec
   `{flow_definition: plan.preserved_draft_candidate, expected_revision: <révision retournée par publish>}`.
   Le contenu utilisateur est conservé dans un draft actualisé, avec son node
   Prepare toujours non publié. Relire ce draft et comparer son contenu au plan.
   Si l'étape 3 échoue, restaurer `backup.flow_draft.flow_definition` via PUT
   **uniquement** avec la révision courante attendue de l'étape 2 ; ne pas
   écraser une édition survenue entre-temps.
5. Pour chacun des trois bindings, relire et comparer au snapshot avant
   `PATCH /system-bindings/{key}` avec
   `{published_flow_version_id: <nouvelle version>, ingress_id: <entrée préservée>, confirmation_policy: "confirm", on_unavailable: "unavailable"}`.
   Les trois actions restent sur la même publication. L'API de binding ne porte
   pas de champ CAS ; la relecture et l'absence d'édition concurrente sont donc
   nécessaires pendant cette étape. Vérifier les trois résolutions après écriture.
6. Mettre à jour **seulement** `settings.ecommerce_claims.triage` dans une
   transaction opérateur : verrouiller la ligne workspace, comparer ce sous-objet
   à `plan.preconditions.triage`, vérifier que le System courant pointe sur la
   nouvelle version et son hash, puis copier `triage_after_publication` en
   remplaçant `$published.version_id` par l'ID retourné. Réassigner une copie
   des settings existants, sans remplacer les autres sous-objets et sans lire
   ou écrire de secret dans un fichier. Émettre l'audit de configuration.
   Un simple PATCH avec le seul fragment `triage` ne convient pas : l'endpoint
   workspace remplace les settings fournis. Cette liaison est nécessaire pour
   que la file et son contrat de prédiction suivent la publication.
7. `PUT /experiences/{experience_id}/draft` avec `pages: plan.work_pages`,
   `binding_keys: plan.work_binding_keys` et la révision Work attendue du plan.
   La navigation et les composants existants sont conservés ; la carte de
   prédiction référence la nouvelle épingle. Lire `/ready-check`, exiger aucun
   blocker, relire l'expérience puis créer une release avec
   `expected_draft_revision`, `expected_content_sha256`,
   `expected_experience_updated_at` et `expected_bindings_sha256` issus de ces
   lectures. `POST /experiences/{id}/deployments` utilise `channel: "live"`, l'ID
   de cette release, `expected_current_release_id` et
   `expected_deployment_updated_at` de `preconditions.deployment`, avec son
   audience conservée. Le reçu doit identifier la release et ses trois bindings.

Un échec intermédiaire se diagnostique avec les réponses conservées. Tant que
la publication, les bindings, le triage et la release ne sont pas cohérents,
ne pas annoncer le parcours activé. Les versions/releases précédentes restent
disponibles ; leur restauration passe par les actions produit et leurs CAS.

## Activer et vérifier les déclencheurs

Suivre le [contrat produit des déclencheurs](../../../../agentium-flow-trigger-operations.md).
Le plan fournit les corps de création **désactivés**, sans secret. Le webhook
accepte `claim_id` dans la cohorte publiée et la métadonnée `_webhook` injectée
par le serveur ; le cron n'accepte que `{}`. Il n'y a qu'une source HTTP et une
source schedule, conformément à la sélection actuelle des adapters.

1. Vérifier les cinq entrées via `/systems/{id}/ingresses`. Créer le hook en
   pause, installer son secret uniquement chez l'émetteur. Activer l'opt-in
   événementiel du workspace et régler le System en mode `live`. Activer le
   hook après ces contrôles.
2. Envoyer un dossier autorisé avec HMAC SHA-256 sur les octets JSON exacts.
   Lire le statut métier même après HTTP 200. Rejouer le même objet : même Run
   accepté, pas de deuxième action. Modifier le contenu constitue un nouvel
   événement ; `event_id` seul n'est pas une clé d'idempotence.
3. Vérifier l'identité d'exécution autorisée, l'enquête, le snapshot A1, les
   cinq réponses/citations/abstentions dans Work et la porte humaine. Une
   signature valide ne prouve ni succès de l'enquête ni autorisation d'un paiement.
4. Créer le schedule en pause avec sa zone `Europe/Paris` et `{}`. Pour la
   qualification, choisir une échéance proche explicite, observer **un** tick
   réel puis désactiver le schedule. Le cron n'est pas arrêté par le mode
   `dry_run` ou le coupe-circuit des événements. Son dernier Run doit produire
   la file scorée visible dans Work, sans enquête ni reçu. Ne pas laisser une
   récurrence tourner tant que PostgreSQL ou le modèle échoue.

## Fermer la boucle MLOps avec des preuves

Activer d'abord le monitoring du modèle effectivement épinglé, à 60 minutes,
sans proposition de réentraînement. Observer son System technique, ses Runs et
ses erreurs dans Model Center. Cela ne crée pas un second System métier Luma.

Identifier ensuite le challenger réellement compatible et qualifié par
inférence. La version v3 proposée dans le plan ne doit pas devenir implicitement
le champion du registre : conserver le choix existant et expliciter toute
décision ultérieure. Activer shadow seulement quand cette paire est valide,
avec échantillonnage borné à 10 % et timeout de 15 secondes. Des appels effectifs
doivent créer des comparaisons ; montrer effectifs, erreurs et couverture des
labels avant de parler d'amélioration. Shadow ne modifie pas la réponse servie.

Le feedback concerne **un `prediction_id` et un `sample_id`**, et le vrai label
de résolution au-delà de 72 heures. Une acceptation de remboursement n'est pas
ce label. Les corrections utilisent le retour actif par ligne et restent
traçables. Une cohorte synthétique peut qualifier le mécanisme si elle est
explicitement nommée comme telle ; elle ne constitue pas une mesure terrain.

Quand la fenêtre de labels et les seuils de monitoring le justifient, activer
`propose_retraining` avec le mode `original_plus_feedback`, fraction maximale
0,25 et fenêtre choisie explicitement. La proposition fige son jeu de données ;
la personne examine la porte HITL avant entraînement d'un challenger. Comparer
les résultats, puis décider séparément de la promotion et du repinning des
consommateurs. Les observations de prévision attendent leurs dates éligibles.

## Recette UI et Impact

- Work reste l'entrée métier : rechercher un dossier, voir son conseil SLA,
  ses preuves, la revue qualité et l'action humaine sans ouvrir plusieurs Systems.
  Tester aussi un manque de preuve, une abstention/erreur Judge et un reçu déjà
  enregistré ; aucune relance ne doit créer un deuxième reçu.
- Dans Flow, les cinq sources et le Judge ont des labels métier. Les actions du
  panneau source restent compactes ; création en pause, timezone, prochain
  déclenchement et dernier Run doivent être lisibles au clavier et sur petit écran.
- La file planifiée doit apparaître dans Work comme la file manuelle, avec le
  bon Run/dataset/version. L'enquête d'un seul dossier ne remplace jamais cette file.
- Impact conserve le périmètre du System métier et les échecs. Les tentatives
  dédupliquées, appels du Judge et recalculs ne sont pas des dossiers résolus.
  Les coûts du modèle et du Judge restent traçables ; le scénario financier
  demeure 8 min / 2 min / 40 €/h / 0,50 € par dossier, sans ROI humain observé.

Tests locaux : 8 tests de transformation/contrat dans ce dossier, plus tests
backend de routage immuable et trajet réel cron → préparation/scoring → Work.
Ces tests ne remplacent pas les reçus de publication et de recette live.
