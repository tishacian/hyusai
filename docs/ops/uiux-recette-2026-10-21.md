# Recette UI/UX après déploiement — 21 octobre 2026

La révision frontend et backend servie par `https://agentium.papai.ai` est
`34244ab77ca0b1ecfcf0835abe02a748b6440544`, annoncée vérifiée par les deux
endpoints build-info. Son code fonctionnel est identique au candidat poussé
`270a086f0238b84a4f3cac3c7194b5de4008869f` ; trois documents diffèrent.
Le présent rapport complète le [bilan avant déploiement](uiux-plan-2026-10-21/README.md).
Les corrections issues de cette recette sont sur `feat/uiux-recette` ; elles
ne sont pas présentées comme déjà déployées.

## Préservation de Luma

L'utilisateur a explicitement demandé de préserver ses données. Les contrôles
sur le domaine déployé sont des lectures. Dans le navigateur, les méthodes
d'écriture sont bloquées ; seule la validation d'authentification
`POST /api/v1/auth/validate`, dont le code ne fait que vérifier le JWT, est
autorisée. La connexion préalable utilise l'API d'authentification. Les tentatives
automatiques d'écriture du journal `/api/v1/audit` sont bloquées et consignées.
Aucun import, Run, décision, changement de rôle, publication, installation,
réinitialisation ou suppression de données métier n'est déclenché.

Les réponses JSON de quatre ressources ont la même empreinte SHA-256 avant
et après les contrôles Luma :

| Ressource observée | État conservé |
| --- | --- |
| Flow `f3ea83de-df89-45ec-8a85-c00d676b2713` | Brouillon r38 ; publication `b8eb64d3-e417-41bf-898a-7b1ad232d64a` |
| Work `reclamations` | Même réponse complète de lecture de l'application publiée |
| Dataset `336aed57-8637-42bc-9d81-ab4f820f68f6` | v7, 23 lignes |
| Dataset `7f5350c4-3346-437a-bf53-aa3ef46aae36` | v1, 70 lignes |

Cette comparaison porte sur les quatre réponses API observées ; elle ne
constitue pas une sauvegarde de la base et des fichiers.

## Contrôles réellement exécutés en service

- Santé : `/api/v1/health/live` et `/api/v1/health/ready` répondent 200 ;
  disponibilité déclarée du runtime, de PostgreSQL, de Qdrant et du stockage S3.
- Trois connexions réussies. Le créateur est propriétaire du workspace partagé ;
  les deux autres comptes y ont le rôle `workspace_contributor`. L'un a aussi
  le rôle administrateur de plateforme. Le nom du compte « restricted » ne
  prouve donc pas un droit de lecture seule.
- Pour les trois comptes, catalogue Work et accueil Work répondent 200.
  Les deux comptes non membres d'Andritz obtiennent 403 sur ce workspace,
  y compris l'administrateur de plateforme.
- 15 ouvertures navigateur : Work, Applications, Connexions, Missions et
  Sécurité du compte, avec chacun des trois comptes. Aucune redirection vers
  la connexion, aucune erreur JavaScript ni erreur API de lecture observée.
- 9 ouvertures Luma : Dossier, Charge et capacité, Amélioration, avec chacun
  des trois comptes. Aucune erreur JavaScript ni erreur API de lecture.
  Axe 4.13.0 : aucune violation des règles sélectionnées WCAG 2 A/AA,
  2.1 AA et 2.2 AA sur ces neuf états rendus, en français au format bureau.

Ces ouvertures ne qualifient ni les écritures métier, ni les parcours humains
complets, ni les fournisseurs réels. Les écritures de télémétrie bloquées
limitent aussi la portée de ce passage à la lecture de l'interface.

## Validation locale et corrections

Tous les scénarios d'écriture utilisent des fixtures sur HTTP loopback ou une
base PostgreSQL jetable indépendante de la production.

Les corrections produit issues des défauts reproduits sont les suivantes :

- Missions : ordre des verrous de reprise aligné sur les workers pour éviter
  deux deadlocks ; accolades de l'exemple JSON du prompt échappées pour permettre
  le démarrage d'une nouvelle mission.
