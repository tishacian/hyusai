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
indisponible échoue. Les refus d'autorisation applicative et les refus de politique
`HANA_TLS_REQUIRED` / `HANA_DESTINATION_DENIED` ne déclenchent pas ce repli.
Activer ce mode uniquement sur les workspaces de démonstration concernés.

**Limite de qualification conservée :** la formulation initiale promettait que
toute erreur d'authentification ou de certificat resterait distincte d'une panne.
Le pilote ne fournit pas encore cette distinction au service : les exceptions
de `dbapi.connect` deviennent toutes `HANA_CONNECTION_FAILED`, code éligible au
repli explicite en lecture. Une démo réussie ne qualifie donc ni le compte HANA
ni le certificat vu par le pilote. Le chiffrement et la vérification TLS restent
actifs ; aucun essai avec certificat non vérifié n'est ajouté. `/hana/test`
n'a pas de repli et reste le contrôle de connexion HANA réel.

Les tests isolés couvrent autorisation membre/admin/drapeau, erreurs contenant
un faux secret, absence du mot de passe global, TLS, pin DNS, métadonnées,
réponses DNS mixtes, réseaux internes, SQL et repli explicite. Ils ne constituent
pas une qualification sur une instance HANA réelle : le certificat et la
transaction en lecture seule doivent être vérifiés avec le pilote déployé lors
de la recette, ainsi que la connectivité des destinations internes inventoriées.

## Showcase : démo explicite retenue le 14 octobre 2026

Le propriétaire de la livraison a choisi le repli de démonstration pour
`agentium-showcase`, l'ancienne instance d'essai étant probablement indisponible.
L'[analyse et les preuves](../dataops-release-blockers-2026-10-14.md) conservent
le diagnostic ; l'expiration du trial n'est pas confirmée dans le panneau SAP.
Cette décision n'active aucune configuration sur la VM et ne vaut pas une
autorisation de fusion ou de déploiement.

Après qualification des images candidates et dans le cadre de la livraison :

1. Comme administrateur de `agentium-showcase`, relire `/api/v1/hana/config`
   dans le contexte de ce workspace. Conserver l'hôte, le port, le compte et
   le secret enregistrés ; ne pas extraire ce dernier.
2. Enregistrer `demo_mode=true`, `encrypt=true`,
   `ssl_validate_certificate=true`. La sauvegarde `/api/v1/hana/config` exige
   l'hôte, le port et le compte ; reprendre leurs valeurs lues, omettre le champ
   `password` pour garder le secret existant. Ne jamais envoyer
   `password_encrypted`. Conserver `HANA_ALLOW_INSECURE_TLS=false` et
   `HANA_WRITES_ENABLED=false` côté serveur.
3. Relire la configuration et vérifier ces trois booléens ainsi que
   `password_set=true`. Une nouvelle sauvegarde du formulaire doit conserver
   le choix, sans réintroduire le mot de passe masqué dans le formulaire.
4. Avec HANA indisponible, vérifier un aperçu et une lecture bornée sur une
   table de démonstration, par exemple `SELECT * FROM DEMO_MAINTENANCE_ORDERS`
   avec `max_rows=1`, `allow_writes=false`. Attendre `source=demo_dataset` et
   l'indication visible de données de démonstration dans l'aperçu. Ne pas
   interpréter un résultat synthétique comme une lecture de l'instance SAP.
5. Vérifier que le test de connexion enregistrée expose encore l'échec vivant
   lorsque l'instance est indisponible. Les refus d'accès HTTP, de politique
   TLS/réseau et la garde d'écriture doivent rester des refus. Les autres
   workspaces conservent leur configuration ; ce mode n'est pas semé globalement.

Le repli tente d'abord HANA, donc peut attendre l'échéance de connexion. Il reste
soumis à la politique réseau et aux bornes du moteur de données synthétiques ;
il ne rend pas toute requête SQL valide et ne garantit pas un fonctionnement
hors ligne. Si HANA redevient accessible, la source doit être affichée comme
vivante. Pour retirer le repli, enregistrer `demo_mode=false` en conservant
les deux paramètres TLS à `true` ; cette procédure ne recrée pas une instance SAP.

Les scripts de seed ne sont pas utilisés pour cette activation : ils ont un
périmètre plus large et certains écrivent dans HANA. Ne pas modifier directement
la base de production pour contourner les contrôles du connecteur.

## Action hors dépôt encore nécessaire

Le plan signale un token Docker Hub en clair dans
`papai-latest/spark-service/docs/README_prerelease.md`, hors de ce checkout.
Le propriétaire du compte doit le révoquer, remplacer les références autorisées
et vérifier son historique d'utilisation. Ce fichier et le compte Docker Hub
ne sont pas accessibles ici : **aucune révocation n'a été effectuée ni vérifiée**.
