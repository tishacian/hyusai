# Luma : qualification du modèle après activation du socle

## PostgreSQL rétabli après déploiement de `718c99bf`

Le 19 octobre, l'API et le frontend annoncent la révision
`718c99bf7e9e07fb689ff0bcd4a1ffd90fca2ece`. Le compte fourni pour la recette
est `workspace_owner` de Showcase et reçoit `can_configure: true` ; le compte
administrateur de recette de l'opérateur n'avait pas cette permission workspace.
Aucun rôle n'a été modifié.

Le mode **Sans chiffrement** a été sélectionné et enregistré depuis la fiche
PostgreSQL de Showcase. Le secret existant est conservé. À **15 h 56, heure de
Paris**, le test renvoie `connected`, le catalogue expose sept tables et l'aperçu
relit **23 lignes et cinq colonnes** de `showcase_ecommerce.claims`, avec
`sslmode=disable` dans la provenance. La file Work renvoie ses trois dossiers de
présentation et RC-1042 retrouve ses six documents sources.

Le recalcul déclenché depuis la Business App a créé le Run
`9f482184-1b93-451d-a35e-be95893a72e2`, terminé en **30,38 secondes** sur cette
révision, dans le Flow publié v5 du System Luma. Les trois appels réussissent :
extraction PostgreSQL, transformation SQL/DataOps, scoring ML. Le résultat
`ready` porte sur les 23 dossiers du corpus, dont trois sont présentés dans Work.

- Dataset préparé : `64538d75-3042-4030-94fd-37ba1105b200`, 23 lignes.
- Dataset scoré : `5fc56662-04c8-4d42-8b5a-7d1dd3f5e9e3`, 23 lignes.
- Modèle : SLA v5, `2e71ce6f-800f-4d02-b59e-498e40fe48eb`.
- Risques affichés pour les dossiers de présentation : environ 80 %, 17 % et 2 %.

Ces pourcentages sont des scores sur données synthétiques, pas des gains
financiers ni des décisions de remboursement. Le Run de surveillance ML
`3c758903-0f2b-4923-81e3-138e61f626e1` reste en `hitl_pending` ; la validation
de la connexion et du scoring n'approuve pas son réentraînement.

Le réexamen de RC-1042, déclenché ensuite depuis Work, a créé le Run
`612a4abf-7a54-4965-ad7d-26606d77f3e6`. Il utilise le même System, le même
Flow publié v5 et la même révision runtime. Ses **12 appels réussissent** :
préparation des données, transformation SQL, scoring v5, rapprochement avec le
dossier, quatre décisions agentiques, lecture PostgreSQL, recherche des règles,
recherche des preuves de livraison et proposition de résolution. Le Run atteint
`hitl_pending`, sans erreur. La proposition demande une enquête transporteur en
raison de la différence de code postal entre le bordereau et la commande.
La vue Flow du Run s'ouvre : préparation, scoring et enquête sont réussis,
la validation attend et l'enregistrement du reçu n'a pas démarré.

Aucune approbation n'a été exécutée et aucun nouveau reçu n'a été créé. RC-1042
possède déjà un reçu simulé historique du 2 octobre, visible à côté de la nouvelle
proposition : ce réexamen ne doit pas être présenté comme une seconde action
réalisée. Le parcours jusqu'à la validation humaine est vérifié ; l'exécution
après approbation et un nouveau ROI réalisé ne sont pas qualifiés par cette passe.

## Vérification après déploiement de `945013ac`

Le 19 octobre, l'API et le frontend annoncent tous deux
`945013ac52d1d1608a529c1070b1c1dfcd3b84c1`, avec révision vérifiée.
La v5 reste en service et appelable ; aucune nouvelle version n'a été créée
par le déploiement.

