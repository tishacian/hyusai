# Luma — qualification en service sur a2be58d1

Le 22 octobre 2026, le pilote Work a atteint la validation humaine avec les
**cinq critères du Judge satisfaits**. Ses onze appels fournisseur sont visibles
dans Usage. Le plafond de **2 000 EUR par mois sur Showcase entier, Luma inclus**
est actif depuis 13:24:17 UTC. La campagne de 48 exécutions est lancée et reste
**en cours** dans le relevé initial ci-dessous ; aucun bilan de réussite de cette
campagne n'est encore établi.

Cette note constate l'état après la
[préparation de la livraison](luma-usage-qualification-2026-10-22.md). Elle ne
modifie pas le [runbook produit](model-quality-usage-release-2026-10-22.md).
Les heures ci-dessous sont en UTC, sauf le fuseau explicitement indiqué pour
le budget. Le relevé initial de campagne correspond au démarrage du job à
13:25:01 ; ses résultats finaux doivent être ajoutés après contrôle.

## Révision et admission des appels

L'API annonce la révision vérifiée
`a2be58d1689a4c9e8071039ed9fc6c9580fe74c4`. L'attestation Usage enregistrée à
`2026-10-22T13:14:37.573419Z` retourne `ready=true`,
`USAGE_ADMISSION_READY`, sans transport manquant dans son contrat de livraison.

Cette readiness repose sur une **déclaration opérateur**
(`attestation_basis=operator_declaration`) pour l'API, les workers CPU et
DataOps, le runner de connecteurs et l'agent LiveKit. Ce n'est pas une découverte
automatique de l'état de tous les processus. La garantie annoncée est
`admission_at_configured_tariffs_and_bounds` : admission aux tarifs et bornes
configurés, pas plafonnement d'une facture fournisseur externe.

## Pilote Work et Judge

L'enquête du dossier fictif **RC-5003** a été lancée depuis l'expérience publiée
`reclamations`, binding `showcase.claims.investigate`. Le Run
`3ec3dc31-dd94-4574-8f3c-a3b3207333b9` a démarré à 13:15:22 et conserve le statut
`hitl_pending`, sur `hitl.review`. L'action attend la décision humaine ; le Run
n'est pas présenté comme terminé ni comme un remboursement exécuté.

Le Run utilise la publication **v10**
`b8eb64d3-e417-41bf-898a-7b1ad232d64a`, hash
`77d4d521a3526fce8a25ee125ddf010976d637f2f2335d8afee98f1a4dbd09f0`.
Treize invocations sont terminées : préparation du dataset, préparation visuelle,
scoring ML, contexte SAV, quatre décisions de l'agent, consultations PostgreSQL
et documentaires, proposition puis Judge.

L'évaluation `924630c0-2e2f-4db2-aa7f-61f2b2a20d3b`, rubrique
`claims-resolution-review` v1, est techniquement terminée et porte
`quality_status=passed`. Les cinq réponses portent `status=answered`, `value=true` :

- preuves étayées ;
- respect de la politique ;
- montant et absence de remboursement en double ;
- contradictions traitées ;
- incertitude et validation humaine respectées.

La couverture conservée est de **5 questions sur 5** et **3 ensembles de preuves
sur 3**. La disposition reste `review`. La confiance est absente avec le motif
`calibration_not_qualified` : ce pilote ne qualifie pas une calibration du Judge
ni un taux de justesse sur une population de dossiers.

## Usage du pilote, avant tarifs EUR et plafond actif

Les onze appels du pilote ont précédé la création des tarifs EUR et l'activation
du plafond. Leurs snapshots USD restent inchangés. Le relevé Usage de 13:24:32
est complet pour les appels conservés de ce Run, sans reconstruction historique.

| Mesure | Valeur constatée |
| --- | ---: |
| Appels envoyés / terminés | 11 / 11 |
| Appels échoués, inconnus, bloqués ou en attente | 0 |
| Tokens d'entrée | 48 928 |
| Tokens de sortie | 3 769 |
| Tokens totaux | 52 697 |
| Tokens d'entrée en cache | 16 128 |
| Tokens de raisonnement | 2 560 |
| Coût calculé couvert | 0,080558400000 USD ; 11/11 appels |

| Usage | Appels | Tokens totaux | Coût calculé USD |
| --- | ---: | ---: | ---: |
| Décisions de l'agent, GPT-5 | 4 | 43 077 | 0,062092250000 |
| Judge, GPT-5 | 1 | 9 500 | 0,018463750000 |
| Embeddings, text-embedding-3-small | 6 | 120 | 0,000002400000 |

