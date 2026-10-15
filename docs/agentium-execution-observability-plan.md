# Exécution et observabilité communes — O0 à O7

Décision de travail du 15 octobre 2026. Base : `demo/agentic` à `0b63fcec`.
Ce plan complète les plans DataOps, calcul local et connecteurs ; il ne remplace
ni leurs critères de recette ni leurs preuves historiques. Le code ne permet
pas de déclarer a posteriori un critère satisfait. Une validation locale n'est
pas une certification de la VM. Aucune activation en production n'est implicite.

## Résultat attendu

Un responsable suit une même exécution depuis le System jusqu'à ses étapes,
tentatives, décisions, calculs, résultats et reçus. Un agent peut appeler un
traitement DataOps/ML, et un traitement peut appeler un agent, sans intégration
propre au scénario. L'attente HTTP, le calcul et l'attente humaine ont des durées
et des ressources distinctes. La narration reste différée.

Les vues existantes Opérations, Qualité, Performance et Traces sont conservées.
La supervision du System porte sur la promesse (fraîcheur, complétude,
acceptation, réception), celle du workspace sur les travaux et arbitrages,
celle de la plateforme sur les capacités, files, baux et politiques. Toutes
les autorisations sont appliquées côté serveur, y compris pendant un flux.

## Autorités et compatibilité

| Domaine | Autorité native |
|---|---|
| Workflow | Run, version de Flow et contrats immuables ; le runtime choisi possède son curseur d'exécution |
| Invocation et preuves | SkillInvocation, modèle effectivement appelé, décisions et sources vérifiées |
| Préparation, SQL et scoring | RecipeExecution selon L1 du plan local |
| Connecteurs | ComputeRun et registres d'écriture/réconciliation |
| Entraînement | MLModel actuellement ; distinguer explicitement version d'artefact et tentative dans la projection |
| Acceptation et livraison | ServiceWindow, ServiceAttempt, qualifications, décisions et DeliveryReceipt |

Le pont C0 avait fait de RecipeExecution une projection de ComputeRun sous
`connector_framework_enabled`, contrairement à L1. Les nouveaux calculs du
contrôle O3 suivent RecipeExecution. Les liens C0 existants sont drainés sous
leur ancien contrôleur. Aucun transfert au milieu d'une tentative, aucune
seconde tâche pour le même calcul. Les réservations de ressources sont des
enregistrements de coordination et non un second état métier.

La projection de supervision conserve `kind`, identité native, Run/étape,
parent, tentative, version, moteur, état natif et état affiché. Une réussite
technique, un résultat accepté et une livraison reçue restent trois faits.
Les données historiques sont étiquetées comme snapshots : aucun événement
d'exécution ancien n'est inventé lors du backfill.

## Choix de composants

| Brique | Décision | Limite |
|---|---|---|
| PostgreSQL | Contrats, états métier, journal, outbox, admission atomique | NOTIFY n'est pas un historique ; aucune transaction DB distribuée avec Temporal |
| RabbitMQ | Transport Celery et notifications séparées | Au moins une fois ; confirmation et déduplication ; pas de garantie exactly-once sur une cible externe |
| SSE | Diffusion navigateur authentifiée avec curseur | Reprise implémentée par le serveur, buffers bornés, commandes par REST |
| LangGraph | Candidat agentique à qualifier | Checkpointer persistant requis en mode autonome ; reprise d'un nœud peut rejouer ses effets |
| Temporal | Candidat à la durabilité des workflows longs/composites | Files propres, contrôle déterministe, Activities pour E/S ; service et historique à exploiter |
| OpenTelemetry | Corrélation des traces techniques | Ne remplace ni le journal métier complet ni les preuves ; conventions GenAI à versionner |

L'intégration officielle LangGraph–Temporal est en Public Preview au moment de
la revue documentaire. Son checkpoint et ses retries ne doivent pas être
doublés par ceux de LangGraph/Celery. Épingler une combinaison réellement testée,
car le packaging récent diffère des exemples plus anciens. Les dépendances
d'orchestration restent isolées des images ML et du backend général.

