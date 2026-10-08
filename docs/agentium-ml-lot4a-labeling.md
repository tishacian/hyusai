# Lot 4a — Étiquetage LLM de datasets

La Skill `llm_label_dataset_v1` ajoute une colonne de classes à un dataset
existant, avec le modèle du workspace. Elle publie une nouvelle version
`source="generated"` seulement quand toutes les lignes sont étiquetées. Les
colonnes originales et leur ordre sont conservés. Les labels restent marqués
**non revus** : la validation humaine et la comparaison avec un modèle distillé
relèvent du lot 4b.

## Utilisation dans un Flow

Ajouter **Label Dataset with LLM** depuis la catégorie Data. Brancher un dataset
en entrée ou définir `sources`, par exemple `[{"dataset_id":"…"}]`. La référence
épinglée est prioritaire. Le formulaire de paramètres est disponible en FR/EN.

Paramètres obligatoires :

- `text_columns` : noms des colonnes texte à envoyer au modèle ; les autres
  colonnes restent dans la sortie sans être envoyées au fournisseur ;
- `labels` : liste des classes autorisées ;
- `instruction` : règle d’étiquetage ;
- `input_cost_per_million` et `output_cost_per_million` : tarifs estimatifs USD
  par million de tokens du modèle utilisé, renseignés explicitement.

Les options appartiennent au graphe publié, dans le bloc interne `_label`.
Les données d’entrée ne peuvent pas remplacer ses consignes, ses tarifs ou ses
limites. Le workspace vient du contexte serveur. La résolution du modèle et le
contrôle de politique passent par le même chemin que `workspace_llm_v1`.

| Paramètre | Défaut | Plafond |
|---|---:|---:|
| `batch_size` | 10 lignes | 50 |
| `max_rows` | 500 lignes | 5 000 |
| `max_tokens` | 100 000 | 2 000 000 |
| `max_output_tokens` | 2 048 par appel | 8 192 |
| `max_cost_usd` | 1 USD estimé | 100 USD estimés |
| `timeout_s` | 300 s par invocation | 900 s |

`label_column` vaut `label` par défaut et doit être une nouvelle colonne.
`output_name` nomme la nouvelle table. Un dataset dépassant le plafond de lignes
est refusé, sans échantillonnage silencieux. La source est limitée à 32 MiB, et
chaque prompt à 32 000 octets. Réduire `batch_size` pour des textes longs.

OpenAI et Azure OpenAI utilisent une sortie JSON Schema stricte ; Ollama reçoit
le schéma dans `format`. Les autres fournisseurs sont refusés avant tout appel.
La validation locale impose les classes, les identifiants de ligne et un
résultat par ligne, même si le fournisseur accepte une réponse incorrecte.
Les réponses Markdown, les valeurs non finies et les identifiants dupliqués
ne produisent aucun dataset prêt à entraîner.

## Budget, interruption et reprise

Un `WorkspaceJob` conserve la source figée par ID, version et empreinte SHA-256,
la configuration, les compteurs cumulés et les références des lots terminés.
La sortie est réservée dans la même transaction que le job. Aucun schéma de
base de données n’est ajouté.

Avant chaque appel, le service réserve des tokens et leur coût estimé avec une
borne conservative calculée sur la taille du prompt et du schéma, plus la
limite de sortie. Les compteurs effectivement rapportés par le fournisseur
ajustent cette réservation. Sans compteurs complets, la réservation reste
consommée et `unknown_attempts` augmente. Une réponse invalide reste comptée.
Ces estimations n’alimentent jamais un coût fournisseur « mesuré ».

Le modèle est figé pour le job. Les fallbacks et les retries SDK sont désactivés
sur ce chemin, pour éviter des appels supplémentaires ou un tarif différent.
Chaque appel est limité à 45 secondes, dans la durée restante de l’invocation.
La politique, l’accès au workspace et la disponibilité des datasets sont
revérifiés entre les lots et avant publication.

Les lots validés sont écrits dans l’ObjectStore, sous le préfixe du dataset,
avec leur empreinte. Le curseur n’avance qu’après sauvegarde. Un verrou par
workspace empêche deux producteurs simultanés : verrou de session PostgreSQL,
ou verrou de fichier pour une base SQLite locale. Une coupure du producteur
libère le verrou ; elle ne remet pas les compteurs à zéro.

Pour reprendre, renseigner `resume_job_id` avec l’identifiant présent dans
l’erreur du Flow ou le journal des jobs. Conserver les colonnes, classes,
consigne, modèle et tarifs ; la source peut être omise, car son ID est conservé.
Les budgets de tokens et de coût peuvent être **augmentés explicitement**,
jamais réduits. La durée est un plafond par invocation ; les dépenses restent
cumulées sur le job. Les lots terminés ne sont pas renvoyés au LLM. Une réponse
perdue avant sauvegarde peut avoir été facturée : sa réservation demeure et sa
nouvelle tentative consomme un nouveau budget.

Réutiliser un job terminé renvoie le même dataset, avec zéro appel nouveau.
Les APIs génériques de création et de transition des jobs ne peuvent pas
fabriquer ce type de job ni modifier son état. L’annulation du Flow interrompt
le traitement ; la suppression d’un dataset pendant un appel est respectée.

## Traçabilité et livraison

Le résultat de Skill contient l’enveloppe dataset, `job_id` et `labeling`.
La lignée publique du dataset contient la source/version, les colonnes envoyées,
les classes, l’empreinte de consigne, le modèle demandé et les modèles retournés,
les tarifs, les compteurs et le statut `unreviewed`. Elle ne contient ni clé
fournisseur ni texte complet des prompts.

La preuve d’usage canonique reste celle du moteur d’invocation, avec ses cas
complet, partiel ou indisponible. Une reprise sans appel déclare explicitement
zéro token pour la nouvelle invocation ; elle ne rejoue pas l’usage historique.

La livraison reconstruit backend, worker et frontend, sans nouvelle dépendance
ni migration. Après déploiement depuis le dépôt de référence, exécuter
`catalog-check`, puis `catalog-apply` pour publier cette nouvelle Skill si requis.
La validation fournisseur réelle relève de la recette avec les credentials du
workspace ; les tests de développement simulent le transport et n’engagent
aucun appel facturé.
