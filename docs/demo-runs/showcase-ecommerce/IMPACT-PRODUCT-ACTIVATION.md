# Assembler la vue SAV avec les fonctionnalités produit

Cette configuration utilise exclusivement le
[parcours produit de personnalisation d’Impact](../../impact-configurable-blocks.md).
Les noms et hypothèses Luma sont des données saisies dans la vue du workspace,
sans insertion conditionnelle dans le code de l’interface.

L’[activation native du 7 octobre 2026](IMPACT-NATIVE-QA-2026-10-07.md) a suivi ce
parcours et ajouté les graphiques standard en exécutions. La vue SAV est
enregistrée comme vue par défaut ; ne pas la recréer si elle est déjà présente.

## Prérequis de livraison

Déployer le commit qui introduit les blocs configurables via le processus VM
opérateur existant. La livraison précédente `0a4503e9` affichait encore une carte
globale et ne connaît ni le nouveau périmètre de vue ni les endpoints génériques.
Ne pas enregistrer cette configuration avec l’ancienne interface ou rejouer
l’installation de la business app. Il n’y a pas de nouvelle migration.

Le déploiement et la synchronisation des miroirs ne configurent pas la vue :
l’assemblage ci-dessous est une action utilisateur dans le produit. Il ne
change ni le Flow publié, ni la release Work, ni le plan de composition.

## Configuration dans Showcase

Avec un compte propriétaire ou administrateur, choisir **Agentium Showcase**,
puis **Impact → Personnaliser** :

1. Nommer une nouvelle vue **SAV — activité et scénario**, puis **Créer une vue**.
2. Choisir **Luma Maison — Réclamations** comme System de la vue. Vérifier son
   identité `f3ea83de-df89-45ec-8a85-c00d676b2713` si plusieurs noms se ressemblent.
3. Conserver **7 jours**. Le dénominateur initial de la nouvelle vue est
   **Exécutions**, avec un bloc d’activité déjà présent.
4. Nommer le bloc **Luma — activité SAV**. Conserver les indicateurs d’état,
   d’appels, de coûts et de temps technique.
5. Ajouter **Scénario financier** dans le catalogue Comprendre et le nommer
   **SAV — hypothèses de capacité**. Renseigner les conventions validées :

   | Paramètre produit | Valeur déclarée |
   | --- | --- |
   | Devise | EUR |
   | Traitement manuel | 8 min / dossier |
   | Travail humain assisté | 2 min / dossier |
   | Coût horaire chargé | 40 €/h |
   | Budget complet / unité | 0,50 €/dossier |
   | Unité métier | Dossier SAV |
   | Source et contexte | Conventions de démonstration validées par l’utilisateur ; aucun temps humain ni gain réalisé mesuré. Budget comprenant appels, infrastructure, licence et intégration amortie. |

   Le **volume mensuel** est facultatif. Le laisser vide en l’absence d’un
   volume métier déclaré. La valeur illustrative antérieure de 1 000 dossiers
   ne constitue pas une mesure des essais ni une hypothèse confirmée de volume.

6. Placer le bloc d’activité en premier et le scénario en second. Cocher
   **Ouvrir cette vue par défaut dans le workspace**, puis **Enregistrer la vue**.
7. Recharger Impact : le nom de vue, le périmètre Luma, l’ordre des deux blocs
   et les hypothèses doivent être conservés.

Pour conserver un registre ou un cadran supplémentaire, les ajouter avec le
catalogue normal. Leurs graphiques de résultats utilisent le même périmètre
Luma, la même période et les exécutions terminées ; le graphique du bloc
d’activité inclut également les tentatives échouées. Les autres vues du
portefeuille restent disponibles dans le sélecteur.

## Vérification attendue

La [campagne native](ACTIVITY-ROI-2026-10-07.md) conserve ses preuves. Sur les
7 jours de sa réalisation, le précédent rapport a montré 23 tentatives,
15 terminées, 8 échouées et 231 appels, en incluant les 3 exécutions de
présentation. Ces valeurs doivent être vérifiées sur le nouvel endpoint,
pas copiées dans une configuration de graphique. Elles évoluent avec les
nouvelles exécutions et avec la fenêtre glissante.

Le scénario renseigné calcule **3,50 €/dossier** et **700 % de ROI projeté**, avec
un seuil de **0,75 minute**. Sans volume mensuel, aucun gain mensuel n’est
affiché. Le résultat du benchmark humain reste inconnu. Une exécution technique
ou une projection déclarée ne peut pas remplir les mesures du benchmark.

La QA locale du parcours produit utilise volontairement un autre System,
d’autres hypothèses et une autre devise pour vérifier l’absence de dépendance
à Luma. Après déploiement, effectuer une vérification native en lecture seule,
puis ce seul assemblage UI ; il n’est pas nécessaire de relancer la campagne
ou de produire de nouveaux reçus pour voir son activité.
