# DataOps en production — bilan du 14 octobre 2026

L'opérateur rapporte la mise en production de
`0e401afc6b2ddd2e60f46edabf6d9c85120e277e`, avec révision vérifiée dans
`build-info`, puis l'activation globale de Delta, des contrats de service et du
scoring en flux. Ce bilan consigne ses opérations et observations ; il ne
présente pas de nouveaux appels VM ni de nouvelles recettes exécutés depuis
l'environnement de rédaction. Aucun nouveau bundle brut de logs n'est joint.

Le miroir GitHub contient cette révision sur `demo/agentic` et dans `main`
(`ed4e714f`). DataOps y a été intégré sous `aa99c247`, puis `0e401afc` corrige le
dimensionnement des objets exacts du dump préalable avec `mc stat`. La présence
du commit dans Git confirme son identité, pas à elle seule son exécution en
production : celle-ci est rapportée par le contrôle `build-info` de l'opérateur.
La PR #5 reste ouverte dans son historique antérieur ; elle n'est pas la preuve
d'une fusion de cette révision.

## Configuration effective rapportée

La préparation DataOps est active. Trois lignes ont été ajoutées à
`source-001.env`, après une copie vers
`/root/dataops-enable-2026-10-14/source-001.env.before-delta-contracts-streaming` :

```dotenv
DATAOPS_WRITE_DELTA_ENABLED=true
SERVICE_CONTRACTS_ENABLED=true
ML_SCORE_STREAMING_ENABLED=true
```

Le backend et le worker DataOps les ont chargées. Ces paramètres sont globaux :
ils ouvrent les fonctionnalités pour tous les workspaces, avec leurs contrôles
d'accès habituels. Ils ne créent ni contrat, ni corpus de calibration, ni modèle.
Leur portée diffère des activations limitées à un workspace décrites dans les
procédures de préparation Showcase.

La narration, l'écriture HANA et le TLS non sécurisé restent fermés. Le repli
HANA Showcase `demo_mode=true` a été choisi mais n'est pas encore enregistré.
Aucun contenu secret du fichier d'environnement ou de sa copie n'est reproduit
ici. La copie de ce fichier ne constitue pas une sauvegarde des données Delta.

## Vérifications et limites

| Domaine | Observation rapportée | Portée de la validation |
|---|---|---|
| Révision | `build-info` affiche `0e401afc`, révision vérifiée | Révision de production rapportée par l'opérateur |
| Services | Accueil, health, disponibilité, Keycloak et LiveKit : HTTP 200 ; OpenBao descellé ; SFTP sain | Disponibilité au contrôle, sans promesse de disponibilité future |
| Logs | Aucun traceback applicatif depuis le redémarrage | Fenêtre observée par l'opérateur |
| Delta | Préparation réelle via le worker DataOps, une ligne de sortie dans une part Delta, workspace `default` | Ce parcours est validé en production ; le volume et les sorties multi-parts ne le sont pas par cette sonde |
| Contrats | Liste accessible dans `default` et Showcase, zéro contrat | Fonction ouverte ; aucune promesse publiée ni livraison reçue démontrée |
| Juge typé | Calibration : « corpus introuvable » au lieu de « fonction désactivée » | Route accessible ; aucun corpus, fournisseur ou verdict ainsi qualifié |
| Scoring en flux | Option chargée, aucun essai lancé | Fonction activée, recette fonctionnelle et débit en production restant à établir |

Dans `default`, aucun modèle tabulaire ou de clustering n'est disponible.
Showcase en contient ; une recette de scoring demande un dataset avec les
colonnes et types attendus par la version du modèle choisie. L'activation ne
vaut donc pas validation de la cible de 2 à 3 millions de lignes par jour.
Les mesures locales précédentes restent attachées à leurs révisions et ne sont
pas requalifiées comme mesures de production.

## Sonde Delta conservée dans `default`

| Objet | Identifiant | Nom | Taille logique rapportée |
|---|---|---|---|
| Entrée | `97a4cdda-68d7-4920-8d8a-82b4fe51fc92` | `delta-activation-probe-input` | 2 lignes |
| Sortie | `cd500cce-85c4-4576-ad35-6f8133660cdf` | `delta-activation-probe` | 1 ligne, 1 part Delta |

