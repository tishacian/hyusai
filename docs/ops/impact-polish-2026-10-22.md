# Impact — pilotage par audience, 22 octobre 2026

## Parcours de présentation

Terminer la démonstration sur la décision, après avoir montré le travail du SAV
et la construction de l’application. Les données Luma restent fictives, les
exécutions sont réelles, les remboursements sont simulés et le gain financier
reste une projection explicite.

| Étape | Geste | Bénéfice exprimé pour le client |
| --- | --- | --- |
| **Work — traiter** | Ouvrir Réclamations, les faits PostgreSQL, le document source et une enquête conservée | « Le conseiller dispose des faits et d’une proposition motivée pour traiter son dossier. » |
| **Work — organiser** | Montrer la file de 23 dossiers scorés et Charge et capacité | « Le responsable priorise les dossiers et anticipe la charge de son équipe. » |
| **Builder — application** | Ouvrir l’application publiée Pilotage SAV — équipe puis son éditeur | « Le métier assemble son espace de travail à partir de traitements disponibles et choisit son audience. » |
| **Builder — Flow** | Montrer connecteur, préparation, modèle, recherche documentaire, raisonnement, Judge et accord humain ; ouvrir le résultat conservé d’un nœud | « Le même traitement combine les données et l’IA, avec des contrôles et un résultat vérifiable à chaque étape. » |
| **Impact — SAV / Opérations** | Choisir le périmètre et la période, sélectionner le jour puis ouvrir sa preuve | « Le manager suit ce qui a tourné, ce qui attend et ce qui a échoué. » |
| **Impact — Direction** | Lire résultats, coûts, bases de valeur ; ouvrir la vue SAV et son scénario financier | « La direction peut comparer le service rendu à son budget avec des hypothèses visibles. » |
| **Impact — Conformité** | Examiner bases, provenance, avis ; ouvrir le contrôle d’une enquête | « Les décisions restent justifiables et les réserves sont conservées. » |

La restitution d’une prévision et celle d’une enquête peuvent venir de Runs
différents : sélectionner et nommer le Run consulté. La vue Conformité ne
constitue ni une certification réglementaire ni un verdict Judge automatique.
Les deux nouvelles enquêtes de cette recette ont un Judge **non évalué** et
restent soumises à une décision humaine.

Les preuves en service, leurs identifiants et les volumes avant/après sont dans
[la recette d’activité Luma](luma-impact-activity-2026-10-22.md). Elle a été faite
sur `d03ce83a`, avant le polish de cette livraison.

## Changements produit génériques

- Titres et intentions distincts pour Direction, Opérations et Conformité ; les
  vues personnalisées conservent leur nom et leur assemblage.
- Navigation entre vues à position stable sous le titre. Périmètre, période
  7/30/90 jours et actualisation accessibles directement. Actualiser recharge
  les preuves sans remplacer les paramètres en cours de personnalisation.
- Liens courts vers résultats, bases de valeur et avis. Le nombre d’avis est
  explicitement celui observé parmi les vingt derniers avis du workspace ; il
  n’est pas présenté comme un total exhaustif sur le système et la période.
- Alertes ML compactes : priorité des alertes/échecs, détail à la demande,
  accès à Opérations ML. Le compteur distingue événements chargés et historique
  total. Désactivation et indisponibilité restent distinctes d’une absence
  d’alertes. Le périmètre du résumé est le workspace, car un modèle consommé
  par un Flow peut appartenir à un autre système d’entraînement.
- Activité hiérarchisée : terminées, tentatives, échecs/annulations et attentes.
  Chronologie quotidienne en paliers, preuves par jour, appels et coûts partiels
  visibles. Une tentative ne devient pas un dossier distinct ni un gain humain.
- Scénario financier : gain unitaire mis en avant, résumé des hypothèses toujours
  visible, méthode détaillée repliée. Hypothèses incomplètes, budget nul et volume
  mensuel absent conservent leurs états explicites.
- Objectifs et règles de pilotage dans un volet secondaire. L’objectif reprend
  le système choisi ; les automatisations gardent leur périmètre workspace.
- Présenter respecte l’assemblage Opérations, Conformité et personnalisé. La
  narration Direction optimisée n’est utilisée que pour son assemblage par
  défaut ; retirer ou déplacer un bloc conserve le choix utilisateur.
