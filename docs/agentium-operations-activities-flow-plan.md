# Opérations, Activités et suivi des jobs dans le Flow — R1 à R5

Date de décision : **16 octobre 2026**. Statut : **plan de développement**.
Base vérifiée : `demo/agentic`, `f4329db35d428e5f646028c783d7ee335de76e3b`.
Aucun lot de ce document n'est déclaré implémenté ou qualifié par sa rédaction.

## 1. Décision et résultat attendu

Conserver **Opérations et Activités comme deux onglets distincts**, avec Qualité,
Performance et Traces. Depuis une alerte ou un indicateur d'Opérations, ouvrir
les activités concernées, puis retrouver le job sur le nœud du Flow exécuté.
Depuis ce nœud, revenir au même travail, à ses tentatives et à ses preuves.

Le moniteur garde sa polyvalence : exécution agentique, DataOps, ML et leurs
compositions, traitements rapides et longs, attentes humaines et externes.
L'affichage explique ce qui attend, ce qui travaille, ce qui a échoué et ce que
l'utilisateur peut faire. Réussite technique, acceptation et livraison restent
trois faits distincts.

**Le nuage de points et la matrice des preuves sont des capacités à préserver.**
Leur présence, leurs données, leurs interactions et leurs liens vers le Run
font partie de la recette bloquante, avec le radar et l'historique de Qualité.
Leur simple présence dans le code ne ferme pas cette recette.

