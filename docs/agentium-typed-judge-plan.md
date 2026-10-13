# Agentium — plan du juge typé

État du code au 13 octobre 2026. Ce document décrit le contrat livré, ses limites
et les preuves nécessaires avant activation. Il complète le
[plan DataOps](agentium-dataops-plan.md), le
[protocole de qualification](ops/typed-judge-qualification.md) et le
[budget partagé des fenêtres](ops/service-window-budget.md).

Le juge `evaluate_v2` et son workflow de qualification sont implémentés. Les
tests locaux utilisent un transport fournisseur simulé : **aucun fournisseur,
profil métier ni corpus réel n'est qualifié par ce travail**. Le raccordement
prévu à **Gemini via OpenRouter est différé**. La narration est laissée de côté :
`narration_enabled=false`, Skill en bêta et parcours en brouillon. Sa présence
dans le code ne constitue aucune activation ni recette documentaire.

## 1. Lots et état de livraison

| Lot | Implémenté dans le dépôt | Condition restant à remplir |
| --- | --- | --- |
| J1 — questions et réponses | Contrats fermés, schéma compilé par rubrique, questions statiques publiées, réponses typées, abstention, validation des citations, persistance canonique | Choisir les questions, preuves et critères du premier usage réel |
| J2 — exécution gouvernée | Model Plane existant, contrôle d'accès, réservations durables, limites, usage mesuré, transport image inline et refus des routes non qualifiées | Raccorder puis qualifier réellement Gemini/OpenRouter ; vérifier modèle retourné, modalités, quotas, compteurs et tarif |
| J3 — qualification et approbation | Corpus immuable, annotations humaines indépendantes, séparation des familles, rapport, profil applicable et décision Work liée aux digests | Constituer et qualifier un vrai corpus selon des seuils métier préalablement fixés |
| J4 — recette d'exploitation | Tests de refus, reprise, budget partagé, revue et publication ; interfaces Flow/Runs/Work | Exécuter la campagne réelle sur l'environnement cible, conserver ses preuves et faire accepter le résultat par son responsable |

Le scoring de 2 à 3 millions de lignes emploie les contrôles déterministes de
schéma, cardinalité, complétude et prédiction native. Il ne déclenche aucun LLM
par ligne. Un juge éventuel porte sur un rapport ou une unité de preuve bornée,
avec son périmètre explicite. Le volume documentaire précédemment envisagé
(500 pages et environ 500 images) reste une cible différée, sans qualification
de débit ni de qualité revendiquée ici.

## 2. Contrat J1

Une unité contient `subject_ref`, `rubric_id`, `rubric_version`, les questions,
les preuves autorisées, un budget et un tarif référencé. `batch_key` identifie
le lot et `request_key` l'unité ; le wrapper les produit côté serveur. Pour un
Run de service, le lot est lié à la fenêtre et conserve ses engagements entre
tentatives. Une nouvelle tentative peut avoir une nouvelle clé d'unité : elle
n'obtient pas un nouveau budget de fenêtre.

Chaque question possède une clé stable et un texte explicite. Son type est
`boolean`, `choice`, `multi_choice`, `score` ou `probability`. Les choix sont
fermés ; un score déclare ses bornes ; une probabilité est dans `[0, 1]`.
`required`, `requires_evidence`, `acceptable_values` ou les bornes d'acceptation
décrivent la recette de la question. Les seuils métier ne sont pas déduits du
nom de la rubrique. Pour un choix multiple, `[]` peut signifier « aucune catégorie
observée » et demeure distinct d'une abstention.

Les plafonds du contrat sont 32 questions et 64 références de preuve par unité.
Le prompt, la sortie, les appels, les tokens, la durée et le coût ont des limites
explicites. Ces plafonds techniques ne sont pas des recommandations de taille
ou des garanties de qualité.

| Sortie d'une question | Signification |
| --- | --- |
| `answered` | Valeur du type attendu, raison `null`, explication courte et citations requises valides |
| `abstained` | Valeur `null`, raison explicite : `insufficient_evidence`, `ambiguous`, `out_of_scope` ou `unsupported_modality` |
| `invalid` | Réponse inutilisable ou exécution échouée ; valeur et confiance `null`, code d'erreur exploitable |

