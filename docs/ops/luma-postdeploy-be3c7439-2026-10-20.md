# Luma — recette en service de be3c7439

Cette recette du 20 octobre 2026 reprend après le déploiement de
`be3c7439920903a55b61beeef1067a9b85361e4a`. Les Runs de prévision, d'enquête et
de planning attestent cette révision dans leurs preuves d'exécution.
L'opérateur confirme Alembic `141_event_execution_principal`, sans changement
de drapeau. Aucune installation Luma ni publication de Flow n'est rejouée.

## Ce qui fonctionne dans le produit déployé

| Parcours | Preuve |
| --- | --- |
| Prévision Work | Run `13998de3-88d1-4e77-8fe8-51bc26fd674e` terminé ; graphique avec 42 observations et 28 prévisions |
| Préparation visuelle | Aperçu du dataset PostgreSQL v7 : 23 lignes, neuf colonnes ; SQL compilé visible dans son dialogue |
| Délégations | Les consentements du webhook et du planning sont enregistrés sur la v10 sans HTTP 500 |
| Planning | Run `3d9cd35d-1f24-414c-897e-6a9cf2b05052` terminé : PostgreSQL → préparation → scoring v5, 23 lignes |
| Livraison signée | Webhook temporaire accepté et répétition dédupliquée ; son exécution est détournée vers une ancienne attente humaine, voir ci-dessous |
| Judge | Appel effectué, mais réponse explicitement tronquée ; aucune qualité validée |

Les tests navigateur utilisent les assets et API du site déployé au travers
d'un relais HTTPS local vérifiant le certificat serveur. Aucune réponse n'est
substituée. Ce relais ne qualifie pas la diffusion SSE en temps réel.

## Prévision et continuité de lecture

Depuis **Work → Réclamations → Charge et capacité → Actualiser la prévision**,
le Run termine en environ 19,7 secondes. Le modèle produit
`a67139ad-9de1-4f69-8899-b9dca093f146`, puis l'assemblage SQL publie
**Luma — Charge passée et prévisionnelle v1**,
`7f5350c4-3346-437a-bf53-aa3ef46aae36`.

L'API de série renvoie 70 lignes sur 70, sans troncature. L'interface distingue
l'observé, la prévision et l'intervalle à 80 %, et affiche la version, l'heure
de production et l'accès aux valeurs. L'historique couvre le 28 août au
8 octobre ; la prévision couvre le 9 octobre au 5 novembre. Il s'agit de
données de démonstration synthétiques.

Un retour sur cette page après navigation ou rechargement affiche néanmoins
« Pas encore démarré » et une série vide. Le résultat existe ; le lecteur ne
retrouve pas l'exécution précédente. Ce défaut de continuité est distinct du
calcul de prévision, maintenant qualifié. Une lecture ne doit pas lancer
automatiquement une nouvelle exécution pour retrouver ce résultat.

## Aperçu sans modification du Flow

Dans le plan accessible, sélectionner **Préparer le dataset et les contrôles
SAV**, puis **Ouvrir l'atelier**. Le choix temporaire
**Luma — Faits SAV PostgreSQL v7**,
`336aed57-8637-42bc-9d81-ab4f820f68f6`, donne l'aperçu final des 23 dossiers.
La provenance du Run reste visible.

Le panneau SQL mesure 1 040 × 720 pixels sur un écran de 1 440 × 1 000 ;
l'éditeur occupe sa hauteur et les en-têtes du tableau restent derrière.
Échap ferme le SQL. La conversion en nœud SQL reste désactivée avec cette
source temporaire. Après fermeture de l'atelier, le brouillon et la
publication sont strictement identiques à leurs snapshots initiaux.

## Judge : refus maintenant explicite

L'enquête `87d57af2-1a45-417f-a54d-e4d0d12b85e2`, sur RC-1043, reste en revue
humaine. L'invocation `62be0aed-0bea-4966-8447-06299f8ec469` renvoie :

- `status=failed`, `quality_status=unassessed`, `disposition=review` ;
- `reason=JUDGE_OUTPUT_TRUNCATED`, transmis depuis la raison de fin fournisseur ;
- zéro question validée sur cinq ;
- 8 706 tokens d'entrée et 8 192 de sortie, soit 16 898 ;
- 0,0928025 USD au tarif déclaré, et non un montant de facture.

