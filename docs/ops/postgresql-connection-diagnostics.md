# Diagnostiquer une connexion PostgreSQL depuis Agentium

Le test, l’explorateur et le lecteur des réclamations partagent des diagnostics
fermés de connexion. Les textes libpq ne
sont jamais renvoyés ni journalisés : ils peuvent contenir le compte, l’hôte,
des chemins de certificats ou des secrets. Un message inconnu reste
`PG_UNAVAILABLE` ; ce code ne prouve aucune cause particulière.

## Vérification depuis l’interface

1. Sélectionner le workspace concerné, puis **Connecteurs → PostgreSQL**.
2. Dans **Chiffrement**, conserver **TLS vérifié (recommandé)**, ou choisir
   explicitement **Sans chiffrement** pour un endpoint qui le nécessite.
   Seul un administrateur peut enregistrer ce choix. Sans TLS, les données
   échangées ne sont pas protégées pendant leur transport.
3. Enregistrer, puis **Tester la connexion**. Une configuration enregistrée n’est pas un test
   réussi. Le test est exécuté depuis le backend avec les paramètres enregistrés.
4. Corriger la cause indiquée ci-dessous, puis retester. **Explorer les tables**
   doit également réussir : `SELECT 1` seul ne prouve pas les droits de lecture.
5. Sélectionner une table et lire un aperçu. Reprendre ensuite le parcours Work
   concerné pour vérifier le lecteur métier et le worker.

Le choix est propre à la connexion ; il ne désactive pas TLS pour les autres
connecteurs. Une modification efface le résultat du test et les aperçus affichés.
Il faut enregistrer puis refaire ces vérifications avant d’utiliser la source.

Le registre **Connections** expose le même choix sur les connexions PostgreSQL
utilisées par DataOps et les runners du framework. Il s’agit d’une configuration
distincte du connecteur historique utilisé par Work Luma. Modifier une entrée
du registre ne modifie pas le connecteur historique, et réciproquement.
La migration du connecteur vers le registre est ponctuelle, pas une
synchronisation ; elle conserve le mode choisi lors de la migration.

La lecture métier conserve ses codes historiques de schéma, permissions et
timeout, ainsi qu'un code générique pour les causes inconnues. Pour une panne de
connexion reconnue, elle transmet le même code fermé que le connecteur :
l'application peut expliquer la cause sans exposer les paramètres ni le message
du pilote. Un consommateur peut réessayer ; la configuration reste une action
d'administration.

| Code | Vérification opérateur |
| --- | --- |
| `PG_TLS_TRUST_REQUIRED` | libpq n’a pas pu charger l’autorité de certification. Vérifier sa présence et sa lisibilité dans le conteneur applicatif, sous l’utilisateur du processus. |
| `PG_TLS_VERIFICATION_FAILED` | Vérifier la chaîne, l’expiration et le nom/IP du certificat présenté par PostgreSQL. Le champ hôte doit correspondre à son identité certifiée. |
| `PG_TLS_UNAVAILABLE` | Le serveur a annoncé qu’il ne supporte pas TLS. Configurer TLS côté PostgreSQL, ou faire sélectionner explicitement **Sans chiffrement** par l’administrateur si cette connexion doit fonctionner sans TLS. |
| `PG_SSLMODE_INVALID` | Le mode enregistré est invalide. Choisir **TLS vérifié** ou **Sans chiffrement**, enregistrer puis retester. |
| `PG_TLS_FAILED` | La négociation TLS a échoué sans cause plus précise reconnue. Consulter les diagnostics serveur dans le périmètre opérateur. |
| `PG_AUTH_FAILED` | Vérifier le compte, le secret enregistré et `pg_hba.conf`, depuis la source réseau du conteneur Agentium. |
| `PG_DATABASE_NOT_FOUND` | Corriger le nom de base enregistré. |
| `PG_CONNECTION_REFUSED` | Vérifier hôte, port, listener PostgreSQL et filtrage réseau. |
| `PG_CONNECTION_TIMEOUT` | Vérifier routage, pare-feu et réponse du serveur depuis Agentium. |
| `CONNECTOR_DNS_FAILED` | Vérifier la résolution du nom depuis le conteneur ; la résolution du poste utilisateur ne suffit pas. |
| `CONNECTOR_DESTINATION_DENIED` | Vérifier les autorisations réseau et les exceptions approuvées du workspace, sans désactiver la politique. |
| `PG_PERMISSION_DENIED` | Donner au compte les droits de lecture sur les seules tables nécessaires. |
| `PG_TIMEOUT` | La session est établie, mais une instruction ou un verrou a dépassé son délai. Vérifier charge, verrous et portée de la lecture. |
| `PG_QUERY_FAILED` | La session est établie, mais la requête a échoué. Le SQLSTATE affiché permet le diagnostic sans exposer SQL ou données. |

## Contrôle opérateur dans la VM

Après déploiement du correctif, ce contrôle utilise **la configuration existante**,
les secrets stockés et la politique réseau du workspace. Il ne crée ni ne modifie
aucune donnée. Remplacer le slug par celui du workspace à diagnostiquer. Le nom
`agentium-backend` est celui du Compose VM du dépôt.