- En-tête du registre accessible au lecteur d’écran ; enregistrement de la
  personnalisation disponible dans un pied de panneau fixe.

Aucun système, dossier, nom Luma ou hypothèse financière n’est ajouté au code
de l’hyperviseur. Les cartes Activité et Scénario financier restent des blocs
de configuration génériques. La vue SAV existante n’a pas été remplacée.

## Activation et configuration

Dans **Impact → Personnaliser**, choisir le périmètre, ajouter les blocs Activité
et Scénario financier, saisir les hypothèses, organiser les blocs puis enregistrer.
Le choix de vue par défaut est enregistré avec cette configuration du workspace.
Les contrôles de lecture n’écrivent pas automatiquement la configuration.

Dans Showcase, le bloc Activité a été ajouté à la vue Opérations enregistrée et
sa sauvegarde relue. Pour les nouvelles installations, ce bloc fait également
partie de l’assemblage Opérations par défaut. Les vues déjà enregistrées ailleurs
restent inchangées ; leur activation passe par Personnaliser.

Le scénario SAV conserve 8 minutes manuelles, 2 minutes assistées, 40 €/h et
0,50 €/dossier : projection de 3,50 €/dossier et ratio de 700 % selon cette
convention. Le volume mensuel n’est pas renseigné dans la configuration live.
Les captures de tests isolés peuvent utiliser un volume conventionnel pour
tester le rendu ; elles ne constituent pas une mesure ou configuration live.

## Correctif révélé par les essais simultanés

Deux enquêtes simultanées ont tenté de créer la même version de dataset.
L’allocation `max(version) + 1` est désormais protégée par un verrou
transactionnel PostgreSQL par workspace et slug, commun aux imports, uploads,
transformations et réservations. Les autres datasets restent indépendants.
Le verrou est libéré au commit ou rollback ; aucune migration n’est nécessaire.

Le contrôle négatif reproduit la collision de version 19 avec l’ancien code.
Ne pas masquer le Run de recette en échec ni le déclarer réparé rétroactivement.

## Livraison et vérification

Déployer le commit porteur de ce document sur le **frontend**, l’**API** et tous
les **workers / runners qui produisent des datasets**, notamment CPU et DataOps.
Aucun nouveau drapeau ni migration. Les anciens producteurs doivent avoir
terminé avant de qualifier la concurrence, puisqu’ils ne prennent pas le verrou.
Ne pas rejouer l’installation Luma ni modifier ses publications.

Après déploiement :

1. Vérifier la révision servie et celle des producteurs de datasets.
2. Dans Impact, ouvrir les quatre vues, tester période, périmètre, détail ML,
   jour → preuve et Présenter. Vérifier la conservation de la vue SAV et de
   l’absence de volume mensuel.
3. Dans Work et Flow, relire les résultats de la file et de la prévision listés
   dans la recette d’activité. Le brouillon r38 et la publication v10 restent
   inchangés.
4. Qualifier deux traitements concurrents sans approbation de remboursement :
   datasets de versions distinctes, états réellement observés, aucune collision.
   Cette recette en service reste à faire après déploiement ; les tests locaux
   ne la remplacent pas.

Validation locale : **124 tests frontend ciblés, 105 tests backend de régression,
9 tests de concurrence sur PostgreSQL 16 jetable et 19 scénarios navigateur**
réussis. Compilation production, i18n, chrome, liens de navigation et hooks de
conformité vérifiés. Les scénarios navigateur couvrent FR/sombre, EN/clair,
mobile, droits de lecture, brouillon préservé, présentation et preuves. Aucun
débordement à 390, 1280 et 1440 px ; aucune violation Axe dans les parcours
qualifiés. Le mobile conserve du défilement pour consulter les mesures.

Le nouveau frontend a aussi été ouvert localement avec les lectures de l’API
Showcase en service, les écritures métier étant bloquées dans ce relais :
les quatre vues s’ouvrent, le filtre SAV sélectionne réellement Luma, et les
mesures affichées sont **27 tentatives, 11 terminées, 7 échecs, 9 attentes et
180 appels**. La projection conserve son volume mensuel absent. Captures
`12-preview-polished-sav.png` et `13-preview-polished-*.png` dans
`/workspace/scratch/luma-impact-polish-2026-10-22/`. Cet aperçu valide la lecture
des données réelles ; il ne signifie pas que ce frontend a été déployé.
