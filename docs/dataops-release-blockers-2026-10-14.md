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
Le relevé SSH du 14 octobre confirme **1 356 Mio** pour le backend réellement
présent en production, avec Docker **29.1.3**, stockage **containerd/overlayfs**
(`driver-type=io.containerd.snapshotter.v1`). Ce chiffre est produit par
`docker image inspect .Size`, comme le script de budget. Il ne doit pas être
soustrait aux charges utiles OCI décompressées ci-dessus.

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
Cette reconstruction locale n'avait exécuté aucune commande sur la VM ;
le relevé SSH décrit ci-dessous a ensuite mesuré les images existantes.

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
Le stockage containerd de la VM est maintenant confirmé par `docker info`.
La référence de code citée concerne Docker 28.4, pas la version 29.1.3 relevée :
elle explique la distinction de métriques mais ne remplace pas la mesure.
La taille du fichier tar OCI n'est pas non plus exactement cette somme :
elle inclut son propre emballage.
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
Le relevé sur la VM identifie désormais l'artefact historique déployé et le
stockage. Il ne qualifie pas une image candidate absente.

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

## Relevé Docker sur `omnirag-demo`

Le [rapport SSH](evidence/dataops-vm-check-2026-10-14/docker-images.json),
relevé à 08:58 heure de Paris, utilise le collecteur versionné sans modification.
L'empreinte du script de budget de la VM est identique à celle attendue :
`1abd2f02b780fff2190099833bffc7a631c34aad2b397018112a2b9e25aa1366`.
Tous les plafonds d'origine sont imposés au processus de contrôle.

| Image `ad10dbc2b6cb` | `.Size`, octets | Mio entiers | Plafond Mio | Verdict |
|---|---:|---:|---:|---|
| backend | 1 422 295 390 | 1 356 | 1 400 | OK |
| worker | 1 792 603 614 | 1 709 | 1 760 | OK |
| frontend | 29 899 091 | 28 | 40 | OK |
| ml-ts | 1 229 944 394 | 1 172 | 1 240 | OK |
| livekit-agent | 104 374 853 | 99 | 110 | OK |

Les révisions OCI de ces cinq images sont
`ad10dbc2b6cb464c8e7c6b19af8ffc46a3b3fb3b`. Le descripteur du backend est le
manifeste `sha256:edc26ba7f12f32f5c06ddeb138ff6486faa89e807a1542e7c96087a7a20f376e`.
Backend/worker et backend/ml-ts partagent chacun neuf couches.
`docker image ls` affiche 5,42 Go pour ce backend, tandis que son `.Size` vaut
1 422 295 390 octets : l'affichage de la liste ne doit pas remplacer la métrique
lue par le contrôle de release.

L'[inventaire](evidence/dataops-vm-check-2026-10-14/vm-state.json) examine les
identifiants, tags et révisions de **204 images Agentium**. Aucun tag ou label
ne correspond à `bd724044` ni `a90272c1`. Les contrôles de ces tags échouent pour
images manquantes ; ils ne constatent pas un dépassement. Le script de budget
passe pour la référence déployée, mais **aucun verdict VM sur le candidat n'est
possible**. Les calculs OCI de 1 283/1 636 Mio ne deviennent pas des mesures VM.
L'espace libre sur `/` est de 137 494 495 232 octets au relevé ; aucune archive
n'a été transférée ou chargée et aucune image n'a été construite, tirée ou purgée.
Les identifiants et dates de démarrage des cinq conteneurs contrôlés sont
[identiques après les sondes](evidence/dataops-vm-check-2026-10-14/containers-after.txt).

## HANA Showcase : échec SQL reproduit, cause non établie

Le [relevé du candidat](evidence/dataops-vm-check-2026-10-14/hana-showcase.json)
utilise les deux modules HANA exacts de `a90272c1`, chargés seulement en mémoire
dans un processus `docker exec` séparé du backend existant. Le pilote est celui
du runtime déployé, **hdbcli 2.29.27**. Aucun fichier n'est installé sur la VM.
Ce contrôle du service ne qualifie ni l'image candidate complète ni les routes
HTTP et leurs contrôles d'accès.