Le déclenchement natif du 19 octobre à **13 h 57, heure de Paris**, a créé le Run
`3c758903-0f2b-4923-81e3-138e61f626e1`. Sa preuve d'exécution indique aussi
`945013ac52d1d1608a529c1070b1c1dfcd3b84c1` côté worker. La mesure est réussie,
la branche `review` est choisie et le Run atteint **`hitl_pending`**. Le nouveau
résultat ne contient plus `ML_SPEC_INVALID` ; l'ancien refus reste dans
l'historique.

La proposition `c555afbc-fb68-594f-8a98-af01d87ed42c` est
`queued / awaiting_approval`, liée à la décision
`76ee091f-1dea-4d87-93f6-3fa54efb300c`, encore `proposed` et sans confirmation
humaine. Aucun challenger n'est créé ni promu. Le dataset figé
`e595df71-bf0a-4305-8dfe-950418500150` est prêt, avec **4 627 lignes et huit
colonnes** : six entrées prédictives, la cible et `language`.

- 3 486 lignes d'apprentissage, dont les 64 retours synthétiques retenus ;
- 1 141 lignes de test indépendantes préservées ;
- langue connue pour les 1 141 lignes de test et les 3 422 autres lignes
  d'apprentissage ; inconnue, donc nulle, pour les 64 retours ;
- contrat d'entrée à six variables et `fairness_columns=["language"]` conservés.

La fiche modèle affiche « Validation humaine attendue », les données figées et
un lien vers le Run. Son Flow montre `schedule`, `monitor` et `route` réussis,
avec `review` en attente humaine. L'écran de décision expose les actions
Approuver et Refuser ; aucune de ces actions n'a été exécutée pendant la recette.
Le gate prévoit un rejet à expiration le **21 octobre à 13 h 57, heure de Paris**.

Le planning a été restauré puis relu : quotidien actif, `0 0 * * *` en UTC,
prochain déclenchement le **20 octobre à 02 h 00, heure de Paris**. Aucun cron
temporaire ne subsiste. Une approbation autorisera un entraînement distinct ;
elle ne mettra pas automatiquement ce futur challenger en service.

Work reçoit maintenant le diagnostic fermé `PG_TLS_UNAVAILABLE` et l'explique
en français comme en anglais. Les actions Réessayer et Explorer PostgreSQL sont
visibles pour l'administrateur. Les captures live à 1 440 et 390 px ne présentent
pas de débordement horizontal. Le test du connecteur confirme toujours que
l'endpoint ne propose pas TLS : ce déploiement ne rétablit pas sa disponibilité.

## Résultat après déploiement de `d95ba09f`

Le 19 octobre, l'API et le frontend annoncent la révision complète
`d95ba09fc589af64eb6f351a54b9faeaf74503ba`. Le runtime enregistré par le nouvel
entraînement confirme la même image côté worker.

- **SLA v5** : `2e71ce6f-800f-4d02-b59e-498e40fe48eb`, entraînée en 37,5 s,
  `ready`, appelable, puis mise en service depuis la fiche modèle. Le réglage
  workspace existant ne demande pas de seconde approbation pour cette promotion.
- Le dataset conserve 4 573 lignes et les six entrées prévues. AUC de test :
  **0,820671**. L'évaluation signale trois contenus communs entre apprentissage
  et test : ce score ne constitue pas une validation indépendante sans réserve.
- Le contrat d'artefact, le runtime et une référence de **256 lignes** sont
  enregistrés. Play a servi la v5 ; l'explication automatique est contrefactuelle
  pour ce modèle calibré. Une recherche contrefactuelle séparée a abouti.
- **Flow publié v5** : `f3fc70cd-0a51-4719-bbf3-ce30d787f4d4`, 24 nœuds et
  25 liens. Seuls la version du modèle et son libellé changent. Le brouillon
  utilisateur conserve ses 25 nœuds et 26 liens, révision 25.