- Work : restitution du focus après rendu de la liste et conservation des
  paramètres dans les liens des résultats et des décisions.
- Flow : ouverture du journal par le paramètre canonique `facet=triggers`,
  avec compatibilité du lien historique `tab=triggers`.
- Paramètres du workspace : le rafraîchissement de ses données après activation
  ne détruit plus le composant qui affiche le reçu de l'écriture.
- Applications : les cellules du tableau s'empilent sur mobile, avec tous les
  champs et actions, leurs libellés traduits et les associations aux en-têtes.

Aucune migration ni modification de données n'accompagne ces corrections.

### Missions et compilation

Les [preuves PostgreSQL et Celery](uiux-plan-2026-10-21/recette-missions-2026-10-21.md)
comptent **5 tests PostgreSQL, 9 tests SQLite et 1 scénario de processus
Celery/beat réussis**. Le scénario Celery démarre par la vraie échéance beat
de 30 secondes (émission observée après 30,017 s), puis tue un worker, reprend
sa tentative et vérifie la préservation des étapes et le refus des doublons.
La base PostgreSQL, les deux workers et beat sont locaux et ont été arrêtés.
Le transport filesystem et les réponses de modèle déterministes ne qualifient
ni RabbitMQ ni les fournisseurs ou la topologie de production.

Le build standard `npm run build:prod`, avec téléchargement des polices,
réussit sur le candidat corrigé. Les avertissements de budgets et de dépendances
CommonJS existants restent non bloquants. Les contrôles i18n, navigation,
chrome (**1 921**) et replis (**126/126**) passent, sans hausse des budgets.
Ruff et le formatage des cinq fichiers Python concernés passent.
La suite frontend complète `npm run test:unit` exécute **2 592 tests, tous
réussis**, sans test ignoré ni nouvelle tentative automatique. Le journal
est conservé dans `/tmp/agentium-recette/frontend-unit-final.log`.

### Suite cœur locale

Les **47 cas distincts** des six fichiers ci-dessous disposent tous d'un
passage réussi, après correction des fixtures et sélecteurs. Ce résultat
cumule la campagne initiale et les relances ciblées ; il ne désigne pas une
exécution unique de 47 cas. Aucun composant produit n'a été modifié pour cette
suite.

| Fichier Playwright | Cas réussis | Périmètre |
| --- | ---: | --- |
| `76-connector-deposit-receipts-mocked.spec.ts` | 2 | Reçus par fichier accepté/refusé, FR/EN à 320 px |
| `80-state-contract-mocked.spec.ts` | 13 | Lectures/écritures explicites, réponse perdue, deux matrices axe sur Evaluation Preset |
| `81-decisions-and-roles-mocked.spec.ts` | 10 | Droits de décision, vérification après coupure, absence de doublon, confirmation et conflit de rôle |
| `82-navigation-reads-mocked.spec.ts` | 6 | MFA inconnu, sessions, récupération de mot de passe, recherche et restitution du focus, FR/EN |
| `86-data-evidence-mocked.spec.ts` | 10 | Connaissance, modèles exécutables, fraîcheur, schéma PostgreSQL et retour au dataset versionné |
| `87-operations-mocked.spec.ts` | 6 | Mission enregistrée avant lancement, historique, erreurs de lecture et confirmation des consommateurs d'un secret |

Résultats bruts, sans nouvelle tentative automatique :

- `/tmp/agentium-recette/core-run.log` : 39 réussis, 8 échoués, 6 minutes.
- `/tmp/agentium-recette/core-corrected.log` : 22 réussis, 2 échoués, 1,3 minute.
- `/tmp/agentium-recette/core-navigation-final.log` : 6 réussis, 0 échec, 17,2 secondes.

Les corrections portent sur les options Playwright placées au mauvais niveau
dans les fichiers 86/87, le h1 du dépôt distingué de son récapitulatif, le
contrat des chunks (`content`) et les métadonnées PostgreSQL manquantes
(`checked_at`, colonnes), la conservation du paramètre de navigation `lens`,
le libellé exact de confirmation d'une relance, la session déconnectée requise
pour récupérer un mot de passe et l'annonce de filtrage distinguée du statut
de chargement. Les assertions de reçu, d'absence d'écriture et de conservation
des preuves sont maintenues.