Il n'y a pas de diagnostic de citation sur ce refus : la limite fournisseur
est atteinte avant validation. Les compteurs ne séparent pas le raisonnement
du texte final ; ils ne prouvent donc pas que les citations seraient la cause.
Le plafond n'est pas augmenté et aucune relance supplémentaire n'est effectuée
pour obtenir artificiellement un succès. Aucune décision humaine n'est prise.

## Événements : qualification bornée

Les consentements lient les deux sources permanentes à la publication v10.
Le secret du webhook permanent n'étant pas récupérable, aucune rotation n'est
effectuée. Un webhook temporaire indépendant permet de vérifier la signature
et la déduplication, sans toucher au Flow.

La première livraison et sa répétition aboutissent au même événement
`88d5483f-7f64-49d3-8fbf-82b8c3c1a566`. Le moteur le met toutefois en attente
sur le Run historique `ebb99328-f345-4650-8cd6-5ddd0e465e21`. Aucune approbation
ni reprise de cette attente humaine n'est effectuée. La signature et la
déduplication sont qualifiées, pas le lancement d'une nouvelle enquête par ce
webhook.

Le planning est testé à 13 h 52, Europe/Paris. Le Run porte un principal
délégué lié à la v10, avec `initiated_by_user_id=null`, et termine la file de
23 dossiers avec le champion v5. Le planning retrouve ensuite
`0 8 * * 1-5`, Europe/Paris, désactivé et sans prochain tick actif.
Le webhook temporaire est supprimé après sa mise en pause ; une nouvelle
livraison signée est refusée par HTTP 404. Le System revient en `dry_run`.

Le routage actuel peut sélectionner une attente humaine sans corrélation
explicite. Ce comportement ne permet pas d'isoler des réclamations distinctes.
Une correction générique doit exiger une corrélation exacte pour alimenter
une attente ; les nouveaux événements suivent autrement le lancement normal,
avec les contrôles de publication et de délégation.
La [recette événementielle détaillée](luma-events-qualification-be3c7439-2026-10-20.md)
conserve les identifiants, les états finaux et les limites de cette qualification.

## Versions et conservation

- Flow publié v10 : `b8eb64d3-e417-41bf-898a-7b1ad232d64a`.
- Trois bindings Work : cette même version.
- Brouillon Flow r37, dont le nœud utilisateur isolé `flow.mv95zi21.1`.
- Brouillon Work r11 ; release `a82202e4-6116-4267-9bc3-e14923684ba7`.
- Champion SLA v5 ; challenger v6, shadow 10 % et délai 30 secondes.

La lecture du suivi ML conserve deux comparaisons terminées, trois anciens
dépassements du délai de 15 secondes et aucune paire labellisée. Aucun gain
de précision n'est démontré par ces deux comparaisons et aucune promotion
n'est effectuée.

## Corrections produit issues de cette recette

La livraison qui accompagne ce rapport corrige les écarts constatés, sans
ajout de configuration propre à Luma :

- **Relecture Work** : une action à entrée fixe retrouve en lecture seule son
  dernier Run autorisé, pour le même utilisateur, workspace, application,
  release, page, composant, binding, version de Flow et entrée publiée.
  Les échecs et exécutions en cours restent visibles. Aucun POST, aucune
  nouvelle exécution et aucune navigation après succès ne sont rejoués lors
  de cette relecture. Les formulaires à saisie variable restent hors de ce
  mécanisme.
- **Routage des événements** : seule une corrélation explicite, exacte et
  unique peut alimenter une attente existante. La mémoire anonyme historique
  ne devient plus le contexte d'un nouveau dossier. Le schéma d'entrée, la
  publication et l'autorité de la cible sont contrôlés avant écriture.
  Aucun événement ne vaut approbation ou reprise d'une décision humaine.
