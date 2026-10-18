# Recette écran Observabilité — 18 octobre 2026

**Verdict : échec de la recette globale. Repli demandé à l'opérateur, non exécuté
par cet environnement.** La tuile « En cours » ouvre une population différente
de celle de son compteur. Qualité est validée sur le parcours testé. Les étapes
suivantes ne sont pas déclarées qualifiées.

## Candidat et périmètre réels

- Production backend et frontend : `12cdac727b724fbf2bc0157fb38d555134d51f9d`,
  révision vérifiée par les deux `build-info`.
- `health` et `health/ready` répondent 200.
- Workspace : `agentium-showcase` ; compte authentifié de rôle plateforme
  `user`, propriétaire de ce workspace. Ce compte ne simule pas les deux
  autres profils.
- Les deux options sont ouvertes au début de la recette, vérifiées via
  `/api/v1/observability/activities/features`.
- Migration 138, budgets d'images et mesures 1,40 s / 1,90 s : déclarés livrés
  par l'opérateur ; ils ne sont pas remesurés par cette recette navigateur.
- Chromium, TLS vérifié, interface anglaise, thème clair. Aucun Run créé,
  aucune évaluation relancée, aucun droit ou paramètre de production modifié.

## Échec bloquant : destination de la tuile « En cours »

Observation réelle, fenêtre de 30 jours arrêtée au
`2026-10-18T09:33:42.737Z` :

1. Opérations affiche les tuiles exhaustives sous les droits de l'utilisateur.
2. La tuile `operations-tile-running` affiche `Running / 0`.
3. Son lien contient `facet=activities`, `kind=run`, `since=30d` et `as_of`,
   mais **aucun filtre de statut**.
4. Le clic ouvre Activités ; l'API répond 200, `total=1`, et renvoie l'activité
   `de576f78-e72a-5520-bc69-c4d8e4cb1d8a` avec `status=failed`.

Le compteur mesure les états `pending`, `running`, `waiting`. Sa destination
affiche tous les Runs. Le code du candidat confirme que cette tuile appelle
`tileQuery()` sans argument, contrairement aux tuiles terminées et en échec.
Un correctif doit transmettre et appliquer la même union de statuts à la liste
et aux séries, y compris après rechargement ; filtrer seulement `running`
laisserait un écart pour les travaux en attente.

Preuve : [running-tile-live.json](../evidence/observability-live-2026-10-18/running-tile-live.json).
Les captures de la tuile et de sa destination sont conservées localement.

## Ce qui a été vérifié

| Étape | Résultat et portée |
| --- | --- |
| Révision, santé, connexion, options | Vérifiées réellement |
| Badge d'exhaustivité et destination « En cours » | Badge présent ; destination incorrecte, recette en échec |
| Qualité : nuage et matrice → Run → preuve → retour/rechargement | Réussi sur 1440 et 390 px, clavier, même Run et même extrait |
| Radar et historique | Visibles et alimentés dans la recette Qualité |
| Comparaison exhaustive séries/liste du propriétaire | Canari préparé et typé, non exécuté après le déclenchement du repli |
| Deux parcours composites nouvellement exécutés | Non exécutés |
| Flow historique | Lectures API réelles sur quatre Runs ; recette écran complète et handshake SSE non exécutés |
| Trois profils | Seul le propriétaire workspace est disponible ; responsable System restreint et administrateur plateforme non qualifiés |
| Révocation d'un droit pendant le flux | Non effectuée ; pas de compte restreint de recette disponible |

Les snapshots historiques lus par l'API sont présents sur les Runs Luma
`519ce4f9-583e-4d70-a4b7-c3229d1749d8` et
`666a0219-36a5-4dc2-871d-a92fe44575f2`, avec versions différentes et corrélation
explicitement partielle. Le Run Chat
`c8e9d120-b76e-4405-8b5f-4e54be8ce5de` n'a pas de graphe enregistré. Ces lectures
ne prouvent ni deux nouveaux composites, ni des transitions SSE, ni une
révocation à chaud.

## Repli autorisé à exécuter sur la VM

La consigne opérateur exige la fermeture des **deux** options dès qu'un parcours
échoue. La condition est remplie. L'environnement de recette dispose de HTTP,
mais d'aucun VPN ni droit TCP vers la VM ; il ne peut donc pas lancer `up`.
L'opérateur a été sollicité immédiatement après la reproduction du défaut.

1. Sauvegarder la configuration active et y fixer :

   ```dotenv
   ACTIVITY_SERIES_ENABLED=false
   EXECUTION_VIEW_ENABLED=false
   ```

2. Relancer la commande `up` habituelle avec les **mêmes images**
   (`AGENTIUM_IMAGE_TAG=12cdac727b72`) et les mêmes profils activés. Le script
   versionné est
   `/srv/agentium-data/worktrees/demo-agentic/scripts/agentium-vm-deploy.sh`.
   Modifier le bundle d'environnement effectivement employé par cette commande,
   pas seulement des variables du shell d'appel.
3. **Conserver la migration 138**, le journal d'activité et les services de
   contrôle. Ce repli ferme les lectures, pas l'enregistrement des travaux.
4. Vérifier santé, révision et `/observability/activities/features` :
   `enabled=true`, `activity_series_enabled=false`, `execution_view_enabled=false`.

Le dernier état observé est conservé dans
[final-state.json](../evidence/observability-live-2026-10-18/final-state.json).
Une demande de repli ne vaut pas une preuve de son application.

## Rejouer après correction et nouvelle décision d'ouverture

Les tests `66`, `67` et `68` sont sélectionnés par
`frontend-ng/playwright.observability-live.config.ts`. Les identifiants doivent
être injectés dans `E2E_USERNAME` et `E2E_PASSWORD` ; ils ne sont pas enregistrés
dans le dépôt. Le test 66 garde des options attendues fermées par défaut pour
reproduire la recette du 17 octobre ; les attentes explicites suivantes
correspondent à la présente livraison :

```bash
cd frontend-ng
E2E_BASE_URL=https://agentium.papai.ai \
E2E_SHOWCASE_WORKSPACE_SLUG=agentium-showcase \
E2E_EXPECTED_REVISION=12cdac727b724fbf2bc0157fb38d555134d51f9d \
E2E_EXPECT_ACTIVITY_SERIES=true \
E2E_EXPECT_EXECUTION_VIEW=true \
E2E_FLOW_RUN_IDS=519ce4f9-583e-4d70-a4b7-c3229d1749d8,666a0219-36a5-4dc2-871d-a92fe44575f2 \
npx playwright test --config=playwright.observability-live.config.ts
```

Sur un candidat corrigé, remplacer le SHA attendu par la révision réellement
déployée. Ne pas rouvrir les options pour exécuter cette commande sans avoir
traité l'échec. Le test historique ne remplace pas les composites nouvellement
exécutés et les contrôles de révocation avec les trois vrais profils.
