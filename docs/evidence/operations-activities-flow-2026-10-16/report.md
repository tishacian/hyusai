# Qualification locale — Opérations, Activités et Flow

Date : 16 octobre 2026. Base : `demo/agentic` à `f4329db3`, plan à
`1cc5c8f5`. Le plan d'origine est conservé. Ce dossier est une preuve locale,
pas une attestation de production, de certification connecteur ou de release.

**Verdict du candidat `0e745155` :** comportement fonctionnel couvert localement,
build frontend réussi, charge R2 **non qualifiée au seuil de 2 s**. La dernière
paire de mesures donne 5,479 s pour l'activité et 9,468 s pour les coûts.
Les options de lecture Flow et séries restent `false` par défaut. Aucun seuil
ni drapeau de production n'a été modifié.

| Lot | État documenté |
|---|---|
| R1 | Implémenté ; conservation des huit combinaisons Qualité et séparation des onglets testées localement |
| R4 | Implémenté ; corrélations, droits, suivi historique, SSE et compositions testés localement |
| R2 | Implémenté ; exactitude fonctionnelle et droits testés, objectif de latence non atteint |
| R3 | Plan d'origine conservé, rapport et handover reliés aux documents O0–O7 |
| R5 | Dossier local produit ; recette Showcase, images et qualification de release à effectuer par l'opérateur |

## Périmètre et sources

Le code initial figure dans `636bb533`, les adaptations des tests de la base
dans `36b5ed6a`, et l'ouverture explicite des graphiques Qualité dans la recette
navigateur dans `2fb19419`. `source-sha256.json` identifie les fichiers du
candidat final ; chaque banc de charge conserve aussi ses propres empreintes.
Les derniers correctifs de lecture et d'autorisation sont dans `93014b8f`,
`a38ddf0e` et `0e745155`. Les commits documentaires suivants ne changent pas le
code mesuré ni construit.

Les journaux ont leurs chemins locaux normalisés et leurs séquences ANSI
retirées. Le résumé des tests unitaires frontend contient le début et la fin
du journal, sans reproduire les milliers de lignes intermédiaires. Les captures
proviennent des fixtures déterministes de Playwright, pas de Showcase.

## Tests et contrôles fonctionnels

| Contrôle | Résultat | Preuve et limite |
|---|---|---|
| Suite backend, 4 processus | 9 868 réussites, 222 ignorés, 3 échecs | `backend-full.log` ; les trois échecs sont reproduits sur la base, puis corrigés et rejoués ci-dessous |
| Reproduction des trois échecs | 3 échecs identiques sur `1cc5c8f5` | `backend-baseline-failures.log` |
| Reprise ciblée backend après correction | 122 réussites | `backend-final-targeted.log` ; séries, IAM, fenêtres, PostgreSQL, Flow, tests de base corrigés |
| Unités Angular | 2 302 réussites | `frontend-unit-summary.log` |
| Navigateur Chromium | 18 réussites | `frontend-browser.log`, `screenshots/` ; API et SSE simulées |
| Reprise SSE après expiration du curseur | 23 réussites ciblées sur le correctif final | `frontend-sse-final.log` ; abandon des anciens événements, relecture et nouveau curseur |
| Attente native d'invocation | 1 régression réussie, avec cinq cas de filiation | `backend-waiting-final.log` ; une simple attente ne devient pas une dépendance externe inventée |
| Séries finales, PostgreSQL et reçus | 35 réussites | `backend-series-final.log` ; comparaison SQL/natif, bornes UTC, droits, replis complets |
| Contrats et droits récursifs des reçus | 36 réussites | `backend-receipt-grants.log` ; aucune lecture d'ObjectStore pour l'autorisation de métadonnées |
| Régression finale Flow, Activités et IAM | 57 réussites | `backend-flow-activity-regression.log` |
| Construction Angular de production | Réussite, 73,88 s ; bundle initial 922,69 ko, transfert estimé 244,11 ko | `frontend-build.log` ; seuils d'erreur respectés, avertissements de taille et de templates conservés |
| Traductions | 12 700 clés, contrôle réussi | `frontend-i18n.log` |
| Catalogue de navigation | Contrôle réussi | `frontend-navigation.log` |
| Charte UI | Échec préexistant : 7 halos pour une limite de 6 dans `styles.scss` | `frontend-chrome.log` et `frontend-chrome-baseline.log` ; aucun changement de cette feuille ni du plafond |
| Conformité statique | Réussite, 16/22 déclarations statiquement contrôlées | `compliance.log` ; les attestations de runners restent séparées |
| Ruff | 15 nouveaux fichiers Python sans erreur ; huit fichiers du dernier correctif sans erreur | `new-python-ruff.log`, `python-final-ruff.log` ; `python-lint-comparison.json` compare aussi les fichiers historiques du premier lot à la base, qui n'est pas globalement propre |

