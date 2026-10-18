# Livraison M1, M2, M3 et M4.1 — Agentium

La référence reste `agentium-mlops-papai-parity-plan.md`. Cette livraison part
de `demo/agentic` à `47e289da`, se limite à Agentium et ne modifie pas la
production. Les branches sont empilées pour garder les lots révisables :

| Lot | Branche | Contrat |
|---|---|---|
| M1 | `codex/mlops-m1-governance` | Droits courants, audit, promotion relue, clés expirables, budgets atomiques, consentement et rétention |
| M2 | `codex/mlops-m2-correctness` | Feedback par échantillon, holdout préservé, dérive régression/multiclasse et historique |
| M3 | `codex/mlops-m3-operations` | Endpoints, agrégats, alertes durables, livraisons reprises et tarifs explicites |
| M4.1 | `codex/mlops-m4-export` | Export administrateur d’une version MLflow vérifiée |
| M4.2 | `feat/mlops-m4-requalification` | Requalification d’un modèle pour un nouvel environnement d’exécution, attestée et révocable |

Les détails, écarts et preuves propres aux lots sont dans
`agentium-mlops-governance-implementation.md`,
`agentium-mlops-correctness-implementation.md`, `agentium-mlops-operations.md`,
`agentium-mlops-export-implementation.md` et
`agentium-mlops-requalification-implementation.md`. M4.2 part de
`demo/agentic` à `d814837b`, où M1 à M4.1 sont déjà assemblés.

## Contrats d’assemblage

- Le feedback interdit par la conservation des entrées reste interdit en M2.
  Les valeurs d’entrée recopiées dans les contributions d’explication sont
  retirées du journal, sans modifier la réponse de l’appelant. Le scoring en
  flux applique aussi la politique de conservation à son journal manuel.
- Les modifications de politique, promotions et quotas d’exposition prennent
  le même verrou de workspace ; les lecteurs rechargent la politique après
  l’attente. Une ancienne copie ORM ne peut contourner la nouvelle approbation.
- Le snapshot du moniteur et sa transition M3 partagent la transaction. Un
  rejeu ne renvoie pas la même alerte. Les échecs et refus de serving ont une
  transaction de métadonnées indépendante, bornée en PostgreSQL à 250 ms
  d’attente de verrou et 1 s par instruction. Une panne de télémétrie conserve
  le refus métier initial, et reste signalée dans les logs.
- Les budgets interactifs concernent `/predict` et `/forecast`. Le scoring
  asynchrone conserve l’admission DataOps, avec comptabilité des lignes produites.
  Un tarif Skill déclaré est distinct d’un coût effectivement mesuré ; le CPU
  non attribuable et le coût d’une invocation native différée restent inconnus.
- Le téléchargement M4 réinterroge les permissions M1 et l’identité de l’artefact
  après sa copie. L’audit précède les octets, même en mode rapport M1.

## Recette d’exploitation à effectuer avant activation

1. Sauvegarder les données puis appliquer 135, 136 et 137 dans cet ordre, avant
   les nouveaux processus. Les downgrades qui détruiraient des garanties ou des
   données sont refusés ; ne pas effacer ces données pour contourner la garde.
2. Vérifier les identités des Runs planifiés et leurs appartenances actuelles.
   Un ancien Run sans initiateur persistant doit recevoir une identité technique
   explicite. Observer `ml.model.permission_report`, puis attribuer les rôles
   nécessaires avant de passer `ML_RBAC_ENFORCED=true`.
3. Convenir de la durée de conservation, puis activer `ML_RETENTION_ENABLED`.
   Il reste `false` par défaut et l’interface l’annonce. La purge conserve les
   références du shadow encore en attente.
4. Activer `ML_OPERATIONS_ENABLED`, puis vérifier une prédiction, un scoring,
   un refus de quota et leur agrégation après un intervalle clos de cinq minutes.
   Qualifier les scopes System, workspace et plateforme avec des comptes dédiés.
5. Configurer et tester une destination réelle avant `ML_ALERTS_ENABLED` :
   SMTP existant, ou références de secrets workspace pour URL HTTPS et HMAC.
   Vérifier transition, retour à la normale, indisponibilité, reprise et
   déduplication. Le destinataire doit dédupliquer l’identifiant de livraison.
6. Vérifier scheduler et worker général pour `agentium.ml_operations_tick` ;
   aucune livraison réseau n’occupe le worker court `control`. Les deux
   drapeaux M3 sont `false` par défaut et aucun canal n’est semé.

Aucune dépendance ou image n’est ajoutée. Les tailles réelles d’images, la
charge, les destinations SMTP/webhook et la VM n’ont pas été qualifiées ici.
Un export peut contenir l’exemple métier enregistré lors de l’entraînement ;
la fiche modèle le signale avant le téléchargement.

## Montée de version de l’image (M4.2)