Exécution sur `http://127.0.0.1:4321` avec `/usr/bin/chromium`, API entièrement
simulées, deux workers autorisés, `--retries=0 --max-failures=8`. Commande pour
rejouer les six fichiers depuis `frontend-ng` :

```sh
E2E_BASE_URL=http://127.0.0.1:4321 E2E_CHROMIUM_EXECUTABLE=/usr/bin/chromium \
  ./node_modules/.bin/playwright test --config=playwright.mocked.config.ts \
  e2e/tests/{76-connector-deposit-receipts,80-state-contract,81-decisions-and-roles,82-navigation-reads,86-data-evidence,87-operations}-mocked.spec.ts \
  --workers=2 --retries=0 --max-failures=8
```

Les matrices du fichier 80 couvrent deux états d'Evaluation Preset en FR/EN,
clair/sombre et 1440/456/320 px. Leur succès ne couvre pas l'accessibilité de
toute l'application. Les missions et les appels PostgreSQL simulés ne prouvent
pas la concurrence des workers ni l'accès à un fournisseur réel.

### Création, Work et Luma en local

Les **111 cas distincts** des dix fichiers suivants disposent tous d'un passage
réussi. Ce résultat cumule le passage initial sur le code déployé et les
relances ciblées des défauts corrigés ; ce n'est pas une exécution unique de
111 cas sur le candidat final. Les assertions n'ont pas été affaiblies et les
relances utilisent `--retries=0`.
Le [relevé par scénario](uiux-recette-2026-10-21/creation-evidence.json)
conserve le dernier passage réussi et les empreintes SHA-256 des journaux.

| Fichier Playwright | Cas réussis | Périmètre |
| --- | ---: | --- |
| `26-work-home-mocked.spec.ts` | 8 | Accueil, reçus, FR/EN et thèmes, clavier, retour au dossier sélectionné, liens Run avec paramètres |
| `28-claims-studio-mocked.spec.ts` | 26 | Luma/Claims : preuves, Judge, décisions, erreurs PostgreSQL, priorité et provenance, file mobile et reçus |
| `33-work-ml-blocks-mocked.spec.ts` | 12 | Prédictions et séries temporelles, provenance, indisponibilité, restauration du résultat sans soumission supplémentaire |
| `50-flow-data-prep-mocked.spec.ts` | 8 | Préparation, SQL, aperçu d'un Run, test isolé de source, cinq étapes et câblage réel des ports |
| `53-flow-triggers-mocked.spec.ts` | 6 | Flow publié en lecture, journal des livraisons, planification et webhook FR/EN |
| `70-typed-judge-diagnostics-mocked.spec.ts` | 4 | Citation invalide et réponse tronquée distinguées d'un appel terminé |
| `72-access-state-activation-mocked.spec.ts` | 16 | Accès fermé/refusé/invérifiable, confirmation d'activation, conflit et réponse perdue |
| `73-blank-start-mocked.spec.ts` | 13 | Départ vierge, inventaire explicite, exemples choisis, imports refusés et états inconnus |
| `74-wizard-resume-mocked.spec.ts` | 6 | Reprise par adresse et rechargement, erreurs de lecture, champ refusé et largeur de 320 px |
| `75-studio-contract-receipt-mocked.spec.ts` | 12 | Contrat de binding, résultat de test identifié, reçu de déploiement, conflits et rollback |

Les défauts produit reproduits puis revérifiés sur le build corrigé sont le
focus Work restauré après rendu, les deux liens Run conservant `systemId`,
l'ouverture du journal par la query canonique et le reçu d'activation conservé
après rafraîchissement du workspace. Pour le journal, le test autorise seulement
l'événement exact de télémétrie `navigation.resolved` relatif à l'alias
`tab=triggers` ; toute autre écriture pendant la lecture fait échouer le test.

