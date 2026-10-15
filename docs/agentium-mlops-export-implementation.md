# M4.1 — Export MLflow, 15 octobre 2026

Lot indépendant depuis `47e289da`, dépendant de la gouvernance M1. Aucun import
BYOM, changement de dépendance, requalification d'environnement ou déploiement.

`GET /ml-models/{id}/export` exporte exactement la version demandée du workspace
courant. Le nouveau router `ml_exports` applique `ml_permissions.require` pour
`export` avant la copie puis après celle-ci. M1 garde cette nouvelle opération
strictement administrateur, même lorsque les anciens droits sont en mode rapport.
La ligne modèle est reverrouillée pour refuser une modification de version ou
d'artefact pendant la copie. L'audit est commité avant l'envoi des octets.

L'archive ZIP contient le répertoire `model/` inchangé du producteur, son contrat
d'artefact, un manifeste SHA-256 et un README. L'inventaire, le namespace, les
tailles, empreintes, profil de confiance et versions de runtime passent par les
gardes existantes `download_model_dir` et `verify_model_bundle`. Aucun modèle
n'est désérialisé pendant l'export. Un runtime absent/incompatible, un artefact
legacy ou une entrée d'exemple manquante sont refusés : ce lot ne convertit rien.
Les octets temporaires sont supprimés après la réponse, après un refus ou une
déconnexion du client. La réponse est `no-store` et fournit `X-Archive-SHA256`.

Le README distingue le résultat pyfunc MLflow de l'enveloppe de prédiction
Agentium. L'exemple d'entraînement est dans l'archive et peut contenir des données
métier ; l'interface le dit avant téléchargement. Le contrat exporté n'est pas
une signature cryptographique indépendante de l'archive.

## Intégration M1

- Le router est enregistré séparément ; aucun changement à `ml_models.py`.
- Le composant FR/EN `ModelExportComponent` est raccordé à l’onglet de réglages
  de la fiche modèle. Sa capacité provient de `serving.permissions.export` renvoyé
  par M1 ; aucune déduction de rôle ne se fait dans le composant.
- Le client utilise `HttpClient` authentifié ; les changements de principal,
  workspace ou modèle invalident le téléchargement en cours. Il ne suit aucune
  URL arbitraire et libère son URL de blob.
- M1 est une dépendance stricte. Les tests API de ce lot chargent le vrai module
  de permissions du commit `b75eea2b` via un plugin externe de qualification,
  sans le recopier dans le lot. Après assemblage, aucun plugin n'est nécessaire.

## Preuves et limites

[`manifest.json`](evidence/mlops-export-2026-10-15/manifest.json) conserve résultats,
empreintes et logs légers. 16 tests backend passent : archive inchangée/hashée,
refus de falsification/runtime/namespace/legacy, droits administrateur et
inter-workspace, audit obligatoire, révocation pendant copie, changement de
source et nettoyage après déconnexion.

Un vrai `mlflow models serve -m . --env-manager local` a servi l'archive extraite
hors du dépôt, avec environnement minimal sans PYTHONPATH ni credentials de
registre. `/ping` et `/invocations` répondent 200 ; les prédictions `[0,0,1,1]`
sont identiques à celles de la régression logistique sklearn entraînée dans le
test. Cela qualifie cette voie tabulaire/skops, pas toutes les familles ni une
autre version de dépendances. Le serveur local est arrêté après la recette.

2265 tests unitaires UI, TypeScript, i18n, navigation et un build de production
passent. Le composant est raccordé à la carte M1 ; TypeScript passe après assemblage.
Aucune recette navigateur intégrée à la carte n’est revendiquée.
Le guard `ui-chrome` reste rouge sur le halo préexistant de `src/styles.scss`
(7 occurrences, budget 6), inchangé dans ce lot.

Commandes depuis `backend` :

```bash
PYTHONPATH=/workspace/mlops-m4-evidence:$PWD /workspace/agentium/.venv/bin/python -m pytest \
  app/tests/services/test_ml_exports.py app/tests/api/test_ml_exports_api.py \
  -p m1_test_dependency -q -p no:cacheprovider -W ignore
```

Le plugin externe, conservé avec les preuves, ajoute uniquement le chemin des
services M1 à l'import pour cette qualification. Depuis `frontend-ng`, Node
`v24.19.0`, npm `11.9.0` :

```bash
node_modules/.bin/tsc --noEmit -p tsconfig.app.json
npm run check:i18n
npm run check:nav-links
npm run check:ui-chrome
TMPDIR=/workspace/mlops-m4-evidence/tmp GOMEMLIMIT=3GiB GOMAXPROCS=2 npm run test:unit
TMPDIR=/workspace/mlops-m4-evidence/tmp GOMEMLIMIT=3GiB GOMAXPROCS=2 npm run build:prod
```

Ruff ciblé et `git diff --check` passent. Aucune qualification PostgreSQL, Docker,
VM ou tous-lots n'est revendiquée pour cet export isolé.

## Vérification après assemblage

Les 16 tests backend ont été rejoués avec les vraies permissions M1, sans plugin
externe, y compris le serveur HTTP MLflow indépendant (36,74 s). La commande
depuis `backend` est `PYTHONPATH=. python -m pytest app/tests/api/test_ml_exports_api.py app/tests/services/test_ml_exports.py -q`.