Cache et raisonnement sont des sous-ensembles des compteurs d'entrée et de sortie,
pas des tokens supplémentaires à additionner. Les quatre décisions de l'agent
ont cette fois une réservation de tokens et de montant non nulle dans le journal.
Ce pilote précède toutefois l'activation : il ne constitue pas, à lui seul, une
recette du refus lorsque le plafond EUR est atteint.

La base de coût est `provider_tokens_at_versioned_tariff` ;
`billed_amount=null`. Ces montants calculés ne sont ni une facture, ni une mesure
de temps humain, ni une preuve d'économie ou de ROI réalisé.

## Tarifs EUR et budget workspace actif

Les sources OpenAI et BCE ont été reconsultées le 22 octobre à 13:14 UTC, avec
quatre réponses HTTP 200. Le dernier taux servi par le flux quotidien BCE est
daté du **21 octobre 2026** : **1 EUR = 1,1234 USD**. La conversion enregistrée
est **0,890154886950 EUR par USD**, inverse arrondi moitié paire à 12 décimales,
puis multiplication et arrondi moitié paire à 12 décimales.

| Modèle OpenAI | Version EUR créée | Entrée EUR/M | Cache EUR/M | Sortie EUR/M |
| --- | ---: | ---: | ---: | ---: |
| gpt-5 | 2 | 1,112693608688 | 0,111269360869 | 8,901548869500 |
| text-embedding-3-small | 2 | 0,017803097739 | non déclaré | 0 |
| gpt-4o-mini | 1 | 0,133523233042 | 0,066761616521 | 0,534092932170 |

Ces versions ont été créées entre 13:19:11 et 13:19:31. Les tarifs USD originaux,
les sources et leurs dates sont conservés dans la provenance. Les prix sont ceux
des appels synchrones standard, sans remise Batch. La sortie embedding est un
zéro technique, ce protocole ne produisant pas de tokens de complétion. La
conversion est une convention interne datée, pas un tarif fournisseur facturé en
EUR ni un change automatiquement actualisé.

La politique `ea7877f3-7f31-4ff6-ab38-88c92ed5260c`, **révision 2**, a été activée
à `2026-10-22T13:24:17.281044Z` et relue active :

- périmètre `workspace`, sans restriction à Luma ;
- limite de **2 000 EUR**, sans plafond de tokens supplémentaire ;
- mois calendaire dans le fuseau `Europe/Paris` ;
- première période de l'activation au `2026-10-31T23:00:00Z` ;
- `reconciliation_required=false` lors de la relecture initiale.

Les compteurs étaient à zéro lors de l'activation, avant la campagne. Ce relevé
ne décrit pas leur consommation ultérieure. Les appels USD du pilote ne sont
pas convertis ni réaffectés rétroactivement à cette première période.

Un tarif ne qualifie pas un transport : Ollama/vLLM, vision, outils hébergés et
voix LLM temps réel restent refusés sous plafond faute de contrat d'admission
qualifié. STT/TTS sont hors de ce budget LLM. Un modèle textuel sans tarif dans
la devise plafonnée ou sans borne de sortie est également refusé avant envoi.

## Campagne de non-régression lancée, résultats en attente

| Référence | Valeur |
| --- | --- |
| Campagne | `5a8a9d28-e30b-4eff-9efa-56b0fe840d6d` |
| Job | `b947d818-14a3-4178-84ff-1d8b10338041` |
| Suite | `7ff7e53f-f9fc-4df1-827b-c31ff84714da`, révision 1 |
| Baseline | `082748bb-f83c-4f73-895c-5efbd6287f32` |
| Brouillon candidat lu par le préflight | révision 38 |
| Méthode | `server_assertions` |
| Mode | `qualified_prefix`, arrêt à la frontière humaine |
| Volume prévu | 12 dossiers × 2 versions × 2 répétitions = 48 Runs |
| État au démarrage | `running`, étape `canonical_runs`, aucun résultat final |

Le préflight final est éligible, sans issue bloquante. Son hash est
`033333e2d8409dd7cdd561c8bac4d52c0304a231c48ff30380eba56e3424b21c`.
Il qualifie le préfixe retenu sans sauvegarder ni réparer le brouillon utilisateur.
Les relevés avant campagne conservent séparément le Flow, le binding publié,
le modèle SLA, les datasets métier et les douze dossiers.