Ce plan précise le [plan d'exécution O0–O7](agentium-execution-observability-plan.md)
et reprend R1/R2/R3 de la
[fiche papAI/Agentium à `3a2d60f7`](https://github.com/tishacian/hyusai/blob/3a2d60f78630068a91ef6c6fb8a8132bbb5eb74d/docs/papai-jobs-flow-observability.md).
La fiche reste une analyse datée ; le présent document définit les travaux à
réaliser après les décisions utilisateur. R4 ajoute le suivi dans le Flow ; R5
qualifie l'ensemble. Les correctifs de papAI sont hors périmètre.

## 2. Base vérifiée et écarts à prendre en compte

| Sujet | Constat sur la base | Conséquence |
|---|---|---|
| Opérations | Le shell affiche `ActivitiesComponent` ; le moniteur historique n'est monté qu'en repli lorsque la fonction est fermée | R1 restaure l'accès permanent au moniteur et crée l'onglet Activités |
| Synthèse historique | `/workspace-overview` lit au plus 200 Runs, 100 jobs et 100 évaluations avant ses calculs | R1 rend la couverture explicite ; R2 fournit les agrégats exhaustifs sous droits |
| Qualité | Nuage, matrice, radar et historique existent ; le canari 23 vérifie surtout le point et son lien vers le Run | Étendre la recette aux cellules, au clavier et aux deux états du drapeau |
| Graphiques de runs | Hypervisor V2 possède déjà une courbe quotidienne issue des Runs, plafonnée à 2 000 runs lisibles | Réutiliser les composants pertinents ; R2 apporte la supervision exhaustive autorisée |
| Activités | Huit sources, journal transactionnel, curseur par workspace, droits natifs et SSE rejouable | Étendre ces contrats ; conserver les moteurs comme autorités d'exécution |
| Flow | Snapshot/version/hash du Run, checkpoints, traces d'invocations et liens de délégation existent ; l'état client résume surtout le dernier passage d'un nœud | R4 doit distinguer version exécutée, passages, tentatives et jobs |
| MLOps | La base contient M1–M4.1, dont les métriques d'endpoints et alertes M3 | Les réutiliser ; une fusion Git ne prouve pas leur activation en production |
| Production | L'activation d'observabilité à `4a404d61` est rapportée dans le dépôt | R1 corrige une interface déjà déclarée active ; les défauts `false` ne décrivent pas la VM |

Provenance de production :
[bilan opérateur du 15 octobre](ops/execution-observability-production-2026-10-15.md).
Il ne s'agit pas d'une nouvelle vérification de la VM. Le
[bilan d'implémentation](agentium-execution-observability-implementation.md)
distingue les candidats locaux, les essais et les activations rapportées.

Trois corrections de la fiche sont intégrées dès la conception :

- Le coût d'un Run peut déjà sommer ses invocations. Additionner tous les
  parents et enfants produit un double compte ; `cost_known` peut désigner
  seulement un sous-total connu.
- Classer des activités par création et statut actuel produit des **cohortes
  de créations**, pas l'histoire des états au fil du temps.
- `cpu_seconds` et le pic mémoire peuvent venir d'`ExecutionReservation` au
  détail ; ils ne sont pas tous dans `Activity.snapshot`. Une réservation
  actuelle n'est pas une consommation mesurée ni son historique.

## 3. Modèle d'interface et responsabilités

| Vue | Question de l'utilisateur | Contenu et accès |
|---|---|---|
| Opérations | Où faut-il intervenir ? | Alertes, santé des systèmes, runs et jobs, volumes, latences, signaux qualité, décisions de recherche et timeline du workspace ; liens vers le détail |
| Activités | Que fait ce travail, et pourquoi attend-il ? | Liste filtrée, état, parent/enfants, tentatives, mesures, historique, preuves et commandes autorisées |
| Qualité | Sur quelles évaluations et preuves repose le résultat ? | Nuage, matrice, radar, historique, couverture et investigation du Run |
| Performance | Comment se comportent les services techniques ? | Métriques API/cache existantes, avec leur nature et leur fenêtre explicites |
| Traces | Quels appels composent cette exécution ? | Runs, invocations, cascade et investigation existantes |
| Flow en suivi | Où en est le run sur son graphe ? | Version exécutée, nœuds, travaux liés et frise des passages/tentatives |

| Responsable | Portée utile | Règle de droits |
|---|---|---|
| System | Engagements du System, runs, décisions, livraisons et travaux associés | Autorisations natives du System, du Run et de chaque preuve ; aucune permission créée par le titre « responsable » |
| Workspace | Ensemble des travaux lisibles, files d'attente, erreurs et arbitrages | Appartenance courante et droits par objet ; lecture et annulation restent distinctes |
| Plateforme | Santé globale, réservations/limites, workspaces concernés | Agrégats administrateur dédiés ; ouvrir un objet ou une preuve applique encore sa politique native |

Un même fait garde le même identifiant et le même vocabulaire entre les vues.
Les compteurs de runs portent sur les Runs ; ceux d'activités portent sur les
activités. Une activité d'invocation et son Run comptent comme deux activités,
mais jamais comme deux runs. Une activité sans Run reste consultable sans
fabriquer un rattachement au Flow.

### Navigation, filtres et actualisation

- Canonique : `/observability?facet=operations` et
  `/observability?facet=activities`. Opérations reste l'entrée sans sélection.
- Conserver `/observability/quality`, `/performance`, `/traces` et l'alias
  `system_id`. Les nouveaux liens utilisent `systemId`.
- Les anciens liens portant `activityId`, y compris avec `facet=operations`,
  sont normalisés vers Activités. Une sélection explicite Qualité/Performance/
  Traces garde sa destination. Un `scope` ancien sans facet dirige vers
  Activités, notamment `scope=platform`. Tester ces règles sans boucle de
  redirection.
- Conserver workspace autorisé, System, période, sélection et retour au
  changement de vue. Un paramètre d'URL ne confère aucun droit.
- R1 fixe les fenêtres `24h`, `7d`, `30d` pour Opérations, Activités et Qualité,
  avec défaut commun `7d`, paramètres reflétés dans l'URL et même cutoff lors
  d'un passage entre vues. Conserver une ancre effective `as_of`/bornes dans
  la navigation ; ne pas recalculer `Date.now()` à chaque changement d'onglet.
  Un rafraîchissement explicite actualise cette ancre et l'affiche. Aujourd'hui
  les plages diffèrent : cela exige aussi
  les adaptations API/moniteur, pas seulement un contrôle dans le shell.
- Les compteurs dont l'horloge diffère (création, fin, évaluation) l'indiquent.
  Un filtre non applicable à Performance ou à une jauge actuelle est signalé.
  Aucun indicateur ne prétend partager un périmètre qu'il ignore.
- À terme, les indicateurs R2 alimentent les tuiles correspondantes d'Opérations.
  Les signaux qualité/recherche et les engagements gardent leur source métier.
  Le tableau détaillé se trouve dans Activités ; Opérations montre des résumés
  et raccourcis. Les alertes ML réutilisent M3.
- Un seul propriétaire du flux par vue active et workspace ; arrêt au départ,
  au changement de workspace ou d'identité. Mutualiser la découverte des
  capacités, éviter deux requêtes/listeners concurrents shell/composant.
- Perte de connexion : badge de fraîcheur, données datées et commandes fermées
  jusqu'à relecture. Révocation : purge immédiate des données concernées.

## 4. R1 — Conserver Opérations et ouvrir Activités séparément

**Taille M**, car les périodes, liens et droits doivent rester cohérents.

1. Ajouter la facet Activités au shell. Monter toujours le moniteur historique
   dans Opérations ; conserver alertes, six tuiles, décisions de recherche,
   listes Systems/jobs et timeline. Traduire les libellés encore codés en anglais.
2. Présenter Activités lorsque la capacité serveur est connue et activée.
   Distinguer découverte en cours, fonction fermée, accès refusé et panne.
   Un lien direct vers une fonction fermée affiche cet état et un lien vers
   Opérations ; une panne n'est jamais présentée comme « aucune activité ».
3. Retirer le moniteur de repli interne à `ActivitiesComponent`, après avoir
   rétabli son montage dans Opérations. Éteint, Activités n'appelle ni liste,
   ni SSE, ni commandes. Ne pas arrêter le journal en production pour tester R1.
4. Raccorder périodes, portée System et liens de synthèse aux filtres réellement
   appliqués par le backend. Conserver les droits existants en remplaçant les
   compteurs : une synthèse ne révèle pas de travaux cachés au détail.
   Tant que R2 n'a pas remplacé les calculs tronqués, indiquer l'échantillonnage
   et sa couverture ; ces KPI ne sont pas présentés comme des totaux exhaustifs.
5. Conserver Qualité/Performance/Traces et la cascade d'un Run. Leurs capacités
   sont des invariants de recette, pas des composants à déplacer dans Activités.

**Fichiers à reprendre :**
`frontend-ng/src/app/features/observability/observability-shell.component.ts`,
`observability-facets.ts`, `observability-facet-redirect.ts`,
`workspace-monitor.component.ts`, `quality-dashboard.component.ts`,
`activities/`, navigation canonique et liens depuis les Systems ;
`backend/app/api/v1/endpoints/observability.py` pour les filtres de synthèse.

**R1 est accepté lorsque** les cinq onglets coexistent avec la fonction ouverte,
les quatre historiques restent utilisables lorsqu'elle est fermée, tous les
blocs du moniteur sont accessibles, les anciens favoris fonctionnent et la
recette Qualité du §8 passe. Les contrôles de droits sont testés côté API.

## 5. R4 — Suivre les jobs dans la version exécutée du Flow

Ce lot vient avant les nouveaux graphiques agrégés. Il réutilise le graphe et
ses composants de rendu ; il ajoute un **mode suivi en lecture seule** distinct
de l'édition du brouillon. Ouvrir un run ne déclenche ni sauvegarde, ni validation
mutante, ni publication du Flow.

### R4.1 — Contrat des passages, tentatives et travaux (taille L)

| Objet | Identité et autorité |
|---|---|
| Run | `run_id`, version/hash et `flow_snapshot` figés ; moteur natif propriétaire |
| Nœud défini | `node_id` dans ce snapshot ; peut rester non exécuté |
| Passage du nœud | Identité persistée distincte pour chaque entrée logique ; chemin d'itération/branche conservé lorsqu'il existe |
| Tentative | Identité stable au rejeu de transport, distincte lors d'un nouvel essai métier ; lien au passage |
| Travail concret | `native_kind/native_id`, invocation, RecipeExecution, ComputeRun ou sous-Run ; références existantes conservées |
| Activité | Projection d'observation du travail ; aucune nouvelle autorité d'exécution |

- Exploiter les données existantes : checkpoints du Run, `SkillInvocation.trace`
  (`node_id`, indices de retry/boucle), `ComputeRun` (nœud/tentative), liens de
  délégation du Run. Ne jamais déduire une correspondance de la seule proximité
  temporelle ou du slug d'un Skill.
- Utiliser les identifiants natifs d'invocation et de calcul avant d'ajouter
  une nouvelle identité. Un identifiant de passage additionnel n'est nécessaire
  que si les données persistées ne distinguent pas les exécutions d'un nœud
  sans invocation. Retry, tour agentique et branche ont des dimensions distinctes.
- Compléter les émissions natives quand une identité ou un horodatage manque.
  Persister les nouvelles corrélations avec la transition dans la même
  transaction. Si un schéma additionnel est nécessaire, le rendre additif et
  indexé par workspace/run/nœud ; figer la migration après inspection des
  émissions, sans renuméroter les migrations d'autres lots.
- Une projection de lecture versionnée regroupe ces références sans recopier
  prompts, lignes de données, sorties brutes ou raisonnements internes.
  Les détails sensibles restent derrière les API de preuve existantes.
- Les états d'exécution reprennent le vocabulaire commun. Les nœuds seulement
  définis portent « non démarré » ; les branches explicitement écartées portent
  « non exécuté » avec motif. Ni l'un ni l'autre n'est un job en file.
- Afficher attente en file, dépendance, humain ou service externe uniquement
  lorsqu'une source le prouve. Un lien manquant ou historique ambigu est
  « indisponible », jamais une durée nulle ou une réussite déduite.
- Les horodatages de tentative viennent de la source persistée ; les pings ne
  réécrivent pas le début. Dépassement d'échéance, perte, annulation et résultat
  externe inconnu gardent leurs distinctions, même si un ancien statut natif
  n'en fournit qu'une partie.
- Boucles et agents : afficher les nœuds connus dès le lancement, puis ajouter
  les invocations réellement découvertes. Aucun total global inventé pour un
  graphe dynamique. Les échecs des tentatives antérieures restent visibles
  après un succès. Un sous-Run expose sa relation typée (délégation ou rejeu).
- Sur les anciens runs, qualifier la couverture : corrélation exacte,
  partielle ou absente. Un backfill n'invente ni transitions ni tentatives.

**Surface de lecture à ajouter :**
`GET /api/v1/runs/{run_id}/execution-view`, schéma versionné, protégé par les
droits natifs du Run et de chaque travail. Il fournit métadonnées du snapshot,
**topologie sûre** (identifiants, types, libellés validés et arêtes), version de
lecture, curseur, résumés de nœuds, références de travaux et couverture. Ne pas
exposer `flow_snapshot` brut et ses configurations : l'API actuelle du Run ne
renvoie que ses métadonnées, et `/perspective` ne fournit pas cette topologie.
Paginer les passages/tentatives ; ne pas renvoyer des milliers d'invocations
dans chaque réponse. Le nombre de pages n'altère pas les totaux autorisés.

Utiliser le journal durable d'activités comme signal d'invalidation, puis relire
la projection versionnée. Ajouter un filtre par Run/sous-arbre, autorisé côté
serveur, avec un seul abonnement ; aucun flux par nœud ou par enfant. Une
transition de nœud peut ne changer que les checkpoints, aujourd'hui absents de
la liste des champs projetés : R4.1 doit alors émettre une notification durable
de métadonnées dans la transaction du checkpoint. Dédupliquer par identité
persistée de transition, pas par timestamp. Aucun événement par token ou ligne.

Le snapshot et le raccord au direct doivent garantir le rattrapage sans trou,
y compris pour un enfant créé pendant la connexion. Un curseur expiré provoque
une resynchronisation explicite. `/runs/{id}/stream` garde son usage existant,
mais son rejeu actuel de checkpoints et sa déduplication temporelle ne valent
pas un curseur durable de nœud. S'il est aussi consommé pour les tokens, il ne
pilote pas les états et ses droits sont revérifiés même sous trafic continu.
Le navigateur ne décide pas de l'état métier.

### R4.2 — Vue de suivi, panneau jobs et frise (taille L)

- Depuis un System ou son Flow, sélectionner un run autorisé, avec version,
  déclencheur et période. Le run explicitement sélectionné ne change pas au
  démarrage d'un autre. « Dernier run de cette version » est un choix explicite.
- Afficher le snapshot de ce run. Un ancien run sans snapshot présente ses
  traces disponibles et indique l'absence de graphe historique ; le brouillon
  actuel n'est pas présenté comme le graphe exécuté.
- Sur chaque nœud : état, étape/message public, attente, nombres de travaux
  terminés/en cours/en erreur. Une couleur est toujours accompagnée d'un libellé
  ou symbole accessible. Une progression numérique exige un dénominateur réel.
- Le panneau d'un nœud présente passages, tentatives et jobs, moteur/placement
  lorsqu'ils sont connus, temps, coûts couverts et liens vers preuves, modèle,
  dataset, activité, invocation ou sous-Run sous leurs propres droits.
- La frise montre les intervalles observés et le parallélisme ; elle distingue
  attente, exécution et revue humaine. La durée du Run n'est pas la somme des
  durées de branches parallèles. Toute lacune temporelle est signalée.
- Canonique proposée : `/runs/{runId}?view=flow&nodeId=…&activityId=…`, avec
  sélection facultative du passage/tentative. Implémenter via le catalogue de
  navigation. Conserver les liens d'investigation actuels et tester retour,
  rechargement et partage. Vérifier que l'activité appartient bien à ce Run.
  Préserver les paramètres existants `reference_run`, `correction` et `node`
  du builder : ils désignent une aide à la correction du brouillon, pas le mode
  de lecture historique. Ne pas détourner leur comportement.
- Conserver la lecture d'Activités pour les jobs autonomes sans Run. Depuis
  un asset, ouvrir ses activités lorsqu'un lien de filiation explicite existe ;
  l'exploration générale amont/aval des assets reste dans son plan DataOps.
- Les commandes réutilisent les capacités natives. Annuler un job n'annule
  pas silencieusement le Run entier. Afficher la portée réelle de l'action,
  la demande, son application et la fin séparément. Conflit de version : relire
  puis reconfirmer. Pas de bouton « relancer ce nœud » sans contrat natif sûr ;
  proposer seulement le rejeu du Run déjà autorisé et réellement disponible.

**Fichiers à reprendre :**
`backend/app/models/run.py`, `backend/app/models/compute_run.py`,
`backend/app/services/run_engine/`, `backend/app/services/activity_observability/`,
`backend/app/api/v1/endpoints/runs.py`,
`frontend-ng/src/app/features/orchestration/flow/`,
`frontend-ng/src/app/features/runs/`, `frontend-ng/src/app/core/run-stream.service.ts`
et le catalogue de navigation. Les contrats figés du Flow restent inchangés.

**R4 est accepté lorsque** deux parcours composites (agent → préparation/ML →
revue/livraison et données → agent → revue/livraison) se suivent depuis les deux
entrées, avec branche parallèle, tentative échouée puis réussie, attente humaine,
job long et sous-Run. Une édition ultérieure du System ne change pas leur vue
historique. Les scénarios d'échec et de droits du §8 passent.

## 6. R2 — Séries temporelles fiables, réutilisées entre les vues

**Taille L**, compte tenu des droits, de la comptabilité et du volume.
Les courbes détaillées sont dans Activités ; Opérations utilise les mêmes
agrégats pour ses synthèses et renvoie vers le filtre correspondant. Conserver
les autres indicateurs existants et leur définition ; aucune équivalence de
chiffres n'est revendiquée entre populations différentes.

### Contrat API et temps

Ajouter `GET /api/v1/observability/activities/series` **avant** la route dynamique
`/activities/{activity_id}`. Sélecteur `metric=activity|cost` ; filtres :
`system_id`, `kind`, `status`, `from`,
`until`, `bucket=hour|day`, `time_basis=created|finished`. Les fenêtres UI sont
traduites en bornes UTC inclusives/exclusives `[from, until)` ; limite 30 jours.
Réponse : bornes, `as_of`, définition de la population, buckets, totaux,
couverture et méthode des quantiles. Le fuseau d'affichage est explicite.

En mode `activity`, `kind` sélectionne les activités comptées et les durées.
En mode `cost`, `kind` est obligatoirement `skill_invocation` ou `compute_run`,
`status` filtre ces sources et `time_basis=finished` est obligatoire. Refuser
une combinaison incompatible plutôt que retourner zéro. La série de dépenses
possède ses filtres et son libellé explicites ; un filtre « Runs en échec » ne
devient pas silencieusement « invocations en échec ». Elle partage le workspace,
le System et les bornes temporelles, pas une population implicitement identique.

| Série | Sémantique |
|---|---|
| Créations | Activités créées dans la tranche, avec statut courant à la lecture ; libellé « état actuel des travaux créés » |
| Terminaisons | Activités terminées dans la tranche, y compris commencées avant la période ; horodatage absent compté dans la couverture manquante |
| Durées | p50/p95 des seules durées mesurées, par type homogène et seulement sur travaux terminés ; effectif mesuré et population éligible fournis |
| Coûts | Montants et couverture par base/coût/devise, attribués selon la règle ci-dessous |
| Ressources | Réservations actuelles/limites avec `as_of`, séparées des séries historiques |

R2 ne promet pas de reconstruire combien de jobs tournaient à chaque instant.
Cela exige un historique de transitions complet et sa couverture, absent des
backfills. Les séries de cohortes ne seront pas présentées comme cet historique.

Les totaux et buckets proviennent d'une même lecture cohérente en base, après
application des droits natifs. Ne pas comparer deux réponses prises à des
instants différents comme preuve d'égalité. La recette utilise un jeu figé ;
pour `created`, elle compare aussi à `/activities` sur le même périmètre. Les
filtres `finished` ne réutilisent pas le filtre de création par inadvertance.
Pas de moyenne de percentiles. Un mélange de types conserve des distributions
séparées, plutôt qu'un p95 mélangeant une invocation courte et un Run long.

### Contrat des coûts et ressources

1. Définir une clé d'observation stable par coût natif, tentative lorsqu'elle
   existe, base et devise. Une même dépense liée à plusieurs vues compte une
   fois. Les coûts de tentatives échouées réellement observés sont inclus.
2. Pour le fournisseur, agréger les invocations dont la preuve de coût est
   recevable. Le coût agrégé du Run sert au détail ou à un contrôle de cohérence,
   jamais comme dépense supplémentaire. Un montant historique de Run sans
   ventilation reste présenté séparément et n'entre pas dans ce total.
3. Séparer fournisseur mesuré, tarif calculé/prix catalogue et allocation
   d'infrastructure. Respecter les preuves M3 : `cost_measured=true` peut couvrir
   un tarif calculé ; ne pas décider de sa nature sur ce seul booléen.
4. Retourner montant connu, nombre couvert, nombre inconnu et complétude.
   Un sous-total connu ne devient jamais « coût total » si une partie manque.
   Une monnaie distincte reste distincte ; pas de conversion implicite.
   Un zéro n'est connu que s'il est étayé par la source.
5. Un montant est attribué à la date de fin de son travail source. S'il manque
   une date ou une preuve, conserver cette lacune dans la couverture. Les coûts
   des descendants d'une cohorte de Runs ne sont pas déduits de cette série :
   ce serait un autre mode avec sélection explicite des Runs, descendants sous
   leurs droits et affectation des dépenses aux buckets des parents. Ce mode
   n'entre pas dans R2 ; les coûts détaillés du Run restent accessibles en R4.
6. Ne pas additionner les agrégats d'endpoints M3 aux mêmes invocations. Les
   endpoints restent leur vue spécialisée, avec un lien depuis le job/model.
7. CPU mesuré, CPU alloué × durée, RSS, mémoire réservée et spill gardent unités,
   provenance et couverture séparées. Réutiliser `ExecutionReservation` quand
   la mesure existe. Une donnée absente reste nulle ; une jauge actuelle reste
   datée. L'historique d'occupation CPU n'est pas inventé.

### Portées, charge et affichage

- Les séries System/workspace appliquent `filter_visible` ou une traduction SQL
  testée équivalente **avant** l'agrégation, y compris les règles spécifiques des
  connecteurs et jobs privés. Les pages ne limitent jamais les totaux.
- La portée plateforme montre les jauges actuelles et totaux par workspace de
  `/platform-overview`, clairement hors filtre temporel. Une série historique
  multi-workspaces n'entre pas dans R2 ; elle exigera son API, son périmètre et
  sa recette administrateur. Ne pas simuler cette portée en concaténant des
  réponses de workspaces depuis le navigateur.
- Réutiliser les briques de graphiques et Chart.js existantes avec chargement
  différé. Légendes, couleurs non ambiguës, couvertures et tableau accessible
  restent disponibles en FR/EN, clair/sombre et sur petit écran.
- Tester en PostgreSQL sur 100 000 activités réparties sur 30 jours et droits
  mixtes, avec 10 lecteurs concurrents et des écritures actives. Objectifs
  initiaux à mesurer : p95 série ≤ 2 s, surcroît RSS ≤ 256 Mio par requête,
  aucune écriture du moteur bloquée par la lecture. Consigner matériel, requêtes
  SQL et couverture. Ce sont des critères proposés, pas des résultats acquis.
- Si le parcours par lots de 250 ne tient pas cette recette, optimiser la
  sélection autorisée ou matérialiser par unités dont les droits restent
  contrôlables. Ne pas cacher des données derrière une troncature silencieuse,
  partager un cache entre droits différents ou relever le budget pour conclure.

**Fichiers à reprendre :**
`backend/app/api/v1/endpoints/activities.py`,
`backend/app/services/activity_observability/{projection,queries}.py`,
les modèles/mesures natifs, `frontend-ng/src/app/features/observability/`,
et les composants graphiques réutilisables de l'Hypervisor.

**R2 est accepté lorsque** un Run à 0,10 USD avec son invocation à 0,10 USD
donne 0,10 USD de dépense, un coût inconnu reste visible, un travail commencé
avant la période et terminé dedans apparaît au bon endroit, les quantiles
ignorent les mesures absentes sans les transformer en zéro, les droits filtrent
tous les buckets et la recette de charge est documentée.

## 7. R3 — Documentation, ordre de livraison et périmètre

R3 accompagne chaque lot : aligner le plan O0–O7, son bilan et sa recette sur
les changements **effectivement livrés**, avec SHA et preuves. La présente
planification ne réécrit pas les résultats historiques et ne ferme aucun lot.

| Lot | Dépendance | Livraison autonome | État initial |
|---|---|---|---|
| R1 + R3 | Contrats de navigation/période du §3 | Opérations conservé, Activités séparé, Qualité protégée | À développer |
| R4.1 + R3 | Autorités O0–O3 existantes | Corrélations persistées et API de lecture du Flow | À développer |
| R4.2 + R3 | R1 et contrat R4.1 | Vue du run sur Flow, panneau jobs, frise, navigation réciproque | À développer |
| R2 + R3 | Contrats métriques du §6 et R1 ; exploite les corrélations R4 lorsqu'elles sont nécessaires | Séries et synthèses cohérentes | À développer |
| R5 | Lots concernés assemblés | Dossier de recette et handover de release | À réaliser |

Ordre de valeur : **R1 → suivi dans le Flow → séries agrégées**.
R4.1 peut avancer en parallèle de R1. Après stabilisation du contrat, R4.2 peut
être développé sur fixtures pendant la qualification backend. La définition
des coûts R2 peut avancer en parallèle, sans retarder la restauration R1.
Limiter le travail simultané à trois axes : backend/contrats, interface,
recette. Pas de dates calendaires promises avant estimation des corrélations R4.

Chaque livraison garde une PR révisable issue de `demo/agentic` à jour, ou une
branche empilée avec dépendance explicite. Fusion et déploiement suivent le
processus de release existant ; ce plan n'effectue ni l'un ni l'autre. R1 peut
être livré indépendamment de R4/R2. La fermeture du chantier entier exige R5.

Le socle reste PostgreSQL, RabbitMQ/Celery et SSE. Aucun nouveau moteur de DAG
ni activation Temporal/LangGraph n'est nécessaire à ces écrans. Kubernetes,
Spark, Kafka, nouvel usage de Redis et narration gardent leur
[handover différé](agentium-execution-deferred-handover.md). Une refonte de la
filiation des assets, des alertes métier ou du scheduler est hors périmètre.

## 8. R5 — Recette de conservation, de continuité et de livraison

### Matrice de non-régression obligatoire

| Domaine | Scénarios et résultat attendu |
|---|---|
| Opérations/Activités | Fonction ouverte/fermée, découverte lente, 404, 403, 500 ; moniteur toujours accessible ; Activités distinct ; panne distincte d'une liste vide |
| Couverture du moniteur | Corpus supérieur à 200 Runs, 100 jobs et 100 évaluations ; troncature annoncée avant R2, puis totaux autorisés exhaustifs pour les indicateurs remplacés |
| Qualité | Nuage et cellules de matrice sélectionnables, radar/historique alimentés, preuve liée au Run exact ; score absent ≠ 0 ; toutes les capacités fonctionnent avec Activités ouvert ou fermé |
| Parcours preuve | Point **et** cellule → sélection → Run → invocation/preuve → retour ; rechargement et clavier Enter/Espace ; pas d'ID substitué par le dernier Run |
| Navigation | Anciens favoris, alias `system_id`, périodes et scope ; changement d'onglet, retour navigateur, changement workspace ; aucun filtre affiché mais ignoré |
| Flow historique | Run A sur v1 puis édition/publication v2 et Run B ; A reste sur v1, sans autosave ; run sans snapshot honnêtement incomplet |
| Flow dynamique | Branche écartée, fork/join, boucle, agent avec outils découverts, retry échoué puis réussi, sous-Run ; aucun faux job en file ni tentative écrasée |
| Asynchrone | Tâche rapide terminée avant ouverture, job long, attente humaine, dépendance externe, deadline, perte du worker et retour tardif ; états cohérents entre liste et nœud |
| Commandes | Annulation acceptée mais non terminée, réponse perdue/rejeu même clé, conflit de version, capacité absente ; aucune action non supportée proposée |
| Reconnexion | Déconnexion au moment d'une transition, doublon, ordre d'arrivée inversé, curseur expiré, rechargement, client lent ; état retrouvé depuis le stockage durable |
| Droits | Responsable System, membre restreint, admin workspace, admin plateforme ; enfant plus privé que parent ; révocation en plein flux ; aucun compteur, lien ou événement révélant un objet caché |
| Mesures | Parent/enfant non doublés, devises/bases séparées, durée parallèle correcte, inconnus conservés, période franchie, sous-total partiel explicitement marqué |
| Présentation | FR/EN, clair/sombre, clavier, axe et viewport 390 px ; états chargement/vide/partiel/erreur, sans régression des Tokens v2 |

Un événement ancien ne fait pas régresser l'état affiché. Pour un retour tardif,
la vue respecte la version et l'autorité natives ; si le moteur accepte un
résultat en contradiction avec sa terminalisation, signaler l'anomalie et
ouvrir un défaut du moteur. R4 ne masque pas ce défaut par une vérité locale
du navigateur et ne réécrit pas l'orchestration pour fermer sa recette.

Exécuter les invariants critiques Qualité et onglets dans les **huit combinaisons**
FR/EN × clair/sombre × Activités ouvert/fermé. Les scénarios techniques ont
ensuite des tests ciblés ; éviter de multiplier toute la matrice inutilement.

### Tests et preuves à produire

- Étendre les tests de facets/routes et ceux d'`activities/` ; remplacer les
  assertions actuelles qui entérinent le remplacement d'Opérations par les
  nouveaux invariants. Ajouter de vrais tests d'interaction de la matrice.
- Étendre les e2e
  `frontend-ng/e2e/tests/23-observability-evidence-canary.spec.ts`,
  `59-activity-observability-mocked.spec.ts`,
  `60-activity-observability-canary.spec.ts` et les tests Flow existants.
  Le canari 23 peut aujourd'hui être ignoré faute de Run évalué : un skip
  n'est pas une preuve de conservation. Fournir un corpus local déterministe
  puis une recette Showcase avec un Run évalué identifié.
- Backend : invariants de projection/IAM, corrélation des passages et tentatives,
  rollback de la transition, SSE et migrations sur PostgreSQL jetable. Pour
  une migration nouvelle, vérifier compatibilité des lecteurs et refus d'un
  downgrade destructif ; ne pas prétendre rejouer tout Alembic si seules les
  migrations ciblées l'ont été.
- Frontend : tests unitaires pertinents, TypeScript, `check:i18n`,
  `check:nav-links`, contrôle de chrome existant, e2e puis `build:prod` sur
  l'arbre final de chaque lot UI. Une modification après build impose une
  nouvelle validation pertinente. Les régressions préexistantes sont isolées
  et documentées, sans relever les plafonds pour les masquer.
- Archiver SHA, commandes, versions, résultats, cas ignorés, captures et résultats
  de charge. Distinguer preuve locale, recette simulée et vérification VM.
  La conservation graphique exige une assertion d'interaction, pas seulement
  une capture ou un build réussi.

### Livraison et repli

Recette progressive par lot sur Showcase, puis vérification des trois profils
sur la configuration cible par l'opérateur disposant de l'accès VM. Avant
livraison : consigner options effectives et build-info, contrôler migrations,
services `control` et santé selon la
[recette existante](agentium-execution-operations.md). Les tailles d'images
sont mesurées si le contenu de release change, avec les budgets en vigueur.
Aucun scénario de panne destructif ne tourne sur la production.

R1 conserve le drapeau d'observabilité existant. Prévoir des capacités de lecture
séparées pour le nouveau suivi Flow et les séries, afin de pouvoir les refermer
sans arrêter le journal, les workers ou les admissions déjà actives. La fermeture
d'une vue ne supprime aucun état, événement ou donnée. Les migrations additives
restent en place ; tout retour d'image dépend de leur compatibilité documentée.

Le chantier est terminé lorsque le responsable peut partir d'un signal dans
Opérations, identifier son activité, retrouver le job sur le bon Flow et ouvrir
sa preuve, avec les mêmes droits et le même état après reconnexion, tandis que
le nuage de points et la matrice de Qualité restent pleinement utilisables.