La configuration du workspace `agentium-showcase` confirme : connecteur activé,
`encrypt=true`, `password_set=true`, secret résolu côté serveur. Les clés
`ssl_validate_certificate` et `demo_mode` ne sont pas enregistrées ; le candidat
applique donc **`true` et `false`**. Les drapeaux effectifs restent
`hana_allow_insecure_tls=false`, `hana_writes_enabled=false` et
`hana_network_policy_mode=report`. Aucun secret n'est exporté.

Le [contrôle TLS indépendant](evidence/dataops-vm-check-2026-10-14/tls-peer.json)
depuis le même conteneur réussit avec `ssl.create_default_context`, nom DNS
vérifié et TLS 1.3. Le certificat SAP SE est émis par
`DigiCert G5 TLS RSA4096 SHA384 2021 CA1`, valable du **8 octobre 2026** au
**23 avril 2027** ; son SAN couvre `*.hna1.prod-us10.hanacloud.ondemand.com`.
Il n'y a donc pas de preuve d'un certificat invalide à cette destination lors
de la sonde. Ce contrôle OpenSSL ne prouve pas à lui seul la confiance de hdbcli.

Les deux opérations du candidat échouent avant toute lecture SQL :

- `test_connection` (lecture de DUMMY sans repli) : `HANA_CONNECTION_FAILED`, 502.
- `SELECT 1 FROM DUMMY`, `max_rows=1`, `allow_writes=false` : même résultat,
  aucune ligne et aucun `source=hana_live`.

Le pilote retourne `-10709`, `RTE:[200121]`, « Invalid connect reply » avec une
réponse **HTTP 400** reçue à la place du protocole SAP HANA. L'échec se produit
avant authentification/lecture ; il ne démontre ni un mauvais mot de passe ni
un rejet du certificat par le pilote.

Une [sonde différentielle](evidence/dataops-vm-check-2026-10-14/hana-showcase-sni-diagnostic.json)
a ajouté uniquement `sslSNIHostname=destination.host` en mémoire, en conservant
l'IP épinglée et la validation TLS : même HTTP 400. Une connexion diagnostique
avec le nom DNS, sans épinglage et avec TLS strict, échoue aussi de la même façon.
La distinction entre `sslHostNameInCertificate` et `sslSNIHostname` est décrite
par [SAP](https://help.sap.com/docs/r/f1b440ded6144a54ada97ff95dac7adf/2.16/en-US/f6fb06ffe4484f6fa61f10082b11663d.html).
Ces essais ne suffisent pas à attribuer la cause au SNI ou à l'épinglage ; aucun
correctif de ce type n'est conservé. Il reste à vérifier côté SAP que cette
adresse expose bien le service SQL de l'instance attendue et ses conditions
d'accès, puis refaire le test hdbcli strict et la lecture bornée.

Le blocage HANA reste ouvert. Activer une exception TLS n'est pas justifié par
ces résultats. Aucun choix parmi les modes suivants n'est appliqué :

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

Les sondes passent par les fonctions de service et une transaction PostgreSQL
`READ ONLY`, pas par `/api/v1/hana/config` ou `/hana/test` en HTTP authentifié.
Le [script de reproduction](evidence/dataops-vm-check-2026-10-14/check_hana_vm.py)
conserve seulement la configuration non secrète, `password_set`, les paramètres
TLS et des erreurs expurgées du mot de passe. Les scripts de seed n'ont pas été
utilisés. Les [48 tests HANA ciblés](evidence/dataops-vm-check-2026-10-14/hana-tests.txt)
passent localement ; ce résultat n'est pas une lecture HANA réussie ni une
nouvelle exécution de la suite backend complète.

Aucune exception TLS ni démo n'est activée par cette note. Le choix de l'utilisateur
et sa vérification restent nécessaires avant tout déploiement.
