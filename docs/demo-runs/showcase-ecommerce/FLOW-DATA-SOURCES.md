# Sources de données dans le Flow Luma

Livraison sur `demo/agentic`, contrôles du 5 octobre 2026.

Le Flow Builder propose un groupe repliable **Sources du workspace** et permet
de rechercher les connecteurs configurés et les collections accessibles. Un
nœud générique `source.connector`, de catégorie Données, référence le connecteur
du workspace. Son cadre reprend celui des collections ; ses actions utilisent
les boutons compacts du chrome, à 28 px. Une configuration enregistrée ne vaut
pas une connexion vérifiée.

## Parcours utilisateur

1. Dans Showcase, ouvrir le Flow du système **Luma Maison — Réclamations**.
2. Sélectionner **PostgreSQL · Luma Maison**. L'inspecteur montre la base, le
   périmètre des tables et les étapes liées. **Ouvrir le connecteur** mène au setup
   canonique existant.
3. Cliquer une table du périmètre ou **Parcourir les tables**. Choisir le schéma
   puis la table ; consulter les colonnes, types et clés primaires.
4. **Aperçu · 25 lignes** effectue une lecture PostgreSQL réelle, bornée et
   horodatée. Les valeurs exactes et les lignes supplémentaires sont signalées.
   Le lecteur vérifie à nouveau l'empreinte de la source. Une erreur conserve
   les références, sans afficher un aperçu de substitution.
5. Une table découverte peut être ajoutée au périmètre du nœud. **Étapes liées**
   ouvre l'inspecteur de l'étape consommatrice ; **Relier une étape** crée une
   vraie liaison de données, enregistrable et annulable dans le Builder.

Le catalogue se vide immédiatement lors d'un changement de workspace. Les
réponses tardives de l'ancien contexte sont ignorées. L'exploration PostgreSQL
conserve les droits administrateur du setup existant. Un nœud référencé reste
visible si sa configuration devient indisponible.

## Contrat et graphe métier

La configuration du nœud contient uniquement `connector_id`, `read_mode` et
les références `{schema, table}`. Elle ne contient aucun hôte, compte de connexion,
mot de passe ou SQL libre. Le nœud émet une référence ; le lecteur de l'étape
consommatrice réalise la lecture dans son workspace. Les autres connecteurs
configurés sont proposés en mode référence, avec accès à leur setup ; ils ne
reçoivent pas un explorateur SQL ou un lecteur universel.

Luma déclare les sept tables `showcase_ecommerce` : `claims`, `orders`,
`customers`, `order_items`, `shipments`, `refunds`, `document_refs`. PostgreSQL
est lié à **Enquêter avec les preuves** et à l'étape d'action, qui relit les
faits après la validation humaine. Les sources effectivement lues et la
référence du nœud apparaissent dans la provenance du snapshot et du reçu.

Les collections autorisées par `workspace.settings.ecommerce_claims` sont
instanciées avec le type existant `source.collection`, puis liées à l'enquête.
Sur le workspace vérifié, il s'agit des règles, des trois dossiers LM-1042 à
LM-1044 et du benchmark : **cinq collections**. Les archives restent exclues
de l'enquête. Le graphe proposé conserve les sept étapes et leurs positions,
et compte **13 nœuds / 13 liaisons**.

Les bindings viennent du graphe figé du Run ; le payload utilisateur et les
modifications ultérieures du System ne peuvent pas les remplacer. Pour les
Flows Luma déclarant ces sources, une dépendance PostgreSQL absente ou
incomplète bloque avant la lecture. Une preuve documentaire hors des
collections liées est refusée avant la recherche, y compris si toutes les
liaisons documentaires ont été supprimées. Les anciens Runs conservent leur
contrat historique.

Une référence live reste distincte d'un dataset importé. La préparation d'un
snapshot DataOps demeure dans l'[explorateur PostgreSQL](POSTGRESQL-EXPLORER.md).
Cette évolution conserve les sources de déclenchement SFTP existantes et ne
déclenche ni entraînement MLOps ni nouvelle mesure de ROI.

## Activation de l'existant par l'opérateur

Déployer backend, worker et frontend du même commit, après synchronisation du
miroir Bitbucket, par le [runbook VM sûr](../../ops/agentium-safe-vm-deployment.md).
Cette livraison n'ajoute ni migration SQL ni dépendance runtime. Conserver le
connecteur `luma_claims_reader` et les documents existants.

L'activation est explicite : aucun remplacement de graphe au démarrage. Le
script utilise les publications et releases natives, dans une transaction.
Il conserve un brouillon limité à la présentation, et refuse un changement
métier non publié ou un draft d'application différent de la release déployée.
Il retire uniquement les quatre valeurs de vue chat inactives que l'ancien
Builder ajoutait par défaut au DAG Luma. La disposition existante est conservée.

Identités observées le 5 octobre ; vérifier qu'elles sont toujours courantes
dans `flow-state` et dans le canal live de l'Experience avant l'activation :

