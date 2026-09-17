# Handover Agentium — reprise au 17 septembre 2026

## Demande à reprendre

Le propriétaire, Thibaud, a demandé d’arrêter les nouveaux développements pour économiser ses crédits et livrer un rapport complet R0–R6 avec preuves, screenshots et URLs. Ce dossier satisfait cette demande. **Ne pas reprendre automatiquement le développement au seul motif d’ouvrir le dossier : attendre la consigne de reprise.** La roadmap entière n’est pas terminée.

Lire d’abord `README.md`, puis les documents du dépôt :

- `docs/agentium-delivery-roadmap.md` : périmètre des lots.
- `docs/agentium-release-process.md` : processus obligatoire de release.
- `docs/ops/brd-system-roadmap-progress.md` : synthèse courante en tête ; entrées plus anciennes historiques.
- `docs/ops/agentium-r0-closure.md` : liste bornée pour fermer R0.
- `docs/evidence/release-e30230ae-2026-09-17/README.md` : dernière qualification runtime.

La demande initiale du goal est également conservée localement dans `/Users/thibaudishacian/.codex/attachments/bf19ea19-1b45-478b-a37d-b6cde027f75f/pasted-text-1.txt`. Si ce fichier est absent sur une autre machine, la roadmap versionnée et ce dossier restent les références de reprise.

## 1. État Git et runtime à ne pas confondre

| Emplacement | Branche / état au début du dossier |
|---|---|
| `/Users/thibaudishacian/Developer/DATATEGY/papAI/omnirag-brd-roadmap` | `codex/brd-system-roadmap`, HEAD documentaire `b6601f5e34fc87fdcdf66d3c4b204afae7cc7bc3`, deux fichiers de code modifiés |
| `/Users/thibaudishacian/Developer/DATATEGY/papAI/omnirag-cost-release` | `demo/agentic`, même HEAD documentaire ; dernier état contrôlé propre |
| `/Users/thibaudishacian/Developer/DATATEGY/papAI/omnirag` | Checkout original sur branche cursor, modifications étrangères : **ne pas éditer, réinitialiser ou nettoyer** |
| VM `/srv/agentium-data/worktrees/demo-agentic` | Build worktree, runtime `e30230aea3f58518bbe2219a5b2dbbdd757bab2f` |
| VM `/home/ubuntu/omnirag` | Ancien checkout, ancrage des montages : **ne pas supprimer ou réinitialiser** |
| carakai `/opt/agentium-protected-runner/repos/omnirag` | Runner root, HEAD e30230ae, marqueur `.agentium-source-sha` |

Ce dossier peut être committé après b6601f5e : `git log -1` et `git status` font foi pour le HEAD documentaire final. Le rapport ne provoque aucun rebuild runtime.

SHA live complet : `e30230aea3f58518bbe2219a5b2dbbdd757bab2f` ; tag des images `e30230aea3f5`. Rollback consigné : `1e374c3c1b71`.

- Backend : `sha256:30945ab1d3a7e5d4db412e9c3c9c83be01e0eb076b60b712b74e8045b630eacb`
- Worker : `sha256:f94f4c32d5b9e27afea41555df9486c9132c5392fdbee75bbb5fb21347d8a175`
- Frontend : `sha256:cfa505dbe3344ac15b386168ac9948e5e9449a8b4595c421e3506042d138add4`

Vérifier en lecture seule `/api/v1/build-info` et `/build-info.json` avant de qualifier ou déployer. Tous les anciens handles de build, déploiement et tests sont terminés ; aucun n’est à reprendre ou à relancer simplement parce que l’ancien échange est interrompu.

## 2. Travail non committé : petits corpus Giskard

Fichiers dans `omnirag-brd-roadmap` :

1. `backend/app/services/evaluation/campaigns.py`
2. `backend/app/tests/api/test_evaluation_campaigns.py`

Diff conservé : `giskard-small-corpus.patch` ; environ 60 insertions et 4 suppressions au moment de l’arrêt. **Lire le diff courant avant toute application : il est déjà présent dans ce worktree.** Sur un autre checkout compatible, utiliser d’abord `git apply --check` ; ne pas écraser des modifications existantes.

Le service exigeait 8–500 chunks pour deux opérations distinctes. La proposition conserve ce seuil pour générer un testset, mais accepte 1–500 chunks pour `job.kind == "evaluation_raget"`, dont les questions sont déjà relues. Zéro chunk est refusé avant appel au fournisseur. L’étape est `judge` pour cette évaluation, `generating_testset` pour la génération. Aucun changement frontend ou nouvelle dépendance.

Tests locaux : **44 passed, 531 warnings, 2.46 s**, log `giskard-small-corpus-tests.log` dans ce dossier, source `/tmp/raget-small-corpus-tests.log`. Les tests remplacent l’adapter/fournisseur : **ils ne qualifient pas le SDK réel sur un petit corpus**. Aucun gate complet, commit ou déploiement de ce correctif.

