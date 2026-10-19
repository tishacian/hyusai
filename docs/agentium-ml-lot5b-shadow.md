# Lot 5b — Scoring fantôme du challenger

Le scoring fantôme compare une version tabulaire effectivement servie au
meilleur candidat compatible et appelable selon le score primaire du registre.
Il est désactivé par défaut et ne modifie
jamais les prédictions retournées, le champion, le compteur d'usage du challenger
ou le journal des appels servis.

## Activation et périmètre

`POST /ml-models/{model_id}/shadow` accepte :

```json
{"enabled": true, "sample_percent": 10, "timeout_s": 15}
```

Le taux est un entier de 1 à 100, le délai de 1 à 60 secondes. L'autorisation
requiert les droits M1 de configuration shadow, accordés notamment au
contributeur et au relecteur ; un viewer peut lire mais pas activer cette
charge. La réponse de lecture fournit l'autorité effective `can_configure`.

La configuration appartient à une version précise dans
`params_json.mlops.shadow`. Elle n'est pas héritée lors d'une promotion.
Le mécanisme concerne uniquement les modèles tabulaires de classification et
de régression prêts à servir. Le challenger doit avoir la même cible, les
mêmes classes en classification et des entrées de mêmes types présentes dans
la requête servie. Une incompatibilité est un résultat ignoré avec un code explicite.

### Sélection opérationnelle du candidat

Le classement conserve la métrique primaire du champion et sa direction ; la
version la plus récente départage les scores égaux. Les candidats sont limités
à la même lignée et au même workspace, prêts et non champions. Pour le shadow,
les versions incompatibles, non appelables selon leur contrat de lecture ou
dépassant 256 MiB sont écartées avant tout téléchargement ou chargement.
La première version admissible est retenue. L'alias `@challenger` du registre
reste le classement historique par score : il n'est pas réécrit par le shadow.

La section Monitoring explique cette distinction et liste les versions mieux
classées écartées avec leur motif. Le bloc API `shadow.selection` expose
`policy: best_callable_compatible` et `excluded: [{id, version, reason}]`.
La sélection est également conservée dans la prédiction et l'intention de
calcul. Readiness, activation, staging et comparaison partagent cette règle.
Sans candidat admissible, l'activation est refusée avec un motif explicite ;
un shadow déjà activé ignore l'appel en conservant ce motif. Un échec du
candidat sélectionné ne déclenche pas de second calcul avec une autre version.

Cette présélection ne certifie pas les octets du modèle : le worker garde les
vérifications d'intégrité, de confiance et d'environnement avant toute lecture.

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

Le subprocess reçoit l'ancre `metrics_json.artifact` du registre autorisé. Il
contrôle l'inventaire total avant téléchargement, borne chaque copie en flux,
puis applique le contrat commun de lecture (SHA-256, versions et types skops)
avant de charger MLflow. Le plafond shadow de 256 MiB reste applicable.
L'ancre participe aussi à l'identité des deux modèles : les intentions
historiques créées sans elle sont annulées avec `ML_SHADOW_MODEL_CHANGED`, sans
reconstitution de confiance ni modification des réponses primaires. Les
prochains appels créent de nouvelles intentions avec le contrat courant.

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
Le feedback identifie chaque échantillon retenu et n'est jamais étendu aux
autres lignes du lot. Une métrique non disponible reste `null`.

Les durées de prédiction, de chargement du challenger et du traitement complet
sont distinguées. Le calcul fantôme porte sur au plus 64 lignes, même si
l'appel primaire contient davantage de lignes : les durées par appel ne sont
donc pas un benchmark à volume égal. Aucune durée n'est convertie en coût USD.

## Qualification

- 76 tests ciblés service/API/monitoring/protection des jobs/imports passent,
  dont une concurrence réelle entre deux livraisons et le refus d’écriture
  par un producteur dont le bail a été repris.
- 117 tests de non-régression du service de prédiction et de l’API Models passent.
- Deux tests réels passent : chargement MLflow et scoring du challenger dans
  un subprocess sans modification de la réponse primaire ; interruption d'un
  appel C natif au délai maximal.
- 117 tests frontend ciblés, 7 parcours navigateur FR/EN, compilation Angular
  et contrôles i18n passent. Le build production unique de cette branche passe.
- Aucun changement de dépendance ni migration. Backend et worker doivent être
  reconstruits ensemble ; le beat doit enregistrer `agentium.ml_shadow_recover`
  et le worker tabulaire `agentium.ml_shadow`.

### Vérification de la sélection — 19 octobre 2026

- 110 tests backend passent : shadow service/API, classement des familles et
  sous-processus MLflow réel. Après ajout du contrôle de la taille dans
  l'inventaire, les 54 tests shadow service/API passent à nouveau.
- 28 tests frontend ciblés et i18n passent ; 12 parcours navigateur passent,
  dont l'explication d'une ancienne version exclue sur mobile FR et desktop EN.
- Le scénario de régression conserve un ancien candidat mieux noté mais
  illisible et sélectionne le candidat appelable moins bien noté. Champion,
  scores d'entraînement, classement registry et réponse primaire sont inchangés.
- Déployer API, frontend et tous les workers qui peuvent journaliser les
  prédictions (CPU/DataOps selon le routage). Le worker de calcul shadow doit
  garder le même contrat de lecture. Aucun nouveau drapeau ni migration.
- Après déploiement : vérifier `shadow.challenger` et les exclusions, activer
  explicitement un échantillonnage borné, générer un appel, attendre le job puis
  vérifier la paire et la réponse primaire. Ne pas réutiliser une ancienne
  intention pour prouver la nouvelle sélection.
