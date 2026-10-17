# Recette réelle du moniteur Showcase — 17 octobre 2026

Révision cible : `8679a4f26efe089024df7680d894f68169f5ff21`.
Site : `https://agentium.papai.ai`. Workspace : `agentium-showcase`.

**Parcours de preuve validé sur la production**, en Chromium, thème clair et
interface anglaise, avec le rôle propriétaire du workspace. Le canari réussit
en 2,4 minutes. Une réserve visuelle subsiste sur les libellés du radar à 390 px.
Ce verdict ne ferme pas R5 dans son ensemble ni les qualifications R2/R4.

## Périmètre

Cette recette contrôle la conservation de Qualité après la livraison du moniteur
Opérations/Activités. Elle utilise le compte de recette autorisé, propriétaire du
workspace, et les évaluations déjà enregistrées. Elle ne lance aucune évaluation
ni aucun Run, ne modifie aucune configuration et n'active ni les séries R2 ni le
suivi Flow R4. Elle ne qualifie pas les autres rôles IAM ni ces deux capacités.

Le corpus exposé dans la fenêtre de 30 jours contient sept évaluations : deux
complètes et cinq partielles. Les deux complètes ont des affirmations reliées à
des extraits documentaires disponibles. Ces extraits n'ont pas de lien vers une
invocation ; une preuve documentaire reste vérifiable sans inventer ce lien.

## Exécution reproductible

Le canari dédié est
`frontend-ng/e2e/tests/66-showcase-quality-release-canary.spec.ts`.
Il exige un compte explicite et échoue si le corpus ou la preuve manque ; aucun
cas n'est ignoré pour faire passer la recette. Il vérifie séparément le point du
nuage et la cellule de matrice, en 1440 et 390 px, au clavier, avec Run exact,
preuve comparée aux données de l'API, retour et rechargement. Le radar et
l'historique doivent être visibles et alimentés.

Dans un environnement où `E2E_USERNAME` et `E2E_PASSWORD` sont déjà injectés :

```bash
cd frontend-ng
E2E_BASE_URL=https://agentium.papai.ai \
E2E_SHOWCASE_WORKSPACE_SLUG=agentium-showcase \
E2E_EXPECTED_REVISION=8679a4f26efe089024df7680d894f68169f5ff21 \
npx playwright test --config=playwright.showcase.config.ts
```

La configuration utilise le proxy de l'environnement s'il existe et conserve
la validation TLS. Traces, vidéos et captures automatiques sont désactivées pour
ne pas enregistrer l'authentification. Les captures explicites interviennent
après connexion. Les mutations sont bloquées ; seuls les appels de connexion,
validation et renouvellement de session sont autorisés en POST. L'audit de
navigation automatique est supprimé et compté séparément.

Les preuves JSON ne contiennent que des identifiants, états et résultats. Les
captures de documents restent dans les résultats locaux du navigateur ; elles
ne sont pas publiées dans le dépôt.

## Preuves et verdict

Les contrôles publics, le contrôle authentifié et le diagnostic de corpus sont
conservés dans [le dossier de preuves](../evidence/showcase-quality-qualification-2026-10-17/).

| Contrôle réel | Résultat |
| --- | --- |
| Révisions backend et frontend, avant et après | SHA attendu et vérifié |
| Opérations par défaut et cinq onglets | Réussi |
| Nuage → Run → preuve → retour/rechargement, 1440 px | Réussi, clavier Enter |
| Matrice → Run → preuve → retour/rechargement, 1440 px | Réussi, clavier Espace |
| Mêmes deux parcours en 390 px | Réussis, sélection et période conservées |
| Radar et historique, deux tailles | Alimentés et visibles ; réserve sur les libellés du radar mobile |
| Écritures métier tentées | Aucune |
| Audit automatique de navigation | 30 appels supprimés par le canari ; livraison de cet audit non qualifiée ici |
| Options après recette | Supervision ouverte, séries et suivi Flow fermés |

Évaluation : `417379b9-c451-4415-a707-6afb46ba9593`.
Run : `c8e9d120-b76e-4405-8b5f-4e54be8ce5de`.
Affirmation : index `0` ; extrait : `1`. Le contenu de cet extrait et ses
métadonnées de source ont été comparés dans le navigateur avec l'API, sans
copier le texte dans les journaux. Aucun lien d'invocation n'étant présent,
son ouverture reste hors de cette preuve de recette ; elle n'est pas simulée.

La revue visuelle du radar 390 px montre des libellés coupés aux bords du
canvas. Le graphe reste alimenté et les parcours de preuve fonctionnent ;
la lisibilité intégrale des douze dimensions sur mobile reste à corriger.
Les tests de visibilité ne doivent pas être présentés comme une validation
de cette lisibilité.

La recette a nécessité deux corrections de son propre banc : accepter les
preuves documentaires sans lien d'invocation, puis autoriser le POST de
validation de session utilisé au démarrage du frontend. Aucun correctif de
l'application n'a été déployé. Le compte canari historique refusé au premier
essai a été remplacé par le compte explicitement fourni pour cette recette.

Les résultats de production ne couvrent pas les membres restreints, les huit
combinaisons langue/thème/drapeaux, ni les snapshots et reconnexions du suivi
Flow. Les preuves locales précédentes restent distinctes. Les contrôles
d'images et de services de contrôle sont ceux du bilan de release opérateur,
pas des mesures renouvelées ici.