- **Work release 4** : `6b45b6f2-8688-4b8b-a76d-deb9508956e9`, déployée sur
  `live`. Les trois bindings et le contrat imbriqué du triage pointent vers le
  nouveau Flow/modèle. La publication a passé le ready-check sans blocage ni
  avertissement ; les accès et le brouillon Work sont conservés.
- Surveillance quotidienne activée sur v5, avec proposition de réentraînement
  configurée pour une validation humaine. System technique :
  `aff1a77b-f40e-4c08-b960-52a0006c36cb`, planning
  `72943ce8-1397-41a7-9573-386ab82ccc5f`. L'ancien planning v1 est désactivé.

Un déclenchement natif du scheduler a exécuté le Run
`f3c03c6e-2130-4b87-87fe-e5918788edc0` à 09:03 UTC, en 6,53 s. La mesure et
son historique sont enregistrés et le Flow d'exécution s'ouvre. La proposition
de réentraînement est toutefois refusée avec **`ML_SPEC_INVALID`** : le gel du
dataset retire la colonne auxiliaire `language`, encore déclarée dans
`fairness_columns`. Les étapes de validation et d'entraînement sont donc
ignorées ; ce Run terminé ne prouve pas le parcours humain complet.
Le planning temporaire de recette a été remplacé par sa cadence quotidienne
initiale (`0 0 * * *`, UTC), vérifiée active avec prochaine échéance le 20 octobre.

La campagne a effectué **un appel de 64 lignes**, plus deux appels unitaires de
qualification, soit trois appels et 66 lignes. Les 64 résultats synthétiques ont
été associés aux `sample_id` réellement conservés. Le rapport
`c754dbde-8e43-4cb4-b1cf-124fe52a568f`, terminé le 19 octobre à 08:54 UTC, utilise
64/64 échantillons sans exclusion : **48 réponses correctes, accuracy 75 %**.
Le résultat serveur correspond au calcul local sur les réponses effectivement
servies. La fenêtre isole le batch `a8c9289e-69c2-4fda-865b-a0a70b3682eb`.

Ce corpus équilibré est synthétique et non revu humainement. Il qualifie la
chaîne prédiction → feedback → analyse, pas une qualité réelle en production ni
un ROI financier. Ce ne sont pas 64 enquêtes Work. La langue n'est pas une entrée
servie : l'équité par langue reste non mesurée dans ce rapport. TreeSHAP ne
s'applique pas à ce modèle calibré ; le shadow reste indisponible tant que son
challenger v2 conserve l'ancien format d'artefact.

Le journal expose l'entraînement v5 comme `succeeded`. La série d'activité du
19 octobre entre 08:00 UTC et l'heure de lecture contient un entraînement réussi
avec une durée mesurée de 37 458,9 ms. Aucun coût financier n'en est déduit.

## Blocage PostgreSQL constaté avant `718c99bf`

La recette navigateur charge la nouvelle application, mais sa file échoue.
Le test du connecteur et le catalogue renvoient tous deux **`PG_TLS_UNAVAILABLE`** :
le serveur PostgreSQL annonce qu'il ne prend pas en charge TLS. Le lecteur métier
sur la révision déployée n'expose encore que `POSTGRESQL_READ_UNAVAILABLE`.
Les lectures du connecteur et le diff des settings confirment que le réépinglage
n'a pas modifié sa configuration.

Sur cette révision, la reprise exige TLS natif sur l'endpoint PostgreSQL,
un certificat valide pour l'hôte configuré et l'autorité de confiance au backend
et au worker, avec `sslmode=verify-full`. La livraison suivante ajoute le choix
administrateur explicite décrit ci-dessous pour les endpoints sans TLS.
Suivre [le diagnostic PostgreSQL](postgresql-connection-diagnostics.md), puis
vérifier connexion, catalogue et aperçu avant de relancer la file et une enquête
Work. Aucun nouveau Run métier ne peut être déclaré réussi avant ces contrôles.

### Reprise PostgreSQL sans TLS demandée le 19 octobre

