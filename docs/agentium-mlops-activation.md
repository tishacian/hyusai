# Activer une boucle MLOps depuis un System métier

Ce guide décrit les capacités présentes dans le dépôt au 17 octobre 2026. Il
ne constitue pas une attestation de déploiement, d'entraînement ou de mesure.
Le System métier consomme un modèle ; Model Center possède les opérations
techniques de ce modèle. Leur Flow de surveillance apparaît dans **Systems →
Model operations**, sans créer une seconde application métier.

## Périmètre effectivement disponible

| Opération | Tabulaire classification/régression | Forecasting classique | Forecasting deep (Chronos) |
|---|---|---|---|
| Entraîner explicitement une nouvelle version | Oui, runtime requis | Oui, runtime requis | Oui, runtime deep et fondation autorisée requis |
| Prédire et consulter la disponibilité de la version | Oui | Oui | Oui |
| Retours sur des échantillons retenus | Oui, `sample_id` | Utiliser les observations datées | Utiliser les observations datées |
| Comparaison shadow | Oui | Non | Non |
| Mesure sur observations de prévision | Sans objet | Oui | Oui, contrat temporel identique |
| Surveillance planifiée et proposition de réentraînement | Oui | Oui | Non |

Une version `status=ready` signifie que son entraînement s'est terminé. Il faut
également vérifier `serving.callable`, le contrat d'artefact et un appel réel.
Le précontrôle ne charge pas les fichiers ; les empreintes et types sont
revérifiés avant l'inférence. Un ancien artefact sans contrat est conservé et
refusé. Aucun ajout de métadonnées ne le convertit en artefact qualifié.

## Réparer une version incompatible

Si seul l’environnement d’exécution a changé et qu’une référence existe, un
administrateur peut d’abord **requalifier** la version (Réglages ›
Environnement d’exécution ; voir `agentium-mlops-requalification-implementation.md`).
Sinon, ou si la requalification échoue, réentraîner.

Dans Model Center, ouvrir la version puis **Réentraîner**. Le studio reprend
son dataset, sa cible, ses variables, son algorithme, ses réglages et sa spec.
Vérifier le dataset et les choix avant soumission. Une nouvelle version dans
la même lignée laisse le champion existant en place. Évaluer puis promouvoir
reste une décision indépendante.

Les routes ci-dessous sont préfixées par `/api/v1` et utilisent le workspace
courant et les droits de la session :

1. `GET /ml-models/{id}` fournit `model`, `dataset`, `catalog` et `serving`.
2. `POST /ml-models/plan` reçoit exclusivement les champs de plan :
   `dataset_id`, `task`, `target`, `features`, `algo`, `knobs` et `spec`.
   Reprendre `model.params.knobs` pour les réglages. Un HTTP 200 peut contenir
   un `refusal` : vérifier ce champ avant de poursuivre.
3. `POST /ml-models` reprend ces champs et peut ajouter `name`, `description`,
   `test_size` et `cross_validation`. Le nom détermine la lignée par son slug :
   conserver le nom du modèle pour créer une version de cette même lignée.
   Ne pas envoyer le modèle sérialisé entier ni son ancien bloc d'artefact.
4. Attendre le statut final via `GET /ml-models/{new_id}`, puis vérifier la
   disponibilité et appeler la version explicitement, sans suivre le champion.
   Un test sur un challenger ne doit pas être interprété comme une promotion.
5. Comparer métriques, jeu de test et résultats. `POST /ml-models/{id}/champion`
   est une demande de promotion distincte, soumise à la gouvernance du workspace.
   Si elle renvoie une décision, suivre le parcours de revue fourni par l'UI.

La route de plan ne reçoit pas `name`, `test_size` ou `cross_validation`.
L'identifiant de dataset désigne une version ; lire cette version et son
empreinte avant de préparer l'entraînement. La boucle automatique ci-dessous
fige en plus les sources et le test final dans la proposition approuvée.

## Retours et comparaison shadow

Le journal doit avoir retenu les entrées avec consentement. À partir d'un
`prediction_id` réel, `GET /ml-models/{id}/predictions/{prediction_id}` expose
les identifiants des échantillons, sans recopier leurs entrées. Envoyer ensuite
`POST /ml-models/{id}/feedback` avec `{prediction_id, sample_id, label}`.
Le label doit être une issue connue, pas la prédiction elle-même ni une issue
future inventée. Les anciens labels de lots sans index sont exclus.

Activer `POST /ml-models/{id}/shadow` avec, par exemple :

```json
{"enabled": true, "sample_percent": 10, "timeout_s": 15}
```