Une réponse JSON mal formée, une clé inattendue, un nombre non fini, une catégorie
inconnue ou une citation fausse invalide l'évaluation ; aucune réparation LLM
silencieuse n'est lancée. L'enveloppe `schema_version=2` conserve `evaluation_id`,
les hashes de rubrique et de preuves, `answers`, `status`, `quality_status`,
`coverage`, l'exécution de modèle et les mesures de coût/usage.

Trois notions restent séparées :

- `status=completed|partial|failed` décrit l'exécution et les réponses disponibles ;
- `quality_status=passed|failed|unassessed` applique les critères explicites aux
  questions requises ; terminer l'appel ne suffit pas à passer la recette ;
- `confidence` décrit une mesure empirique applicable au juge, jamais le score
  de qualité ni une probabilité que le modèle se serait attribuée.

La disposition reste `review`, y compris avec une réponse complète et un profil
qualifié. Une ligne canonique `EvaluationScore` conserve cette évaluation et son
identité ; les anciens scores composites non applicables restent `null`.

## 3. J2 : modèle, preuves et vision

La route est résolue par le Model Plane existant et contrôlée avant envoi.
L'entrée libre d'un Run ne peut fournir ni contexte privé, ni secret, ni route
de remplacement. Le tarif doit correspondre au fournisseur/modèle résolu. Le
juge désactive les replis et retries automatiques : un timeout ou une réponse
ambiguë ne justifie pas un second appel susceptible d'être facturé.

Les preuves proviennent d'actifs A1 immuables du même workspace. Le résolveur
serveur contrôle droits natifs, version, digest et hash du contenu sélectionné.
Un texte joint n'est accepté que s'il correspond à la preuve autorisée. Une
citation textuelle identifie cette preuve et un intervalle Unicode `[start,end)`
dont l'extrait doit être exact. Les contrôles sont rejoués avant l'appel et après
la réponse ; une révocation tardive retire le contenu rendu sans effacer le coût.

Les documents sont traités comme données non fiables, avec consigne d'ignorer
leurs instructions et sans outils accordés au modèle. Les octets image et les
identifiants secrets ne sont pas persistés dans l'évaluation. Ces mesures
réduisent les possibilités d'injection ; elles ne prouvent pas la justesse
sémantique d'une réponse ou d'une description d'image.

La vision exige une référence de route A1 explicitement qualifiée. Seuls les
octets d'images autorisées et vérifiées sont envoyés inline ; aucune URL arbitraire
du payload n'est téléchargée. La route borne nombre d'images, octets par image,
octets totaux, pixels et tokens réservés par image. Le code accepte PNG, JPEG
et WebP fixes ; formats, dimensions et animations sont vérifiés avant l'appel.

La citation image lie `evidence_id`, `image_sha256`, une région normalisée
`[gauche,haut,droite,bas]` ou `null`, et une description visible. Elle atteste la
référence citée, pas la véracité de la conclusion. Sans route applicable, la
vision est refusée ou rend une abstention explicite sans faux appel texte.
Une identité de modèle retourné manquante ou différente invalide la qualification
attendue ; le modèle configuré ne remplace pas cette observation.

Les chemins de transport actuellement testés concernent OpenAI/Azure. Cela ne
qualifie ni ces services réels ni Gemini/OpenRouter. Le lot futur doit employer
les points d'extension du Model Plane, prouver un vrai échange texte/image sur
la route retenue, puis produire la trace expurgée et la qualification humaine
décrites dans le runbook. Une qualification du transport ne qualifie pas la
qualité des réponses.

## 4. Budget, mesure et reprise

Les limites se cumulent : unité, lot du juge, route image et, pour un Run de
service, fenêtre partagée. Une réservation persistée précède chaque envoi ; son
calcul utilise les bornes de prompt/schéma/sortie, les réserves image et le tarif
figé. La concurrence est bornée avec les verrous existants. Les plafonds d'appels
et de tokens subsistent même avec un tarif explicitement nul.

Le ledger `service_window_budget_v1` réunit les étapes et les Runs d'une même
fenêtre. Les allocations d'étape facultatives ne peuvent dépasser son budget
global. L'autorité vient du lien Run → tentative → fenêtre en base, avec contrôle
de la lease, de la fence, du System et de l'échéance. Une réservation d'entrée
libre ne peut fabriquer cette autorité. Un worker périmé ne poursuit pas le
traitement ; une mesure tardive peut encore comptabiliser sa dépense originale.