Une nouvelle image qui change scikit-learn, skrub, numpy, scipy, pandas, MLflow
ou skops fait refuser par le service chaque modèle produit par l’ancienne. La
procédure pour en garder le plus possible :

1. **Avant de déployer**, avec l’image courante, enregistrer les prédictions de
   référence des modèles qui n’en ont pas :
   `python -m app.cli.ml_runtime_requalification capture --all-workspaces --dry-run`,
   relire, puis la même commande avec `--apply`. C’est idempotent : un modèle
   déjà capturé est ignoré. Les modèles entraînés depuis M4.2 sont capturés
   automatiquement après leur entraînement.
2. **Déployer** l’image ; appliquer la migration 139 si ce n’est pas fait.
   L’API et le worker général doivent tourner sur la même image.
3. **Requalifier**, avec la nouvelle image : depuis la fiche (Réglages ›
   Environnement d’exécution, administrateurs) ou en masse,
   `python -m app.cli.ml_runtime_requalification requalify --all-workspaces --apply`
   (le processus de la CLI est le lecteur attesté : il doit tourner sur
   l’image de service).
4. **Relire les échecs** : la CLI sort en code 1 et écrit une ligne JSON par
   modèle (`failed` avec écarts mesurés, ou `refused` avec un code). La fiche
   affiche la dernière tentative et ses écarts.
5. **Réentraîner les échecs** avec le réentraînement existant, puis évaluer et
   promouvoir comme d’habitude.

Un modèle **sans référence** après la montée reste refusé : sa référence ne
peut plus être capturée (elle exige l’environnement producteur) et il doit être
réentraîné. Il en va de même si son dataset source a disparu, et pour les
familles non éligibles (servies hors de l’API, clustering). Une attestation se
révoque depuis la fiche ; le service la refuse alors au prochain appel.

## Lots conservés ouverts

M4.3 (BYOM isolé), M5 et M6 ne sont pas déclarés livrés. M4.2 est livré sur sa
branche, non assemblé à `demo/agentic`. M6 reste le lot « model instance/model as a pod », conditionné
par un besoin mesuré et D4. La dérive multivariée optionnelle, Kubernetes, Spark,
Kafka, tout nouvel usage de Redis et la narration conservent leurs handovers
existants. La parité d’export est prouvée pour un tabulaire sklearn/skops avec
MLflow natif ; elle n’est pas étendue implicitement aux autres familles.

## Validation de l’assemblage

Preuves et empreintes : [`manifest.json`](evidence/mlops-integrated-2026-10-15/manifest.json).

- **269 tests d’assemblage réussis**, avec les vraies courses PostgreSQL,
  les refus de quota sous verrou, les journaux et snapshots transactionnels,
  le scoring réel, les permissions et le catalogue de surface.
- **68 tests de migrations PostgreSQL réussis** : chaîne ciblée jusqu’à 137,
  comparaison ORM/DDL, downgrade et ré-upgrade, grâce des anciennes clés et
  refus d’un downgrade destructif. Ce n’est pas un rejeu depuis une base vide
  de tout l’historique Alembic ; les voisins hors du périmètre sont estampillés.
- **16 tests d’export réussis** avec M1 réel, dont un serveur MLflow HTTP hors
  du dépôt donnant les mêmes prédictions que le modèle source.
- **2 285 tests frontend réussis**, TypeScript, i18n, navigation et build de
  production réussis. Le frontend est identique à celui construit après les
  derniers rebases, hors déplacement du correctif de fixture vers sa branche M2.

Le contrôle `ui-chrome` reste rouge sur `src/styles.scss` (7 halos, plafond 6),
identique à la base `47e289da` et non modifié par cette livraison. Les plafonds
ne sont pas relevés. Les tests de droits historiques ont été alignés sur la
matrice M1 (shadow autorisé au relecteur) et les fixtures de Flow utilisent un
initiateur et une appartenance réellement persistés, avec enforcement actif.

La régression ML élargie en `-n 4` donne **1 235 réussites, 22 ignorés et un
échec** : `test_timeout_preserves_completed_sections`. Ce test suppose qu’un
processus forké publie son premier résultat en 100 ms, ce qui n’a pas été tenu
sous cette charge parallèle. Son fichier et le code d’explications sont
strictement identiques à `47e289da` (empreintes dans `existing-checks.json`).
Le test passe seul et **les 22 tests de son fichier passent en série**. Aucun
budget produit ou assertion n’a été modifié pour masquer ce résultat. La
qualification parallèle n’est donc pas présentée comme entièrement verte.

La conformité statique passe (16 des 22 déclarations vérifiées statiquement ;
les attestations d’exécution restent séparées). La suite globale du dépôt
n’a pas été relancée. Ces résultats ne valent ni certification de la VM ni
qualification SMTP/webhook ou de charge.