```bash
docker exec -i agentium-backend python - <<'PY'
import json
from app.db.base import SessionLocal
from app.models.workspace import Workspace
from app.services.connectors.generic.service import get_config, test_connection
from app.services.connectors.generic.postgresql_browser import catalog, PostgresBrowseError

with SessionLocal() as db:
    workspace = db.query(Workspace).filter(Workspace.slug == "workspace-a-diagnostiquer").one()
    config = get_config(workspace, "postgresql", include_secrets=True)
    result = test_connection("postgresql", config)
    print(json.dumps(result))  # Statut, diagnostic fermé et date uniquement.
    if result["status"] == "connected":
        try:
            result = catalog(workspace)
            print(json.dumps({"catalog": "read", "accessible_tables": len(result["tables"])}))
        except PostgresBrowseError as error:
            print(json.dumps({"catalog": "failed", "code": error.code, "sqlstate": error.sqlstate}))
PY
```

Ne pas imprimer `config`, les variables d’environnement ou les exceptions brutes.
Un accès réussi depuis un poste extérieur ne valide pas le routage, la confiance
TLS ni les autorisations vus depuis le conteneur.

## Modes de transport et confiance TLS

Les deux modes pris en charge sont `verify-full` et `disable`, enregistrés dans
`values.sslmode`. L’absence du champ conserve `verify-full` pour les connexions
existantes. Les modes opportunistes tels que `prefer` et les valeurs invalides
sont refusés avant résolution réseau. Un échec TLS ne provoque **aucun repli
automatique** vers une connexion non chiffrée.

Le test, l’explorateur, l’import, les lectures Work et l’adaptateur PostgreSQL
des tâches DataOps utilisent le mode de leur configuration. Ils conservent le
nom d’hôte original et l’adresse résolue pour la connexion, les contrôles réseau,
les droits du workspace et les limites des requêtes. Le mode sans chiffrement
ne change pas ces contrôles. Redshift conserve son transport TLS vérifié.

Avec `verify-full`, le certificat et son identité sont vérifiés. Aucun chemin
arbitraire de certificat dans le conteneur n’est accepté depuis le formulaire.

Pour le connecteur historique, libpq peut lire une autorité configurée par
l’opérateur via `PGSSLROOTCERT` ou son emplacement de confiance par défaut.
Le fichier doit être fourni par le déploiement, en lecture seule, et accessible
au processus qui effectue réellement la lecture. Vérifier séparément backend
et worker : le succès dans un conteneur ne prouve pas la configuration de l’autre.
Une modification d’environnement nécessite de recréer les services concernés,
pas seulement de les redémarrer. Pour les runners isolés du nouveau framework,
qualifier leur propre contrat de confiance et de montage ; ne pas supposer
qu’ils héritent de toutes les variables du backend.

Si le serveur présente un certificat pour un nom DNS et que la configuration
TLS utilise une IP, utiliser le nom certifié après vérification de sa résolution
et des accès autorisés. `require`, `prefer` et `verify-ca` ne font pas partie du
contrat du connecteur.
Le certificat HTTPS du site Agentium est distinct du certificat PostgreSQL.

## Déploiement et vérification du choix de transport

Déployer le backend, le frontend et les workers qui exécutent les lectures de
connecteurs. Pour le framework isolé, reconstruire et déployer aussi l’image
du runner contenant l’adaptateur et les profils de la même révision. Les profils
sont mis en cache en mémoire : les processus existants doivent être recréés.
Ce changement ne demande ni migration de base ni nouveau drapeau fonctionnel.
Aucune configuration existante n’est passée automatiquement en mode non chiffré.

Après enregistrement, tester la connexion, charger le catalogue et produire un
nouvel aperçu. Pour qualifier un import, utiliser une nouvelle requête : un
dataset déjà créé reste un snapshot et le même `request_id` restitue volontairement
le résultat précédent. Le fingerprint distingue les deux modes ; un ancien
aperçu ne peut pas autoriser une nouvelle lecture après changement de transport.

Dans le registre Connections, l’enregistrement incrémente la révision, invalide
le dernier test et les autorisations d’exécution précédentes. Les tâches et
surveillances épinglées à une ancienne révision doivent être requalifiées ;
vérifier leurs consommateurs avant de reprendre le parcours DataOps.

La validation locale du 19 octobre couvre un vrai serveur PostgreSQL avec
`ssl=off` : les modes absent et `verify-full` échouent avec `PG_TLS_UNAVAILABLE`,
le mode `disable` permet le test, le catalogue, l’aperçu, l’import et une lecture
métier. Cette preuve locale ne remplace pas la recette de l’endpoint déployé.

## Limite de la recette du 16 octobre 2026

La recette live antérieure a observé `unreachable` sans détail, `PG_UNAVAILABLE`
pour le catalogue et `POSTGRESQL_READ_UNAVAILABLE` dans Work. Elle **ne démontre
pas** un défaut TLS, de réseau ou d’authentification particulier. Les tests du
correctif reproduisent ces catégories de panne sur des pilotes simulés ; la
cause live reste à relever après déploiement avec ce diagnostic.

Le 19 octobre, après déploiement de `d95ba09f`, le test et le catalogue de Showcase
renvoient tous deux `PG_TLS_UNAVAILABLE`. Cette nouvelle observation établit
l'absence de TLS sur l'endpoint configuré ; elle ne valide pas encore la
confiance du certificat, l'authentification ou les droits. Ces derniers restent
à vérifier après activation de TLS ou après le déploiement et la sélection
explicite du mode sans chiffrement.