Les six familles couvrent la contradiction de livraison, la perte confirmée,
le remboursement en double, les preuves manquantes, la politique et sa
provenance, puis le conseil ML et l'autorité humaine. Les assertions portent
sur la proposition et la trajectoire, dont PostgreSQL, DataOps, scoring,
décisions de l'agent, Judge et arrêt avant action métier. Ce sont les contrôles
**prévus**, pas encore leur résultat.

La comparabilité annoncée est `limited` : les empreintes de collections sont
conservées, mais les révisions externes de modèles et la recherche documentaire
en direct ne sont pas immuables. Ce corpus déjà examiné sert à la répétabilité
et à la non-régression ; il n'est pas un holdout aveugle. La méthode enregistrée
ne constitue pas un résultat Giskard ni une qualification de calibration.

## Preuves et clôture à compléter

### Relevé intermédiaire à 13:51 UTC

La campagne a sept Runs terminaux sur 48 : quatre satisfont les assertions,
un ne les satisfait pas et deux restent non évalués. Un huitième est en cours,
quarante attendent. Ce n'est pas un bilan final. Le premier essai passe ses
14 assertions de sortie, ses 12 contrôles de trajectoire et le Judge, puis
s'arrête à la frontière humaine prévue (`cancelled`, `termination=human_gate`).
Ses 11 appels sont valorisés à **0,065231404665 EUR**, pour **53 134 tokens**.

Le scoring du deuxième essai, recette `ad11cb3216bf4849c2c25dd0cb722adb353f`,
est resté bloqué après son départ à 13:26:52. La campagne a repris après cet
incident et conserve son échec. Le diagnostic opérateur a ensuite établi la
cause : la transaction du Judge CPU retenait le verrou de workspace pendant
l'appel fournisseur et l'admission d'usage réclamait un verrou incompatible.
La terminaison ciblée de la session PostgreSQL 324529 a libéré le traitement
à 13:42:48, après 956 secondes d'attente. L'essai avait déjà dépassé son délai :
son échec doit rester dans la campagne, avec une nouvelle tentative distincte.
Les piles et verrous opérateur sont conservés sous
`/srv/agentium-data/deployments/incident-20261022T1326Z-dataops-score/`.

Le candidat RC-5003 s'arrête à une demande humaine sans produire la proposition
attendue : ses assertions de sortie échouent, sans verdict Judge. Ce n'est pas
un Judge déclarant une proposition incorrecte. Les contrôles d'absence d'action
métier restent satisfaits. La baseline du même dossier a produit une proposition,
mais son contrôle Judge a échoué techniquement et reste non évalué.

Les traces précisent ces deux causes. Le quatrième appel de décision du candidat
rencontre `APIConnectionError` sur GPT-5 ; le secours Ollama est refusé avant
envoi, puis la boucle demande un humain. La baseline rencontre
`JUDGE_PROMPT_TOO_LARGE` : reconstruction de **32 149 octets pour une limite de
32 000**, contre 29 737 pour le pilote. Les passages documentaires sont plus
longs. Aucune limite ni preuve n'est modifiée pendant la campagne. Ces deux
résultats ne mesurent pas une erreur de raisonnement du Judge.

Les lectures après le premier essai confirment : Flow r38, publication v10,
binding d'enquête, datasets métier et état de serving SLA identiques à l'état
après pilote. Les données et reçus RC-5003 restent identiques ; seule la date
de lecture de provenance varie. Cela ne remplace pas le contrôle final des
douze dossiers après campagne.

### Relevé de préservation à 14:14 UTC

La campagne conserve 19 essais terminaux : 14 `passed`, 1 `failed`, 4
`unevaluated`, avec 1 Run en cours et 28 en attente. Les deux nouveaux refus
Judge de RC-5005 et RC-5009 sont aussi `JUDGE_PROMPT_TOO_LARGE`. Aucun budget
de preuve, critère, version de Flow ou manifeste n'est modifié pendant l'essai.

Les douze dossiers RC-5001 à RC-5012 ont été relus : leurs champs `data` et
`receipts` sont identiques aux relevés avant campagne. Les réponses complètes
Flow r38 et version publiée v10 sont également identiques. Ce contrôle est un
point intermédiaire ; il ne remplace pas la comparaison à la clôture.

### Écran « traitement non abouti » de RC-1042