L'activation requiert une version tabulaire appelable et, s'il est déjà connu,
un challenger dont le contrat et le runtime sont lisibles. Une incompatibilité
d'artefact ou de runtime est expliquée en identifiant le challenger concerné ;
la désactivation reste disponible. Sans challenger, la configuration préalable
est possible mais ne produit aucune comparaison.
Le challenger provient du registre, pas d'un identifiant transmis dans cette
requête. Il doit avoir des entrées, une cible et des classes compatibles. Les
nouveaux appels retenus alimentent le shadow, pas les appels historiques.
Le worker vérifie les artefacts avant de scorer, sans changer la réponse servie.

`GET /ml-models/{id}/monitoring` expose la paire courante, les succès, attentes,
échecs et cas ignorés. Les qualités comparées utilisent les retours de chaque
échantillon au même index dans les deux résultats. Un échantillon hors du
résultat borné, non conservé ou appartenant à un autre workspace ne contribue
pas au score. Une absence de vérité terrain reste une valeur indisponible.
Latence, taux d'accord et qualité observée restent des mesures distinctes.

## Surveillance, proposition et approbation

Pour un tabulaire, un administrateur peut appeler
`POST /ml-models/{id}/monitoring/policy` avec :

```json
{
  "enabled": true,
  "propose_retraining": true,
  "interval_minutes": 60,
  "retraining_data": {
    "mode": "original_plus_feedback",
    "max_feedback_fraction": 0.25,
    "feedback_window_days": null
  }
}
```

Le rythme est de 60, 360 ou 1440 minutes. La configuration crée ou réutilise
le Flow technique canonique du modèle et sa planification. Son lien apparaît
dans Model Center → Monitoring, avec les Systems métier consommateurs.

Chaque exécution conserve un instantané. Une proposition requiert notamment
un badge `alert`, un champion explicite, aucune proposition active pour cette
fenêtre et des sources admissibles. Le mode par défaut conserve le dataset
d'origine et son test final, déduplique les retours, exclut les observations
du test et requiert au moins 40 nouveaux échantillons étiquetés admissibles par
défaut (`ML_RETRAINING_MIN_FEEDBACK_ROWS`). Un ancien modèle sans partition
vérifiable est refusé. L'absence de proposition n'est donc pas un échec du cron.

Le Flow conduit à un gate HITL `approve_model_retraining`. La décision humaine
est liée aux données, paramètres et preuves figés. Après approbation, le worker
crée un challenger ; il ne devient pas champion automatiquement, même si le
champion d'origine a disparu. Comparaison et promotion sont une étape distincte.

Pour une prévision, associer d'abord les observations disponibles par
`POST /ml-models/{id}/monitoring/actuals` avec `{dataset_id, follow_latest:false}`.
Les dates, cibles, séries et covariables doivent correspondre à la spec. Les
prévisions émises après l'instant qu'elles prétendent prédire n'entrent pas
dans la mesure. Une association est possible pour Chronos ; sa planification
de réentraînement n'est pas prise en charge par cette version du produit.

## Prérequis d'exploitation

- Appliquer les migrations M1–M3 (135, 136, 137) avant les processus concernés.
- Déployer ensemble API, worker ML, scheduler et frontend ; réconcilier les
  Skills `ml_monitor_model_v1` et `ml_retrain_model_v1` avant d'activer la politique.
- Vérifier `TABULAR_DATA_ENABLED`, `ML_TRAIN_ENABLED`, `ML_PREDICT_ENABLED`, les
  runtimes spécialisés et les identités persistées des Runs planifiés.
- Le beat doit exécuter `agentium.scheduler_tick`, `agentium.ml_shadow_recover`
  et `agentium.ml_retraining_recovery` ; le worker doit consommer le shadow et
  les entraînements. L'API n'est pas une preuve que le worker fonctionne.
- M3 ajoute les agrégats et alertes avec `ML_OPERATIONS_ENABLED` et
  `ML_ALERTS_ENABLED`, désactivés par défaut. Configurer et tester une destination
  réelle avant d'activer les notifications. Aucune destination n'est créée ici.
- La rétention est une convention séparée (`ML_RETENTION_ENABLED`). Sans
  entrées retenues, ne pas attendre de retours ni de réentraînement depuis ces
  appels. Les coûts absents restent inconnus ; la durée ne devient pas un coût.

## Vérification produit du correctif Shadow

Les tests ciblés couvrent les retours multilignes, corrections de labels,
anciens labels unitaires ou ambigus, consentement, périmètre workspace, résultat
shadow borné, contrat legacy/runtime et désactivation malgré un artefact bloqué.
Les tests d'inférence réelle conservent le chargement MLflow isolé et les refus
du lecteur. La recette navigateur vérifie le motif et la désactivation en
français et anglais. Ces contrôles locaux ne certifient pas les ressources de
la VM ni les résultats métier d'une démonstration.
