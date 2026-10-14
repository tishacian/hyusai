# Suivi de la revue DataOps et juge typé — 13–14 octobre 2026

La [revue indépendante](codex-review-dataops-typed-judge.md) reste inchangée : elle
porte sur `45ccc915`. Ce suivi consigne les correctifs qui la suivent. Le premier
bilan de livraison surestimait les suites ciblées et la conformité au plan.
**La branche n'est toujours pas déclarée fusionnable ou déployable.**

## Qualification finale du 14 octobre

Le code a été figé sur `bd72404472bfd57c01cc2e4a9747ff5e3049814f` pendant
la suite complète, les constructions et les mesures ci-dessous. Les commits
de preuves qui suivent ne changent pas ce runtime.

La suite backend Linux donne **8 864 réussites, 145 ignorés et aucun échec**
en **952,48 s**, avec quatre workers et sans exclusion par sélection. Les
16 tests d'isolation des aperçus sont inclus. La conformité passe
(16/22 affirmations vérifiables statiquement ; attestations de runner distinctes),
ainsi que la cohérence des 232 dépendances. Le contrôle Helm/Terraform/Ansible
avait passé sur les sources de déploiement inchangées. Le
[manifeste final](evidence/dataops-completion-2026-10-13/validation-final.json)
et les [traces compressées avec empreintes](evidence/dataops-completion-2026-10-13/final-suite/files.json)
conservent les résultats et le périmètre des tests ignorés.

Les deux images Linux/amd64 ont été réellement construites avec les options
de release : RAG activé dans les deux, Giskard activé dans le worker. Leurs
couches OCI sont vérifiées par empreinte compressée et `diff_id` décompressé.
La somme des charges utiles des couches utilise la comptabilité Docker classique,
calibrée exactement sur les quatre couches de la base Python locale. Elle
ne constitue pas un `docker image inspect` de la VM de déploiement.

| Image | Octets comparables Docker classique | Mio entiers | Plafond inchangé | Résultat |
|---|---:|---:|---:|---|
| Backend | 3 741 006 259 | 3 567 | 1 400 | Dépassé |
| Worker | 4 903 956 499 | 4 676 | 1 760 | Dépassé |

