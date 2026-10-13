# Suivi de la revue DataOps et juge typé — 13 octobre 2026

La [revue indépendante](codex-review-dataops-typed-judge.md) reste inchangée : elle
porte sur `45ccc915`. Ce suivi consigne les correctifs qui la suivent. Le premier
bilan de livraison surestimait les suites ciblées et la conformité au plan.
**La branche n'est toujours pas déclarée fusionnable ou déployable.**

## Traitement des cinq points bloquants

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

## Vérification locale

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

## Limites qui restent ouvertes

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
