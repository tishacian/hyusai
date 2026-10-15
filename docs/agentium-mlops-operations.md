# M3 — Exploitation des modèles Agentium

Implémentation candidate depuis `demo/agentic` (`47e289da`), sans activation ni déploiement. La fiche `agentium-mlops-papai-parity-plan.md` reste la référence ; ce document décrit les contrats réellement ajoutés à Agentium. Il ne contient aucune action corrective papAI.

## Endpoints et portée

`/models/endpoints` expose les modèles possédant une clé active ou une Skill publiée : version servie, métadonnées des clés, dernier audit, badge, trafic et coût. Le lien du registre n’apparaît que lorsque `ML_OPERATIONS_ENABLED=true`. Une boîte d’alertes apparaît aussi dans les deux vues Hypervisor sous ce même drapeau.

L’API `/api/v1/ml-operations` expose `features`, `endpoints`, `alerts`, `channels` et `deliveries`. Les données sont filtrées avant pagination : membre actif du workspace, droits de lecture du System pour les membres, modèles sans System limités au créateur et aux administrateurs. Le périmètre plateforme exige un administrateur de plateforme. Les administrateurs du workspace gèrent ses canaux et les accusés de lecture. Un accès à un modèle n’accorde pas la lecture des destinations ou des livraisons du workspace.

Aucune clé de prédiction, aucun hachage de clé et aucune valeur secrète ne sort dans cette API. La page reste disponible en lecture si la création d’alertes est arrêtée. Elle ne démarre pas de modèle et ne déclenche aucune prédiction.

## Comptabilité et précision

`record_inference(db, requested=…, served=…, caller=…, row_count=…, duration_ms=…, error_code=…, measured_cost_usd=…, cpu_seconds=…, tariff_cost_usd=…, event_id=…)` rejoint la transaction d’appel. `event_id`, lorsqu’il est fourni, est idempotent dans le workspace. Les erreurs sont réduites à un code technique sûr. Les entrées et sorties du modèle ne sont jamais recopiées dans `ml_inference_usage`.

Les échecs complets doivent avoir zéro ligne prédite. Un temps mural n’est pas une mesure CPU attribuable. Le coût mesuré, le tarif et le coût inconnu restent séparés : aucune mesure manquante n’est remplacée par zéro ni par le tarif de la Skill. Le coût pour 1 000 lignes indique la couverture des appels effectivement mesurés. Le tarif pour 1 000 lignes a son propre dénominateur : seules les lignes couvertes par un tarif USD explicite entrent dans ce calcul. Une publication sans tarif reste inconnue. Les anciens Skills ML recevaient un zéro synthétique (`per_prediction`, USD, `unit_price=0`) : ce zéro reste inconnu tant qu’un responsable ne confirme pas explicitement `pricing.confirmed=true` dans la configuration catalogue. Un zéro confirmé est un véritable tarif nul ; un tarif positif reste calculable sans ce marqueur. Aucun journal historique n’est réécrit. Les unités reconnues sont `per_prediction`, `per_1000_predictions` et `per_call`. La preuve du tarif est une liste blanche (source catalogue, empreinte, monnaie, unité et quantité), jamais le contenu brut du catalogue. Un CPU sans mesure attribuable retourne `null`, même après agrégation.

Le moteur crée un collecteur éphémère par invocation et fige le tarif à son démarrage. Les wrappers appellent `ml_inference_cost.record_skill_inference(ctx, row_count=…)` après production des lignes. Le moteur calcule ensuite `SkillInvocation.cost` et conserve une preuve `state=calculated`, distincte d’un coût fournisseur mesuré. Ni les entrées ni les sorties JSON d’une Skill ne peuvent déclarer ce coût. Le champ historique `cost_measured=true` englobe un calcul étayé ; l’état de la preuve permet de le distinguer. Le tarif USD apparaît aussi dans les agrégats d’endpoint sans devenir un coût mesuré.

La tâche `agentium.ml_operations_tick` agrège le journal dans `ml_usage_rollups`, par endpoint, version servie, catégorie d’appelant et intervalle de cinq minutes. Elle verrouille les modèles dans un ordre stable, traite un lot borné et marque les événements dans la même transaction que l’agrégat. Un rejeu ne recompte pas les mêmes appels.

Les latences sont des distributions à bornes fixes, fusionnables. Les p50 et p95 sont **des bornes supérieures estimées**, affichées avec `≤`, et jamais des moyennes de percentiles. Les bornes vont de 1 ms à 5 000 000 ms ; au-delà, un compteur `latency_overflow` est fourni et un percentile non bornable reste nul. Une latence absente n’est pas zéro. Les fenêtres 24 h et 7 jours se terminent au dernier intervalle de cinq minutes clos ; l’API retourne `from`, `until` et `as_of`. Le retard d’agrégation n’est pas présenté comme du temps réel.

Le journal brut est purgé après `ML_USAGE_RETENTION_DAYS` seulement lorsque son agrégation est enregistrée. Les agrégats restent indépendants de la conservation des prédictions et du feedback de M1/M2. La migration 137 refuse un downgrade destructif si l’une de ses tables contient des données.

## Alertes et reprise

`monitor_transition(db, model=…, badge=…, source_id=…)` persiste le changement de badge et l’alerte dans la transaction du résultat de surveillance. Une première observation stable ne déclenche pas de bruit. Le retour à l’état stable après une alerte est conservé. Les échecs des Systems de surveillance existants et les clés proches de leur expiration sont également recherchés par la tâche périodique. Les refus de quota passent par `emit_alert(..., event_type="quota_reached", …)` dans la transaction du refus persisté.