- **Génération Judge** : l'appel utilise le réglage de raisonnement déjà
  disponible pour les modèles GPT-5 et transports compatibles, avec une
  consigne de réponse concise. Les paramètres effectifs sont tracés et
  participent à l'identité de l'évaluation. Les budgets et la validation des
  citations restent inchangés. Cette correction doit encore faire l'objet
  d'une enquête en service ; elle ne prouve pas à elle seule une réponse valide.
  La confiance calibrée exige également le même protocole et les mêmes
  paramètres ; les anciens profils sans cette preuve restent consultables
  mais ne fournissent pas de confiance au nouveau protocole.
- **Lecture du contrôle qualité** : l'état de l'évaluation est distingué de
  la fin de l'appel technique. Un refus affiche sa raison connue et une
  action utile, sans répéter cinq fois le même message ni afficher une
  explication technique anglaise dans le parcours français. La grille des
  questions reste consultable.

Les captures de cette section fonctionnelle ne doivent pas être confondues :
la prévision et l'atelier sont qualifiés sur le frontend **déployé** de
`be3c7439` ; la reprise au rechargement et les nouveaux messages Judge relèvent
de la **livraison suivante**.

La nouvelle carte Judge est aussi contrôlée avec le build local contre la
sortie réelle de l'enquête `87d57af2…` : motif de troncature, progression
« Évaluation interrompue », cinq questions repliées et absence de répétition
du texte backend anglais. La préparation native `data_prep_v1` retrouve son
libellé dans la progression, au même titre que la transformation SQL.

## Vérifications de la livraison

- Événements : 103 tests de routage, mémoire, contrats, déduplication et
  gouvernance.
- Judge, vision et calibration : 81 tests ; budgets, compteurs, citations et
  compatibilité des profils conservés.
- Relecture Work : 29 tests exécutés sur SQLite et PostgreSQL 16, ainsi que
  52 tests Work/datasets existants.
- Configuration composée Luma : neuf tests, dont cohérence du budget Judge
  et conservation du brouillon.
- Interfaces : tests unitaires et parcours navigateur FR/EN, bureau/mobile,
  sombre/clair, clavier et axe. Les scénarios vérifient notamment le retour
  sur la page sans nouveau POST, les sorties masquées, les réponses tardives,
  le changement de workspace et l'obligation de recharger une release changée.

Les contrôles de langue et de chrome passent. La compilation de production
est vérifiée sur les sources finales ; les avertissements de budget initial,
CSS Chat/Work/Studio et CommonJS dagre restent non bloquants. La relecture
indépendante a aussi vérifié le ciblage d'une ancienne publication et les
courses entre relecture, nouvelle action et sortie de Work.

## Reprise après cette livraison

Déployer le commit qui contient ce rapport sur l'API, le frontend, les
workers CPU et les processus de contrôle des événements ; conserver la
cohérence de révision des workers DataOps, `ml-ts`, du beat et du runner de
connecteurs. Aucune migration ni nouveau drapeau n'est requis.

1. Revenir sur **Charge et capacité** avec le compte ayant lancé la prévision.
   Le dernier résultat doit apparaître sans cliquer sur l'action. Vérifier
   aussi son maintien après rechargement, et l'absence de nouvel appel métier.
2. Ouvrir le contrôle qualité de l'enquête ci-dessus ; le refus pour réponse
   tronquée doit être immédiatement compréhensible.
3. Lancer une nouvelle enquête gouvernée. Vérifier les paramètres de
   génération effectifs, les compteurs et le résultat métier du Judge.
   Conserver le refus si la réponse reste invalide ; ne pas le convertir en
   réussite pour la présentation.
4. Qualifier une nouvelle réclamation signée, distincte des anciennes
   attentes humaines, avec la v10 et une délégation valide. Vérifier signature,
   déduplication, nouveau Run et identité d'exécution.
5. Vérifier les brouillons r37/r11, les bindings v10, le champion v5 et le
   shadow 10 % / 30 secondes. L'activation durable des sources doit conserver
   l'horaire ouvré prévu, sans cron fréquent de recette.

Les preuves et captures restent hors dépôt dans
`/workspace/scratch/luma-postdeploy-be3c7439/`. Aucun secret d'authentification
ni secret de webhook n'est conservé dans ce rapport.
