# Recette Flow : audit natif et projection d'invocation

## Recette opérateur après la PR #17

L'opérateur rapporte la fusion de la PR #17 sur `6227b529`, puis une ouverture
temporaire des séries et du Flow sur les images `bb33ceba`. Les résultats
suivants proviennent de son compte rendu, sans nouveaux journaux bruts déposés
dans ce suivi :

- séries : tuiles, parité liste/séries, volume/durées/dépenses, clavier,
  1440 et 390 px réussis pour le contributeur et l'administrateur plateforme ;
- Qualité : nuage/matrice → Run → preuve réussis pour le contributeur, options
  ouvertes, avec retour, rechargement, clavier et mobile ;
- Flow : arrêt sur le 404 de l'API d'invocation pour les deux comptes ;
- profil propriétaire non déroulé ; les deux options ont été refermées.

La production reste sur `bb33ceba5250e69aa4c59109f91f981f5095d446`.
`6227b529` ne changeait que les tests et la procédure. La migration 138 et les
images ne changent pas dans le correctif de recette décrit ici.

## Cause du 404

Le canari 68 transformait le lien UI
`/runs/{run_id}/invocations/{invocation_id}` en appel de l'API homonyme et
exigeait un 200. Cette API est réservée à la projection 360 de l'invocation,
commandée par `skill_invocation_360_projection_v1`. Son verrou est indépendant
de `EXECUTION_VIEW_ENABLED`.

Quand la projection est fermée, la route dédiée renvoie intentionnellement
404, même pour un administrateur. L'écran utilise alors l'audit natif contenu
dans `GET /api/v1/runs/{run_id}`, champ `invocations`, après filtrage des droits
et occultation des données. Le lien UI reste valable. Ce comportement est
déjà couvert par les tests API et composant.

La vérification HTTPS du 18 octobre, commencée à 14:04 UTC, confirme pour les deux
comptes de recette :

- les deux révisions vérifiées restent `bb33ceba` ;
- le journal est ouvert ; séries et Flow sont fermés ;
- la projection d'invocation effective est `false` ;
- l'API dédiée répond 404 ; le Run répond 200 et contient bien l'invocation
  `27c0d226-8c21-4c88-a815-01ba38beecfc` sous
  `519ce4f9-583e-4d70-a4b7-c3229d1749d8` ;
- le second Run `666a0219-36a5-4dc2-871d-a92fe44575f2` contient seize
  invocations autorisées.

Le 404 rapporté établit une erreur du canari. Il ne qualifie pas pour autant
le reste du parcours Flow, interrompu avant les étapes suivantes.

Preuve indépendante :
[contrôle HTTP](../evidence/observability-flow-invocation-2026-10-18/native-invocation-http.json).

## Correction de la recette

Le helper partagé `e2e/fixtures/native-invocation.ts` lit le drapeau effectif
du workspace et vérifie l'identité exacte du Run et de l'invocation dans la
source correspondante. Si la projection est ouverte, un échec de son API
reste bloquant : aucun repli automatique après 404.

Le canari 68 suit désormais le vrai lien de la carte Flow au clavier, vérifie
l'écran d'invocation, le recharge, puis revient au Flow, sur 1440 et 390 px.
Le canari Qualité 66 utilisait la même hypothèse quand une preuve comporte un
lien d'invocation ; il emploie désormais le même helper.

Un canari 69 vérifie séparément les liens directs d'invocation et leur
rechargement, sans exiger l'ouverture du Flow. Il compare le JSON d'audit
affiché à celui du Run autorisé à l'intérieur du navigateur : seules les
identités, les états et les résultats booléens sortent vers les preuves.
Il vérifie le rôle réel du principal, la révision exacte et les options
avant/après. Il n'autorise aucun appel métier en écriture.
La configuration désactive aussi le snapshot d'accessibilité automatique
de Playwright en cas d'échec (`PLAYWRIGHT_NO_COPY_PROMPT=1`). Les captures
explicites d'audit contiennent des données et restent dans le répertoire
privé de recette ; elles ne doivent pas être publiées avec les reçus JSON.

Injecter les identifiants du compte dans `E2E_USERNAME` / `E2E_PASSWORD`, puis
exécuter depuis `frontend-ng`, avec un répertoire privé par profil :

```bash
umask 077
export E2E_BASE_URL=https://agentium.papai.ai
export E2E_SHOWCASE_WORKSPACE_SLUG=agentium-showcase
export E2E_EXPECTED_REVISION=bb33ceba5250e69aa4c59109f91f981f5095d446
export E2E_OBSERVABILITY_PROFILE=restricted
export E2E_EXPECT_ACTIVITY_SERIES=false E2E_EXPECT_EXECUTION_VIEW=false
export E2E_INVOCATION_TARGETS='[{"runId":"519ce4f9-583e-4d70-a4b7-c3229d1749d8","invocationId":"27c0d226-8c21-4c88-a815-01ba38beecfc"},{"runId":"666a0219-36a5-4dc2-871d-a92fe44575f2","invocationId":"937838f5-a3a8-4f8a-8b32-af2838b9185d"}]'
npx --no-install playwright test \
  --config=playwright.observability-live.config.ts \
  69-native-invocation-live-canary.spec.ts \
  --output=/tmp/observability-invocations-restricted
```

Pour l'administrateur, changer le profil en `platform_admin`, les identifiants
injectés et le répertoire de sortie. Adapter le SHA attendu si la production
change. Le test échoue si le rôle, les options ou le corpus diffèrent ; aucune
simulation ne remplace les données absentes.

## Résultats du correctif

Le canari 69 a réussi réellement pour le contributeur et l'administrateur,
sur les deux paires de Run/invocation ci-dessus et aux deux largeurs, avec
comparaison de l'audit affiché et rechargement. Les deux options sont restées
fermées avant/après ; aucun appel métier en écriture n'a été tenté. Huit
captures restent privées. Reçus :
[contributeur](../evidence/observability-flow-invocation-2026-10-18/restricted-live.json),
[administrateur](../evidence/observability-flow-invocation-2026-10-18/platform_admin-live.json).

Validation ciblée : 11 tests API existants, 8 tests unitaires de composants
et modèles, TypeScript strict sur les canaris 66–69 et leur configuration,
cinq tests Playwright découverts dans quatre fichiers. Un échec volontaire
local a également confirmé que la configuration conserve les métadonnées
d'erreur sans copier le contenu de la page.

La vérification TypeScript globale E2E échoue encore hors des fichiers
modifiés : types du test `33-work-ml-blocks-mocked` et alias `@app` non résolus
par cette configuration. Aucun résultat global vert n'est revendiqué. Le
canari 66 complet n'a pas été rejoué ici ; la branche d'invocation partagée
a été exercée par le 69. Voir le
[manifeste](../evidence/observability-flow-invocation-2026-10-18/manifest.json).

## Suite de la qualification

La correction ne demande ni reconstruction d'image, ni migration, ni ouverture
de la projection 360. La recette Flow 68 corrigée doit être relancée après
réouverture coordonnée des séries et du Flow selon la
[procédure VM](observability-reopening-recipe-2026-10-18.md).

Restent à qualifier : Flow complet sur les deux Runs, profil propriétaire,
Run actif et deux nouveaux composites, reconnexion pendant une transition
avec reprise sans doublons, conservation du snapshot après publication d'une
nouvelle version, et révocation avec graphiques/Flow ouverts. La réussite du
canari 69 ne ferme aucun de ces contrôles. Les deux options restent fermées
à l'issue de ce travail.