Le coût `cost.amount` est calculé **à partir des compteurs fournisseur complets
et du tarif déclaré**. Sa méthode est `provider_tokens_at_declared_tariff` ;
`billed_amount` reste `null`. Ce montant n'est pas une facture reçue du fournisseur.
Sans compteurs complets, coût et usage inconnus restent `null` et la réserve
reste engagée. Un zéro explicite, notamment l'absence prouvée d'appel, est distinct
d'une absence de mesure. Une mesure partielle ne libère pas prématurément un
plafond distant.

Une reprise avec la même clé et le même contrat retrouve le résultat canonique
sans nouvelle dépense fournisseur. Une clé réutilisée avec un contenu différent
est refusée. Une unité restée `pending` demande une réconciliation ; elle n'est
pas relancée aveuglément. Les dépassements réels restent enregistrés, et une
facture contradictoire ou un budget dépassé bloque les admissions/publications
concernées. Les totaux du ledger et du Run ne sont jamais additionnés comme deux
dépenses distinctes. Voir les règles détaillées dans le
[runbook des budgets](ops/service-window-budget.md) ; ses exemples mixtes ne
constituent pas une activation de la narration.

## 5. Qualification humaine indépendante

L'API `/api/v1/typed-calibration` permet de créer un corpus, annoter ses unités,
attacher les évaluations canoniques, lire le rapport puis qualifier un profil.
Elle utilise l'identité authentifiée et les droits du workspace. Les créations
de corpus/routes et leur qualification sont administrées ; aucun identifiant
d'annotateur déclaré par le client ne remplace l'identité de session.

Le protocole à exécuter sur les futures données réelles est le suivant :

1. Figer rubrique, questions, critères, modèle configuré/retourné, source, langue
   et tâche. Déclarer volumes minimaux, défauts critiques, seuils de précision,
   rappel, couverture, erreurs critiques manquées et borne de confiance. Déclarer
   Brier/ECE quand applicables et tolérances des scores ; aucun seuil métier
   n'est inventé par le logiciel.
2. Enregistrer des unités A1 et leurs familles documentaires dans les partitions
   `dev`, `calibration`, `test`. Pages, révisions et dérivés d'une famille restent
   ensemble ; les hashes de contenu sont également contrôlés. Le test doit être
   indépendant, avec au moins deux familles dans chacune des partitions de
   calibration et de test. Un test déjà exposé ne peut devenir le test neuf d'un
   réglage ultérieur.
3. Faire annoter calibration/test par deux personnes distinctes avant leur
   évaluation par le juge. Une divergence exige l'adjudication d'une troisième
   personne. Conserver notes et identités immuables ; une vérité de référence
   inconnue bloque la qualification. Organiser la revue en aveugle : le serveur
   vérifie provenance et chronologie, pas les échanges hors plateforme.
4. Exécuter le juge sans profil qualifié sur ces mêmes unités, puis attacher les
   `evaluation_id` existants. L'API ne reçoit pas de réponses modèle inventées
   par l'appelant et refuse la sélection d'une seconde tentative plus favorable.
5. Examiner toutes les unités attendues et les rapports calibration/test :
   précision, rappel, couverture, défauts critiques manqués, tailles des groupes,
   Brier/ECE lorsque les observations existent. Une abstention sur une référence
   contenant un défaut critique compte comme un défaut manqué.
6. Qualifier uniquement si tous les critères figés passent. Le profil A1 immuable
   lie modèle, rubrique, contexte, corpus, annotations, prédictions et rapport.
   Un changement, une révocation ou une liaison manquante retire son applicabilité.

La confiance disponible est une borne inférieure empirique de Wilson à 95 % sur
l'événement « toutes les réponses requises de cette famille sont correctes ».
La famille est l'unité statistique ; ses pages ne deviennent pas artificiellement
des observations indépendantes. Cette mesure conservatrice est liée à la
population qualifiée et ne garantit pas une réponse particulière. Sans profil
concordant, `confidence=null`. Le minimum des confiances de plusieurs unités
n'est pas une confiance calibrée pour le lot entier.

J2450 est le premier protocole documentaire préparé, pour **les erreurs de
traduction** : catégories `WT`, `SE`, `OM`, `SA`, `SP`, `PE`, `ME`, en choix simple
ou multiple. Il exige source, traduction et références autorisées. Il ne fournit
ni score général de narration ni score pondéré SAE improvisé. La campagne J2450
réelle est différée avec le parcours documentaire.