Le Run `612a4abf-7a54-4965-ad7d-26606d77f3e6` attendait `hitl.review` depuis
le 19 octobre. Sa demande a expiré après 72 heures, le 22 octobre à 13:59:53
UTC. La décision `4e465cdb-9d6e-4798-a44e-2b91388d8a1a` est `rejected`,
avec `approved_by=system:gate_ttl`. La reprise à 14:00:32 a néanmoins atteint
`ecommerce_resolution_simulate_v1`, qui a refusé l'action avec
`CLAIM_HUMAN_APPROVAL_REQUIRED`.

Il s'agit d'une expiration de validation, pas d'un verdict de qualité du Judge
ni du blocage DataOps précédent. Le reçu antérieur n'atteste pas cette tentative.
Les preuves minimales sont dans
[expired-approval-evidence.json](../evidence/luma-live-qualification-a2be58d1-2026-10-22/expired-approval-evidence.json).

### Correctifs produit à livrer et reprise de recette

Le lot ferme les transactions avant l'appel du Judge et remplace le verrou
workspace de l'admission d'usage par `FOR NO KEY UPDATE`. La sérialisation des
budgets reste vérifiée, sans bloquer les insertions qui référencent le workspace.
Les redélivrances Judge restent exclusives pendant l'appel fournisseur.

La reprise ciblée d'un essai crée un Run et un job distincts, liés au résultat
initial. Le Flow et son contrat viennent de l'exécution figée, sans relire le
brouillon utilisateur. Le corpus, les modèles et les droits sont revalidés.
Les tentatives supplémentaires restent séparées des 48 mesures initiales.
Le refus sur une porte humaine sans route de rejet explicite arrête la
continuation ; il ne tente plus l'action protégée. Work distingue l'expiration,
le rejet, l'échec attesté et une lecture momentanément indisponible.

Procédure après livraison :

1. Conserver les preuves de campagne et les relevés Luma. Ne pas interrompre
   le processus de campagne en cours pour une recréation de worker ; attendre
   sa fin ou organiser une reprise contrôlée de ses tâches avec l'opérateur.
2. Déployer le commit accompagnant ce document sur l'API, le frontend et les
   workers concernés, selon le processus de livraison habituel. Ce lot n'ajoute
   ni migration ni drapeau et ne rejoue pas l'installation Luma.
3. Vérifier la révision et renouveler l'attestation Usage seulement après
   confirmation opérateur des cinq composants, workers recréés et sessions
   LiveKit drainées. Le plafond existant reste à 2 000 EUR ; pas de second budget.
4. Dans Observabilité → Qualité → Tests, ouvrir la campagne
   `5a8a9d28-e30b-4eff-9efa-56b0fe840d6d`. Reprendre uniquement le candidat du
   premier cas RC-5001, essai initial `2f54f016-e707-4f4f-aea3-b4718f243093`.
   Conserver l'échec initial et vérifier le nouveau Run jusqu'à la frontière
   humaine, sans action. Une réponse réseau perdue se vérifie avec la même clé
   de demande, pas avec une nouvelle tentative.
5. Recontrôler le pilote, le message d'expiration de RC-1042, les coûts et la
   préservation de r38/v10, bindings, modèles et reçus. Ne pas transformer les
   échecs historiques en réussites. Une nouvelle enquête métier reste distincte
   de l'ancienne approbation expirée.

Une reprise de campagne dont le worker s'arrête après sa prise en charge reste
`running` jusqu'au diagnostic opérateur : elle n'est pas relancée automatiquement,
afin de ne pas doubler les appels d'une exécution dont l'issue est inconnue.

Validation du lot avant livraison :

- Transactions Judge et admission Usage : 65 tests ciblés passent, dont les
  régressions sur PostgreSQL réel ; aucune transaction ouverte pendant l'appel
  Judge et aucune double admission budgétaire concurrente dans ces essais.
- Reprises de campagne : 88 tests de service/API et 4 tests PostgreSQL passent
  (idempotence, distribution exclusive, corpus modifié, droits et historique).
  Les 4 essais locaux du préfixe hybride Luma passent aussi avec un vrai petit
  artefact ML ; ces tests n'utilisent pas le fournisseur LLM de production.
- Rejet humain : 154 cas distincts couvrent DAG, TTL, SAP, sous-flows, AgentLoop
  et reviews ML. Une seconde revue n'a trouvé aucun défaut bloquant.
