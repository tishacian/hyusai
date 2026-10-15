# Actifs gouvernés et promesses de service

**Production, 14 octobre 2026 :** selon le compte rendu opérateur,
`SERVICE_CONTRACTS_ENABLED=true` est chargé globalement sur `0e401afc`.
Les listes de `default` et Showcase répondent avec zéro contrat. Les routes
de calibration sont accessibles, mais aucun corpus ni cycle de livraison
n'est qualifié par ces contrôles. Voir le
[bilan de production](dataops-production-2026-10-14.md).

Une livraison est une preuve publiée, distincte de l'exécution d'un Run. Le
socle ajoute sept tables via `126_service_contracts`, après
`125_retrieval_bench_runs`. Il ne crée aucun job Celery ni canal de notification.
Les raccordements au moteur publié et au tick existant utilisent les services
ci-dessous ; les helpers font `flush`, jamais `commit`.

## Versions, preuves et droits

`register_asset(db, workspace_id, kind, logical_key, manifest, parents=(), run_id=None)`
enregistre un `AssetVersion` pour `dataset`, `model`, `document_set` ou `reference`.
Le manifeste JSON canonique est écrit une seule fois sous une clé adressée par
son SHA-256 dans l'ObjectStore du workspace. Les objets natifs restent à leur
emplacement ; aucun octet de dataset ou modèle n'est recopié. Le manifeste décrit :

- `objects: [{key, sha256, size_bytes}]`, dans `workspaces/<workspace_id>/` ;
- `native_refs: [{kind, id}]`, enrichies de la version et d'une empreinte de
  l'identité native ;
- `output`, données à vérifier contre le schéma de livraison ;
- `evidence`, extraits citables avec `id`, `text`, `sha256`, `kind`, ou un
  `locator: {object_key, json_pointer?}` vers un objet déclaré.

`asset_ref(asset)` produit `{asset_id, workspace_id, kind, version, digest}`.
`resolve_asset_ref` refuse une autre portée, une autre version, une modification
du manifeste, des parents non autorisés à l'enregistrement ou des octets natifs
altérés. La vérification des fichiers se fait en flux. Les références natives
doivent rester disponibles et correspondre à leur identité enregistrée.

Les qualifications sont des lignes distinctes, immuables et numérotées. Le
callback serveur `record_qualification(..., status, policy, evidence, confidence)`
lie les empreintes de l'actif, de la politique et des preuves. Les statuts sont
`qualified`, `rejected`, `review_required`, `needs_requalification`. Seule la
dernière ligne peut autoriser une nouvelle publication ; une requalification
ne réécrit ni l'historique ni les reçus déjà émis. La qualification n'est pas
une API qui accepte un verdict fourni par un navigateur.

`authorize_judge_evidence(evidence, ctx)` ouvre une session séparée et vérifie
l'acteur, le Run, les références immuables, les accès natifs et les extraits
effectivement enregistrés. Un hash envoyé par l'appelant ne suffit pas. Les
preuves inline doivent être présentes dans l'entrée persistée du Run. Sans
utilisateur humain, un Run ne peut citer qu'un actif qu'il a produit ou une
référence exacte déjà déclarée dans son entrée. Les images ne sont pas acceptées
par ce résolveur textuel.

## Contrat et calendrier

`create_contract(db, workspace_id, system_id, owner_user_id, definition,
created_by=..., logical_key='default')` crée une nouvelle révision. Le System
appartient au workspace, le créateur est administrateur et le responsable est
un utilisateur actif membre. `publish_contract` fige la révision ; une correction
crée une nouvelle version. Les termes comprennent :

- `timezone`, `cadence` (`daily` ou `weekly`), `days` (lundi = 0),
  `deadline` (`HH:MM`), `starts_on`, `ends_on` facultatif ;