## 6. Flow, Work et compatibilité

L'inspecteur Flow conserve une configuration structurée `typed_evaluation` avec
questions statiques, critères, budget, tarif et références A1 de profil/route.
La publication fige son schéma ; le DAG injecte le bloc privé `_typed_evaluation`
depuis le graphe autorisé. Seuls sujet et preuves prévus peuvent venir des sorties
amont. Les interfaces Runs exposent réponses, preuves, couverture et besoin de
revue ; elles ne transforment pas un score en confiance.

`evaluate_v1` reste une Skill versionnée distincte. Aucun remplacement de sens
ou migration silencieuse des graphes publiés n'est effectué. Adopter v2 exige
de configurer ses questions, adapter les bindings de sortie, valider puis publier
une nouvelle version du System. Les anciens Runs restent lisibles avec leur
contrat d'origine.

Le moteur de service possède l'approbation et la livraison. La complétude
technique, la qualité, les seuils, le budget et les droits sont vérifiés avant
publication. Une confiance inconnue ne déclenche aucune acceptation automatique.
La revue Work porte sur la fence, le digest du candidat et celui de sa
qualification effectivement présentés. Une modification concurrente impose une
nouvelle revue. Le reçu prouve la livraison de cette version exacte ; il
n'élargit pas les droits de lecture de ses objets.

## 7. Conditions de recette et limites de preuve

| Recette | Preuve attendue |
| --- | --- |
| Contrats | Tous les types, multi-choix vide, abstention et invalidité ; refus des champs/valeurs inconnus et citations fabriquées |
| Autorisations | Refus inter-workspace, source révoquée, hash modifié, contexte privé issu du payload et route vision non qualifiée |
| Transport | Requête image inline vérifiable, modèle retourné observé, plafonds effectifs et trace réelle expurgée ; tests simulés insuffisants pour qualifier le fournisseur |
| Mesures | Coût inconnu `null`, zéro prouvé, tarif lié au modèle, consommation conservée après timeout, dépassement et refus avant appel |
| Reprise | Identité stable, résultat sans double appel, unité ambiguë à réconcilier, cumul entre Runs, refus de fence périmée |
| Calibration | Identités indépendantes, partitions sans contamination, absence de sélection des essais, calculs vérifiés et invalidation après changement modèle/rubrique/contexte |
| Livraison | Candidat techniquement complet, politique satisfaite, revue liée aux bons hashes, reçu idempotent et octets exportés vérifiés |

Les tests de référence sont `test_typed_judge.py`, `test_typed_vision.py`,
`test_typed_calibration.py`, `test_model_execution.py`, `test_window_budget.py`
et `test_service_contracts.py`, sous `backend/app/tests/services/`. La recette
réelle de scoring publié jusqu'au reçu/export est dans
`test_dataops_published_pipeline.py` ; elle n'atteste aucun appel de juge réel.
Les commandes et exemples API sont dans le
[runbook de qualification](ops/typed-judge-qualification.md).

Pour une future recette documentaire, `coverage` rapproche le périmètre déclaré
et traité ; il ne prouve pas que chaque défaut a été reconnu. Les défauts
critiques doivent être cherchés sur l'inventaire complet, découpé en unités
bornées. Un contrôle échantillonné ne devient pas une preuve sur toutes les pages.
La qualification doit conserver résultats réels, tailles des corpus, coûts
mesurés, refus, rapport signé et révision du code exécutée.

## 8. Fichiers de référence

| Responsabilité | Chemins dans le dépôt |
| --- | --- |
| Contrats et compilation | `backend/app/schemas/typed_evaluation.py` |
| Exécution et confiance | `backend/app/services/evaluation/typed_judge.py`, `typed_calibration.py` |
| API de qualification | `backend/app/api/v1/endpoints/typed_calibration.py` |
| Modèle gouverné | `backend/app/services/model_plane/execution.py` et clients existants |
| Actifs, budget, approbation | `backend/app/services/governed_assets.py`, `window_budget.py`, `service_promises.py`, `service_engine.py` |
| Intégration Flow | `backend/app/services/skills_registry/wrappers/skills.py`, `backend/app/services/run_engine/dag.py` |
| Interfaces | `frontend-ng/src/app/features/orchestration/flow/flow-dataops-inspector.component.ts`, `features/runs/skill-invocation-view.component.ts`, `features/experience/work/service-delivery.component.ts` |