- Frontend : 2 770 unités passent ; les derniers ajustements de récupération
  ont ensuite passé les 19 tests ciblés Claims/navigation. Quatre parcours
  navigateur couvrent reprise QA et récupération Work, en français/anglais,
  desktop/mobile, avec zéro violation Axe dans les périmètres inspectés.
- Build de production hors téléchargement de polices, i18n, navigation,
  chrome et pre-commit passent. Les avertissements de taille existants du
  frontend restent présents ; aucun budget n'a été relevé.

Ces vérifications locales ne remplacent pas la recette après déploiement.
À 14:26 UTC, la campagne en service conserve 26 essais terminaux : 21 conformes
aux assertions, 1 non conforme et 4 non évalués ; 22 restent sans verdict.

### Refus financier effectivement testé

Un système de recette distinct, `f94ef829-f90d-4236-9a76-e8a8779b2e3f`, reçoit
temporairement un plafond système de **0 EUR**, sans plafond de tokens. Le Run
de prévisualisation `84369af8-f5a8-43a5-b942-434be854f6cc` produit exactement un
appel refusé : `USAGE_BUDGET_EXHAUSTED`, dimension `cost`, devise `EUR`, et
`dispatched_at=null`. Aucun appel fournisseur ni fallback n'est envoyé. La
consommation et la réservation du budget de recette restent à zéro.

La politique de recette est ensuite désactivée, révision 2, et le système
retiré (`retired`), en conservant les preuves. Le budget Showcase reste actif
à 2 000 EUR. Le POST initial du budget de recette avait expiré côté client
en attendant un verrou ; sa création a été relue avant toute suite, sans
renvoyer la mutation à l'aveugle.

### Correctif générique de supervision, non déployé

Un blocage du lancement avec `preexec_fn` a été reproduit localement lorsqu'un
autre thread détient le verrou d'import de `resource`. Le superviseur lance
désormais un bootstrap Python isolé, applique les plafonds CPU/mémoire/fichiers
avant le code utilisateur, puis effectue `exec`, sans callback Python entre
fork et exec. Les plafonds hérités plus stricts, le groupe de processus,
l'environnement filtré et l'annulation des descendants sont conservés.

**66 tests ciblés passent**, dont processus réels, import concurrent,
timeouts/annulations, limites, scoring ML de 5 000 lignes et profilage DataOps.
Aucune dépendance, migration ou option nouvelle. Ce correctif retire un risque
reproduit ; il ne prouve pas que ce risque explique l'incident observé en service.
Sa livraison devra atteindre les processus qui utilisent le superviseur,
notamment DataOps, avec les contrôles d'images habituels. La production décrite
dans ce rapport reste `a2be58d1`.

Les relevés de cette session sont dans
`/workspace/scratch/luma-qualification-a2be58d1/`. Les captures et un relevé
intermédiaire sans identifiants d'accès sont archivés dans
[les preuves de recette](../evidence/luma-live-qualification-a2be58d1-2026-10-22/README.md).

| Constat | Artefacts de la session |
| --- | --- |
| SHA et readiness | `build-info.json`, `readiness-attestation.json` |
| Enquête et verdict détaillé | `pilot-start.json`, `pilot-progress.json`, `04-pilot-judge-evidence.png` |
| Usage conservé | `pilot-usage-summary.json`, `pilot-usage-calls.json` |
| Prix, taux et contrôles de conversion | `tariff-source-receipts.json`, `tariff-source-ecb-daily.xml`, `tariff-eur-validation.json` |
| Tarifs enregistrés | `tariff-eur-created-gpt-5.json`, `tariff-eur-created-text-embedding-3-small.json`, `tariff-eur-created-gpt-4o-mini.json` |
| Budget activé puis relu | `budget-activated.json`, `budget-verified.json`, `06-budget-live.png` |
| Contrat et lancement de campagne | `campaign-preflight-final.json`, `campaign-created.json`, `campaign-job.json`, `campaign-progress.json` |

La clôture devra ajouter le bilan final des Runs et assertions, les abstentions
ou échecs conservés, l'usage EUR de la campagne et les réservations restantes,
puis les comparaisons avant/après du brouillon, de la publication, des bindings,
du modèle et des données métier. La calibration et toute qualification Giskard
éventuelle restent des preuves distinctes à produire. Aucun résultat de ces
étapes n'est anticipé ici. La recette de refus financier isolée est décrite
ci-dessus.