Le test de câblage utilise uniquement des graphes simulés. Il recharge des
nœuds sans arêtes, attend la sauvegarde de chaque connexion et positionne la
souris sur le centre actuel du port, avec vérification de l'élément réellement
sous le pointeur. Cela élimine les coordonnées périmées pendant les changements
de disposition et évite de confondre un câble déjà créé par la palette avec une
nouvelle connexion. Les trois arêtes attendues, leurs ports et leur persistance
restent vérifiés, sans événement DOM injecté ni clic forcé.

Journaux sous `/tmp/agentium-recette` :

- `creation-luma-browser.log` : 86 réussis, 6 échoués, 1 interrompu et 18 non joués ; arrêt au sixième échec, 7,9 minutes.
- `creation-remainder-browser.log` : 18 réussis et 1 échec, 45,4 secondes.
- `creation-fixes-browser.log` : 3 réussis et 4 échecs, 1,3 minute.
- `creation-last-four-browser.log` : 3 réussis et 1 échec, 1,1 minute.
- `creation-drag-final-browser.log` : les deux scénarios de câblage FR/EN réussis, 50,6 secondes.

Exécution sur `http://127.0.0.1:4322` avec `/usr/bin/chromium` et
`playwright.mocked.config.ts`. Les API sont intégralement simulées ; aucun
jeu de données Luma réel n'est importé, modifié ou supprimé. Ces succès ne
remplacent pas le test 71, le second corpus réel ni une validation des fournisseurs.

### Accessibilité et finition

Les fichiers navigateur 24 et 72 couvrent **45 tests distincts**, tous réussis
après correction, sans test ignoré ni échec attendu. Work, Connexions,
Applications et le wizard ont chacun passé les 12 combinaisons FR/EN,
clair/sombre et 1440/456/320 px, avec mouvement réduit : **48 combinaisons**,
aucune violation axe détectée et aucun débordement dans les éléments contrôlés.
Les trois anciens marqueurs d'échec attendu ont été retirés.

Le tableau des applications conserve ses en-têtes associés, ses libellés
traduits et ses actions sur petit écran. Le champ de recherche reste dans le
cadre : à 320 px, ses bornes sont 70–306 px dans les quatre combinaisons de
langue et thème. Les parcours clavier vérifient le focus de navigation, les
citations, le lecteur de source et le retour par Échap. La préférence de
mouvement réduit fige le canvas de connexion.

La [preuve détaillée](uiux-recette-2026-10-21/accessibility-evidence.json)
conserve les résultats et les contrôles axe incomplets (`aria-prohibited-attr`,
`aria-valid-attr-value`, `color-contrast`), qui demandent une revue manuelle.
Cette couverture ne valide pas une séance réelle à 200 % de zoom, un lecteur
d'écran ou le panel humain.

Les trois groupes navigateur totalisent **203 scénarios locaux distincts
réussis**. Il s'agit d'une campagne ciblée, sur plusieurs passages, et non
d'une exécution de tout le catalogue Playwright. Les empreintes des fichiers
source et tests livrés figurent dans [source-files.sha256](uiux-recette-2026-10-21/source-files.sha256).

## Recette restant distincte

Le test 71 crée puis supprime un workspace et refuse explicitement
`agentium.papai.ai`. Il n'est pas exécuté sur le domaine fourni. Le second
corpus de bout en bout reste à jouer sur une pile dédiée avec les audiences
requises. Les comptes fournis ne remplacent pas les participants du panel.

Restent aussi à mesurer les seuils du panel et du premier regard du lot 9,
la lecture par technologie d'assistance et les interactions réelles avec les
fournisseurs. La matrice source détaillée des 58 stories demeure nécessaire
pour certifier leur couverture exhaustive.

Les preuves techniques de cette session sont sous `/tmp/agentium-recette`.
Les [résultats de production sans contenu métier](uiux-recette-2026-10-21/production-evidence.json)
sont également conservés dans le dépôt. Les fichiers temporaires contenant
les identifiants et jetons ont été supprimés après les lectures.
Les rapports ne contiennent aucun mot de passe, jeton ou contenu de dossier.
