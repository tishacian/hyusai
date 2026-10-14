# Calcul DataOps local avant Kubernetes et Spark

Ce cadrage du 14 octobre 2026 avance les parties utiles sur la VM : registre des
calculs, mesures, accès objet direct et discipline SQL. Il amende l'ordre de
D-16, §10.3 et §12 du [plan original](agentium-dataops-plan.md), sans le réécrire.
**Statut : à implémenter et à qualifier.** Ce document n'active aucune option,
ne modifie aucune limite et ne livre aucun placement Kubernetes ou Spark.

Le [bilan de production](ops/dataops-production-2026-10-14.md) reste la référence
des fonctions activées et des recettes effectuées sur `0e401afc`. Le scoring en
flux doit encore être exercé sur Showcase avec un dataset compatible avec le
modèle ; aucun client pilote supplémentaire n'est nécessaire à ce lot local.

## Mesures de départ et limites

Le [benchmark local](evidence/dataops-completion-2026-10-13/scoring-3m.json)
porte sur `bd724044`, des données synthétiques et des appels directs aux services.
Il n'est pas une campagne en production ni un parcours avec livraison acceptée.

| Mesure | Résultat et portée |
|---|---|
| Entrée | 3 000 000 lignes, 854 328 168 octets physiques |
| Pipeline | 330,552 s ; enveloppe complète 353,480 s |
| Ressources | 2 CPU, 4 Gio, sans swap |
| RSS de l'arbre | Pic échantillonné de 2 139 041 792 octets, toutes les 50 ms |
| Mémoire cgroup | Pic de **4 294 967 296 octets**, plafond atteint ; 2 018 événements `max`, aucun OOM ni `oom_kill` |
| Livraison | Aucun reçu créé |

La [preuve cgroup](evidence/dataops-completion-2026-10-13/scoring-3m-cgroup.json)
interdit de présenter le RSS de 2,1 Go comme un plafond de mémoire du conteneur.
Le rapport entre 24 heures et 330,552 s vaut environ 261 ; ce n'est pas la marge
d'une fenêtre réelle, qui inclut disponibilité des entrées, attente, concurrence,
reprises, revue humaine et livraison. La durée justifie de privilégier le local,
sans conclure à une réserve mémoire de moitié ni à une garantie quotidienne.

Les 20 Gio du plan ne sont pas une capacité mesurée :
`dataops_max_input_mb=20480` borne actuellement chaque dataset. Le placement
agrégé 2/20/200 Gio et son repli automatique avec spill ne sont pas implémentés.
Les défauts du code sont 1 Gio DuckDB, 2 threads, 4 Gio pour le runner, 4 Gio de
spill, 4 Gio de sortie et 900 s pour une préparation. La configuration effective
du déploiement prime ; aucune de ces limites ne doit être relevée par ce cadrage.

## Quatre lots locaux

| Lot | Résultat attendu | Ordre |
|---|---|---|
| L1 — Registre et admission | Bail, annulation, échéance, quotas et rattachement des coûts sur les exécutions existantes | Commencer avec L2 |
| L2 — Mesures et décision | Coût documenté, volumes, CPU, mémoire, spill, attente et échéance | Instrumentation de L1 et du runner |
| L3 — Runner et S3 | Lecture/écriture directes contrôlées, qualifiées sur MinIO | Après le contrat de finalisation L1 ; essais E/S isolés possibles avant |
| L4 — SQL portable | Contrat neutre, adaptateur DuckDB explicite, contrôle AST et corpus | En parallèle, sans implémenter Spark |

Limiter le travail simultané à deux ou trois agents. Les changements de registre,
publication et E/S doivent être intégrés séquentiellement lorsque leurs contrats
dépendent les uns des autres.

### L1 — Enrichir le registre existant

`RecipeExecution` est déjà la ligne durable de SQL, préparation et scoring en
flux. Elle porte identité, workspace, Run/nœud, annulation, timeout, résultats et
durée. L1 conserve cette identité et les API existantes. **Pas de seconde table
`compute_runs` pilotant le même calcul maintenant.** Le remplacement de D-16
et la double lecture restent une décision de migration de D4, si un futur
placement la rend nécessaire ; les recettes de migration originales restent
alors applicables.

Une ligne représente une tentative de calcul. Une redélivrance Celery conserve
cette identité ; une reprise explicite crée une tentative liée, sans recompter
la première. Centraliser acquisition, renouvellement et finalisation pour SQL,
préparation et scoring. Ajouter par migration compatible les champs nécessaires :
propriétaire, jeton de bail, génération monotone, expiration, échéance absolue,
ressources réservées, politique figée et références de mesures.

