# Agentium System 360 — pack de démo du 21 juillet 2026

Ce dossier conserve le déroulé, les observations automatisées et les captures
préparées pour la démonstration du 21 juillet 2026.

## Provenance et portée

- Environnement observé : production, `https://agentium.papai.ai`.
- SHA applicatif annoncé par la VM, le backend et le frontend :
  `cfa3f616050bb5f75c9a3709219b52939e7ec0bd`.
- Le runner Playwright utilisait une copie locale du harness avec des
  durcissements E2E non committés : sélecteurs moins ambigus, attentes de rendu,
  captures par lens, quatrième app Andritz FSE et garde console.
- Les champs GitLab CI des JSON sont vides. Ces fichiers sont donc des
  **observations locales liées au SHA applicatif**, pas des attestations CI
  protégées et pas une preuve formelle `runner_verified` ou `deployed_verified`.
- Les identifiants workspace, System et Capability présents dans l'observation
  comportementale sont des identifiants internes, sans secret ni jeton.

Ce pack ne doit modifier ni le manifeste de conformité, ni la matrice générée,
ni le statut du mental model. La promotion formelle reste réservée au job GitLab
protégé.

## Contenu

- [Déroulé de démo](demo-runbook.md)
- [Statut, résultats et limites connues](status.md)
- [Protocole de validation sans coaching](validation-protocol.md)
- [Observation comportementale System 360](observations/lot6-system360-behavior-local.json)
- [Observation du runner System 360](observations/lot6-system360-runner-local.json)
- [JUnit du smoke multi-workspace 5/5](observations/workspace-smoke-junit.xml)
- [Captures de secours](screenshots/)

Le JUnit conserve les chemins d'attachements générés par Playwright. Ils ne sont
pas portables hors du répertoire de résultats original ; les images utiles ont
donc été copiées séparément dans `screenshots/`.

## Résultats observés

- Canari authentifié System 360 : 1/1 passé sur les quatre lenses, avec
  invariants de contexte, historique, facettes, purge workspace, confrontation
  UI/API et garde console propre sur ce parcours.
- Smoke fonctionnel : 5/5 passé pour Andritz, Showcase, Sentinel et Octocity.
- Validation humaine : non réalisée au moment de l'archivage ; ne pas revendiquer
  `user_validated`.
- Les écarts console découverts pendant le diagnostic strict sont consignés dans
  [status.md](status.md).

## Intégrité des observations brutes

| Fichier | SHA-256 |
|---|---|
| `lot6-system360-behavior-local.json` | `80fdc4661804c3fb2e6e7e9170dafac388ea7d6b9c3662462cae5007e7b60ae8` |
| `lot6-system360-runner-local.json` | `fbf600dae4379afa92b002b032f8511a015fcce4553e4cfad0413eb6e74b8814` |
| `workspace-smoke-junit.xml` | `e7802ab2da6ba36df3d05c9e7707519f79ae87309cdc125a28d920b99a2f72c5` |
