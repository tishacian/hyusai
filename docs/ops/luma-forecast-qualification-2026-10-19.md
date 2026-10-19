# Luma — qualification de la prévision de charge, 19 octobre 2026

La prévision classique v2 est entraînée et répond sur le déploiement
`718c99bf7e9e07fb689ff0bcd4a1ffd90fca2ece`. Elle remplace la référence Chronos
legacy dans le Flow publié v6, sans nouveau système ni modification du champion
SLA. **L'appel Work reste bloqué par la matérialisation Delta des timestamps** :
le correctif générique ci-dessous doit être déployé puis le parcours relancé
avant d'annoncer « Charge et capacité » comme rétabli.

## Modèle et données vérifiés

| Élément | Valeur |
| --- | --- |
| Modèle | Luma — Charge SAV · classique |
| ID | `7668e105-62d0-45f3-9e28-15c684bd07fa` |
| Slug / version | `luma-charge-sav-classique` / **2** |
| Famille / algorithme | `forecasting` / Ridge, récursif |
| Dataset | `1268f620-0608-4a56-b095-0143e6e213e4`, version 1 |
| Historique | 420 jours synthétiques, du 15/08/2025 au 08/10/2026 |
| Cible | `claim_count`, fréquence quotidienne |
| Décalages | 1, 2, 7, 14, 28 et 56 jours |
| Entraînement | 14,005 s ; état `ready`, `serving.callable=true` |
| Promotion | Aucune ; cette version doit être **épinglée** |

Le modèle est autonome : aucune covariable future ni donnée client ne doit
être fournie pour prévoir. Le champ `campaign_active` du dataset n'est pas
utilisé par ce contrat.

**L'ancrage reste le 8 octobre.** Les 28 prévisions couvrent le **9 octobre au
5 novembre 2026**. Il faut afficher cet ancrage dans « Charge et capacité » ;
« les 28 prochains jours » serait trompeur à la date de cette qualification.
Le dataset n'a pas été rallongé artificiellement pour déplacer les dates.

## Backtests chronologiques

Trois fenêtres de 28 jours, soit 84 points hors entraînement, sont conservées
dans la fiche du modèle. Aucun remplissage de date manquante.

| Mesure | Classique v2 | Naïf saisonnier, période 7 |
| --- | ---: | ---: |
| Erreur absolue moyenne, dossiers/jour | 2,1888 | 3,9762 |
| MASE | 0,5162 | 0,9383 |
| Couverture observée de l'intervalle nominal 80 % | 87,5 % | 66,1 % |
| Largeur moyenne d'intervalle | 7,7640 | 12,0000 |

L'erreur absolue moyenne du classique est inférieure d'environ **45 %** à celle
du naïf sur ces mêmes fenêtres. Ce sont des mesures sur données synthétiques,
pas une performance commerciale ni une économie observée. La couverture de
87,5 % ne garantit pas une couverture future équivalente.

## Appel réel qualifié et contrat de raccordement

`POST /api/v1/ml-models/7668e105-62d0-45f3-9e28-15c684bd07fa/forecast` :

```json
{
  "inputs": [],
  "version": 2,
  "params": {"horizon": 28, "interval_level": 0.8, "explain": true}
}
```

Réponse **200**, modèle et version servis conformes, 28 lignes finies avec
`lower_bound <= pred <= upper_bound`. L'explication linéaire comprend 28 étapes
et les contributions des retards à la pointe de charge. L'appel est conservé
sous `4941f2c8-85c0-46ff-a4ac-e32879d65665`.

Paramètres du nœud générique `ml_forecast_v1`, `forecast.predict` :

```json
{
  "model_id": "7668e105-62d0-45f3-9e28-15c684bd07fa",
  "model_slug": "luma-charge-sav-classique",
  "pinned_version": 2,
  "horizon": 28,
  "interval_level": 0.8,
  "output_name": "Luma — Prévision de charge SAV"
}
```

Les colonnes produites restent `series`, `timestamp`, `pred`, `lower_bound`,
`upper_bound`. La transformation `forecast.timeline` peut donc conserver
l'assemblage existant des 42 derniers jours d'historique et de la prévision.
Le lien de la page Work doit pointer vers le nouveau modèle et annoncer v2.
L'ancien champion de la lignée classique reste v1 : omettre `pinned_version`
pourrait encore appeler cet artefact legacy. Aucune promotion implicite n'a
été effectuée.

Cette qualification couvre l'entraînement et l'appel réel de prévision. La
recette Work suivante a révélé un défaut que l'appel de nombres seul ne couvre
pas.