Ne pas retirer simplement l’interdiction des questions dupliquées dans l’adapter RAGET : les réponses y sont indexées par question, ce qui pourrait rattacher une réponse au mauvais Run. Ne pas affaiblir les assertions de refus pour obtenir une suite verte. Les contrôles contractuels natifs, le jugement sémantique et la décision humaine ont des significations différentes.

## 3. Entités de production à conserver

**Ne jamais approuver, relancer ou remplacer ces Runs ou décisions R1 dans le cadre d’une reprise technique.** Utiliser un candidat isolé et de nouvelles preuves lorsque la reprise est autorisée. Une décision humaine exige un geste explicite de la personne concernée.

### PIH généré

- System : `85d7e34e-0f0a-4565-8a93-a8710342536b`.
- BRD conservé : `184ab6a2-1d41-482d-ae8b-236dbc476f96`.
- Proposition : `e6a2ab64-a8eb-4ecd-9319-60a66ee20dba`.
- Batch : `512bdb27-9cf9-4a62-991d-07ffe4556295` ; trois Runs en attente de revue.
- Diagnostic de citations sur les sorties inchangées : 6/4/11 citations examinées, 0/0/5 absentes de la source. Le troisième Run ne peut pas être annoncé comme livrable validé.
- System PIH de démonstration distinct : `a021f6c3-fed5-4940-a3e1-53d5a7617f57`, draft r3 / publication v1. C’est lui dans la capture Flow historique, pas le System généré.

### NorthForge généré

- System : `ea63cf3a-3c42-47ba-a923-abcd0cb811ba`.
- BRD conservé : `ffc6102b-e1c6-4c67-8ce2-38885bdba6f5`.
- Proposition appliquée : `86658a91-fc74-4226-8429-a3ec3fe1854e`.
- Draft r2, empreinte `12f9cfa64c92675f3c5336dbb7cbb5d3dc8fbeecb58e44719b1c4aed1575259a`.
- Six Runs officiels conservés en attente de décision ; cinq briefings et une pause du planner dans la recette historique.
- Sonde supplémentaire : Run `c511f059-c285-4c6d-9225-ee935b93abe5`, décision `814ee417-95eb-449d-8b8a-d7a612b05a60`, expiration consignée au 19 septembre. Son expiration éventuelle ne donne aucune autorisation de la remplacer.
- Mauvaise génération conservée et **non appliquée** : job `00f68887-2dad-4b68-82e2-665d1c2d8b64`, proposition `de87d014-e13b-4500-b7a8-827175659bd9`. Les entrées contenaient des consignes de recette. Ne pas la sélectionner comme candidat validé.

### Qualification isolée NorthForge

Fichiers locaux `/tmp/agentium-brd-input-separation/`, notamment `generation-oracles/candidate.json`. Copie pérenne du candidat : `docs/evidence/brd-input-separation-2026-09-17/generated-candidate.json` et dossier `proofs/` du rapport.

Empreinte du DOCX d’origine : `4585ab4704af9fc24d57bdd9db425be099f18ab92c6679b99853966de19391e3`. Le candidat généré a une clé d’entrée peu lisible `live-worker` ; D-1 reste non couverte. Six cas initiaux : 4 réussites, 2 échecs. Les acceptations/refus du harness local ne sont pas une recette humaine.

Après e302, seul le cas historique a été rejoué avec le même candidat, les mêmes assertions et le retrieval déployé. Résultat correct 30/55 minutes, source exacte, un appel. Run **local** `4e515aa6-4228-4cf2-a6a0-728067ad4761`, invocation `83acf9f1-ab46-4dc0-90c0-b4864cc342a8` ; ne pas générer des liens de production pour ces identifiants.

## 4. Autres preuves à retrouver

- **R0/R4** : System Operational Analysis `15b05919-c93b-4648-8581-8a41cbe2fae6`, Experience `f286295a-ebef-44d2-a4a3-d0dbf04c866f`, Flow publié `e997f4e4-3b51-4eef-9481-389f3a9afae4` ; binding `showcase.operational.analyze`. Résultats exacts 120/155/+35 minutes, 3 retards, NF-04 +25 ; aucune économie attestée.
- **R2** : Run hybride réussi `7c2dca09-ef24-4dda-9291-8c9e64b44df5` ; absence reconnue `201a5ac4-d9e8-491f-86e0-6ac7b8baaecc` ; succès C-HAH séparé `8ec6ee27-76b1-4ace-b051-2b05c2596f28`. Fixture Capture à 6 bar distincte de PMP-700 à 700 bar.
- **Giskard réel** : System `a1cd8c00-6474-48bd-9d87-dba29f017e92`, suite `9cf497f2-1a8f-4581-b18f-5539eb80166b`, comparaison `0f4ba081-3b49-46e2-9f06-3827ed6292f8`, job RAGET `48f3c313-e521-47e1-9f0a-36b009b82c72`. Trois cas × deux versions, comparabilité limitée ; pas une génération de testset nouvellement qualifiée.
- **Dernière release** : `/tmp/agentium-brd-input-release/handoff.json` et `docs/evidence/release-e30230ae-2026-09-17/`. Les fichiers `/tmp` peuvent disparaître ; privilégier les copies versionnées.
- **Canaries** sur carakai : `/tmp/iteration-canaries-20260917T055551Z.lgzwS6`. Les six captures courantes du rapport en proviennent ; provenance dans `captures-provenance.json`.