`ServiceWindow` conserve l'autorité sur la promesse, ses tentatives, l'acceptation
et la livraison. Relier le calcul à sa tentative de service sans recopier cet
état métier. Un ancien détenteur de bail ne peut plus publier des versions ou
terminer une tentative. La publication des sorties et leur rattachement exigent
une acquisition toujours valide ; plusieurs sorties restent publiées ensemble.

L'admission réserve atomiquement, par workspace et globalement, la concurrence,
les ressources et le budget quotidien en heures-cœur allouées. Réserver l'enveloppe
`cœurs réservés × durée maximale / 3600`, puis solder une fois la tentative
terminée. Une consommation manquante reste inconnue ; elle ne devient pas zéro
et ne libère pas artificiellement le budget après une perte de worker. Les
échecs et annulations consomment leurs ressources réellement engagées.
La politique reste modifiable seulement par l'administrateur de plateforme,
protégée contre les mises à jour ordinaires des paramètres de workspace.

L'échéance couvre attente, lecture, calcul, profil et publication. Garder un
timeout d'exécution distinct lorsque le métier n'a pas encore d'échéance ;
l'absence d'échéance rend le ratio de service indisponible. Annulation et
expiration doivent interrompre aussi un `predict` bloqué, aujourd'hui exécuté
dans le worker et contrôlé seulement entre les lots. Isoler ce calcul pour
arrêter ses processus sans interrompre les autres travaux.

Le renouvellement et le contrôle des baux ne doivent pas attendre derrière le
calcul qu'ils surveillent : une file différente sur le même worker occupé à
concurrence 1 ne suffit pas. Prévoir un contrôle court sur une capacité séparée,
avec ressources bornées. Inclure SQL dans la réconciliation, actuellement
limitée à préparation/scoring et à leur âge, sans heartbeat réel.

**Recette :** deux soumissions concurrentes au dernier quota disponible ;
redélivrance ; perte du worker puis retour de l'ancien détenteur ; annulation
pendant transfert, calcul bloqué et publication ; échéance expirée en file ;
aucune sortie publiée après perte de bail ; conservation et drainage des calculs
antérieurs à la migration. Vérifier les réservations et leur règlement une seule
fois, y compris sur une journée changée pendant un calcul. Couvrir aussi un bail
de calcul valide dont la tentative `ServiceWindow` a expiré ou a été remplacée :
aucune publication au titre de cette ancienne tentative, mais enregistrement
du coût réellement consommé sans réautoriser une reprise.

### L2 — Mesures, coûts et seuils

Conserver une estimation versionnée distincte des observations. `auto` reste un
choix local accompagné d'une raison ; aucune estimation ne soumet un pod ou un
job Spark. Comptabiliser ensemble toutes les entrées du calcul, leur expansion
estimée, les sorties, le staging et le spill. Ne pas confondre octets compressés
stockés, octets transférés, données décodées et mémoire de travail.

| Mesure par tentative | Exigence |
|---|---|
| Volume | Octets/lignes estimés et observés, facteur et version d'estimation, ratio d'erreur |
| Temps | Soumission, admission, lecture, calcul, profil, publication ; attente séparée ; échéance et temps restant |
| CPU | Secondes CPU de toute la tentative et de ses enfants, puis `cpu_seconds / 3600` |
| Ressources allouées | `allocated_cores × elapsed_seconds / 3600`, distinct du CPU consommé ; allocation RAM en Gio-heures |
| Mémoire | RSS avec intervalle d'échantillonnage ; cgroup avec portée, limites et événements ; espace virtuel séparé |
| Disque et réseau | Pic spill/staging, espace libre, octets transférés, appels objet et erreurs |
| Couverture | Métrique absente = inconnue, provenance, portée et version ; aucune attribution d'un cgroup partagé à un seul calcul |

Les mesures cgroup individuelles exigent une isolation et des permissions
qualifiées sur la VM ; sinon conserver la mesure de processus et son périmètre
incomplet. La durée en attente n'est pas du temps CPU consommé.

Figer tarif, devise, date et base de calcul. Une heure-cœur consommée, une
heure-cœur réservée et le coût complet de la VM sont trois grandeurs distinctes.
Sans tarif, le coût monétaire est inconnu. Raccorder les preuves au budget de
fenêtre et à `SkillInvocation` sans ajouter le même coût à chaque niveau.
Les dépenses d'une campagne incluent échecs, reprises, stockage, E/S, modèle et
part allouée des coûts fixes/inactifs lorsque ces données existent ; afficher
la couverture et ne pas appeler un coût CPU seul « coût complet ».

Le dénominateur du coût par résultat accepté provient des décisions/reçus de
gouvernance, dédupliqués par version et politique, jamais du statut `succeeded`
du calcul. Sans résultat accepté, le ratio reste indisponible ; conserver
séparément acceptation humaine et livraison reçue.