La suite backend a été exécutée avec Python 3.12.14, pytest 9.1.1 et
SQLAlchemy 2.0.52. PostgreSQL 16.2 local fournit des schémas isolés aux tests
d'intégration. Il ne s'agit pas d'un rejeu complet de l'historique Alembic.
Node 24.19.0 sert aux contrôles Angular.

Les trois corrections de tests conservent leur intention : la tête Alembic
attendue est 137, avec vérification des liens 137 → 136 → 135 → 134 → 133 ;
les deux scénarios TabICL créent désormais le workspace réel avant de vérifier
le refus du profil retiré. Aucune garde MLOps n'a été supprimée. La suite
complète n'a pas été relancée après ces corrections : le résultat publié est
le résultat complet initial et la reprise ciblée, pas un total vert reconstitué.

Le correctif final `93014b8f` reconnaît le message SSE `resync_required`,
abandonne la connexion devenue incomplète et reconnecte après relecture avec
le curseur du nouvel instantané. Les 23 tests ciblés et le build portent sur
ce correctif ; les 18 recettes navigateur et les 2 302 unités le précèdent.
Le statut natif `waiting` est préservé ; un motif externe exige une recette
persistée dans le même workspace, Run et nœud.

Le build ne relève aucun plafond. Il conserve notamment l'avertissement du
bundle initial au-dessus de 500 ko et ceux des styles Chat/Work/Studio au-dessus
de 24 ko ; leurs seuils d'erreur ne sont pas franchis. Ce build Angular ne
mesure pas la taille de l'image Docker frontend.

Une compilation Angular non bornée lancée simultanément avec pytest a saturé
la mémoire du conteneur. Trois workers de collecte pytest ont été remplacés
avant la suite complète. Les vérifications frontend finales utilisent
`GOMEMLIMIT=4GiB GOMAXPROCS=2` et sont séparées des charges. Ces bornes concernent
l'outil de compilation ; aucun plafond de l'application ou des images n'a changé.

## Recettes couvertes

- Opérations reste le moniteur ; Activités est distinct. Les anciens favoris,
  les capacités lentes/fermées/en erreur et les paramètres de période sont testés.
- Qualité est vérifiée dans les huit combinaisons FR/EN × clair/sombre ×
  Activités ouvert/fermé : point et cellule vers le Run exact, invocation et
  preuve, retour, rechargement, clavier, score absent, radar et historique.
  Les contrôles Axe portent sur les composants de preuves et les onglets,
  pas sur une certification d'accessibilité de toute l'application.
- Le Flow utilise le snapshot exécuté, sans appel à l'éditeur : anciennes
  versions, tentatives, travaux parallèles, attente humaine, sélection stable,
  reconnexion, révocation, graphe adapté à 390 px et lecture sans journal.
- Les tests backend exercent les deux compositions avec exécution DAG réelle
  et dépendances métier déterministes, ainsi qu'une reprise humaine sans
  contexte mémoire de passage. Ils n'appellent ni modèle vivant ni système
  externe de livraison.
- Les droits natifs sont vérifiés pour les membres, reviewers, administrateurs,
  chats privés, workbench, décisions gérées, invocations strictes, calculs et
  jobs. Le cache de lecture ne dépasse pas une identité/transaction ; les tests
  PostgreSQL vérifient la cohérence de snapshot et les écritures concurrentes.
- Les coûts fournisseur/catalogue/infrastructure restent séparés ; les dépenses
  du Run ne doublonnent pas celles des invocations. Les dates et mesures absentes
  restent des lacunes de couverture.

La revue finale a aussi reproduit deux défauts d'autorisation : un reçu issu
d'un Run privé apparaissait dans les comptes d'activités, et un reçu d'actif
public dérivé d'un parent privé pouvait être proposé dans le Flow. Le correctif
réutilise `resolve_asset_ref` et `native_authorizer` récursivement, sans lire
de manifestes ni d'objets en mode métadonnées. Fenêtres et reçus exigent une
adhésion explicite au workspace, même pour un administrateur de plateforme.
Les listes conservent les historiques autorisés après requalification ; le
Flow impose en plus une qualification courante pour sa preuve.