La sortie est explicitement rapportée au format Delta. Le format physique de
l'entrée n'a pas été vérifié séparément dans cet environnement. L'opérateur
autorise la suppression de ces deux sondes ; aucune suppression n'est effectuée
par cette mise à jour documentaire. Leur éventuel retrait doit suivre les
contrôles normaux de filiation et de rétention des datasets.

## Retour arrière après écriture Delta

**Revenir uniquement aux images `ad10dbc2` n'est plus un retour arrière compatible
avec les versions Delta présentes.** Même avec une seule part, le stockage Delta
est un préfixe avec journal, tandis que l'ancien lecteur attend un objet Parquet.
Ne pas attribuer la compatibilité d'un ancien lecteur au seul faible volume de
la sonde.

Le drapeau global concerne aussi de nouvelles ingestions et des datasets dérivés.
Les deux sondes ne sont donc pas un inventaire complet des données susceptibles
d'avoir été écrites depuis l'activation. Les supprimer ne prouverait pas que le
retour à `ad10dbc2` est devenu possible.

Remettre `DATAOPS_WRITE_DELTA_ENABLED=false` arrête les nouvelles écritures Delta
qui dépendent de cette garde ; cela ne convertit pas les versions existantes.
Conserver un runtime capable de les lire pendant une correction en avant. Un
retour vers un runtime antérieur au lecteur Delta exige un traitement explicite
des versions concernées et une validation de compatibilité, avec sauvegardes
cohérentes des références SQL, manifests, journaux et parts. Ne pas restaurer
le dump préalable par-dessus les écritures postérieures à la livraison.

## RabbitMQ et nettoyage effectués par l'opérateur

Le `consumer_timeout` effectif est de **3 600 000 ms**, soit une heure. Le volume
RabbitMQ a été conservé, les **huit workers** se sont reconnectés et le scheduler
tourne. Cette observation remplace l'ancien état « réglage écrit mais broker
non recréé » ; elle ne prouve pas l'achèvement d'une tâche d'une heure.

Quatre runs bloqués ont été annulés ; le compte rendu fournit ces préfixes :

| Workspace | Préfixes des runs annulés |
|---|---|
| `acme` | `d74e8152`, `da2aa766` |
| `andritz` | `827df724`, `3fbd682f` |

Quatre files de réponse sans consommateur ont été supprimées, contenant
respectivement **11 910, 604, 40 et 2 messages**. Le redémarrage a recréé trois
petites files du même type, également supprimées. L'opérateur ne constate plus
de file de réponse orpheline à la fin du contrôle. Les noms et le nombre de
messages des trois dernières files ne sont pas fournis. Ce bilan ne prescrit
aucune purge automatique de files actives.

## Action HANA Showcase restante

Dans **Showcase → Connecteurs → SAP HANA**, autoriser explicitement le repli vers
les données de démonstration, conserver le chiffrement et la validation du
certificat, laisser le mot de passe vide pour garder le secret enregistré, puis
enregistrer. Le formulaire préserve les paramètres existants ; si une exception
TLS y est signalée, ne pas la considérer comme conforme au choix strict.

Relire la configuration pour confirmer `demo_mode=true`, `encrypt=true` et
`ssl_validate_certificate=true`, puis vérifier un aperçu portant
`source=demo_dataset` quand HANA est indisponible. Le bouton de test de connexion
reste un test HANA réel et peut toujours échouer. L'écriture HANA reste fermée.
La [procédure S0](hana-security-s0.md#showcase--démo-explicite-retenue-le-14-octobre-2026)
décrit la recette complète et la conservation du secret.

Ce bilan marque la mise en production et l'activation rapportées, pas
l'achèvement de tous les critères du [plan DataOps](../agentium-dataops-plan.md)
ou du [plan du juge typé](../agentium-typed-judge-plan.md). Narration et Gemini
via OpenRouter restent différés.
