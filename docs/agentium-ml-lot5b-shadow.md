# Lot 5b — Scoring fantôme du challenger

Le scoring fantôme compare une version tabulaire effectivement servie au
challenger choisi par le registre. Il est désactivé par défaut et ne modifie
jamais les prédictions retournées, le champion, le compteur d'usage du challenger
ou le journal des appels servis.

## Activation et périmètre

`POST /ml-models/{model_id}/shadow` accepte :

```json
{"enabled": true, "sample_percent": 10, "timeout_s": 15}
```

Le taux est un entier de 1 à 100, le délai de 1 à 60 secondes. L'autorisation
requiert un contributeur, administrateur ou propriétaire du workspace, ou un
administrateur plateforme. Un viewer ou reviewer peut lire les résultats mais
ne peut pas activer cette charge. La réponse de lecture fournit `can_configure`.

La configuration appartient à une version précise dans
`params_json.mlops.shadow`. Elle n'est pas héritée lors d'une promotion.
Le mécanisme concerne uniquement les modèles tabulaires de classification et
de régression prêts à servir. Le challenger doit avoir la même cible, les
mêmes classes en classification et des entrées présentes dans la requête
servie. Une incompatibilité est un résultat ignoré avec un code explicite.

## Exécution et limites

Le journal primaire et l'intention `WorkspaceJob(kind="ml_shadow")` sont
enregistrés dans une transaction. Un savepoint isole les erreurs de préparation
du shadow. Aucun accès au broker ni chargement du challenger ne bloque la
réponse primaire.

Le beat de récupération tourne toutes les 30 secondes, reprend les intentions
en attente depuis au moins 30 secondes et publie seulement leur identifiant.
Une panne du broker laisse le travail récupérable. Un bail atomique de
90 secondes évite les exécutions concurrentes ; une perte de worker autorise
au maximum deux tentatives. Les erreurs de calcul et timeouts sont terminaux.

Les identités du modèle servi et du challenger sont figées dans l'intention.
Une promotion entre la réponse et le calcul ne change pas la paire. La
suppression, la désactivation ou une modification de l'identité d'artefact
empêche la publication d'un résultat devenu invalide.

Les limites sont de 64 lignes retenues par appel, 512 KiB de payload conservé,
256 MiB d'artefact et 100 intentions actives par workspace. La sélection des
appels est déterministe. Les autres cas sont ignorés avec leur motif. Le calcul
et le téléchargement passent dans un subprocess soumis au délai choisi,
avec mémoire virtuelle limitée à 4 GiB et threads numériques limités à deux.
Sous Linux, la disparition du superviseur tue également son enfant.

Les jobs sont gérés uniquement par le service ; les routes génériques de
création et transition de jobs refusent ce type.

## Lecture des résultats

`GET /ml-models/{model_id}/monitoring` contient un bloc `shadow`, même sans
appel servi. La fenêtre porte sur les 400 derniers appels de cette version.
Les compteurs couvrent les travaux réussis, en attente, échoués et ignorés ;
les dix derniers états montrent leurs versions et erreurs.

Les métriques comparatives concernent uniquement la paire actuelle :
accord en classification, différence absolue moyenne en régression. Avec du
feedback, accuracy et MAE utilisent les mêmes vérités terrain des deux côtés.
Le feedback actuel porte sur la première ligne d'un appel : il n'est jamais
étendu aux autres lignes du lot. Une métrique non disponible reste `null`.

Les durées de prédiction, de chargement du challenger et du traitement complet
sont distinguées. Le calcul fantôme porte sur au plus 64 lignes, même si
l'appel primaire contient davantage de lignes : les durées par appel ne sont
donc pas un benchmark à volume égal. Aucune durée n'est convertie en coût USD.

## Qualification

- 74 tests ciblés service/API/monitoring/protection des jobs/imports passent.
- Deux tests réels passent : chargement MLflow et scoring du challenger dans
  un subprocess sans modification de la réponse primaire ; interruption d'un
  appel C natif au délai maximal.
- Aucun changement de dépendance ni migration. Backend et worker doivent être
  reconstruits ensemble ; le beat doit enregistrer `agentium.ml_shadow_recover`
  et le worker tabulaire `agentium.ml_shadow`.