Prefect sait gérer workflows dynamiques, événements et interventions humaines.
Il n'est pas ajouté comme second orchestrateur de données. Les vues de tâches
et de chronologie Databricks, les contrôles de scénarios Dataiku et les attentes
déférables Airflow servent de références de conception, pas de dépendances.

## Contrat rapide / long

Une opération métier est soumise durablement une seule fois. L'API peut
attendre au plus deux secondes par défaut, puis retourner 202 avec la même
identité et une URL de suivi. Un résultat déjà terminal peut répondre 200.
La déconnexion n'annule pas le travail. Les validations locales légères peuvent
rester dans l'API. Le temps de réponse ne choisit jamais le moteur après coup.

Séparer attente en file, timeout de tentative, échéance métier absolue, TTL
d'une décision humaine et budget cumulé. Une horloge monotone n'est jamais une
échéance persistée. Le code, les entrées, la politique et le moteur sont figés
au début de l'exécution. Une reprise de transport garde l'identité ; une reprise
métier autorisée crée une tentative liée.

Une attente humaine ou externe durable ne garde pas un slot de calcul. Les
actions de contrôle disposent d'une capacité courte séparée. L'admission réserve
atomiquement slots, CPU, mémoire et budget par workspace ET globalement. Une
politique tenant peut diminuer un plafond opérateur, jamais l'augmenter.
L'ancien détenteur d'un bail ne peut plus publier. Un résultat externe inconnu
nécessite une réconciliation avant une nouvelle écriture.

## Événements et mesures

État métier et événement sont enregistrés dans la même transaction. Le flux
utilise une enveloppe CloudEvents, une identité stable et une séquence par
workspace. La publication doit tenir compte de l'ordre de commit : un simple
BIGSERIAL ne prouve pas qu'aucun événement plus ancien ne pourra apparaître.
Les consommateurs dédupliquent ; le curseur est lié au workspace. Snapshot et
reprise ne laissent pas de trou. Un client lent se resynchronise depuis la DB.

Les sources sont réduites à une liste de champs publics. Aucun secret, prompt,
sortie brute, donnée tabulaire ou raisonnement interne dans les notifications.
Les tokens et la progression intensive sont séparés du journal de transitions.
Pas d'événement par ligne scorée. Les preuves restent dans leur stockage et
sont relues sous leurs propres droits. Une révocation ferme le flux même si
celui-ci reçoit continuellement des messages.

Conserver CPU mesuré, ressources allouées × durée, RSS, mémoire cgroup, spill,
volumes, attente, coût du modèle et couverture de mesure séparément. NULL ne
devient pas zéro. Les coûts des tentatives en échec comptent ; les coûts parent
et enfants ne sont pas ajoutés deux fois. Le coût par résultat accepté utilise
les décisions et reçus, pas simplement `succeeded`. Les agrégats SQL portent
sur toute la population autorisée ; la pagination ne limite pas les totaux.

## Lots et portes de validation

| Lot | Livraison | Recette de fermeture |
|---|---|---|
| O0 | Autorités, contrats, plan et handover | Responsabilités et divergences explicites, aucune autorité concurrente |
| O1 | Journal, publication et soumissions durables | Panne entre commit et broker, redélivrance, rollback, absence de double effet |
| O2 | Projection commune, agrégats, détail et SSE | Historique complet, curseur, backfill honnête, isolation, client lent |
| O3 | Admission, délais, annulation, baux, mesures | Dernier quota en concurrence, expiration en file, vieux bail, capacité courte disponible |
| O4 | Essai comparatif de runtimes | Même corpus de pannes, consommation et dépendances mesurées, décision écrite |
| O5 | Deux compositions agent/données | Attentes durables, contrats et reçus réutilisés dans les deux sens |
| O6 | Trois niveaux de supervision et alertes | Diagnostic et action sans copier des IDs, droits, FR/EN, clavier, révocation |
| O7 | Qualification puis livraison progressive | Preuves liées au SHA, budgets, migrations, restauration, drainage et rollback |

