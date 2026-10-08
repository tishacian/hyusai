# Lot 5a — Dérive statistique des variables

L’onglet Suivi conserve le PSI et ajoute un test KS pour les variables numériques
et un test χ² d’homogénéité pour les variables catégorielles. Il affiche la
statistique, la p-valeur ajustée, les effectifs et la raison d’une mesure absente.
La significativité n’est pas une mesure de perte métier et ne déclenche aucun
entraînement ni changement du modèle servi.

## Référence et fenêtre

Le harness tabulaire enregistre `metrics.monitoring_reference` après le partage
train/test : au plus 400 lignes tirées uniformément sans remise dans `X_train`,
avec la graine de l’entraînement, sur les 32 premières variables utilisées.
Les nombres sont conservés comme observations réelles ; les catégories sont
comptées par empreinte SHA-256 de leur valeur complète. Les textes eux-mêmes ne
sont pas ajoutés à cette référence. Le test n’utilise jamais les milieux des
classes d’un histogramme comme s’il s’agissait d’observations réelles.

La fenêtre de surveillance contient les 400 derniers appels de la version
effectivement servie (`served_id`). Un appel peut être adressé à une autre carte
de la lignée : sa mesure appartient à la version qui a répondu. Le calcul des
badges réserve cette limite à chaque version, pour qu’un modèle très sollicité
ne fasse pas disparaître les observations d’un modèle plus calme.

Les tests utilisent les 400 premières valeurs journalisées de cette fenêtre,
dans l’ordre des appels les plus récents. Le journal conserve au plus 64 lignes
par appel : ces mesures décrivent cet échantillon, pas l’intégralité des grands
batchs. Les valeurs manquantes et les nombres non finis ne participent pas aux
tests. Le parcours feedback → dataset reste commun à la lignée.

## Interprétation

Chaque côté doit compter au moins 20 valeurs utilisables. Le χ² exige au moins
deux catégories et des effectifs attendus d’au moins 5 dans chaque case ; au-delà
de 100 catégories, il est indisponible. Une nouvelle catégorie participe au test
si ces conditions sont satisfaites. Aucun regroupement silencieux des catégories
rares n’est effectué.

Les p-valeurs sont corrigées par Holm entre les variables testables d’un rapport.
Une p-valeur ajustée inférieure à 0,05 signale une vigilance, et inférieure à 0,01
une alerte. Les badges retiennent le plus fort signal parmi PSI et tests, tandis
que les barres PSI restent colorées selon le PSI seul. Les alertes statistiques
sont exploratoires : les observations corrélées ou un trafic non représentatif
limitent leur interprétation.

Les modèles antérieurs sans référence affichent `reference_unavailable` pour les
nouveaux tests et gardent le PSI disponible. Un nouvel entraînement produit la
référence. Le jeu de test est exclu et l’artefact servi reste inchangé.

## Contrat et livraison

`GET /ml-models/{id}/monitoring` ajoute `window.model_id` et `served_version`.
Chaque `data_drift.features[]` conserve `name`, `kind`, `value` et `status`, puis
ajoute `psi_status` et `test` : méthode, statistique, p-valeur brute et ajustée,
effectifs, statut et motif d’indisponibilité. Les anciennes réponses restent
lisibles par le frontend.

Aucune migration ou nouvelle dépendance : SciPy est déjà présent. Les imports
scientifiques restent locaux aux fonctions de calcul. Backend, worker et
frontend sont à reconstruire lors de la livraison depuis le dépôt de référence.

La recette couvre les populations identiques et décalées, nouvelles catégories,
catégories rares, faibles effectifs, valeurs non finies, correction de Holm,
fenêtres isolées par version, conservation des anciens modèles et un fit réel
vérifiant que toutes les références appartiennent au train.

Qualification locale : 45 tests de monitoring et statistiques, 62 tests API,
3 contrôles d’empreinte d’import, 114 tests frontend ciblés et 5 parcours
Playwright passent. `ngc`, i18n, UI chrome et liens de navigation passent.
`build:prod` est exécuté une seule fois et réussit, avec les avertissements
Angular connus. Les parcours navigateur couvrent aussi une réponse tardive
qui ne doit pas remplacer les résultats d’une autre version.
