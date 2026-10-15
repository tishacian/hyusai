# Handover — Kubernetes, Spark, Kafka, Redis et narration

État au 15 octobre 2026 ; référence `demo/agentic` à `0b63fcec`.
Livrable O0, à actualiser à chaque livraison O1–O7 puis à la réouverture d'un
chantier. Responsable de reprise : propriétaire plateforme pour infrastructure,
propriétaire du System documentaire pour narration ; opérateur du banc réel
à désigner lors de la qualification. Aucun de ces chantiers n'est activé ici.

Les plans d'origine restent normatifs : [DataOps](agentium-dataops-plan.md),
[amendements](agentium-dataops-amendments.md), [calcul local](agentium-dataops-local-compute-plan.md),
[connecteurs](agentium-dataops-connectors.md), [certification déléguée](agentium-connectors-certification-handoff.md).
Une décision ou preuve historique n'est pas réécrite pour suivre le code.

## Kubernetes éphémère — D4

- **Existant :** chart `ops/helm/agentium/`, Deployment DataOps séparé, placement
  local et primitives de ressources/baux. Helm déploie déjà des services
  permanents ; le différé concerne les Jobs de calcul à la demande.
- **Déclencheur :** cluster d'un client disponible, ou échéance locale intenable
  après optimisation, VM plus grande et examen d'un worker sur VM dédiée.
- **Prérequis :** cluster/version effectivement disponibles, pool extensible si
  une économie élastique est promise, RBAC, réseau, identités objet temporaires,
  stockage, quotas, budget et opérateur de certification identifiés.
- **Première étape :** ajouter un adaptateur de placement au contrat d'exécution
  existant ; conserver identité, bail, publication, annulation et événements.
- **Recette :** soumission/idempotence, perte/reprise de nœud, TTL, annulation,
  ancien bail, secrets expirés, accès inter-workspaces refusé. kind qualifie le
  cycle des Jobs, pas l'autoscaling, le réseau fournisseur ou le coût réel.
- **À revalider :** versions OVH/Kubernetes citées historiquement ; elles ne
  sont ni un inventaire vivant ni une obligation de mise à niveau actuelle.

## Spark — D5

- **Existant :** compilateur de préparation et discipline SQL portable à
  poursuivre, runner DuckDB et stockage objet/Delta ; aucun placement Spark
  qualifié par ce handover.
- **Déclencheur cumulatif :** volume hors fenêtre sur une grosse machine,
  aucun moteur client adapté, cluster et versions compatibles disponibles.
- **Alternative à examiner d'abord :** pousser le calcul vers Databricks ou
  Snowflake via un profil D7 mesuré. Un format Iceberg/Delta ne garantit pas
  à lui seul l'accès au catalogue/stockage ni l'exécution distante.
- **Première étape :** corpus de parité sémantique puis rendu/runner Spark,
  sans changer le contrat des étapes ni retirer de fonction métier.
- **Recette :** nulls, types, dates/fuseaux, unicode, agrégats, jointures,
  fenêtres, multiples sorties, reprise et commits Delta ; coût total et durée
  de bout en bout, reçus compris. La parité ne se prouve pas par une regex SQL.
- **Questions :** moteur/version/opérateur, catalogue, authentification,
  propriétaire du coût et environnement réel de qualification.

## Kafka

- **Existant :** aucun Kafka configuré dans la stack inspectée. Le socle retenu
  est journal PostgreSQL + RabbitMQ + SSE.
- **Déclencheur :** débit/rétention/consommateurs indépendants mesurés dépassant
  les capacités ou coûts acceptables du socle, ou intégration à un Kafka client.
- **Première étape :** benchmark comparatif sur le même corpus et le même
  contrat CloudEvents ; adaptateur de publication, pas second journal métier.
- **Prérequis :** responsabilité d'exploitation, partitions/clés, rétention,
  ACL, schémas et budget définis. Préserver l'ordre par activité et la causalité.
- **Recette :** replay, lag, doublons, rebalance, évolution de schéma, suppression
  de droits et arrêt/redémarrage des consommateurs ; absence de double effet
  sur les systèmes externes. Ne pas promettre exactly-once hors périmètre Kafka.

## Nouvel usage de Redis

- **Existant :** Redis LiveKit optionnel (`realtime-scale` dans Compose) et
  cache Intelligence avec repli mémoire. Aucun nouveau rôle d'orchestration
  n'est attribué à ces instances.
- **Déclencheur :** besoin de cache/coordination à faible latence mesuré et
  bénéfice démontré face à PostgreSQL/RabbitMQ.
- **Première étape :** définir clés, TTL, isolation, politique d'éviction et
  comportement sans Redis. Garder états durables et autorisations dans leurs
  autorités ; ne pas coupler la disponibilité métier au cache LiveKit.
- **Choix ouvert :** cache, Pub/Sub ou Streams selon le besoin. Pub/Sub perd les
  messages des clients absents ; Streams impose rétention, reprise et gestion
  des consommateurs. Aucun de ces choix n'est présélectionné.
- **Recette :** indisponibilité, éviction, clé expirée, reprise, charge, isolation
  et invalidation à la révocation ; comparaison de coût et latence.

## Narration

- **Références :** [contrat Showcase](agentium-showcase-narration-contract.md),
  [gateway](ops/narration-gateway.md), juge typé, actifs et promesses de service.
- **État :** code derrière `narration_enabled=false`, moteur externe non
  raccordé/qualifié dans cette livraison. La route envisagée est Gemini via
  OpenRouter ; elle ne constitue pas un fournisseur déjà qualifié.
- **Déclencheur :** reprise décidée et dépôt/endpoint réel fourni, avec accès et
  environnement de qualification. Aucun client pilote supplémentaire requis.
- **Première étape :** adapter le gateway externe aux contrats d'exécution,
  événements et annulation communs ; conserver le moteur, sans le réécrire.
- **Volume :** plusieurs centaines de pages/images par jour ; la recette
  documentaire existante vise 500 unités, sans compter deux fois page/image.
- **Recette :** manifeste/digests, couverture complète, reprise sans double
  soumission, coûts inconnus explicites, transport vision réel, preuves et
  abstention du juge. J2450 uniquement lorsqu'il s'agit de traduction. Revue
  humaine liée au candidat exact et reçu de livraison effectif.
- **Questions :** endpoint, authentification, modèle/version texte et vision,
  coûts, corpus humain indépendant et destination effective de livraison.

## Règle commune de reprise

Avant le premier changement, relever SHA, drapeaux et déploiement effectifs,
mettre à jour ce document, retrouver les preuves et nommer le responsable.
La première PR de chaque chantier doit expliciter sa dépendance au socle
d'exécution, ses migrations, ses limites et son retour arrière. Les contrats
et événements communs restent stables ; les bancs indisponibles sont indiqués
NOT RUN et transmis à l'opérateur, jamais remplacés par des assertions simulées.