La boîte Hypervisor est une table durable, pas un flux en mémoire. Une même source ne peut être réémise après un redémarrage. Le contrôle de fréquence est sérialisé par modèle : un message par état et type d’événement dans une fenêtre configurée. Les événements supprimés par cette limitation restent dédupliqués. Alerte, livraison et audit partagent la transaction.

Chaque canal activé produit une ligne d’outbox. Le worker revendique une livraison avec un bail SQL, réessaie avec un délai croissant et s’arrête après un nombre maximal d’essais. Une panne après réception mais avant l’enregistrement du reçu peut produire un doublon : la garantie est **au moins une fois**, avec un identifiant de livraison stable pour la déduplication du destinataire. Un processus dont le bail a été remplacé ne peut pas acquitter celui du nouveau propriétaire.

Les appels réseau restent sur le worker Celery général existant, avec une tâche bornée ; le worker court `control` n’exécute ni SMTP ni HTTP. Aucun nouveau broker, Redis, moteur de DAG ou activité par prédiction n’est ajouté. Le scheduler programme la tâche chaque minute lorsqu’un drapeau M3 est actif. Le drapeau d’alertes arrêté suspend aussi les livraisons externes, sans effacer l’outbox.

## Canaux et secrets

- **E-mail** : configuration SMTP existante, destinataire explicite du workspace, envoi via `services/email.py`.
- **Webhook** : deux références `secret://workspace/…`, une pour l’URL et une pour une clé HMAC d’au moins 32 octets. Les valeurs sont résolues au dernier moment par le registre de secrets. Ni URL secrète ni clé ne sont enregistrées dans le canal ou dans le journal d’alerte.
- **Hypervisor** : boîte interne toujours conservée dès que la génération d’alertes est activée ; elle ne nécessite pas de canal externe.

Avant chaque envoi, les droits actuels du créateur du canal et l’activation du workspace sont revérifiés. Les requêtes webhook exigent HTTPS, validation TLS, résolution DNS épinglée et mode réseau `enforce`, même si les connecteurs historiques sont en mode `report`. Les redirections sont refusées ; la réponse et le délai sont bornés. Les exceptions de transport ne sont pas copiées dans les audits.

Signature : `X-Agentium-Signature: sha256=<hex HMAC-SHA256>` sur les octets `X-Agentium-Timestamp + "." + corps JSON exact`. Le destinataire doit vérifier la signature, une tolérance d’horloge explicite et dédupliquer `X-Agentium-Delivery` (également `id` du JSON).

## Réglages d’intégration

| Réglage | Défaut |
|---|---:|
| `ML_OPERATIONS_ENABLED` | `false` |
| `ML_ALERTS_ENABLED` | `false` |
| `ML_USAGE_ROLLUP_BATCH_SIZE` | 10 000 |
| `ML_USAGE_RETENTION_DAYS` | 30 |
| `ML_ALERT_THROTTLE_SECONDS` | 3 600 |
| `ML_ALERT_MAX_ATTEMPTS` | 5 |
| `ML_ALERT_BATCH_SIZE` | 10 |
| `ML_ALERT_KEY_EXPIRY_DAYS` | 7 |
| `ML_ALERT_CHANNELS_MAX` | 20 |

Les hooks sont raccordés aux services de prédiction, de prévision, de scoring local et en flux, ainsi qu’au nouveau snapshot du moniteur M2. Le journal de succès et l’usage sont écrits ensemble. Le refus ou l’échec de serving est enregistré après rollback, dans une transaction indépendante à attente SQL bornée ; un échec de télémétrie conserve l’erreur métier initiale. Les refus d’exposition suivent le même chemin pour conserver leur alerte. La migration 137 suit `136_mlops_correctness`.

Les budgets en requêtes et lignes par minute de M1 concernent `/predict` et `/forecast`, conformément à la fiche. Le scoring asynchrone conserve l’admission et les budgets de calcul DataOps ; il ne consomme pas artificiellement le plafond d’un endpoint interactif. Les lignes produites alimentent néanmoins les métriques M3. Pour une invocation native différée, le wrapper ne dispose pas encore du résultat au retour : son coût Skill reste inconnu tant qu’un règlement natif spécifique n’est raccordé. Aucun coût n’est estimé à partir du volume annoncé par l’appelant.

## Validation locale

Les tests M3 couvrent la séparation des scopes, la révocation de droits, les drapeaux, les erreurs sans payload, le coût inconnu, les fenêtres closes, la fusion des distributions, l’idempotence et le rollback, la limitation de fréquence, la reprise des baux, les retries bornés, les envois par transports factices, la signature et les refus SSRF. Aucun e-mail ou webhook réel n’a été envoyé. Les tests de composant et de modèle de vue sont enregistrés dans le runner frontend. Résultats locaux : **37 tests backend ciblés réussis** (31 M3 et 6 de catalogue de surface), **2 267 tests frontend réussis**, contrôles i18n et navigation réussis, TypeScript et unique `build:prod` réussis. Les avertissements de budget et de compilation Angular déjà présents ne sont pas masqués. Le complément de coût et de portée a ensuite passé **64 tests backend** (dont les contrats de coût du moteur et de membrane), **2 271 tests frontend**, dont les **9 tests UI ciblés** d’Endpoints, TypeScript, i18n/navigation et `build:prod`. **5 tests PostgreSQL locaux** sur schémas jetables qualifient le verrouillage/rejeu des agrégats, le rollback atomique des alertes, les baux concurrents, le refus d’un acquittement périmé et le cycle montée/descente de la migration 137 avec refus de suppression non vide. Cela ne constitue pas un rejeu de tout l’historique Alembic ; l’enchaînement 135–137 relève de la branche d’intégration.

La certification SMTP/webhook d’une destination réelle, le comportement sous la charge de production et les tailles d’images restent une recette d’exploitation. Le développement ne les prétend pas acquis et n’active aucun de ces réglages.