## Échec Work identifié et correctif générique

Le Run `8cd37d8b-7ab7-4fb6-be56-6c96c61b1841`, démarré depuis le composant
`forecast_refresh` de la page `charge`, utilise bien le modèle classique v2 dans
le Flow publié v6 `7abaae46-9bc6-42e1-bace-169398cf9e1c`. Il échoue à
`forecast.predict` avec `ML_FORECAST_FAILED: ValueError: DATASET_SCHEMA_MISMATCH`.

La prévision calcule ses valeurs, mais pandas produit des timestamps UTC en
nanosecondes. Le writer partagé les conservait dans les footers Parquet, alors
que la conversion Delta native déclarait `timestamp`, en microsecondes. Le
contrôle d'intégrité refuse donc à raison la différence avec `timestamp_nanos`.
Le défaut a été reproduit localement avec les 28 réponses de l'appel qualifié.

Le correctif dans `dataops_storage.delta_schema` normalise tous les timestamps
Delta vers UTC/microsecondes avant écriture. Le cast sûr conserve les instants
et refuse les valeurs à nanosecondes qui nécessiteraient une troncature. Aucun
contrôle de schéma n'est désactivé et aucune exception Luma n'est ajoutée.

La régression utilise le vrai `forecast_into`, le stockage local Delta ou
Parquet, le profil et le journal d'inférence ; seule la réponse numérique du
modèle est substituée. Avant correctif, Parquet passe et Delta reproduit
exactement le refus. Après correctif, les deux chemins conservent les 28 dates,
valeurs, étapes et le modèle servi v2 ; la redélivrance ne crée pas de doublon.
Douze variantes d'unité/fuseau vérifient également l'accord footer/commit et
la conservation des instants ; un cas non représentable est refusé avant tout
commit Delta. La suite multipart complète et les tests du worker passent :
**43 tests**, ainsi que Ruff sur les trois fichiers Python modifiés.

Pour terminer la recette :

1. Déployer le correctif sur les producteurs utilisant le writer partagé,
   notamment le worker `ml-ts`, ainsi que les images API, CPU et DataOps
   correspondantes. Aucune migration ni nouveau drapeau.
2. Relancer **Actualiser la prévision** depuis Work. Conserver l'ancien Run
   échoué ; le nouveau Run doit produire son propre dataset immuable.
3. Vérifier `forecast.predict` puis `forecast.timeline` réussis, les 28 lignes
   prévues et les 42 lignes historiques, puis le graphique et sa bande dans
   « Charge et capacité ». Les dates restent 09/10–05/11.

Ce correctif ne nécessite ni nouvel entraînement ni promotion du modèle.

## Refus conservé : naïf saisonnier autonome

Le modèle de comparaison `71e07ece-4fe9-4f04-bb96-cf4f60e2764c`, version 2,
s'entraîne en 14,248 s et expose ses backtests. Son appel autonome est cependant
refusé par `ML_ARTIFACT_UNTRUSTED_TYPES` sur la révision en service : le profil
de lecture ne contient ni `numpy.mean` ni
`skforecast.recursive._forecaster_equivalent_date.ForecasterEquivalentDate`.

Le benchmark naïf intégré au classique a bien été calculé et reste disponible.
Ce refus n'empêche donc pas le raccordement du classique qualifié. Aucune
exception de confiance n'a été appliquée en production.

Le correctif générique du dépôt ajoute seulement ces deux noms au profil
`forecast-skops-v1`. Un test reproduit d'abord le refus, puis sauvegarde et
recharge réellement le naïf saisonnier avec skforecast 0.25.0/skops ; les 28
prévisions restent identiques. Les contrôles vérifient aussi que `numpy.load`
reste refusé en forecasting et que `numpy.mean` reste refusé à l'import externe.
Les tests ciblés du naïf, des cinq fréquences calendaires et de l'interdiction
d'élargir la confiance passent : **7 tests**, ainsi que Ruff sur les fichiers
modifiés. Ce correctif n'est pas encore en service ; le classique déjà qualifié
n'en dépend pas. Après un déploiement ultérieur sur API et worker `ml-ts`,
l'appel du naïf v2 devra être requalifié explicitement avant d'être annoncé
comme disponible.

Les requêtes, réponses et vérifications détaillées sont conservées hors dépôt
dans `/workspace/scratch/luma-four-lots-2026-10-19/forecast/` ; aucun jeton
d'authentification n'est enregistré avec ces preuves.