- `budget`: `max_attempts`, `max_cost`, `max_tokens`, `max_seconds` ;
- `input_payload` JSON canonique, maximum 64 Ko, fourni au moteur publié ;
- `inputs` (0–16) : clé de payload, type et clé logique d’actif, fraîcheur,
  qualification requise, politique facultative et représentation `asset_ref`
  ou `native_id`. La fenêtre fige références/qualifications ; les reprises,
  la constitution du candidat et les livraisons revalident ce snapshot.
  `require_qualified=false` reste facultatif lors d’une reprise inchangée,
  sans autoriser une qualification modifiée ou « à requalifier » ;
- `output_schema` JSON Schema sans référence externe ;
- `output_policy`: destination `work` ou `work:<slug>`, revue humaine exigée par
  défaut, seuil de confiance facultatif, empreinte de politique de qualification
  facultative.

La fenêtre quotidienne commence à minuit local. La fenêtre hebdomadaire couvre
les sept jours terminant au jour choisi (un seul `days`). Les débuts et fins sont
des instants UTC, avec une longueur réelle de 23 ou 25 heures lors d'un changement
d'heure. Une échéance inexistante au printemps avance à la première minute
valide ; une heure répétée en automne prend sa première occurrence.

`tick(db, now, workspace_id=None, limit=1000)` matérialise les périodes absentes,
y compris celles sans Run, sans en soumettre un. Une contrainte unique couvre
workspace, System, service logique et début de période, indépendamment de la
révision du contrat. Une nouvelle révision ne réécrit pas une fenêtre existante.

## Tentatives et publication

`claim_window` réserve les budgets et attribue un token, une échéance de bail
et un compteur `fence` croissant. `renew_lease` ne ressuscite pas un bail expiré.
`complete_attempt` exige ce token et ce compteur ; un ancien worker ne peut plus
modifier la fenêtre après reprise. Les budgets sont cumulatifs entre tentatives.
Les réservations ne sont pas remboursées ; un dépassement réellement mesuré est
enregistré et bloque la livraison, plutôt que d'être plafonné artificiellement.
Un coût, un nombre de tokens ou une durée non mesuré reste `NULL` dans la
tentative ; les valeurs omises ne deviennent jamais zéro. La réservation reste
consommée, y compris après un timeout. Réserver le budget maximal dès la première
tentative empêche donc une relance non mesurée de dépenser deux fois ce budget.
La fenêtre expose séparément `reserved_cost`, `measured_cost` et `cost_coverage`
(`unavailable`, `partial`, `measured`), ainsi que leurs équivalents tokens/durée.
`cost_used` reste l'engagement conservateur cumulé, pas une facture mesurée.

Une tentative réussie place un candidat en `awaiting_review`. Son compteur reste
valide jusqu'à l'échéance de la fenêtre pour la revue et la publication. Une erreur
donne `failed`. `watchdog` distingue `SERVICE_RUN_MISSING`,
`SERVICE_LEASE_EXPIRED`, `SERVICE_REVIEW_OVERDUE` et `SERVICE_DELIVERY_MISSED`.
Les incidents sont durables et dédupliqués, visibles uniquement par le responsable
dans le workspace ; ils ne déclenchent aucun email ou message externe.