| Objet | Identité observée |
| --- | --- |
| Workspace | `agentium-showcase` |
| Acteur propriétaire | `06a2e190-ae2d-4365-b4f3-9952401f531d` |
| System Luma | `f3ea83de-df89-45ec-8a85-c00d676b2713` |
| SHA du Flow publié v2 | `30465eae80dd3f3ab3a49b44e561151742fc7829b3f6b95778bc87ad50b41c3f` |
| Release Work live | `e400b454-771a-45c2-8b74-14ba92a5314f` |

Préparer et relire le résultat, sans publication :

```bash
docker exec agentium-backend python -m scripts.upgrade_ecommerce_flow_sources \
  --workspace agentium-showcase \
  --actor-user-id 06a2e190-ae2d-4365-b4f3-9952401f531d \
  --system-id f3ea83de-df89-45ec-8a85-c00d676b2713 \
  --expected-flow-sha256 30465eae80dd3f3ab3a49b44e561151742fc7829b3f6b95778bc87ad50b41c3f \
  --expected-release-id e400b454-771a-45c2-8b74-14ba92a5314f \
  --channel live > /tmp/luma-flow-sources-review.json
```

Le résultat comprend `flow_definition`, les ressources, les anciennes identités
et le SHA cible `flow_sha256`. Vérifier les cinq collections, les deux liaisons
PostgreSQL, les positions et les étapes métier conservées. Reprendre exactement
la commande avec **`--apply --expected-target-sha256 <SHA cible relu>`** pour
appliquer. Un changement concurrent de Flow, de brouillon ou de release refuse
l'opération. L'application vérifie d'abord les lectures des trois dossiers,
puis publie une nouvelle version, actualise le binding et crée la release Work
sur le même canal et avec la même audience. Les anciennes versions et releases
restent disponibles pour un retour par les parcours natifs de restauration.

## Point live à résoudre : aperçu 503

Le 5 octobre, le catalogue et les colonnes des sept tables répondent 200 depuis
Agentium. Les aperçus de `claims` et `orders`, même limités à une ligne, répondent
503 `PG_UNAVAILABLE`. Le nouveau Flow n'est pas encore activé sur le site.
Le même lecteur passe les tests PostgreSQL 16.2 locaux ; cela ne prouve pas la
réussite de la lecture sur la VM. Le cloud ne peut pas joindre directement la
base métier et ne dispose pas de l'accès SSH retenu pour le déploiement.

Ce diagnostic en lecture seule, exécuté dans le backend déployé, utilise la
configuration enregistrée et restitue uniquement l'étape, la version serveur,
le code fermé et le SQLSTATE. Il n'affiche ni credentials, ni chaîne de connexion,
ni données métier. Conserver ce résultat pour identifier la cause de la 503 :

```bash
docker exec -i agentium-backend python - <<'PY'
import json
from app.db.base import SessionLocal
from app.models.workspace import Workspace
from app.services.connectors.generic import postgresql_browser as pg

stage = "connection"
server_version = None
with SessionLocal() as db:
    workspace = db.query(Workspace).filter(Workspace.slug == "agentium-showcase").one()
    try:
        with pg._connection(workspace) as (connection, _):
            server_version = connection.server_version
        stage = "table"
        table = pg.describe(workspace, "showcase_ecommerce", "claims")
        stage = "preview"
        result = pg.read(workspace, schema=table["schema"], table=table["table"],
                         columns=["claim_id"], fingerprint=table["fingerprint"], limit=1)
        print(json.dumps({"status": "ok", "server_version": server_version,
                          "row_count": result["row_count"]}))
    except pg.PostgresBrowseError as error:
        sqlstate = getattr(error.__context__, "pgcode", None)
        if not isinstance(sqlstate, str) or len(sqlstate) != 5 or not sqlstate.isalnum():
            sqlstate = None
        print(json.dumps({"status": "error", "stage": stage,
                          "server_version": server_version, "code": error.code,
                          "sqlstate": sqlstate}))
PY
```

Après déploiement et activation, reprendre le parcours ci-dessus sur Agentium,
puis vérifier qu'un nouveau Run depuis Work référence la nouvelle version et
conserve la provenance des sources. Les remboursements restent simulés et les
mesures humaines du [protocole ROI](ROI-PROTOCOL.md) restent à réaliser.

## Vérifications de livraison

- Compilation Angular production ; 1 899 tests unitaires frontend.
- Backend : 144 tests de validation, graphe figé, provenance, refus des bindings
  absents et publication atomique de Luma avec mise à jour du pin Work.
- PostgreSQL 16.2 réel isolé : quatre tests de droits, types exacts, aperçu,
  import natif, limites et changement de schéma.
- Navigateur local : huit parcours du nouvel inspecteur, neuf régressions de
  l'explorateur PostgreSQL et quatre régressions de navigation/undo du Flow.
  Captures FR sombre, FR mobile clair et EN clair ; contrôle Axe de l'inspecteur.
- Gardes i18n, chrome, navigation, conformité et pré-commit ciblé.

Les captures locales utilisent des API simulées. Elles attestent le parcours et
le rendu, pas le déploiement ni le preview live.