Les archives OCI complètes pèsent respectivement 1 346 070 528 et
1 716 421 120 octets ; leur taille n'est pas un relevé du budget sur la VM.
Le mode de stockage Docker doit être identifié : `inspect.Size` utilise les
contenus stockés, dont les couches généralement compressées, avec containerd
dans Docker 28.4, et les charges utiles
décompressées avec le stockage classique. Voir le
[diagnostic des deux blocages de release](dataops-release-blockers-2026-10-14.md).
Les constructions durent 104,179 s et 674,854 s. Les imports de
`app.main` et des dépendances épinglées passent, sans réseau ni lifespan.
Dans chaque image, un vrai aperçu de sample réussit, une expansion excessive
reçoit `DATAPREP_PREVIEW_TIMEOUT` à cinq secondes, puis une autre formule
réussit sans cache. Trois enfants distincts sont observés. Les limites restent
512 Mio pour DuckDB, 1 Gio d'espace virtuel pour l'enfant et cinq secondes.
Ce smoke qualifie le refus par échéance ; la preuve de refus mémoire du runtime
local est conservée séparément. La première tentative backend, qui exigeait
uniquement le code mémoire, est archivée avec son script. Le
[bundle d'images](evidence/dataops-completion-2026-10-13/image-final/bundle-index.json)
conserve les métadonnées OCI exactes, les commandes, les résultats et leurs limites.

Le benchmark final traite **3 000 000 de lignes sans exclusion** en
**330,552 s** pour le pipeline : ingestion 76,344 s, préparation 91,121 s et
scoring 163,022 s. Le test pytest dure 344,57 s et son enveloppe complète
353,480 s, entraînement de fixture et démarrage compris. Les entrées
synthétiques variées comportent 32 colonnes, dont 28 supplémentaires ; le modèle
natif produit 35 colonnes en **sept parts Delta**, pour 859 998 846 octets.

Le conteneur est limité à **4 Gio, sans swap, et 2 CPU**, sans réseau. Son pic
mémoire cgroup est exactement 4 294 967 296 octets, avec 2 018 événements `max`,
aucun `oom` et aucun `oom_kill`. Le RSS échantillonné de l'arbre des processus
atteint 2 139 041 792 octets ; il ne mesure pas la même chose que le cgroup.
L'essai utilise un conteneur Python porteur et le venv qualifié monté en lecture
seule, avec Python 3.12.14 ; les smokes d'images utilisent Python 3.12.13.
La qualification porte sur l'ingestion, la préparation et le scoring natif
locaux. La recette à ce volume par un Flow publié et une livraison reçue reste
ouverte (`receipts_created=0`), de même que la qualité métier du modèle.
Le [rapport](evidence/dataops-completion-2026-10-13/scoring-3m.json) et sa
[supervision](evidence/dataops-completion-2026-10-13/scoring-3m-cgroup.json)
conservent les cardinalités, versions, paramètres, empreintes et ressources.
Le conteneur d'essai est retiré et le constructeur dédié arrêté.

Le contrôle des budgets sur la VM reste ouvert ; les dépassements ci-dessus
concernent la comptabilité classique. HANA vivant et les critères de recette
encore ouverts ci-dessous restent à traiter. Aucune fusion ni modification de VM
n'a été effectuée ; narration et Gemini/OpenRouter restent différés.

## Reprise des lots D1a, D1b, D2 et D3

Les correctifs historiques ci-dessous portent sur les révisions qui y sont
nommées. Une nouvelle reprise est enregistrée dans `37f361c5` (backend et
stockage) et `a22442c8` (ateliers frontend). Les preuves correspondantes sont
regroupées dans [le répertoire de qualification](evidence/dataops-completion-2026-10-13/).
Le plan original et la revue indépendante restent strictement inchangés.

- Le compilateur expose 46 contrats d'étapes et 74 fonctions, des sélecteurs
  bornés, les schémas physiques par étape, des règles explicites de collision
  et une inférence qui n'évalue pas les constantes sur une table vide. Le corpus
  comprend 138 cas ordinaires/NULL/vides et 46 schémas attendus indépendants.
  Les recettes `prepare_history` et Nawa A2 donnent les mêmes schémas et
  empreintes de lignes que les SQL existants. Le Flow publié
  Préparer→Joindre→Découper→deux SQL passe en modes strict et overlay, avec
  badges par port : **266 tests ciblés réussis**, voir
  [compiler-flow.json](evidence/dataops-completion-2026-10-13/compiler-flow.json).
- L'aperçu utilise les échantillons persistés et autorise chaque source du
  workspace avant consultation du cache. Les anciens datasets demandent une
  construction au worker, avec intention durable, reprise périodique bornée,
  bail d'exécution et exclusion de la purge. Les **15 tests de reprise/cache**
  passent après correction du profil des valeurs NaN/Infinity. Ces valeurs sont
  signalées dans le profil et sérialisées en NULL dans la grille.
- Les sept opérations ont une entrée dans la palette ; les ateliers, les
  formules, l'historique, l'aperçu de préfixe et la conversion SQL sont livrés.
  **2 193 tests unitaires** passent avant la dernière correction du sérialiseur
  récursif ; **97 tests ciblés**, la construction production et les recettes
  navigateur mockées FR/EN portent sur le frontend final. Le périmètre exact
  est conservé dans [frontend.json](evidence/dataops-completion-2026-10-13/frontend.json).
- Delta utilise le commit natif delta-rs après écriture des parts, sans
  réencodage ni construction maison des actions JSON. Les lecteurs natifs,
  profils bornés, téléchargements en flux et purge séparée sont livrés.
  **47 tests ciblés**, dont quatre sur MinIO réel, passent. Une sortie de
  **3 248 348 018 octets en 25 parts** a été écrite, échantillonnée, livrée,
  relue, vérifiée et profilée en **84,679 s**, dans un client limité à
  **4 Gio/2 CPU**, sans OOM. Cette mesure synthétique de stockage ne remplace
  pas le benchmark de scoring ; son périmètre est détaillé dans
  [d3-validation.json](evidence/dataops-completion-2026-10-13/d3-validation.json).

La première suite complète diagnostique de cette reprise donne **8 838 réussites,
145 ignorés et cinq échecs** en 741,63 s. Le contrôle physique du clustering
appelait encore une API Parquet mono-fichier ; il additionne désormais les
footers avant chargement, en conservant les plafonds globaux. Deux tests de
sécurité/intégrité interceptaient l'ancien point d'entrée de matérialisation :
le premier intercepte la nouvelle API et le second corrompt réellement le
fichier de sa fixture. L'attendu IAM vérifie maintenant exactement les deux
préfixes de purge autorisés, l'absence de PUT et l'interdiction de suppression
pour l'application. Enfin, le contrôle des sources confondait un rapport HTML
Playwright généré avec du code : ce rapport a été archivé hors de l'arbre source,
sans changer le contrôle. Les **39 tests ciblés de ces régressions passent**
après `cc8c0e3a` et `75795e45`. La passe diagnostique avait chargé les tests avant
ces modifications ; elle ne qualifie pas le code final.

La relance sur le backend de `75795e45`, identique à celui de `64a10ba9`, donne
**8 848 réussites, 145 ignorés et aucun échec**, en **743,61 s**, sans exclusion
par sélection. La conformité, la cohérence des 232 dépendances et le scaffold
Helm/Terraform/Ansible passent aussi. Cette passe précède le correctif d'isolation
d'aperçu décrit ci-dessous ; elle ne lui est pas attribuée rétroactivement.
Son [manifeste](evidence/dataops-completion-2026-10-13/validation-before-isolation.json)
conserve la révision, les paramètres et les empreintes des traces.

### Isolation de l'aperçu et contexte des images

Une sonde confinée à 192 Mio, sur DuckDB 1.5.5, exécute l'expression acceptée
`lpad('x',1000000000,'x')` avec une limite DuckDB de 16 MB et une interruption
programmée à cinq secondes. Le processus est tué par le cgroup : sortie 137,
`oom_kill=1`. Aucun service API réel n'a été sollicité. La limite du moteur ne
suffisait donc pas à protéger le processus web qui exécutait l'aperçu.

Le correctif `940bc43b` lance un nouvel interpréteur, applique les limites système
avant les imports natifs et y déplace le décodage des samples, le calcul et le
profil. L'autorisation, les empreintes et le cache restent dans l'API. Le budget
DuckDB par défaut reste 512 Mio ; le plafond d'espace virtuel ajoute une réserve
native de 512 Mio, soit 1 Gio. Ce plafond n'est pas une mesure de RSS. L'enfant
ne reçoit pas l'environnement applicatif ; les sels restent expurgés et seuls
des codes fixes sortent en cas d'erreur. Échéance, arrêt du groupe, attente de
terminaison et résultat JSON limité à 32 Mio sont vérifiés.

Les **271 tests ciblés** passent en **44,74 s**, notamment les expansions par
padding, remplacement et concaténation, l'interruption, le masque des sels,
les profils, les conversions, NULL/NaN et le cache. Une assertion de capture
stderr a ensuite été rendue complète et son test passe séparément ; le runtime
est identique. Voir [la preuve d'isolation](evidence/dataops-completion-2026-10-13/preview-isolation.json).
La première relance complète est arrêtée après **3 452 réussites et un échec**,
en 293,90 s. Cet échec RAG attendait qu'un `asyncio.sleep(40 ms)` reprenne avant
un budget de 60 ms ; la première collection n'avait produit aucun résultat à
l'expiration. Le runtime et le test sont identiques à `ad10dbc2` et à la passe
verte précédente. Les assertions du délai et du repli avaient passé ; aucun
défaut du délai de production n'est démontré. Le test utilise maintenant une
horloge locale contrôlée, conserve une vraie annulation `asyncio` et vérifie
les budgets successifs de 60 puis 20 ms, ainsi que la première collection et
l'absence d'un troisième appel. Les **100 tests du fichier RAG passent**, sans
modification de son runtime. Le [diagnostic](evidence/dataops-completion-2026-10-13/rag-deadline.json)
conserve l'échec et la comparaison de blobs. La relance finale sur `bd724044`
donne **8 864 réussites, 145 ignorés et aucun échec** en **952,48 s**, comme
consigné en tête de ce suivi ; la passe interrompue n'est pas une qualification.

Une première image backend a été construite sur `64a10ba9`, avec RAG activé
selon le script de release. La somme des charges utiles de ses couches est de
**4 310 895 928 octets, soit 4 111 Mio entiers**, au-dessus du plafond de
1 400 Mio. Cette comptabilité classique Docker est vérifiée exactement sur les
quatre couches de l'image Python locale ; elle ne remplace pas un inspect de la
VM de déploiement. L'import de `app.main` et des trois nouvelles dépendances
passe, sans réseau ni démarrage du lifespan.

Le contexte comportait **569 918 533 octets de caches Terraform**. Le commit
`f02e9333` les exclut, ainsi que les états et plans locaux, dans les cinq
contextes concernés ; les 16 tests de contexte passent. Ce retrait ne suffit
pas à respecter le plafond : les trois paquets DataOps représentent 146 Mio,
la couche Hugging Face 933 Mio et le reste de la couche applicative 1 673 Mio.
Les choix Docker/release sont identiques à `ad10dbc2`, mais aucune taille
historique n'a été reconstruite. Le [bundle diagnostique](evidence/dataops-completion-2026-10-13/image-diagnostic/bundle-index.json)
conserve les couches mesurées, leur intégrité et le périmètre du smoke. Les
images finales ont ensuite été construites sur `bd724044` : leurs mesures et
smokes sont détaillés en tête de ce suivi. Les deux plafonds restent dépassés
et n'ont pas été relevés.

Ces preuves ne ferment pas tous les critères du plan : restent notamment les
types limites pour chaque étape, la matrice complète des options/coercions,
les cardinalités détaillées des jointures, la découverte complète asynchrone
des valeurs de pivot, certaines recettes navigateur SQL/Polars/dbt et la
recette déployée. L'implémentation combine des émetteurs SQL et des AST sqlglot ;
une construction exclusivement native en AST et une parité Spark ne sont pas
attestées. HANA vivant, l'historique Alembic depuis zéro et la révocation du
token papAI gardent leurs limites historiques. Narration et le fournisseur
Gemini/OpenRouter restent différés.

## Historique — traitement des cinq points bloquants

| Point | Traitement et preuve |
|---|---|
| 1. Plan | `docs/agentium-dataops-plan.md` restauré intégralement depuis `ad10dbc2`, vérification par diff vide. Les demandes utilisateur et les écarts restent dans [les amendements](agentium-dataops-amendments.md) ; le juge et les contrats ont leurs documents propres. D2 et D3 ne sont pas déclarés terminés. |
| 2. Régressions | Contraintes app/Giskard complétées (`sqlglot`, `deltalake`, `arro3-core`, `deprecated`), catalogue des 32 routes ajouté, tête Alembic actualisée, vraie exécution eager DataOps dans ecommerce, racine Delta canonicalisée et confinement vérifié. Le benchmark RSS est réservé à Linux. Résultat complet consigné ci-dessous. |
| 3. Kubernetes | Contrôle aligné sur worker `cpu,recipes` et Deployment `dataops` séparé ; le mélange reste interdit. Script corrigé vérifié sur la branche et appliqué à la base `ad10dbc2`, avec Helm, Terraform validate et syntaxe Ansible. Aucun apply. |
| 4. Images | Tentative réelle de construction backend avec base Python épinglée, dépendances contraintes et RAG activé. Interrompue par la capacité du disque Docker `vfs` de 32 GiB, au stade 12/15. Aucun artefact image final, donc aucune taille validée. Budgets inchangés. Ce point reste bloquant. |
| 5. HANA Showcase | TLS vérifié et absence de repli implicite conservés. Aucun accès HANA vivant ni modification de configuration de VM. Avant déploiement, confirmer certificat/chaîne de confiance, ou faire approuver une démonstration explicite ou une exception précise. Le comportement Showcase reste à qualifier ; aucun ancien mot de passe n'a été retiré du bundle de déploiement. |

## Autres corrections de la revue

- Toutes les routes DataOps passent par le drapeau du workspace. Les liens et
  routes Data preparation et Service deliveries suivent les fonctionnalités
  effectives du serveur, y compris son activation globale.
- Narration reste fermée par défaut, masquée même si le catalogue l'active par
  override ; le seed Showcase ne crée plus son System/service lorsqu'elle est
  désactivée. Le bilan de couverture compte ce blocage et l'interface ne propose
  plus de l'activer par une action de curation sans effet. Le code expérimental
  est conservé derrière cette garde. Aucun
  raccordement Gemini/OpenRouter ni moteur externe n'est qualifié.
- Les fonctions SQL normalisées par sqlglot sont reconnues. L'inférence du
  schéma de sortie lit les types physiques du pied de page Parquet borné ou les
  métadonnées Delta vérifiées, sans reconstruire les types à partir du profil.
- La publication valide spécifications, ports requis, collisions, noms de
  sorties et interdiction de `inputs_map`. Les sorties d'un split sont nommées
  sur toutes les arêtes que le moteur fusionne. Une sortie unique peut être
  implicite. Union admet de 2 à 16 entrées. L'éditeur supprime les anciens
  sélecteurs incompatibles et conserve les configurations imbriquées des seeds.
- La publication humaine refuse explicitement une génération (`fence`) périmée
  avant de reprendre le bail courant. La barrière fournie par l'appelant existait
  déjà dans le service ; le secret de bail reste côté serveur. Le downgrade 126
  refuse tout enregistrement de gouvernance avant le premier DROP.
- La sauvegarde sélectionne les objets/répertoires référencés SQL/A1, au lieu
  du workspace entier. Une collection native explicitement référencée reste
  sauvegardée. Les évaluations de modèles archivés sont conservées. Taille
  requise inconnue, plafond dépassé ou espace insuffisant arrêtent avant copie ;
  le calcul réserve deux copies et 1 GiB de marge.
- Le timeout RabbitMQ passe à une heure dans Compose et Helm. La recréation
  nécessaire du broker est documentée ; elle n'a pas été exécutée.

## Historique — vérification locale à `54c30f9d`

Les commandes sont lancées depuis le dépôt, sauf indication. Les tests utilisent
les bases SQLite isolées par processus prévues par `conftest.py`, le stockage
local et les workers eager ; ils ne constituent pas une recette PostgreSQL,
RabbitMQ ou S3 en production.

| Vérification | Commande | Résultat |
|---|---|---|
| Backend complet, infra comprise | Depuis `backend` : `../.venv/bin/pytest -q -n 4 --dist=loadfile` | **8 540 réussis, 132 ignorés, aucun échec**, 651,88 s. Aucun test exclu par sélection. |
| Frontend unitaire | Depuis `frontend-ng` : `npm run test:unit` | **2 172 réussis, aucun échec ni test ignoré**. |
| Construction frontend | Depuis `frontend-ng` : `npm run build:prod` | Réussie, code de sortie 0, 150,14 s. |
| Conformité | `.venv/bin/python scripts/agentium_compliance.py --check` | Réussie : 16/22 affirmations vérifiées statiquement ; attestations des runners séparées. |
| Dépendances du venv | `uv pip check --python .venv/bin/python` | 232 paquets compatibles. |
| Scaffold Kubernetes | `ops/scripts/check-k8s-scaffold.sh` | Réussi sur la branche, sur `ad10dbc2`, et avec le script corrigé appliqué à cette base. Aucun apply. |

Le backend complet porte sur **`54c30f9d`**. Les tests et la construction
frontend portent sur `bcd86423` ; le répertoire `frontend-ng` est strictement
inchangé entre ces deux révisions. Python 3.12.14 et Node 24.19.0 ont été utilisés.
Les commandes complètes, paramètres d'environnement, versions et empreintes
des traces sont conservés dans le [manifeste de validation](evidence/dataops-review-2026-10-13/validation.json).

La construction frontend réussit avec des avertissements Angular de templates,
de seuils de taille pour le bundle initial et certains styles, ainsi que le
module CommonJS `dagre`. Les tests unitaires ne sont pas une recette navigateur.
Une tentative de bundling des tests s'est arrêtée avant exécution, faute
d'espace dans `/tmp` ; la relance du même code utilise le disque de travail
pour ses fichiers temporaires.

Les six régressions reproductibles initiales (contraintes ×2, catalogue, tête de
migration, ecommerce ×2) ont été comparées à `ad10dbc2`, où elles passent.
Le défaut de lien symbolique a été reproduit sous Linux avant correction, puis
testé dans les deux sens : alias interne accepté, sortie de racine refusée.

Le test ML cité dans le bilan antérieur échouait également sur `ad10dbc2` dans
ce venv incomplet : `skforecast`, `statsmodels` et `numba` manquaient. Ce n'était
pas une instabilité ni une réfutation de la revue. Le runtime de test a été
complété avec `requirements_ml_ts.txt` et les contraintes qualifiées ; ce test
passe ensuite sans modifier son code ni l'exclure.

La première suite complète après corrections comptait 8 520 réussites,
132 tests ignorés et deux échecs. Le premier révélait un défaut ajouté par le
masquage de narration : `feature_disabled` était absent du bilan de couverture.
Il est corrigé avec des tests de visibilité et de non-contournement. Le second,
TabICL, est lui aussi reproduit sur `ad10dbc2` dans le même environnement ; le
test, les adaptateurs et les exigences de ce runtime sont identiques. Le venv
de test a reçu `torch==2.14.0+cpu`, `tabicl==2.2.0`, `safetensors==0.8.0` et
`einops==0.8.2` sous les contraintes existantes, sans modifier les pins ni les
tests ML. Les 47 tests des deux fichiers concernés passent ensuite.

La suite suivante comptait 8 532 réussites, 132 tests ignorés et un échec : le
test du pilote Probabl observe un descendant encore `R` juste après l'arrêt du
groupe. Le même PID est ensuite observé `Z`. Le runner et le test étaient
identiques à `ad10dbc2`, mais le test isolé et 40 répétitions sur cette base
passent : l'assertion fautive n'y a pas été reproduite. La lecture établit une
attente du seul parent après `SIGKILL`, sans barrière de terminaison du groupe.
Le correctif attend les descendants actifs avec une échéance bornée et refuse
un résultat de qualification si leur terminaison n'est pas confirmée. L'assertion
initiale est conservée ; un test retarde volontairement le signal au descendant.
Aucun lien causal avec la construction frontend n'est établi.

Rapports de contrôle conservés : [construction Docker interrompue](evidence/dataops-review-2026-10-13/images.json), [migration PostgreSQL ciblée](evidence/dataops-review-2026-10-13/postgresql-migration.json) et [comparaison du runtime TabICL avec la base](evidence/dataops-review-2026-10-13/tabicl-baseline.json).
La [comparaison du groupe de processus](evidence/dataops-review-2026-10-13/process-group-baseline.json)
sépare les observations de l'inférence de synchronisation.
Les chemins absolus figurant dans ces JSON désignent des traces locales ; seuls
leurs résumés structurés sont conservés dans le dépôt.

## Historique — limites constatées avant la reprise des lots

La tentative Docker a duré 396,7 secondes et fini avec le code 130. L'annulation
a été déclenchée au seuil de 3 GiB libres ; la copie `vfs` s'est poursuivie
pendant l'annulation, causant une saturation temporaire avant nettoyage du
cache. Les deux `pip check` (application et RAG) ont réussi ; ils
ne prouvent pas qu'une image finale respecte son budget. Le cache de cette seule
tentative a été supprimé et le disque rendu disponible. Le contrôle des budgets
échoue sur images absentes. Les plafonds backend/worker/frontend/ml-ts/LiveKit
restent respectivement 1 400 / 1 760 / 40 / 1 240 / 110 MiB.

La migration 125→126 est vérifiée sur PostgreSQL **17.11 Alpine**, avec les
sept tables et leurs FK réelles, downgrade à vide, réupgrade, rejet d'une FK
invalide et refus sans perte d'un downgrade contenant un asset. Le conteneur
était limité à 512 MiB / 1 CPU, avec PGDATA tmpfs et port loopback, puis supprimé.
L'historique depuis une base vide bloque toutefois en migration 013
(`sharepoint_sync_jobs` absente) : les six contrôles ciblés partent d'un schéma
ORM excluant les sept tables 126, estampillé 125. Ils ne qualifient pas une
restauration de dump de production ni tout l'historique Alembic.

Aucun HANA vivant, aucune qualification MinIO/S3 ou Gemini, aucun
déploiement/build-info n'est attesté. Le benchmark de
3 millions de lignes de la première implémentation n'a pas été relancé sur cet
état corrigé et ne qualifie pas cette livraison.

Les écarts D1a restants (contrat complet des étapes, génération AST, SQL portable,
départage du tri, corpus golden et coercitions union encore fondées sur
les catégories du profil), les ateliers et la recette navigateur D2,
ainsi que les lecteurs natifs multi-parts, téléchargement et purge D3, restent
ouverts. Corriger les régressions de cette revue ne termine pas ces lots.