La revue transmet obligatoirement `expected_fence`, `expected_asset_digest` et
`expected_qualification_digest` (valeur `null` si absente lors de l'inspection).
Une modification des faits inspectés produit `SERVICE_REVIEW_STALE` avant toute
qualification ou décision ; l'opérateur doit rouvrir le candidat à jour.

`review_delivery(..., reviewer_user_id, accept, note, qualify_candidate=False)`
requiert un vrai `User` administrateur et écrit une `Decision` canonique avec ses
champs humains. Elle lie l'actif, la qualification, le contrat, la fenêtre, le
compteur et la destination par une empreinte. L'option explicite
`qualify_candidate=true`, avec note obligatoire, permet une qualification humaine
sans LLM ; elle ne remplace pas une qualification `rejected` et ne contourne pas
une politique de qualification imposée par le contrat.

Un refus humain reste possible pour un candidat non qualifié, rejeté ou incomplet.
Il exige les droits et les trois faits inspectés, écrit une Decision rejetée et
l’incident attribué, sans créer de qualification positive ni de reçu.

Un `technical_status` présent doit valoir `completed`. Une `coverage` présente
doit indiquer un nombre attendu positif, tous les éléments traités et zéro échec.
Ces contrôles ne sont pas contournables par un avis humain. Si ces champs sont
absents sur un candidat historique, la note humaine peut le qualifier, mais la
preuve indique `coverage_measured=false` : aucune couverture n'est inventée.

`automatic_delivery_decision` exige une politique autorisant ce chemin, un seuil
numérique explicite et une confiance mesurée qui l'atteint. Une confiance inconnue
ne produit jamais une approbation automatique.

`publish_delivery(..., decision_id, fence, lease_token)` vérifie à nouveau les
octets, la qualification courante, le schéma et la Decision liée. L'insertion du
reçu et le passage à `delivered` sont dans la même transaction. La clé unique
fenêtre + empreinte d'actif + destination rend la répétition idempotente. Un
changement d'actif, de qualification ou de contrat invalide la revue précédente.

## API et Work

Le routeur `/service-contracts` est actif si `SERVICE_CONTRACTS_ENABLED=true`
ou si `workspace.settings.features.service_contracts=true`. Toutes les routes
exigent un utilisateur actif membre ; les mutations exigent un administrateur.

| Route | Usage |
|---|---|
| `GET /service-contracts` | Révisions des contrats, pagination offset/limit |
| `POST /service-contracts` | Nouvelle révision |
| `POST /service-contracts/{id}/publish` | Publication du contrat |
| `GET /service-contracts/windows` | Fenêtres, filtre `contract_id` facultatif |
| `GET /service-contracts/windows/{id}/candidate` | Résultat, preuves et qualification pour revue |
| `POST /service-contracts/windows/{id}/review` | `{accept,note,qualify_candidate?}` |
| `POST /service-contracts/windows/{id}/publish` | `{decision_id,fence}` ; token gardé côté serveur |
| `GET /service-contracts/receipts` | Historique paginé ; indisponibilité explicite après invalidation |
| `GET /service-contracts/receipts/{id}` | Reçu encore consommable et autorisé |
| `GET /service-contracts/incidents` | Incidents du responsable connecté |
| `GET /service-contracts/assets` | Sources autorisées paginées, métadonnées et qualification courante |
| `POST /service-contracts/assets` | Enregistrement administrateur d’un manifeste ; types calibration/vision réservés |
| `POST /service-contracts/assets/requalify` | Invalidation administrateur et propagation aux descendants |
| `GET /service-contracts/windows/{id}/objects/{index}` | Octets autorisés, liés au digest et au fence inspectés |
| `GET /service-contracts/receipts/{id}/download` | Archive des objets réellement vérifiés |

Le reçu expose des métadonnées, jamais une nouvelle permission de lire un dataset
ni une URL de l'ObjectStore. Les accès aux collections et aux Runs sont revérifiés.
Le composant Work conserve son garde d'accès au dataset publié ; le reçu ne le
remplace pas. Une qualification invalidée ferme la consommation du reçu tout en
gardant la preuve historique de sa publication.

## Vérification et limites

Les tests exécutent les transitions contre SQLite isolé, une concurrence réelle
de claims avec deux sessions, la migration aller-retour, les changements d'heure,
les violations de portée/empreinte, les budgets et la revue humaine. Ils ne
constituent pas un déploiement VM ni une qualification de charge PostgreSQL.
Le test `test_dataops_published_pipeline.py` exerce aussi le vrai ingress publié,
le DAG, préparation/scoring natifs, revue et reçu téléchargeable. La migration et
l’installation suivent le processus habituel de release ; aucun environnement
n’est déclaré déployé par ces tests.
