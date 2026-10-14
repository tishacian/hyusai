# DataOps — tailles d'images et choix HANA, 14 octobre 2026

Ce diagnostic suit la demande de comparer la référence `ad10dbc2` et le candidat
`bd724044`, puis de choisir le comportement HANA Showcase. Le candidat est le
runtime qualifié ; les commits suivants de la branche ajoutent ses preuves.
Le plan original et la revue indépendante restent inchangés. Aucune hausse de
plafond, fusion ou mise en production n'est décidée ici. Les autres lots du plan
restent hors de cette vérification.

## Un seul chiffre de budget, produit sur la VM

La reconstruction historique est terminée. Avec la même base Python épinglée,
la même plateforme Linux/amd64, RAG activé et la même comptabilité OCI, elle
mesure **3 420 Mio**, contre **3 567 Mio** pour le candidat. Le surcroît mesuré
est de **154 697 613 octets, soit 147,53 Mio décompressés** ; il n'est donc pas
de deux Gio dans cette comparaison contrôlée.

| Mesure du backend | `ad10dbc2` reconstruit | Candidat `bd724044` | Différence |
|---|---:|---:|---:|
| Charges utiles décompressées, octets | 3 586 308 646 | 3 741 006 259 | +154 697 613 |
| Même mesure, Mio entiers | 3 420 | 3 567 | +147 |
| Couches compressées, octets | 1 288 128 726 | 1 346 033 449 | +57 904 723 |
| Flux tar des couches décompressées, octets | 3 653 217 280 | 3 809 157 120 | +155 939 840 |

Les empreintes des couches compressées et leurs `diff_ids` décompressés sont
vérifiés. La construction de la référence a duré 745,031 s. C'est une
reconstruction du source historique aujourd'hui, pas une mesure de l'artefact
historiquement déployé. Les tests du candidat ne lui sont pas attribués.
Le chiffre de **1 356 Mio** communiqué pour la production n'a pas été relevé
à nouveau dans cette session. Il ne doit pas être soustrait à une mesure OCI
sans identifier le même artefact et le même mode de stockage.

L'[attribution par couche](evidence/dataops-image-reconciliation-2026-10-14/baseline-ad10dbc2/backend-comparison.json)
explique exactement les 154 697 613 octets supplémentaires :

| Origine | Différence en octets |
|---|---:|
| Dépendances applicatives | +153 276 771 |
| Contexte copié dans l'image | +1 420 667 |
| Fichiers de dépendances | +183 |
| Couches système | −8 |

Les seules distributions Python ajoutées sont `sqlglot` 30.22.0, `deltalake`
1.6.6, `arro3-core` 0.9.1 et `deprecated` 3.0.0. Toutes les distributions communes
conservent leur version. Hugging Face mesure **978 455 988 octets dans les deux
images**, et les modèles RAG **226 179 470 octets dans les deux**. Aucun cache
Terraform n'est présent dans les deux contextes copiés. Le `COPY` ne révèle donc
pas de nouvelle couche de plusieurs Gio.

Une limite de reproductibilité est observée : les index APT ne sont pas figés.
La reconstruction historique installe `libcurl3t64-gnutls` et `libcurl4t64` en
`8.14.1-2+deb13u7`, contre `u5` dans le candidat déjà construit. Cette différence
est conservée dans le rapport ; la base et le Dockerfile sont identiques, mais
on ne prétend pas que toutes les couches système ont le même contenu.
Le [bundle de 59 fichiers](evidence/dataops-image-reconciliation-2026-10-14/baseline-ad10dbc2/bundle-index.json)
conserve les commandes, entrées, métadonnées, traces compressées et empreintes.
Le constructeur dédié est arrêté ; les archives et le checkout sont conservés.
Aucune commande n'a été exécutée sur la VM.

Le script `scripts/agentium-image-budget.sh` lit `docker image inspect .Size`,
puis divise par 1 048 576 avec troncature. Il est identique entre la référence et
le candidat. Les plafonds restent 1 400 Mio pour le backend et 1 760 pour le worker.

Les mesures du candidat, 3 741 006 259 octets pour le backend et 4 903 956 499 pour
le worker, additionnent les charges utiles des couches OCI. C'est la comptabilité
du stockage Docker classique, calibrée exactement sur la base Python locale :
119 181 182 octets pour le parseur comme pour `docker image inspect` sous `vfs`.
Ce ne sont pas des inspections des images finales sur la VM.

