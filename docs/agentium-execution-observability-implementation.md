# État d'implémentation — exécution et observabilité

Travail du 15 octobre 2026 sur `codex/execution-observability`, issue de
`origin/demo/agentic` à `0b63fcec`. `main` à `24ff6f1d` avait le même arbre,
avec un commit de fusion supplémentaire ; la base et l'upstream ont été corrigés
vers `demo/agentic`. La qualification décrite ci-dessous n'a effectué aucun
déploiement ; l'activation de production rapportée ensuite est distinguée ici.

Références : [plan O0–O7](agentium-execution-observability-plan.md),
[recette d'exploitation](agentium-execution-operations.md),
[handover différé](agentium-execution-deferred-handover.md),
[candidat Temporal natif](agentium-temporal-native-handover.md).
Ce rapport distingue du code testé localement, une qualification de mécanisme,
une activation de production déclarée et une recette VM effectivement attestée.

## Production déclarée le 15 octobre 2026

L'opérateur rapporte `4a404d61` en production, avec journal, supervision,
admission, échéances, annulation et réconciliation ouverts pour tous les
workspaces, ainsi que les services de contrôle actifs. L'API d'activités est
accessible mais vide avant de nouveaux travaux. `build-info`, santé,
sauvegarde, migrations et configuration effective sont ses observations ;
aucune nouvelle vérification VM n'est effectuée ici. `demo/agentic` et
`develop` sont à `4a404d61`, et `main` à `05809a8d`.

Le [bilan de production](ops/execution-observability-production-2026-10-15.md)
consigne cette provenance et le défaut du script à `4a404d61` : l'overlay et les
deux services de contrôle ne font pas partie de son `up`. Le correctif préparé
est celui de cette révision : `up` prend en charge les deux services. Temporal reste
désactivé, la comparaison des moteurs n'est pas réalisée et la certification
du catalogue reste ouverte. Les états DataOps/connecteurs ne changent pas.

## Code disponible

| Lot | Résultat | Limite de la conclusion |
|---|---|---|
| O0 | Autorités, contrats rapide/long, critères, portée canari, handover | Les plans DataOps/connecteurs historiques restent les références de leurs lots |
| O1 | Journal atomique avec écritures ORM/Core, projection native, intentions de soumission identifiantes, confirmations broker, déduplication native | Aucune CDC SQL brut ; les anciennes surfaces non raccordées ne deviennent pas durables par magie |
| O2 | API filtrées, agrégats exhaustifs autorisés, détail et historique, curseur tenant, SSE authentifié/rejouable, attente HTTP bornée 200/202 | La charge et les percentiles sur la VM restent à qualifier |
| O3 | Admission globale/workspace des calculs, réserve interactive, budget journalier, contrôleurs figés, baux, échéances, annulation, réconciliation, worker court séparé | Allocation ≠ CPU consommé ; la télémétrie RSS/cgroup/spill complète n'est pas produite par tous les runners |
| O4 | Essais isolés LangGraph/PostgreSQL, Temporal/LangGraph et candidat Temporal natif sans plugin | La comparaison A/B/baseline à corpus strictement identique reste ouverte ; aucune supériorité de performance n'est revendiquée |
| O5 | Port Skill à identité stable, attente des calculs enfants, deux compositions Temporal natives, revue et reçu du contrat de service | Candidat local fermé par défaut ; fournisseur simulé, profils linéaires explicites, exploitation VM non qualifiée |
| O6 | Vues System/workspace/plateforme dans Opérations, FR/EN, commandes distinctes de la fin du travail, ressources allouées, preuves natives, reconnexion/révocation | Les vues Qualité/Performance/Traces existantes restent nécessaires ; pas de nouvelle promesse d'alerte livrée sans test de service |
| O7 | Scaffolds opt-in, contrôles Helm/Compose, refus de downgrade destructeur, canari navigateur et recette de drainage | Qualification locale : aucune migration VM exécutée dans ce chantier ; migrations ultérieures rapportées par l'opérateur, budgets et certification VM non attestés ici |

Les nouvelles soumissions couvertes par l'outbox sont les démarrages manuels des
Systems, le Runner, les reruns, les préparations/SQL/scoring DataOps, l'entraînement
tabulaire et les calculs connecteurs. Les déclenchements et délégations qui
avaient déjà leur outbox restent dans leur protocole. Les autres tâches Celery,
dont les recettes Python génériques, ne sont pas converties implicitement.

Le journal couvre Run, SkillInvocation, RecipeExecution, ComputeRun, MLModel,
WorkspaceJob, ServiceWindow et DeliveryReceipt. Une ligne technique réussie
n'est jamais rebaptisée résultat accepté ou livraison reçue. Le backfill décrit
un état ponctuel. Les payloads, SQL, secrets et raisonnements internes sont
exclus des événements.

## Concurrence et conséquences opérationnelles

Les nouvelles préparations contrôlées utilisent RecipeExecution comme autorité.
Les tentatives C0 déjà liées à ComputeRun gardent ce lien. Les réservations
communes servent à l'admission, jamais à inventer un second résultat métier.
CPU/mémoire demandés et durée allouée restent séparés de la consommation mesurée.
Une perte de worker laisse une réservation à réconcilier tant que son arrêt
physique n'est pas reconnu.

L'orchestration historique ne réserve pas un slot dans le pool de calcul de
son enfant : avec un quota de deux slots, deux parents auraient sinon empêché
leurs propres enfants de démarrer. Elle garde sa file Flow existante. Cela ne
libère pas le worker Flow lorsqu'un ancien Skill attend un calcul. Les attentes
sans Activity occupée sont qualifiées pour les deux nouveaux profils Temporal ;
les anciens graphes ne sont pas transférés automatiquement.

La nouvelle annulation exige le périmètre canari et les autorisations natives,
y compris la garde canonique du System lié. Les droits sont revérifiés à la
consommation. Une demande durable déjà acceptée peut être drainée après fermeture
des nouvelles admissions ; une révocation de droits peut encore la refuser.
La demande, son application et la terminaison native restent trois états.

Les contrôleurs de récupération utilisent des transactions séparées avec des
attentes PostgreSQL bornées. Un calcul verrouillé ne bloque pas la publication
de l'outbox ou les autres contrôleurs. Le nettoyage des Runs historiques filtre
leur transport avant pagination. La réconciliation Temporal possède son propre
curseur de passage ; elle ne modifie pas le calendrier de publication.

## Décision sur les frameworks

Les essais locaux montrent que LangGraph persiste et reprend son graphe avec
PostgreSQL, et que l'intégration officielle Temporal peut attendre une décision
sans Activity occupée et reprendre après redémarrage. Ils utilisent un port
déterministe explicitement limité à la qualification.

Les deux premiers adaptateurs restent des expériences de mécanismes. Le plugin
LangGraph–Temporal est en Public Preview. Leur
[rapport A/B](evidence/execution-observability-2026-10-15/report.md) conserve
son verdict historique et ne qualifie pas le candidat natif ajouté ensuite.

Le candidat C utilise directement le SDK Temporal. Le Flow publié, ses contrats,
le profil, la révision et l'échéance sont figés. Chaque invocation possède une
identité stable et une empreinte de ses entrées. Un résultat enregistré est relu ;
un effet incertain n'est pas relancé automatiquement. L'IAM est revérifié avant
l'effet et avant sa publication ; un retour tardif ne remplace pas un état perdu.

Les préparations et le scoring en flux rendent leur référence native, puis
libèrent l'Activity. Les timers Temporal attendent le calcul et la revue humaine.
Les signaux réveillent seulement le workflow. Les décisions et reçus proviennent
des contrats de service existants. Le démarrage planifié crée une intention
Temporal au lieu d'une seconde soumission au moteur historique. La file du
worker Temporal porte la révision du code ; les anciennes révisions se drainent.

Le candidat accepte les deux compositions linéaires décrites dans son profil.
Il ne compile pas les branches, boucles, `agent_loop` ou sous-flows historiques ;
ces parcours restent sur leur moteur et profitent du journal commun. Son
activation générale reste soumise à la qualification VM, au fournisseur retenu
et à l'élargissement explicite des profils. Aucun scheduler LangGraph maison ni
Activity encapsulant tout le Flow n'est ajouté.

Le SDK Temporal reste dans l'image d'orchestration optionnelle. Un processus
isolé interdisant les imports Temporal/LangGraph a chargé l'API principale, les
tâches Celery générales et le worker de contrôle. Aucun ajout de dépendance aux
images générales n'est nécessaire pour le journal et le contrôle.

## Validations locales historiques

Les suites ciblées couvrent notamment rollback état/événement, ordre de commit
et backfill concurrents sur PostgreSQL, dernier slot partagé entre workspaces,
expiration en file, panne de publication, doublon, annulation et ancien bail,
contrôleur figé, garde canari, droits retirés après acceptation, et refus de
downgrade avec preuve. Une préparation native réelle a produit son dataset et
soldé son allocation. Les métriques absentes restent `null`.

Le frontend a passé 2 238 tests unitaires, le build de production et les gardes
i18n/chrome/navigation. Les cinq scénarios Chromium locaux couvrent français
bureau, anglais mobile, accessibilité Axe, totaux/pagination, demande d'annulation,
reprise de curseur, révocation, option désactivée et portée plateforme. Le build
et ces scénarios ont été rejoués après ajout des ressources de plateforme.

Les [29 tests du candidat C](evidence/execution-observability-2026-10-15/native-c/report.md)
couvrent les deux compositions jusqu'au reçu, les sorties DataPrep multiples,
le démarrage planifié, les refus et les retours tardifs. Les tests SDK utilisent
un vrai serveur Temporal jetable avec crash et reprise, et une base applicative
SQLite ; trois recettes PostgreSQL distinctes vérifient les courses et verrous.
La qualification [contrôle et transport](evidence/execution-observability-2026-10-15/control-and-scaffold/report.md)
conserve séparément les tests PostgreSQL, RabbitMQ réel et scaffolds. Ces preuves
composantes ne valent pas un parcours complet déployé sur la VM.

La suite backend finale passe sur le code figé : **9 596 réussites, 152 tests
ignorés, aucun échec**, en 925,72 secondes avec quatre workers. Les tests
d'infrastructure opt-in du passage général sont complétés par les recettes
locales distinctes ci-dessus. La conformité statique passe (16 assertions sur
22 vérifiées statiquement ; attestations des runners séparées). Ruff passe sur
les 53 nouveaux fichiers Python ; aucun diagnostic supplémentaire n'apparaît
sur les 26 fichiers Python existants modifiés.

Le [dossier final](evidence/execution-observability-2026-10-15/final-validation/validation.json)
conserve les résultats, commandes et empreintes des 108 fichiers de code, tests
et configuration concernés. Leur contenu est resté identique pendant la suite
finale. Ces résultats ne sont pas une nouvelle exécution sur la production
déclarée à `4a404d61`. La recette [VM](agentium-execution-operations.md) reste
déléguée pour les preuves non fournies : objectifs
p95, tailles des images release, scoring quotidien complet et reçu de livraison
sur la VM ne sont pas certifiés ici. Les reçus locaux des deux compositions
ne se substituent pas à cette preuve d'exploitation.
