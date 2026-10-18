# Opérations, Activités et Flow — implémentation et qualification

Travail du 16 octobre 2026 sur `codex/operations-activities-flow`, depuis
`demo/agentic` à `f4329db3`, avec le plan à `1cc5c8f5`.
Le [plan R1–R5](agentium-operations-activities-flow-plan.md) reste la référence
de recette. Ce rapport distingue le code, les preuves locales et la recette
de production à réaliser par l'opérateur. Il ne déclare aucun déploiement.

## Comportement livré dans la branche

**Opérations** conserve le moniteur du workspace : santé, alertes, runs, jobs,
qualité et recherche. **Activités** devient un onglet distinct. Qualité,
Performance et Traces restent accessibles. Les anciens liens `activityId` et
`scope` rejoignent Activités ; une sélection explicite d'une autre vue conserve
sa destination. Les aliases de System restent acceptés.

Les périodes `24h`, `7d`, `30d` partagent une ancre `as_of` dans l'URL. Un
rafraîchissement explicite la déplace ; changer d'onglet conserve la même borne.
La synthèse historique annonce ses limites de lecture (200 Runs, 100 jobs,
100 évaluations). Les séries d'activités ont leur population distincte et
exhaustive sous droits ; elles ne rebaptisent pas une invocation en Run.
Performance et les réservations actuelles signalent leur autre horloge.

Le suivi `/runs/{id}?view=flow` ouvre le snapshot du Run dans une vue en lecture
seule. Il ne monte pas l'éditeur et ne fait ni validation ni sauvegarde du Flow.
Il expose les passages, tentatives, invocations, recettes, calculs et sous-Runs
lisibles, avec panneau de travaux et frise. Les entraînements et jobs associés
utilisent leurs liens natifs ; les reçus sont rattachés par leur actif produit
et les fenêtres de service par leurs tentatives persistées. Les filtres et sélections ont des
identifiants stables. Les liens vers l'activité et les preuves continuent à
appliquer leurs autorisations natives.

Le graphe est réduit à sa topologie publique : pas de paramètres d'exécution,
prompts, entrées/sorties, secrets, policies, baux ou checkpoints bruts dans cette
API. Les Runs sans snapshot ou sans corrélation fiable sont explicitement
incomplets. Une absence de preuve ne signifie ni « en file » ni coût nul.

## Contrats de lecture

| Surface | Contrat |
|---|---|
| `GET /api/v1/observability/activities/features` | Capacités de lecture séparées, découvertes une fois par contexte navigateur |
| `GET /api/v1/runs/{id}/execution-view` | `schema_version=1`, Run/version/hash exécutés, graphe, synthèses sous droits, page de travaux, couverture, `read_version` et `snapshot_cursor` |
| `GET /api/v1/observability/activity-events[/stream]` | Filtre `run_id` avec `subtree=true` ; descendants résolus à la lecture, y compris créés après le snapshot |
| `GET /api/v1/observability/activities` | `since` inclusif et `until` exclusif, filtres natifs et pagination après droits |
| `GET /api/v1/observability/activities/series` | `from`, `until`, `metric`, `kind`, `status`, `system_id`, `bucket`, `time_basis` ; fenêtre de 30 jours au plus |
| Synthèse et Qualité | `as_of` et borne inférieure partagés ; les évaluations restent des évaluations, pas des activités techniques |

Les entrées d'un nœud reçoivent un identifiant de passage persistant. Les
invocations gardent leur propre identifiant de tentative. Les transitions de
checkpoint et leurs projections sont écrites dans la transaction native ; un
rollback ne produit pas de notification fantôme. Une modification d'une preuve
de coût peut invalider la vue sans changement de statut. Les métriques brutes
restent hors du journal public.

Le curseur est lu avant le snapshot pour rejouer toute transition concurrente.
Une invalidation demande une relecture autorisée, plutôt que de reconstruire
le résultat depuis des événements arrivés dans le désordre. L'expiration du
curseur demande une resynchronisation. La révocation purge la vue et arrête le
flux ; les commandes restent sur le protocole d'Activités existant.

## Sémantique des séries

- `created` décrit **l'état courant des travaux créés** dans `[from, until)`.
  Ce n'est pas l'historique du nombre de jobs simultanément en cours.
