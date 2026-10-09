# Hugging Face : activation locale et migration ML v1

L'import `ready` garantit le contenu. L'activation garantit que l'adaptateur
peut charger ces fichiers et effectuer une inférence dans son runtime. Les deux
étapes sont distinctes ; le téléchargement reste sur `hub-fetch`.

## Activation

Un administrateur du workspace appelle :

```http
POST /api/v1/huggingface/artifacts/{artifact_id}/activate
Content-Type: application/json

{"usage":"embedding","runtime":"ml"}
```

`usage` accepte `forecasting`, `embedding` et `reranker`. `runtime` choisit `ml`
(queue du worker `ml-deep`) ou `rag` (worker général avec l'option de build
`INSTALL_HF_RAG=1`). Forecasting requiert `ml`. La préparation passe d'abord par
la queue `hub_fetch`, puis le runtime vérifie les SHA-256 et réalise un vrai
chargement/essai. La réponse contient un job `hf_adapter_activate`, consultable
avec `GET /api/v1/huggingface/jobs/{job_id}`. Le résultat expose les versions des
bibliothèques réellement utilisées et `validation="loaded_and_inferred"`.

Le catalogue ML n'offre l'artefact qu'après cette validation, et seulement si les
heartbeats des workers de la queue déclarent un inventaire identique et des
versions compatibles avec le rapport. La sélection se transmet dans
`spec.artifact_id`. Aucun chemin local ni jeton ne traverse ce contrat.

Les adaptateurs actuels acceptent :

| Usage | Contrat local |
|---|---|
| Forecasting | `Chronos2Model`, safetensors simple ou index avec tous ses shards. |
| Embedding | BERT, RoBERTa, XLM-RoBERTa ou DistilBERT ; modules standard Transformer, Pooling et éventuellement Normalize ; safetensors simple ou shards complets. |
| Reranker ONNX | Classifieur standard à un logit, `onnx/model.onnx` autonome, `tokenizer.json`, sortie `[batch, 1]` nommée `logits`, sigmoid. Les exports ONNX avec fichiers de poids externes sont refusés. |
| Reranker torch | Classifieur standard à un logit en safetensors, tokenizer local, worker/API ayant installé le runtime optionnel. |

Les bornes de version de l'adaptateur sont dans
`backend/app/services/huggingface/adapters.py`. Les images conservent les
versions exactes des fichiers de contraintes existants. Un rapport issu d'un
autre jeu de versions ne qualifie pas automatiquement un nouveau worker.

## Migration explicite d'un modèle déjà entraîné

Les modèles v1 non migrés continuent à lire le manifeste historique. Pour
associer un modèle entraîné du lot 6a à un artefact v2 :

1. Importer le même dépôt, au même commit, avec exactement les mêmes fichiers
   que l'inventaire v1. Les fichiers supplémentaires rendent la sélection
   différente et empêchent cette migration.
2. Activer l'artefact avec `runtime="ml"` pour le bon usage.
3. Soumettre la migration du modèle entraîné :

```http
POST /api/v1/huggingface/artifacts/{artifact_id}/migrate-legacy
Content-Type: application/json

{"model_id":"identifiant-du-modele-ML-entraine"}
```

Le job `hf_legacy_migrate` s'exécute sur `ml-deep`, avec le provisionnement v1 et
le cache v2 montés en lecture seule. Il exige un modèle `ready`, vérifie que le
modèle local v1 correspond encore au fingerprint enregistré lors de
l'entraînement, puis compare dépôt, commit et inventaire SHA-256 complet à
l'artefact v2 qualifié. Une divergence ne modifie rien.

La réussite persiste une référence `ml_migration` et sa preuve. **Elle ne
réécrit ni les poids entraînés, ni `params_json`, ni le runtime historique.**
Les prochaines prédictions, y compris celles servies depuis un cache mémoire
ou par lot, exigent désormais l'autorisation de l'artefact associé. Une
révocation rend ces nouvelles exécutions indisponibles ; elle ne provoque pas
un retour implicite au lecteur v1.

La liaison et son état sont consultables avec
`GET /api/v1/huggingface/legacy-models/{model_id}/migration`. Le job peut être
annulé avec `POST /api/v1/huggingface/legacy-migrations/{job_id}/cancel` ; une
annulation avant publication ne crée pas de liaison. Les références v1 des
autres modèles restent fonctionnelles. Retirer le provisionnement v1 exige
d'avoir migré ou retiré tous ses usages, et n'est pas effectué automatiquement.