Une ancienne fixture d'Activités utilisait un reçu orphelin et un administrateur
sans adhésion. Elle fournit désormais un actif enregistré et une adhésion
réelle, sans retirer ses assertions de filiation et de tentatives. Les 57
régressions finales incluent ce scénario corrigé. Les séries reviennent au
lecteur natif lorsque des fenêtres ou reçus peuvent entrer dans leur population.

## Charge PostgreSQL — méthode et première mesure

Le script `backend/scripts/qualify_activity_series.py` crée puis retire un
schéma isolé. Il charge 100 000 activités sur 30 jours : 10 % Runs,
80 % invocations, 5 % calculs, 5 % jobs de workspace. Dix lecteurs, répartis
entre deux membres aux droits différents, interrogent le même corpus pendant
qu'un écrivain persiste des travaux et leur projection.

Le banc mesure le service, ses autorisations et l'agrégation. Il exclut HTTP,
la sérialisation JSON, les clients SSE et les gros payloads natifs. Le corpus
est entièrement terminal. Le mode IAM est `compat`, avec vérification native
des chats privés et des propriétaires ; le débit IAM strict n'est pas mesuré.
Les tests fonctionnels stricts ne valent pas une preuve de débit strict.

Machine : conteneur Linux, quota de 4 CPU, affinité de 5 CPU, mémoire limitée
à 16 Gio ; modèle CPU et paramètres PostgreSQL détaillés dans les JSON. La RSS
est mesurée après chargement du corpus et collecte mémoire. Le surcroît est
celui du processus contenant **tous** les lecteurs : inférieur à 256 Mio, il
borne conservativement celui d'une requête, sans division par dix.

| Voie native à `636bb533` | Activités | Coûts d'invocations |
|---|---:|---:|
| p95 des 10 lectures | 111,37 s | 115,42 s |
| SELECT par lecteur | 110 | 132 |
| Surcroît RSS combiné | 212,64 Mio | 218,91 Mio |
| Commits écrivain réussis | 99 | 114 |
| p95 écrivain | 2,05 s | 1,76 s |

Les comptes autorisés correspondent au corpus. Aucune attente PostgreSQL de
type `Lock` n'a été observée par l'échantillonnage ; cela ne prouve pas l'absence
de toute attente brève. Le ralentissement de l'écrivain témoigne de contention
de calcul. Cette première mesure **échoue** au seuil de 2 s ; le plafond reste
inchangé. Preuves : `series-native-100k-activity.json` et
`series-native-100k-cost.json`.

La première agrégation SQL à `a38ddf0e` applique les droits `compat` avant
`GROUPING SETS` et les quantiles exacts. Les autres modes IAM gardent le lecteur
natif ; aucun calcul du candidat IAM n'est utilisé comme nouvelle autorité.
Les comparaisons différentielles portent sur quatre identités et sept
combinaisons de métriques/filtres, avec dates et mesures historiques imparfaites,
chats privés, workbench, sessions supprimées, coûts partiels et jobs BRD.
Les 26 tests du lot passent (`backend-sql-differential-first.log`).

| Première voie SQL, même corpus et concurrence | Activités | Coûts d'invocations |
|---|---:|---:|
| p95 des 10 lectures | 3,93 s | 8,64 s |
| Requêtes SQL par lecteur, y compris `SET` | 10 | 11 |
| Surcroît RSS combiné du processus applicatif | 6,06 Mio | 5,70 Mio |
| Commits écrivain réussis | 48 | 96 |
| p95 écrivain | 51 ms | 68 ms |

Les deux seuils de latence restent dépassés. Les comptes sont exacts et aucune
attente `Lock` de l'écrivain n'est échantillonnée. Les RSS de ce tableau
**n'incluent pas** les processus PostgreSQL. Les JSON
`series-sql-first-100k-activity.json` et `series-sql-first-100k-cost.json`
conservent la mesure complète et les empreintes des sources, sans écraser la
première mesure native.

## Charge finale et limites conservées