Cette distinction compte : dans Docker 28.4, le
[code du stockage containerd](https://github.com/moby/moby/blob/v28.4.0/daemon/containerd/image_inspect.go#L180)
calcule `inspect.Size` en additionnant les tailles des contenus référencés :
manifestes, configurations et couches dans leur forme stockée, généralement
compressée.
Le mode de stockage de la VM n'est pas encore relevé. La taille du fichier tar
OCI n'est pas non plus exactement cette somme : elle inclut son propre emballage.
La [vérification du code Docker](evidence/dataops-image-reconciliation-2026-10-14/docker-accounting.json)
conserve la version et l'empreinte consultées.

Pour les manifestes Linux/amd64 mesurés, la somme calculée des descripteurs
manifest/configuration/couches vaut 1 288 146 714 octets pour la référence,
1 346 051 447 pour le backend candidat et 1 716 398 476 pour le worker candidat
(respectivement 1 228, 1 283 et 1 636 Mio entiers). Ces chiffres expliquent
pourquoi la distinction de stockage peut inverser le verdict. Ils restent des
calculs OCI, **pas le chiffre de budget de la VM** ; le descripteur cible exact
peut notamment être un index. Aucun plafond n'est modifié sur cette base.

Reconstruire `ad10dbc2` avec les mêmes paramètres permet de mesurer le surcroît
du candidat. Si les deux reconstructions sont proches, cela ne prouve pas à soi
seul une erreur de méthode : l'artefact historiquement déployé peut aussi différer
par sa base, ses options, ses dépendances ou son contexte de construction.
Le relevé sur la VM doit identifier les images et le stockage avant de conclure.

Le [collecteur en lecture seule](evidence/dataops-image-reconciliation-2026-10-14/measure_vm_images.py)
fixe le socket Docker local, recueille version/stockage, identifiants et révisions
d'images, descripteur OCI disponible, tailles exactes et `diff_ids`, puis appelle le script de budget original
avec les plafonds inchangés. Il vérifie l'empreinte du script avant exécution.
Il ne construit, ne charge et ne déploie aucune image ; une image absente reste
absente. La réussite du budget et la présence de toutes les images listées sont
rapportées séparément, car le script de release autorise l'absence de `ml-ts`.
Sa [vérification locale](evidence/dataops-image-reconciliation-2026-10-14/probe-local-validation.json)
confirme la mesure de la base, le refus d'une release absente et l'utilisation du
socket local même avec un contexte distant dans l'environnement. Ce n'est pas
une qualification sur la VM.

Sur la VM, avec les tags réellement présents, la commande est :

```bash
python3 /chemin/measure_vm_images.py \
  --tag TAG_REFERENCE --tag TAG_CANDIDAT > /tmp/dataops-image-budget.json
```

Un retour non nul conserve le rapport JSON et signifie qu'au moins un contrôle
n'a pas réussi. Il ne faut pas charger les archives sur la VM sans avoir vérifié
l'espace disponible et préparé un protocole de mesure isolé. L'accès SSH demandé
sert aux mesures, pas à une bascule de services.

## HANA Showcase : décision encore ouverte

Aucun essai vivant ne démontre actuellement que le certificat est invalide.
Le risque `HANA_CONNECTION_FAILED` de la revue doit être vérifié avec la
configuration effective du workspace, la destination et le client HANA du
runtime. Les valeurs historiques de la revue ne valent pas relevé courant.

| Choix exclusif | Configuration | Preuve ou limite |
|---|---|---|
| Certificat valide, recommandé | `encrypt=true`, `ssl_validate_certificate=true`, `demo_mode=false` | Vérifier nom DNS, dates, chaîne et confiance effective de `hdbcli`, puis une lecture réelle. |
| Démo explicite | `demo_mode=true`, TLS strict conservé | C'est un repli après tentative de connexion : une connexion réussie utilise encore HANA vivant. Le repli porte `source=demo_dataset`. |
| Exception TLS pour l'hôte | `HANA_ALLOW_INSECURE_TLS=true`, nom exact dans `HANA_INSECURE_TLS_ALLOWED_HOSTS`, puis `ssl_validate_certificate=false`, `encrypt=true`, `demo_mode=false` | Le trafic reste chiffré, mais l'identité du serveur n'est plus vérifiée. La liste serveur s'applique à l'hôte pour tous les workspaces et n'expire pas automatiquement. |

Deux limites du code doivent accompagner ce choix. Le formulaire HANA n'envoie
ni `demo_mode` ni `ssl_validate_certificate` ; sa sauvegarde rétablit les valeurs
par défaut de l'API, donc peut annuler une démo ou une exception configurée par
ailleurs. Son bouton de test utilise la configuration enregistrée, même si le
formulaire a été modifié sans sauvegarde.

Autre écart à conserver explicitement : le runbook `docs/ops/hana-security-s0.md`
dit que les erreurs d'authentification/TLS ne déclenchent pas la démo. Dans
`backend/app/services/connectors/hana/service.py`, toutes les exceptions de
`dbapi.connect` deviennent pourtant `HANA_CONNECTION_FAILED`, donc peuvent
déclencher le repli si `demo_mode=true`. Les refus de politique réseau et TLS
restent distincts. Ce constat ne modifie ni le contrat ni le comportement attendu.

La lecture autorisée de `/api/v1/hana/config` doit relever seulement les paramètres
non secrets et `password_set`. Un contrôle OpenSSL de la chaîne et du nom ne
suffit pas à prouver la confiance du pilote. `/hana/test` effectue une lecture de
`DUMMY` avec le secret résolu côté serveur, sans repli ; une requête bornée
`SELECT 1 FROM DUMMY`, avec écritures interdites, doit ensuite rendre
`source=hana_live`. Les scripts de seed ne sont pas des outils de diagnostic :
ils modifient la configuration et certains écrivent dans HANA.

Aucune exception TLS ni démo n'est activée par cette note. Le choix de l'utilisateur
et sa vérification restent nécessaires avant tout déploiement.
