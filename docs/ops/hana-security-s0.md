# S0 — HANA : autorisations, secrets et destinations

Le connecteur HANA accepte les écritures HTTP seulement si l'appelant est
administrateur du workspace **et** si `HANA_WRITES_ENABLED=true` sur le serveur.
Le champ `allow_writes` de la requête demande cette autorisation ; il ne
l'accorde pas. La Skill `sap_hana_query_v1` reste en lecture seule. Les lectures
refusent les instructions multiples, les CTE modificatrices et `SELECT INTO`,
et démarrent une transaction SQL en lecture seule. Utiliser également un compte
HANA disposant des seuls droits nécessaires.

## Identifiants et TLS

`HANA_CONNECTOR_PASSWORD` n'est plus lu. Chaque workspace doit avoir son propre
secret dans le registre ; une ancienne variable d'environnement ne rend plus
le connecteur configuré. Changer l'hôte, le port ou l'utilisateur exige de fournir
à nouveau le mot de passe : l'API ne réutilise pas silencieusement l'identifiant
d'une autre destination.

Le chiffrement et la vérification du certificat sont actifs par défaut.
Les paramètres workspace `encrypt=false` ou `ssl_validate_certificate=false`
sont refusés sauf si **les deux** conditions opérateur sont réunies :

- `HANA_ALLOW_INSECURE_TLS=true` ;
- l'hôte exact figure dans `HANA_INSECURE_TLS_ALLOWED_HOSTS` (CSV, sans wildcard).

Ce mécanisme est une exception explicite destinée à une destination identifiée,
pas une désactivation générale de TLS. Les erreurs exposent uniquement un code
fermé (`HANA_TLS_REQUIRED`, `HANA_CONNECTION_FAILED`, etc.) ; aucun texte du
pilote, mot de passe ou hôte fourni par l'utilisateur n'entre dans les logs de
la politique réseau. Les opérations bloquantes passent dans un thread dédié.

## Déploiement progressif de la politique réseau

| Réglage | Défaut | Sens |
|---|---|---|
| `HANA_NETWORK_POLICY_MODE` | `report` | `report` journalise, `enforce` bloque |
| `HANA_ALLOWED_HOSTS` | vide | CSV d'hôtes ou d'IP exacts validés pour HANA |
| `HANA_ALLOWED_CIDRS` | vide | CSV de sous-réseaux explicitement validés |

En mode rapport, les destinations non approuvées restent joignables : ce mode
est une phase d'inventaire, **pas une protection contre la SSRF**. Les événements
`HANA_NETWORK_POLICY` indiquent seulement le mode et la catégorie ; raccorder ce
signal aux alertes existantes. Avant la release qui active `enforce`, inventorier
et valider les hôtes existants et leurs adresses réseau, puis renseigner la liste
dans le bundle serveur. Aucun hôte n'est automatiquement approuvé par une
configuration de workspace.

En mode refus, tous les résultats DNS sont vérifiés, y compris IPv6 et les
adresses IPv4 encapsulées en IPv6. Un hôte DNS approuvé n'autorise pas à lui seul
une adresse privée : ajouter son IP exacte ou le CIDR interne validé. Les adresses
de bouclage, link-local (dont les métadonnées), multicast, non spécifiées ou
réservées sont refusées même si une règle trop large les couvre. Les réseaux
internes explicitement validés restent utilisables.

Le pilote reçoit une IP issue de cette résolution, avec l'identité TLS de l'hôte
original dans `sslHostNameInCertificate`, pour éviter une seconde résolution DNS
non contrôlée. Le routage distribué du pilote est désactivé (`distributionMode=off`).
Il n'y a pas de redirection HTTP sur ce connecteur SQL/TCP. L'egress du conteneur
doit aussi être limité aux destinations approuvées pour couvrir les mécanismes
de topologie/reconnexion propres au pilote et au serveur HANA ; cette PR ne
modifie pas le pare-feu de production.

## Démonstration et vérification

Le repli vers les tables synthétiques exige `demo_mode=true` dans la configuration
HANA du workspace et reste marqué `source=demo_dataset`. Par défaut une connexion
indisponible échoue. Une erreur d'autorisation, de TLS ou de politique réseau ne
devient jamais un résultat de démonstration. Activer ce mode uniquement sur les
workspaces de démonstration concernés.

Les tests isolés couvrent autorisation membre/admin/drapeau, erreurs contenant
un faux secret, absence du mot de passe global, TLS, pin DNS, métadonnées,
réponses DNS mixtes, réseaux internes, SQL et repli explicite. Ils ne constituent
pas une qualification sur une instance HANA réelle : le certificat et la
transaction en lecture seule doivent être vérifiés avec le pilote déployé lors
de la recette, ainsi que la connectivité des destinations internes inventoriées.

## Action hors dépôt encore nécessaire

Le plan signale un token Docker Hub en clair dans
`papai-latest/spark-service/docs/README_prerelease.md`, hors de ce checkout.
Le propriétaire du compte doit le révoquer, remplacer les références autorisées
et vérifier son historique d'utilisation. Ce fichier et le compte Docker Hub
ne sont pas accessibles ici : **aucune révocation n'a été effectuée ni vérifiée**.