- `finished` utilise la fin, même si le travail a commencé avant la période.
  Une date absente apparaît dans la couverture des travaux terminaux créés
  dans la fenêtre ; elle n'est pas remplacée par la date de création.
- Les p50/p95 sont les quantiles exacts par rang, séparés par type de travail,
  sur les seules durées terminales mesurées. Les effectifs éligibles et mesurés
  restent visibles. Les valeurs absentes restent nulles.
- `metric=cost` exige `kind=skill_invocation|compute_run` et `time_basis=finished`.
  Les contrôles de dépense affichent leur propre population ; un filtre de Runs
  en échec ne devient pas un filtre d'invocations en échec.
- Les dépenses proviennent des sources natives : fournisseur mesuré, tarif
  calculé et allocation d'infrastructure, séparés par devise. Un coût de Run
  n'est jamais ajouté aux mêmes coûts d'invocations. `cost_measured` seul ne
  prouve pas la nature du montant : la preuve M3 est requise.
- Le montant connu, sa couverture et les coûts inconnus restent distincts.
  Un vrai zéro étayé est conservé. Aucune conversion monétaire implicite.
- PostgreSQL utilise une transaction de lecture `REPEATABLE READ` pour une
  réponse cohérente. Les droits s'appliquent avant les comptes, quantiles et
  coûts. Sur PostgreSQL 16+, les modes de lecture IAM `compat` peuvent utiliser
  une traduction SQL des droits, testée contre le lecteur natif, puis des
  agrégats avec `percentile_disc`. La cible Compose/Helm reste PostgreSQL 17.
- Les modes IAM `shadow`/`enforce`, les workspaces gérés par la migration 059,
  une filiation d'invocation incohérente ou un PostgreSQL antérieur à 16 gardent
  le lecteur natif. La présence de fenêtres de service ou de reçus dans la
  population à lire impose aussi ce repli : leurs droits ne sont pas traduits
  en SQL. Les autorisations particulières BRD et les dates historiques
  non canoniques sont vérifiées nativement avant l'agrégat ; au-delà de 256 jobs
  BRD ou 128 dates distinctes, **toute** la lecture revient au chemin natif.
  Ces limites choisissent le chemin et ne tronquent jamais ses résultats.
- Le lecteur natif travaille par lots de 2 000 ; le contexte de droits est borné
  et lié à cette seule transaction. Aucun cache n'est partagé entre utilisateurs.
  Les autres lectures et le SSE revérifient leurs droits natifs sans ce cache.

Les fenêtres de service exigent l'appartenance explicite au workspace, même
pour un administrateur de plateforme. Les reçus appliquent les autorisations
natives de l'actif et de ses parents récursivement. La lecture de métadonnées
ne télécharge aucun objet et ne crée pas un droit de consommation. Les listes
gardent les reçus historiques autorisés après invalidation ; le lien de preuve
du Flow exige en plus une qualification courante. Les mêmes restrictions
précèdent les comptes et le rejeu d'événements.

Le tableau accessible reste disponible quand le graphique différé n'est pas
chargé. Les graphiques utilisent Chart.js existant. Aucune dépendance de
runtime, aucun orchestrateur ni infrastructure supplémentaire n'est introduit.

## Qualification locale

Les preuves et leurs empreintes sont rassemblées dans
[`evidence/operations-activities-flow-2026-10-16/`](evidence/operations-activities-flow-2026-10-16/).
Le bilan final y distingue tests SQLite, PostgreSQL, navigateur avec API
déterministe, construction Angular et banc de charge. Les scénarios simulés
ne prouvent ni le fonctionnement d'un fournisseur vivant ni celui de la VM.

Les recettes locales conservent les huit combinaisons Qualité (FR/EN,
clair/sombre, Activités ouvert/fermé), le graphe historique à 390 px et les deux
compositions déterministes. Le correctif de reconnexion reconnaît explicitement
`resync_required` et attend le nouveau snapshot avant de reprendre son curseur.
Une attente native reste une attente ; le motif externe exige une recette
liée au même workspace, Run et nœud.

