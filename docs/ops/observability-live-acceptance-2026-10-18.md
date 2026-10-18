# Recette écran Observabilité — 18 octobre 2026

**Verdict : échec de la recette globale ; repli exécuté par l'opérateur et
confirmé par HTTP depuis cet environnement.** Le défaut de population de la
tuile « En cours » est reproduit ci-dessous sur la livraison avant repli.
Qualité est validée sur le parcours testé. Le correctif décrit en fin de note
n'est pas déployé ; les séries et le suivi Flow restent fermés.

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
- Recette initiale avant repli : Chromium, TLS vérifié, interface anglaise,
  thème clair ; aucun Run créé, aucune évaluation relancée et aucun droit ou
  paramètre de production modifié pendant cette première phase.

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
| Trois profils | Propriétaire vérifié avant repli ; contributeur et administrateur plateforme vérifiés après repli sur les API natives. Comparaison des séries non qualifiée, options fermées |
| Révocation d'un droit pendant le flux | Réussie sur le journal Activités réel : retrait du membership du seul compte de recette, événement SSE de révocation, purge de la liste, des compteurs et du détail, puis restauration des droits |

Les snapshots historiques lus par l'API sont présents sur les Runs Luma
`519ce4f9-583e-4d70-a4b7-c3229d1749d8` et
`666a0219-36a5-4dc2-871d-a92fe44575f2`, avec versions différentes et corrélation
explicitement partielle. Le Run Chat
`c8e9d120-b76e-4405-8b5f-4e54be8ce5de` n'a pas de graphe enregistré. Ces lectures
ne prouvent ni deux nouveaux composites, ni des transitions SSE, ni une
révocation à chaud.

## Repli exécuté et vérifié

L'opérateur rapporte l'exécution sur la VM, contrôlée à
`2026-10-18T11:42:23Z`, puis les images relevées à `11:53:13Z` :

1. Configuration active sauvegardée dans
   `/root/series-rollback-2026-10-18/source-001.env`. Le fichier effectif est
   `/srv/agentium-data/runtime-env/2026-10-12/runtime-env/source-001.env`, sans
   doublon ni surcharge des deux options :

   ```dotenv
   ACTIVITY_SERIES_ENABLED=false
   EXECUTION_VIEW_ENABLED=false
   ```

2. `storage-check`, puis `up` réussis avec les mêmes images
   (`AGENTIUM_IMAGE_TAG=12cdac727b72`), huit workers backend et les profils
   ML-TS, ML-Deep, Hugging Face, OpenBao, connecteurs et contrôle conservés.
   Runner connecteurs inchangé :
   `sha256:d44a53fb8e155645312541bc720885354fa244c2917ccde8e77e6b6e66f9b77f`.
3. Tête `138_activity_measures`, journal, admission, worker et scheduler de
   contrôle conservés. Ces constats VM proviennent du compte rendu opérateur ;
   cet environnement n'a toujours pas d'accès SSH.

Le contrôle HTTP indépendant commencé à `2026-10-18T11:57:56Z` confirme les
deux `build-info` sur `12cdac727b724fbf2bc0157fb38d555134d51f9d`, révision
vérifiée, health/readiness 200 et les options `enabled=true`,
`activity_series_enabled=false`, `execution_view_enabled=false`.
Les deux comptes complémentaires confirment ensuite les mêmes valeurs ;
les routes séries et `execution-view` répondent 404 avec leurs codes de
fonction désactivée, y compris pour l'administrateur plateforme.

Preuve directe : [rollback-http-check.json](../evidence/observability-live-2026-10-18/rollback-http-check.json).
L'ancien [final-state.json](../evidence/observability-live-2026-10-18/final-state.json)
conserve l'observation antérieure au repli, sans réécriture historique.

## Comptes et révocation après repli

L'opérateur a créé deux identités dédiées sans email, puis leur membership
Showcase avant leur premier `/auth/me`. La connexion réelle confirme :

- contributeur : rôle plateforme `user`, scopes `workspace` et `system` ;
- administrateur : rôle plateforme `admin`, scope `platform` supplémentaire.

Le contributeur voit deux activités ; l'administrateur en voit quatre.
L'accès à l'agrégat plateforme est refusé au contributeur (403). Les détails
et événements des deux jobs masqués sont également contrôlés directement.
Le Run historique de Qualité est un ancien `trigger=chat`, sans initiateur,
lisible selon sa politique native : il ne prouve pas l'isolation d'un chat
privé `chat_agentic`.

Aucun profil exclusif à un System n'existe actuellement. Un contributeur
soumis aux droits natifs des Runs/jobs n'est pas présenté comme une preuve
d'isolation par System.

La recette navigateur du journal, commencée à `2026-10-18T12:03:35Z`, a ouvert
deux lignes et un détail, puis observé le handshake et les heartbeats SSE.
Le propriétaire a retiré le membership du seul compte dédié. Le serveur a
émis `ACTIVITY_ACCESS_REVOKED` ; en 1 132 ms après le début de l'appel de
retrait, la liste, les compteurs et le détail étaient purgés, et une nouvelle
lecture API répondait 403. Le membership a été rétabli avec le même rôle,
les mêmes labels et habilitations, sans email. Les deux options restent
fermées. Cette recette ne qualifie pas la purge des séries ni celle du Flow.

Preuves : [profils HTTP](../evidence/observability-live-2026-10-18/rollback-profiles-http-check.json)
et [révocation navigateur](../evidence/observability-live-2026-10-18/revocation-live.json).
Captures conservées hors du dépôt ; aucun mot de passe ni jeton dans les
preuves publiées.

## Correctif préparé après repli

- La tuile transmet `status=pending,running,waiting`, issu du même ensemble
  que son compteur. Le sélecteur affiche explicitement ce groupe en français
  et en anglais.
- La liste, les séries natives et les quatre prédicats PostgreSQL acceptent
  la même union validée. Une valeur inconnue ou un élément vide donne 422 ;
  les filtres simples, droits, fenêtres, pagination et périmètres restent
  appliqués.
- Les champs du formulaire restent des brouillons jusqu'à « Filtrer » :
  liste et graphiques suivent ensemble l'URL appliquée, y compris lors d'un
  rafraîchissement SSE. Les modes de coût conservent le statut sélectionné
  avec leurs types et base temporelle propres.
- Le canari 67 vérifie aussi le sélecteur et les vraies requêtes des
  graphiques, avant et après rechargement. Il n'est pas relancé sur la
  production dont les options sont fermées.
- La revue de la révocation a révélé que, séries ouvertes, vider la liste ne
  détruisait pas leurs graphiques. Le correctif ferme maintenant toute la
  vue, détruit les séries, annule les requêtes et invalide les réponses
  tardives. Trois tests couvrent ce cas, y compris une révocation dès la
  connexion ; la recette live des séries ouvertes reste à exécuter.

Validation backend : 88 tests distincts réussis, dont 17 sur PostgreSQL 17
jetable réel, plus six tests du catalogue de surface. Ruff et contrôle de
whitespace réussis. Les résultats frontend et les empreintes du suivi sont
consignés dans le
[manifeste complémentaire](../evidence/observability-live-2026-10-18/followup-manifest.json).

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