O2 et la conception UI avancent après O0/O1, en parallèle d'O3/O4. Limiter le
travail parallèle à trois axes : runtime, interface, qualification. Les statuts
effectifs sont consignés dans le rapport d'implémentation, jamais déduits de la
présence d'un fichier ou du message d'un commit.

## Qualification des moteurs et compositions

Comparer la baseline à (A) LangGraph/PostgreSQL sur les workers existants et
(B) LangGraph–Temporal officiel. Si A nécessite un nouvel ordonnanceur durable
maison, son critère de simplicité échoue. Si le plugin B bloque, étudier Temporal
natif sur les étapes métier ; ne pas masquer un graphe complet dans une seule
Activity avec une deuxième autorité de reprise.

Parcours 1 : agent → préparation/scoring → agent → revue → livraison.
Parcours 2 : préparation/scoring planifié → agent pour anomalie/explication →
juge et politique → livraison. Réutiliser le routeur modèle du workspace ; les
doublures de test déterministes ne qualifient aucun fournisseur réel.

Showcase est le workspace de recette. Le volume cible numérique est 2–3 millions
de lignes/jour avec un schéma compatible avec le modèle. Le benchmark historique
ne comprend aucun reçu et atteint la limite cgroup de 4 Gio : il ne prouve pas
une livraison quotidienne ni une réserve mémoire de moitié.

Injecter crash avant/après effet externe, perte du broker, doublon, branche en
échec, attente humaine avec redémarrage/version nouvelle, révocation, annulation
pendant publication, dépassement de budget, ordre de commit inversé et reconnexion.
Les tests destructifs tournent en environnements jetables, pas sur la production.

Objectifs initiaux à qualifier sous une charge documentée : accusé durable p95
<500 ms ; transition visible p95 <2 s ; aucun slot de calcul en attente humaine ;
aucun effet externe dupliqué dans les cas certifiés ; aucun accès inter-workspaces.
Mesurer aussi CPU/RAM, disque, croissance du journal et tailles d'images réelles.

Déployer d'abord la lecture/journal, puis de nouvelles exécutions Showcase.
Un ancien workflow termine sous son moteur/version d'origine. Revenir en arrière
ferme les admissions candidates sans effacer états, événements ou données Delta.
Une seule VM reste un point de panne, même avec Temporal et un broker durable.

## Sources documentaires consultées

- [PostgreSQL NOTIFY](https://www.postgresql.org/docs/current/sql-notify.html)
- [RabbitMQ reliability](https://www.rabbitmq.com/docs/reliability)
- [SSE, standard HTML](https://html.spec.whatwg.org/multipage/server-sent-events.html)
- [CloudEvents 1.0.2](https://github.com/cloudevents/spec/blob/v1.0.2/cloudevents/spec.md)
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [Temporal–LangGraph](https://docs.temporal.io/develop/python/integrations/langgraph)
- [Temporal worker versioning](https://docs.temporal.io/worker-versioning)
- [Temporal deployment](https://docs.temporal.io/self-hosted-guide/deployment)
- [OpenTelemetry traces](https://opentelemetry.io/docs/concepts/signals/traces/)
- [Databricks monitoring](https://docs.databricks.com/aws/en/jobs/monitor)
- [Dataiku scenarios](https://doc.dataiku.com/dss/latest/scenarios/index.html)
- [Airflow deferral](https://airflow.apache.org/docs/apache-airflow/stable/authoring-and-scheduling/deferring.html)
- [Prefect capabilities](https://docs.prefect.io/v3/get-started)

Voir [le handover des chantiers différés](agentium-execution-deferred-handover.md).