**La qualification de charge R2 reste ouverte.** Sur le candidat `0e745155`,
100 000 activités et dix lecteurs concurrents donnent un p95 de **5,479 s**
pour l'activité et **9,468 s** pour les coûts, au-dessus des **2 s** visées.
Les comptes autorisés sont exacts ; le surcroît RSS backend combiné est
d'environ 6 Mio et aucune attente `Lock` de l'écrivain n'est observée.
Ce banc exclut HTTP, les gros payloads, le débit IAM strict/shadow et les
fenêtres/reçus protégés. Le [bilan complet](evidence/operations-activities-flow-2026-10-16/report.md)
conserve les mesures intermédiaires, les limites et les résultats des tests.
Il ne ferme ni la performance de R2 ni la recette de release R5.

**Suite du 17 octobre : chemin SQL allégé.** Les causes ont été identifiées :
- une garde de cohérence qui parcourait tout l'historique du workspace ;
- des dates et des durées relues dans le JSON du snapshot ;
- une preuve de coût analysée deux fois par ligne ;
- des débordements sur disque avec un `work_mem` de 4 Mo.

La migration 138, la garde limitée à la population et la mémoire de lecture
réglable (`ACTIVITY_SERIES_WORK_MEM_MB`) corrigent ces points. Les résultats
restent identiques au lecteur natif, qui reste l'oracle des tests.

En mesures entrelacées sur un même poste, le p95 baisse d'un facteur 3 à 6 :
- à 10 lecteurs, de 10,6 s à 1,9 s pour l'activité, et de 11,4 s à 3,6 s pour
  le coût ;
- à 20 lecteurs, de 13,7 s à 2,9 s pour l'activité, et de 32,6 s à 6,1 s pour
  le coût.

Le poste était chargé par d'autres applications ; les valeurs absolues ne sont
pas une qualification. Voir le [dossier du 17 octobre](evidence/activity-series-typed-2026-10-17/report.md).
Le seuil de 2 s reste à vérifier sur la VM, dans la recette ci-dessous.

## Recette de release à déléguer

Les deux nouvelles options valent `false` par défaut :

```dotenv
EXECUTION_VIEW_ENABLED=false
ACTIVITY_SERIES_ENABLED=false
ACTIVITY_SERIES_WORK_MEM_MB=16
```

Elles ferment uniquement les nouvelles lectures. Ne pas fermer le journal,
l'admission, les contrôleurs ou les workers pour tester le repli UI. R1 conserve
l'accès au moniteur avec le journal ouvert ou fermé. Aucun nouveau schéma
Alembic n'est ajouté ; les métadonnées de corrélation sont additives dans les
champs JSON existants.

La lecture native du Flow peut rester ouverte sans journal, comme instantané
actualisable manuellement, sans SSE. Les séries exigent le journal actif.

1. Figer le candidat, suivre le processus de release et mesurer les images avec
   les budgets en vigueur. Relever `build-info`, options effectives et état des
   services de contrôle. Ce travail n'a pas d'accès à la VM.
2. Dans Showcase, identifier un Run évalué et conserver ses IDs d'évaluation,
   Run, invocation et preuve. Jouer point **et** cellule → Run → preuve → retour,
   puis reload, clavier et écran de 390 px. Aucun skip faute de corpus ne vaut
   validation.
3. Ouvrir la lecture Flow, exécuter les deux parcours composites du plan,
   éditer ensuite le Flow et vérifier que le premier Run garde son snapshot.
   Vérifier retry, branche écartée, sous-Run, attente humaine et reconnexion.
4. Qualifier les séries sur la configuration cible avant leur ouverture large,
   avec trois profils : responsable System, membre restreint et administrateur.
   Comparer liste et série `created` sur corpus figé et bornes identiques.
   Conserver les inconnus et les couvertures dans les comptes rendus.
5. Vérifier révocation et relecture avec les comptes de recette, sans scénario
   de panne destructif en production. Fermer séparément une nouvelle lecture
   si nécessaire ; conserver l'état natif et le journal pour la reprise.

La certification Showcase, les budgets d'images du candidat et la charge sur
la VM restent des vérifications de release. Kubernetes, Spark, Kafka, Redis,
Temporal et narration gardent leur handover et leurs décisions séparées.