Seuils initiaux proposés pour la politique locale, à versionner et à qualifier
avant activation ; ce sont des alertes et décisions, pas un autoscaler :

| Signal | Seuil proposé | Action |
|---|---|---|
| Échéance | Durée totale prévue depuis l'entrée en file, revue/livraison comprises, ≥ 80 % de la fenêtre entre cette entrée et l'échéance | Alerter le responsable ; préserver le temps restant sans recompter l'attente écoulée |
| Délai constaté | Échéance dépassée, ou pression ≥ 80 % dans au moins 3 des 5 dernières fenêtres comparables | Analyser concurrence, I/O et placement ; déclencheur D4 après étapes locales |
| Mémoire | Pic cgroup ≥ 85 % de sa limite dans 3 des 5 calculs comparables, ou événements `max` répétés | Examiner working set et limites ; ce n'est pas un manque de CPU |
| Disque | Pic spill/staging ≥ 80 % du quota, ou réserve projetée insuffisante pour entrées/sorties/spill et marge d'exploitation | Refuser la nouvelle admission ou arrêter proprement avant saturation |
| Estimation | Volume réel > 2 fois l'estimation sur 3 calculs comparables | Recalibrer l'estimateur ; ne pas augmenter automatiquement les plafonds |
| Échec dur | OOM, disque plein, perte de bail ou dépassement de quota | Incident dès le premier cas, sortie non publiée, coût conservé |

Comparer la même famille d'opération, version de plan/modèle et classe de volume.
Avant cinq observations, publier les valeurs individuelles et le manque de
recul, sans inventer un percentile. Le benchmark existant déclenche une analyse
mémoire selon cette politique, pas une preuve de besoin Kubernetes.

**Recette :** vrai débordement disque ; pression mémoire avec RSS/cgroup distincts ;
estimation sous-évaluée ; échéance avec attente et reprise ; coût des échecs
compté une seule fois ; absence de métrique/tarif/acceptation visible. Sur Showcase,
commencer par le modèle et le schéma réels, puis mesurer les volumes cibles ;
aucune répétition du benchmark local ne remplace un reçu de livraison.

### L3 — Lecture et écriture S3 par le runner

Aujourd'hui, le worker télécharge les parts, le runner charge des tables
temporaires locales, puis le worker téléverse les sorties. Les lecteurs Arrow
distants et les tests MinIO existants sont réutilisables ; ils ne qualifient pas
encore ce parcours direct. L3 définit une E/S contrôlée, sans Kubernetes.

Le manifeste contient versions, clés autorisées, empreintes et destinations
dérivées côté serveur. Fournir au runner une identité temporaire limitée aux
objets d'entrée et au préfixe unique de sortie de la tentative ; tester émission,
expiration et renouvellement sur MinIO. Aucun secret global dans SQL, arguments,
résultats, traces ou manifestes persistés. Ni endpoint arbitraire de l'appelant,
ni lecture inter-workspaces, ni droit de suppression pour le calcul.

Garder le SQL incapable d'ouvrir librement fichiers, extensions ou réseau.
L'adaptateur d'E/S autorisé effectue les accès objet ; une requête SQL ne gagne
pas un accès S3 général. Les lecteurs doivent rester bornés, avec lecture par
lots et contre-pression ; « direct » n'autorise pas à charger toute l'entrée
en mémoire. Le disque reste disponible pour le spill autorisé.