La dernière paire mesure `0e745155`, après les corrections de droits et de
bornes UTC. Le corpus, les dix lecteurs, l'écrivain, la machine et les seuils
restent identiques. Les fichiers `series-final-100k-activity.json` et
`series-final-100k-cost.json` constituent le résultat final, même lorsqu'une
mesure intermédiaire était plus rapide.

| Mesure finale | Activités | Coûts d'invocations |
|---|---:|---:|
| p95 | **5,479 s** | **9,468 s** |
| Objectif p95 ≤ 2 s | **Échec** | **Échec** |
| Requêtes SQL par lecteur, `SET` inclus | 11 | 11 |
| Surcroît RSS backend combiné | 5,973 Mio | 5,910 Mio |
| Comptes autorisés attendus | Exacts pour les dix lecteurs | Exacts pour les dix lecteurs |
| Commits écrivain | 56 | 75 |
| p95 écrivain | 184 ms | 217 ms |
| Erreurs / attentes `Lock` observées | 0 / 0 | 0 / 0 |

Les commandes retournent le code **1**, car le seuil de latence échoue ; les
trois autres critères du script passent. Cette mesure n'est pas une garantie
de débit sur la VM. En particulier, le corpus exclut les fenêtres de service
et les reçus protégés, qui reviennent au lecteur natif, ainsi que le débit
IAM strict/shadow. Aucun cache partagé ou total tronqué ne contourne ces cas.

Les plans `EXPLAIN (ANALYZE, BUFFERS)` initiaux sont conservés dans
`series-plan-activity-initial.json` et `series-plan-cost-initial.json`. Ils
montrent le coût des jointures, des extractions JSON, des tris exacts et des
fichiers temporaires PostgreSQL. Les profils isolés servent au diagnostic ;
ils ne remplacent pas la mesure concurrente. Le retrait de recherches inutiles
n'a pas amélioré le p95 de la dernière paire ; aucun gain supplémentaire n'est
revendiqué.

Avant d'ouvrir largement R2, le travail de performance reste à qualifier.
La prochaine piste est une projection avec colonnes de mesure typées et
indexées, entretenues transactionnellement et contrôlables sous les mêmes
droits. Elle exige une conception/migration et une comparaison sur la cible,
pas une hausse des plafonds ni l'activation d'un nouvel orchestrateur.

## Reproduction et relais de release

Dans `backend/`, utiliser l'environnement de dépendances du dépôt :

```bash
ACTIVITY_POSTGRES_URL=postgresql://postgres@127.0.0.1:55439/postgres PYTHONPATH=. python -m pytest -q -n 4
ACTIVITY_POSTGRES_URL=postgresql://postgres@127.0.0.1:55439/postgres PYTHONPATH=. python scripts/qualify_activity_series.py --activities 100000 --readers 10 --metric activity --output /tmp/activity-series-activity.json
ACTIVITY_POSTGRES_URL=postgresql://postgres@127.0.0.1:55439/postgres PYTHONPATH=. python scripts/qualify_activity_series.py --activities 100000 --readers 10 --metric cost --output /tmp/activity-series-cost.json
```

Cette URL désigne le PostgreSQL jetable local, pas la production. Le compte du
banc doit pouvoir créer et supprimer son schéma. Exécuter les charges seules,
sans compilation ni suite complète concurrente.

Dans `frontend-ng/`, pour les vérifications locales :

```bash
GOMEMLIMIT=4GiB GOMAXPROCS=2 npm run test:unit
npm run check:i18n
npm run check:nav-links
npm run check:ui-chrome
GOMEMLIMIT=4GiB GOMAXPROCS=2 NG_BUILD_MAX_WORKERS=2 npm run build:prod
```

Les recettes 59 et 65 utilisent un serveur Angular local et un navigateur
Chromium installé ; définir explicitement `E2E_BASE_URL=http://localhost:4200`
et lancer `npx playwright test 59-activity-observability-mocked.spec.ts
65-operations-flow-preservation-mocked.spec.ts --project=chromium --workers=1`.
Ne pas laisser le défaut de configuration pointer ces recettes vers la VM.

Le [rapport d'implémentation](../../agentium-operations-activities-flow-implementation.md)
décrit les options et la recette opérateur. Aucune fusion, aucune construction
d'image Docker, aucune activation et aucun déploiement n'ont été effectués par
ce travail. Showcase, le débit sur la VM, les images et leurs budgets restent
à qualifier séparément. La narration et les infrastructures différées gardent
leur handover existant.