## 5. Gates et environnement

Python de test disponible : `/Users/thibaudishacian/Developer/DATATEGY/papAI/omnirag/backend/.venv/bin/python`.

Node disponible dans `/Users/thibaudishacian/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin`.

Pour le correctif de campagne, depuis `omnirag-brd-roadmap/backend`, commencer par le test ciblé avec l’environnement habituel du dépôt :

```bash
/Users/thibaudishacian/Developer/DATATEGY/papAI/omnirag/backend/.venv/bin/python -m pytest app/tests/api/test_evaluation_campaigns.py -q
```

Avant release, exécuter les tests backend concernés et, dans `frontend-ng`, les gates `check:i18n`, `check:nav-links`, `check:ui-chrome`, `test:unit`, `build:prod`. Les résultats précédents ne qualifient pas un nouveau SHA. Utiliser les mécanismes et canaries existants, pas une seconde infrastructure.

Le dépôt est sur **Bitbucket**. Aucune CI distante n’existe pour cette boucle, même si un `.gitlab-ci.yml` est présent. Ne plus demander d’URL GitLab ou d’attestation de pipeline inexistant.

La release passe exclusivement par un commit poussé de **demo/agentic**, puis build des trois images sur **omnirag-demo**, switch explicite, santé et identités publiques, canaries depuis **carakai**. Lire le document exact avant d’exécuter les commandes. Le worker doit conserver `INSTALL_GISKARD_RAGET=true` pour cette qualification.

Le runner carakai est administré par root ; son origin pointe historiquement vers un bundle local ancien. La dernière synchronisation utilisait un bundle incrémental vérifié et un fast-forward. Le marqueur `.agentium-source-sha` contient le SHA complet, avec saut de ligne, mode 0644. Ne pas contourner un refus SSH par copie sauvage du dépôt, ni faire de reset destructif.

Avant switch, vérifier les jobs durables et tâches worker actifs/réservés. Un timeout d’observation ne prouve pas que le travail a échoué : lire son état persistant avant toute relance. Ne pas multiplier les builds, purger les images ou rejouer une action externe pour simplifier la recette.

## 6. Contraintes produit et recette

- Thibaud décide des bascules et clôtures ; ne pas redemander le nom du responsable.
- Préserver le thème natif NAWA. Le Cockpit commun peut évoluer.
- Préférences et branding n’accordent aucun droit supplémentaire.
- Ne pas confondre Run terminé, contrôle automatique réussi, décision humaine et valeur économique vérifiée.
- Ne pas modifier une Skill partagée ou une version publiée via une correction de draft.
- Pas d’oracle injecté dans la question pour réussir un benchmark ; pas de citations reconstruites fictivement.
- L’authentification Chrome manuelle est à reprendre : dernière page Sign in. Une demande de reconnexion a déjà été faite. Ne pas prétendre avoir une session active.
- QuickTime indisponible pendant la dernière recette ; aucun enregistrement nouveau effectué. Pas d’autorisation obtenue pour une capture vidéo alternative FFmpeg.
- R0 : 0/5 sessions métier et 0/5 développeur renseignées ; vidéo et décision ouvertes. Ne pas remplacer ces essais par des agents ou des tests automatisés.
- Les essais de perte brutale worker et le cas d’observabilité non préparé restent ouverts. Le redémarrage gracieux historique ne prouve pas ces scénarios.

## 7. Première séquence de reprise, lorsque demandée

1. Lire l’état de Git et les identités publiques ; ne pas repartir d’un ancien SHA indiqué au milieu du journal historique.
2. Examiner les deux modifications Giskard déjà présentes et leur patch. Qualifier le petit corpus avec le SDK/fournisseur réel sur une portée synthétique autorisée ; conserver génération et évaluation séparées.
3. Pour R1, traiter refus sémantique, couverture D-1 et citations PIH sur un nouveau candidat isolé. Conserver les anciens cas, leurs verdicts et leurs décisions. Exécuter la suite complète, pas uniquement le dernier cas corrigé.
4. Préparer la revue humaine, la publication et la consommation par un second compte ; ne pas les déduire d’un succès du harness.
5. En parallèle organisationnel, fermer R0 sur vidéo/baseline/décision sans ajouter de nouveaux critères. Poursuivre ensuite R2 complet ; R4 après socle R1, R6 après contrats R2.

**Point d’arrêt : rapport demandé livré ; runtime e30230ae conservé ; correctif Giskard local sauvegardé, non livré.**