Écrire les parts dans le préfixe de la tentative, établir le commit Delta natif,
puis publier les références SQL/A1 seulement après validation du bail et de
toutes les sorties. Une interruption peut laisser des objets non publiés,
jamais un dataset prêt incomplet. Leur nettoyage utilise l'identité de purge
distincte et les règles de rétention existantes. Préserver les lecteurs des
versions Delta déjà présentes et la [contrainte de retour arrière](ops/dataops-production-2026-10-14.md#retour-arrière-après-écriture-delta).

**Recette MinIO réelle :** plusieurs parts et sorties ; comptage des octets
confirmant l'absence de copie intégrale en staging ; accès hors périmètre refusé ;
expiration de l'identité ; perte réseau ; upload partiel ; collision de commit ;
annulation/perte de bail pendant publication ; aucune référence prête vers des
parts incomplètes. Tester le refus lorsque STS/les restrictions nécessaires ne
sont pas disponibles, sans distribuer une identité de plateforme en repli.

### L4 — Préserver le contrat SQL portable

Le contrat canonique doit rester indépendant du moteur. Un rendu DuckDB peut
employer une fonction de son dialecte à travers un adaptateur documenté ; ce
rendu n'est pas une preuve de compatibilité Spark. Ne pas supprimer une fonction
métier existante pour satisfaire un simple test de texte SQL.

Les statistiques globales sont déjà souvent abaissées en CTE d'agrégation puis
`CROSS JOIN`. Généraliser cette règle, sans fenêtre globale `OVER ()`. Vérifier
l'AST de tous les chemins : formules, étapes, opérations, sorties multiples et
préfixes compilés. Interdire les formes listées au §8.2 (`QUALIFY`, `EXCLUDE`,
`UNION BY NAME`, `PIVOT`, `USING SAMPLE`) dans le noyau neutre ; conserver les
fenêtres partitionnées/ordonnées nécessaires et signaler le coût d'une fenêtre
ordonnée globale, potentiellement non distribuable.

Inventorier et isoler notamment `strip_accents`, fonctions de listes/lambdas,
`try_strptime`, `strftime`, `date_sub`, `printf`, `struct_pack` et `quantile_cont`.
Tester leurs contrats sur valeurs nulles, unicode, dates/fuseaux, arrondis,
regex, quantiles et départages déterministes. Le plan exige déjà un shim ; L4
avance son contrat et le rendu DuckDB, sans produire de `sql_spark` ou écrire
un runner Spark. La parité entre moteurs reste une recette future de D5 ou du
profil de moteur client concerné, y compris les types physiques.

## Passage à l'échelle et portes de décision

1. **VM actuelle :** mesurer le parcours complet et les autres charges, régler
   le plan, la concurrence, les limites et le spill dans un budget explicite.
2. **VM plus grande :** comparer capacité, prix, mémoire et temps de traitement
   pour la même recette ; vérifier sauvegarde et reprise avant changement.
3. **VM dédiée au worker `dataops` :** même file, même révision et stockage objet
   partagé ; tous les consommateurs doivent satisfaire l'E/S sans chemin local
   partagé implicite. Qualifier réseau privé/TLS, accès DB/broker/MinIO, secrets
   limités, double livraison, quotas globaux, perte/reprise du nœud, latence et
   coût de transfert. Ajouter un worker n'accélère pas un calcul unique ; cela
   isole l'application et augmente la capacité de travaux indépendants.
4. **D4 Kubernetes éphémère :** ouvrir si un client déploie Agentium sur son
   cluster, ou si les mesures répétées montrent une échéance intenable après
   examen des étapes locales. Pour un gain d'élasticité, disposer d'un pool
   réellement extensible et réductible ; vérifier le minimum à zéro et le coût
   résiduel. Un cluster fixe peut servir l'isolation/l'exploitation du client,
   sans être présenté comme un gain de capacité ou d'économie élastique.
5. **D5 Spark :** n'ouvrir que si les trois conditions sont réunies : volume
   hors de portée d'une grosse machine dans la fenêtre ; aucun moteur client
   adapté pour prendre le calcul ; cluster et versions compatibles disponibles.

Avant un Spark propre à Agentium, examiner un profil D7 ciblé Databricks ou
Snowflake, avec autorisations, coût, exécution distante et résultat traçable.
Iceberg/Delta Sharing peuvent éviter certaines copies si le catalogue et le
stockage sont accessibles au moteur ; leur simple présence ne garantit ni cette
accessibilité ni la poussée du calcul. Aucun catalogue complet de connecteurs
ou déploiement Iceberg n'est ajouté à ce lot. D5 peut rester inutile.

Les mentions OVH 1.31 et Kubernetes ≥1.34/opérateur Spark dans le plan sont des
valeurs de configuration et des choix de conception, pas un inventaire vivant
ni une matrice validée aujourd'hui. À l'ouverture de D5, vérifier les versions
réellement offertes et la compatibilité opérateur/Spark/Delta ; ne pas planifier
des montées de version sur la seule base de ces nombres historiques.

Un futur cluster kind en CI pourra tester soumission, RBAC, annulation, reprise,
TTL et collecte des Jobs. Il ne qualifiera ni l'autoscaling fournisseur, ni le
réseau réel, ni les secrets MinIO de production, ni les coûts.

## Sources de code à réutiliser

| Contrat | Entrées actuelles |
|---|---|
| Exécution et supervision | `backend/app/models/recipe.py`, `backend/app/services/recipe_executions.py` |
| SQL/préparation/scoring | `backend/app/services/dataops/{sql_execution,preparation,scoring,watchdog}.py` |
| Promesse et budget | `backend/app/models/service_contract.py`, `backend/app/services/window_budget.py` |
| E/S et runner | `backend/app/services/dataops/storage.py`, `backend/app/resources/{dataops_runner,dataops_storage}.py` |
| Compilation | `backend/app/services/dataops/{compiler,typed_compiler,formulas,steps,types}.py` |

La réception des quatre lots exige leurs recettes exécutées et reliées aux
révisions, puis une livraison selon le processus habituel. Aucun statut de
réalisation ne découle de ce cadrage.
