# Étendre le parcours Luma avec qualité, événements et suivi du modèle

Procédure mise à jour le **19 octobre 2026**. Le [plan historique](reviewed_plan.json)
et sa [revue](reviewed_plan.review.json) datent du 17 octobre, portent
`applied=false` et `activation_ready=false` et sont **obsolètes pour l'application**.
Ils ne sont pas un reçu d'activation. Reconstruire depuis les lectures fraîches :
la publication Luma v5, le brouillon Flow r25 et la release Work 4 ont depuis été
alignés sur le modèle SLA v5, avec une inférence épinglée réussie. La lecture
PostgreSQL est également rétablie. Le plan reconstruit reste un candidat pour
revue jusqu'aux reçus de publication et d'exécution.

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
10 USD / million sortants**, contrôlé le 19 octobre sur la
[fiche officielle](https://developers.openai.com/api/docs/models/gpt-5).
La remise de cache n'est pas incluse dans cette estimation. Le budget est borné
à un appel, 40 000 tokens, 2 048 tokens de sortie, 0,07 USD, 45 secondes et
32 000 octets de prompt ; un dépassement doit être refusé. La route réellement
résolue doit correspondre au tarif, sans fallback silencieux. Aucun profil de
calibration ni qualification du fournisseur sur le corpus Luma n'est annoncé.
Le score de qualité ne constitue pas une confiance calibrée.

La projection de politique utilise `/citations` et `/references` : les passages,
identifiants de document, page, fragment et empreinte sont conservés sans les
métadonnées de recherche redondantes de `/results`. Le plafond par source reste
32 000 octets. Sur le Run contrôlé le 19 octobre, le prompt reconstruit représente
28 407 octets ; la réservation conservatrice, qui inclut aussi le schéma de sortie,
la marge technique et les 2 048 tokens de sortie, représente 37 931 tokens et
0,06533375 USD. Cette réservation n'est ni une consommation mesurée ni une facture.
Le registre d'invocations reste la source des tokens effectivement rapportés et
des coûts associés ; les coûts inconnus restent inconnus. Ces bornes autorisent
l'essai contrôlé, sans établir de calibration ou de qualité acquise.

Qualification du 19 octobre : une enquête ayant passé ces bornes atteint la
validation humaine, mais le Judge rend `failed / JUDGE_PROVIDER_UNAVAILABLE`
avec zéro réponse sur cinq après un `BadRequestError`. Une invocation terminée
ne constitue donc pas une évaluation réussie. Le schéma compilé a été corrigé
pour déclarer explicitement le type et l'énumération de la citation image,
conformément au [sous-ensemble Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
relu le 19 octobre. Le mode strict et la validation locale des valeurs et des
citations restent actifs. Le corps de la réponse HTTP 400 n'étant pas conservé,
la correction de ce défaut de contrat doit encore être requalifiée en live ;
aucun résultat positif ni cinq réponses valides ne sont présumés.

La boucle MLOps conserve les versions et leurs artefacts. Cette extension garde
l'épingle SLA actuelle : elle refuse un autre modèle ou une autre version, même
si son inférence réussit. Monitoring, shadow, feedback et proposition de réentraînement utilisent
les fonctions produit de Model Center, décrites dans le
[guide d'activation MLOps](../../../../agentium-mlops-activation.md).
Chronos reste hors du réentraînement automatique ; aucune observation future
ni clôture humaine n'est ajoutée pour alimenter artificiellement les courbes.

## Préparer un plan applicable

1. Déployer la livraison finale sur API, workers et frontend ; comparer leurs
   révisions et réconcilier le catalogue. Vérifier `evaluate_v2`, les sources
   webhook/schedule et le snapshot de preuves. La livraison précédente seule
   ne constitue pas un reçu de configuration de ce parcours.
2. Vérifier la lecture PostgreSQL avec le compte limité déjà configuré, pour
   un dossier et la file. Conserver les réglages TLS et les credentials existants.
3. Inspecter l'artefact/serving du modèle SLA actuellement épinglé, puis
   effectuer une inférence **épinglée à cette version**, contrôler `served.model_id`,
   `served.version`, les colonnes, le label positif `1` et `prediction_id`.
   `status=ready` seul ne suffit pas. Ne pas promouvoir pour passer ce contrôle.
4. Faire de nouvelles lectures autorisées et enregistrer les snapshots suivants
   au format `{ "status": 200, "data": ... }` :

   | Fichier | Lecture |
   | --- | --- |
   | `flow-state.json` | `/systems/{system_id}/flow-state` |
   | `work-live.json` | `/work/reclamations` |
   | `experience.json` | `/experiences/4c93ae4b-f2de-438d-b781-bb69a4cb962c` |
   | `work-release.json` | élément dont l'ID correspond à `/work` dans `/experiences/{experience_id}/releases` ; conserver le snapshot complet |
   | `binding-investigate.json` | `/system-bindings/showcase.claims.investigate` |
   | `binding-queue.json` | `/system-bindings/showcase.claims.refresh_queue` |
   | `binding-forecast.json` | `/system-bindings/showcase.claims.forecast` |
   | `collections.json` | `/documents/collections` |
   | `model-sla.json` | `/ml-models/{current_pinned_model_id}` |
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

   Le constructeur refuse une déclaration de fournisseur/tarif/budget incomplète, un modèle
   incompatible, une inférence absente ou provenant d'une autre version, une
   dérive des bindings/triage, une politique de contrôle de draft non publiée
   ou une divergence d'accès/métadonnées entre Experience et release Work.
   Il conserve séparément les modifications de pages du brouillon Work et les
   nœuds, positions et libellés du brouillon Flow. Il refuse un autre modèle,
   une autre épingle dans un brouillon ou l'écrasement d'un fichier de plan existant.
   `--allow-blocked` produit uniquement
   un candidat annoté pour revue lorsque le serving ou son essai manque ; il
   ne permet pas l'activation. La revue hors ligne ne dispense pas des contrôles
   PostgreSQL, fournisseur, autorisations, catalogue et workers ci-dessus.

## Publier sans perdre le draft utilisateur

Ne pas rejouer `activate_ecommerce_composition` ni l'ancien plan du 9 octobre :
ils créent des bindings qui existent déjà et retirent les anciens Systems.
Ici aucun autre System métier n'est créé ou retiré.

L'état lu le 19 octobre est la publication v5
`f3fc70cd-0a51-4719-bbf3-ce30d787f4d4`, le brouillon Flow r25 et la release Work 4
`6b45b6f2-8688-4b8b-a76d-deb9508956e9`. Ces identifiants sont un repère de
lecture, jamais des valeurs à forcer lors d'une exécution ultérieure.
Le brouillon Flow contient le nœud non publié `flow.mv95zi21.1` (Prepare).
`backup.flow_draft` conserve son contenu ; `preserved_draft_candidate` lui ajoute
la même extension sans le supprimer. Seul `publication_candidate`, construit
depuis la publication, est destiné à être publié. De même, `work_pages` reprend
la release live et `preserved_work_draft_pages` conserve le brouillon distinct,
avec ses propres `preserved_work_draft_binding_keys`.

Les templates de requêtes sont dans `request_templates` ; les références
`$response.*` doivent être remplacées par les réponses réelles, jamais envoyées
telles quelles. Si d'autres compléments revus sont composés sur ce plan
(préparation visuelle ou prévision, par exemple), les appliquer aux deux graphes
et aux pages concernées **avant** de valider le graphe final, recalculer les
empreintes et reconstruire les templates. L'empreinte d'un candidat intermédiaire
n'est pas celle du graphe final.

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
   `{flow_definition: plan.preserved_draft_candidate, expected_revision: <response.flow_publish.draft.revision>}`.
   Le contenu utilisateur est conservé dans un draft actualisé, avec son node
   Prepare toujours non publié. Relire ce draft et comparer son contenu au plan.
   Si l'étape 3 échoue, restaurer `backup.flow_draft.flow_definition` via PUT
   **uniquement** avec la révision courante attendue de l'étape 2 ; ne pas
   écraser une édition survenue entre-temps.
5. Pour chacun des trois bindings, relire et comparer au snapshot avant
   `PATCH /system-bindings/{key}` avec
   `{published_flow_version_id: <nouvelle version>}`. Garder les autres champs
   inchangés, notamment les politiques de confirmation et d'indisponibilité.
   Les trois actions restent sur la même publication. L'API de binding ne porte
   pas de champ CAS ; la relecture et l'absence d'édition concurrente sont donc
   nécessaires pendant cette étape. Vérifier les trois résolutions après écriture.
6. Mettre à jour **seulement** `settings.ecommerce_claims.triage`. La voie API
   actuelle est `PATCH /auth/workspaces/{slug}` et ne possède pas de CAS pour
   les settings. Juste avant l'écriture, relire les réglages publics complets
   en mémoire, comparer le triage à `plan.preconditions.triage`, puis copier
   ces réglages et remplacer ce seul sous-objet par `triage_after_publication`.
   Résoudre `$response.flow_publish.published.version_id`, contrôler strictement
   les seuls chemins modifiés et vérifier la publication courante/version/hash.
   Envoyer les settings publics complets, puis relire et comparer le résultat.
   Ne pas envoyer le seul fragment `triage` : cela remplacerait les autres
   réglages publics. Ne jamais mettre les settings complets, tokens ou secrets
   dans les fichiers de préparation. Le serveur conserve les secrets masqués.
   Cette séquence exige une fenêtre sans autre édition de settings ; la relecture
   ne fournit pas de protection atomique contre un autre client concurrent.
   Une transaction opérateur ciblée peut fournir cette protection si elle est
   disponible, mais n'est pas un prérequis de la voie produit API.
7. `PUT /experiences/{experience_id}/draft` avec `pages: plan.work_pages`,
   `binding_keys: plan.work_binding_keys` et la révision Work attendue du plan.
   La navigation et les composants publiés sont conservés, de même que leur
   épingle SLA. Lire `/ready-check`, exiger `ready=true` et aucun blocker,
   examiner les warnings et créer une release avec
   `expected_draft_revision`, `expected_content_sha256`,
   `expected_experience_updated_at` et `expected_bindings_sha256` issus de ces
   lectures. `expected_experience_updated_at` reste celui de l'Experience revue
   dans le plan ; ne pas adopter une valeur concurrente pour forcer la création.
8. Restaurer le brouillon Work distinct avec
   `PUT /experiences/{id}/draft`, `pages: plan.preserved_work_draft_pages`,
   `binding_keys: plan.preserved_work_draft_binding_keys` et
   `expected_revision: <response.work_draft_save.revision>`. La création de
   release ne change pas cette révision. Ne pas prendre une révision plus récente
   pour écraser une modification utilisateur. La release est immuable : cette
   restauration ne change pas son contenu.
9. `POST /experiences/{id}/deployments` utilise `channel: "live"`, l'ID
   de cette release, `expected_current_release_id` et
   `expected_deployment_updated_at` de `preconditions.deployment`, avec son
   audience conservée. Le reçu doit identifier la release et ses trois bindings.
   Relire Work, les trois bindings, le triage, la publication et les deux brouillons
   avant de mettre les déclencheurs en service.

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
   pause, installer son secret uniquement chez l'émetteur. Après déploiement
   de la migration `141_event_execution_principal` et du worker correspondant,
   choisir explicitement « Utiliser mes accès » sur le hook et le planning.
   Les droits portent sur la publication revue ; refaire ce consentement si
   cette publication change avant l'essai. Sans identité déléguée, le scoring
   ML et la capture de preuves Judge refusent les Runs automatiques. Ne pas
   recopier l'identité d'un ancien Run dans le payload pour contourner ce refus.
   Activer l'opt-in
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
   qualification, utiliser un cron borné au jour et au mois de l'essai
   (`minute heure jour mois *`), avec timezone explicite et échéance encore future,
   plutôt qu'une cadence chaque minute. Il n'existe pas de champ produit `run_at`.
   Vérifier `next_fire_at`, puis observer **un** tick réel et le changement de
   `last_run_id`/`last_fired_at`. Désactiver immédiatement le schedule avant de
   suivre l'achèvement du Run ; une exécution lente ne déclenchera pas une suite
   de ticks de qualification. Relire la pause, puis restaurer la cadence finale
   revue ou laisser en pause. Les PATCH de schedule n'ont pas de CAS : comparer
   la configuration avant et après, sans édition concurrente.
   Le cron n'est pas arrêté par le mode
   `dry_run` ou le coupe-circuit des événements. Son dernier Run doit produire
   la file scorée visible dans Work, sans enquête ni reçu. Ne pas laisser une
   récurrence tourner tant que PostgreSQL ou le modèle échoue.

## Fermer la boucle MLOps avec des preuves

Le helper Judge/événements ne configure ni monitoring, ni shadow, ni promotion.
Au 19 octobre, le SLA v5 possède déjà un monitoring quotidien et une proposition
de réentraînement en attente humaine : les conserver, notamment la cadence et
`propose_retraining`. Ne pas rejouer les anciens exemples à 60 minutes du plan
historique. Observer son System technique, ses Runs et ses erreurs dans Model
Center ; il ne constitue pas un second System métier Luma.

Identifier ensuite le challenger réellement compatible et qualifié par
inférence. Conserver le champion existant et expliciter toute décision ultérieure.
Activer shadow seulement quand cette paire est valide,
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

Tests locaux : transformations/contrats, séparation des drafts et protections
des publications dans ce dossier, plus tests backend de routage immuable et
trajet réel cron → préparation/scoring → Work.
Ces tests ne remplacent pas les reçus de publication et de recette live.