Une évolution générique ajoute **Chiffrement → Sans chiffrement** à la fiche
PostgreSQL et au registre Connections. Le défaut reste **TLS vérifié** ; le
produit ne choisit jamais automatiquement le mode non chiffré après un échec.
Cette évolution a été déployée et le choix appliqué à Showcase ; les contrôles
en service sont consignés en tête de ce document.

Suivre [la procédure de déploiement et de vérification PostgreSQL](postgresql-connection-diagnostics.md#déploiement-et-vérification-du-choix-de-transport),
y compris les workers et les runners de connecteurs concernés. Aucune migration
ni nouveau drapeau n’est nécessaire. Dans Showcase, Work Luma utilise la fiche
**Connecteurs → PostgreSQL** historique : modifier uniquement une connexion du
nouveau registre ne débloquerait pas sa file.

La recette a enregistré ce choix explicite dans cette fiche, testé la connexion,
exploré une table et vérifié une lecture fraîche de la file Luma.
Les données transitent alors sans chiffrement PostgreSQL. La recette ne doit pas
réutiliser un ancien snapshot comme preuve de connexion. Les épingles du modèle
v5 et la proposition de réentraînement en attente d’approbation restent inchangées.

## Reprise après livraison des correctifs de cette recette

La préparation du réentraînement conserve maintenant les colonnes d'équité
activées en plus des entrées prédictives et de la cible. Les groupes connus du
dataset source et du test final sont conservés ; une métadonnée absente des
feedbacks reste nulle. La preuve du dataset indique les valeurs présentes et
manquantes par population. Cette correction ne mesure pas l'équité par langue
des 64 prédictions qui n'ont pas cette métadonnée et n'élargit pas leur contrat
d'entrée.

Les limites du pack restent appliquées : le plafond existant de groupes n'est
pas relevé, et une valeur auxiliaire qui ne peut pas être conservée fidèlement
est refusée. Les valeurs absentes sont comptées dans la couverture ; elles ne
sont remplacées par aucun groupe supposé.

La validation locale passe **69 tests** couvrant le réentraînement, la justesse
des partitions et les colonnes auxiliaires. Un entraînement réel du dataset
figé vérifie la signature prédictive inchangée, les groupes du holdout d'origine
et l'absence de promotion automatique. Les cas de groupes texte, entiers,
booléens, partiellement absents et incompatibles sont exercés. Ces résultats
valident le correctif ; le nouveau déclenchement en service reste à vérifier
après déploiement.

La correction Work expose le diagnostic PostgreSQL déjà disponible côté
connecteur ; elle ne rétablit pas à elle seule la connexion. Déployer l'API et
le frontend pour voir la cause et les actions de reprise adaptées aux droits.

Pour vérifier la correction du dataset de réentraînement, mettre aussi à jour
le worker qui exécute la surveillance et la préparation ML. Conserver la v5 en
service et ses épingles : aucun nouvel entraînement ou changement de champion
n'est nécessaire pour déployer le correctif. Il n'y a pas de migration ni de
nouveau drapeau d'activation pour ces changements.

Après déploiement, contrôler un nouveau Run du planning v5 : mesure persistée,
absence de `ML_SPEC_INVALID`, puis proposition présentée pour validation
humaine si les critères de surveillance la justifient. Une proposition ne vaut
ni approbation ni mise en service ; conserver ces étapes et leurs preuves dans
le produit. Le statut `completed` du Run de mesure ne suffit pas à valider ce
parcours. Vérifier ensuite le champion et les épingles réellement utilisés.

## Historique avant correctif

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

## Procédure de réentraînement et de réépinglage suivie

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

## Protocole du corpus de qualification

Ce protocole a été préparé avant le réentraînement ; la campagne est maintenant
effectuée et ses résultats sont consignés en tête de ce document.

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
appliqués : les références utilisées ont été reconstruites depuis la v5 qualifiée.
