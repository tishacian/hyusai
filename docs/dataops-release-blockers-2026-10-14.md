# DataOps — tailles d'images et choix HANA, 14 octobre 2026

Ce diagnostic suit la comparaison locale de `ad10dbc2` avec `bd724044`, le choix
HANA Showcase, puis la mesure VM de `6dcb0d48` rapportée par l'utilisateur.
Les preuves locales et le premier relevé SSH restent historiques ; le nouvel
état et les plafonds autorisés sont consignés ci-dessous. Le plan original et
la revue indépendante restent inchangés. Aucune fusion, mise en production ni
activation HANA n'est effectuée. Les autres lots du plan restent hors de cette
vérification.

## Mesure candidate sur la VM et plafonds retenus

Après le correctif HANA `6dcb0d48c51907a2fa47f31da6c4785a3355021a`, l'utilisateur
rapporte que les images ont été construites sur la VM à côté de la production,
avec les options de release. Le script de budget lit `docker image inspect
.Size`, en Mio entiers après division par 1 048 576. Il échoue aux anciens
plafonds pour le backend et le worker :

| Image | Production `ad10dbc2` | Candidat `6dcb0d48` | Ancien plafond | Plafond autorisé | Marge candidate |
|---|---:|---:|---:|---:|---:|
| backend | 1 356 | 1 412 | 1 400 | **1 480** | 68 |
| worker | 1 709 | 1 765 | 1 760 | **1 850** | 85 |
| frontend | 28 | 28 | 40 | 40 | 12 |
| ml-ts | 1 172 | 1 229 | 1 240 | 1 240 | 11 |
| livekit-agent | 99 | 99 | 110 | 110 | 11 |

Toutes les tailles et marges du tableau sont en Mio. Le dépassement mesuré est
de **12 Mio / 5 Mio**, et non de plusieurs Gio. L'écart à la production est de
56 Mio pour le backend et le worker, 57 Mio pour ml-ts d'après les valeurs
entières fournies. Il correspond au poids compressé des quatre dépendances
`sqlglot`, `deltalake`, `arro3-core` et `deprecated`. Le nombre de couches
partagées reste neuf selon ce relevé. L'analyse locale par couche qui suit
explique la différence avec les sommes décompressées.

L'utilisateur autorise **1 480 Mio pour le backend et 1 850 Mio pour le worker**,
soit environ 4,82 % de marge sur les tailles mesurées. Ces valeurs deviennent
les défauts de `scripts/agentium-vm-build.sh` ; les trois autres plafonds restent
inchangés. La méthode de mesure et le contrôle des couches partagées ne changent
pas. La justification figure dans les [notes de livraison](../CHANGELOG.md#2026-10-14--dataops-candidate-not-deployed).

**Provenance et portée :** ce tableau transcrit le compte rendu VM reçu dans la
conversation ; aucun nouveau log brut, octet exact ni identifiant d'image n'est
joint à ce message. Il ne remplace pas les fichiers du premier bundle SSH et
n'est pas présenté comme une nouvelle commande SSH exécutée depuis cet
environnement. Les conteneurs en service sont rapportés sains sur `ad10dbc2`,
les candidates présentes mais inutilisées, et `demo_mode` non activé.

**Recontrôle VM reçu après `cd015ed6` : réussi, code de sortie 0.** L'utilisateur
confirme avoir relancé le script sur les images `6dcb0d48` déjà construites,
avec les nouveaux plafonds. Le blocage de budget est donc **levé pour ces images
et ces limites**. Ce résultat porte sur des images existantes ; il n'atteste pas
une construction d'images étiquetées `cd015ed6`. La production reste rapportée
saine sur `ad10dbc2`, sans redéploiement, fusion ni activation du mode démo HANA.

Le compte rendu utilisateur est la source de ce résultat ; aucun nouveau log
SSH brut n'est joint. La clôture ne repose plus seulement sur un calcul de marge,
mais elle n'est pas présentée comme une exécution depuis cet environnement.
Une nouvelle construction reste soumise au contrôle de son propre tag, notamment
ml-ts qui n'a que 11 Mio de marge.

Commande de référence conservée pour reproduire le contrôle des images
`6dcb0d48`, sans build ni bascule de service (la ligne exacte exécutée sur la VM
n'est pas fournie dans le compte rendu) :

```bash
AGENTIUM_IMAGE_BUDGET_MB_BACKEND=1480 \
AGENTIUM_IMAGE_BUDGET_MB_WORKER=1850 \
AGENTIUM_IMAGE_BUDGET_MB_FRONTEND=40 \
AGENTIUM_IMAGE_BUDGET_MB_ML_TS=1240 \
AGENTIUM_IMAGE_BUDGET_MB_LIVEKIT_AGENT=110 \
AGENTIUM_IMAGE_REQUIRE_LIVEKIT_AGENT=1 \
  scripts/agentium-image-budget.sh 6dcb0d48c519
```

Le tag de 12 caractères suit la convention de release ; vérifier qu'il désigne
bien les images construites avant de lancer cette commande. Le script de mesure
seul ne définit aucun budget par défaut. La démo HANA demeure préparée avec TLS
strict et écritures désactivées, sans activation par ce changement de plafonds.

Le changement des défauts est vérifié localement : **10 tests du contrat de
build VM réussissent**, la syntaxe Bash des deux scripts et le contrôle de
conformité passent. Ces vérifications utilisent un Docker simulé pour les tests ;
elles ne reconstruisent aucune image et ne rejouent pas le relevé VM.

## Comparaison locale antérieure des couches OCI

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
le candidat. Les plafonds de ce contrôle historique étaient de 1 400 Mio pour
le backend et 1 760 pour le worker ; la décision ultérieure est consignée en tête.

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

## Premier relevé Docker sur `omnirag-demo`, avant construction candidate

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
Le contrôle de release lit `.Size`, soit 1 422 295 390 octets pour ce backend.
Une valeur d'affichage de `docker image ls` rapportée lors du diagnostic n'est
pas conservée dans le bundle et n'est donc pas utilisée comme preuve ici.

L'[inventaire](evidence/dataops-vm-check-2026-10-14/vm-state.json) examine les
identifiants, tags et révisions de **204 images Agentium**. Il conserve le
compteur, les révisions backend et le résultat de recherche vide, mais pas la
liste exhaustive des 204 images qui permettrait de rejouer cette recherche.
Aucun tag ou label correspondant à `bd724044` ou `a90272c1` n'est rapporté.
Les contrôles de ces tags échouent pour
images manquantes ; ils ne constatent pas un dépassement. Le script de budget
passe pour la référence déployée, mais **ce premier relevé ne permet aucun
verdict VM sur le candidat**. Les calculs OCI de 1 283/1 636 Mio ne deviennent
pas des mesures VM.
L'espace libre sur `/` est de 137 494 495 232 octets au relevé ; aucune archive
n'a été transférée ou chargée et aucune image n'a été construite, tirée ou purgée.
Les identifiants d'images, noms et dates de démarrage des cinq conteneurs contrôlés sont
[identiques après les sondes](evidence/dataops-vm-check-2026-10-14/containers-after.txt).

### Protocole historique d'import, remplacé par la construction VM rapportée

Ce protocole avait été préparé avant la construction VM de `6dcb0d48` rapportée
ci-dessus. Il reste conservé pour la traçabilité des archives locales `bd724044` ;
il n'est plus une étape nécessaire à la décision sur les nouveaux plafonds.

Les deux archives OCI déjà construites portent la révision `bd724044` et les
tags `agentium-backend:dataops-review` / `agentium-worker:dataops-review`.
Le [manifeste de transmission](evidence/dataops-image-reconciliation-2026-10-14/candidate-oci-transfer-manifest.json)
conserve leurs tailles, SHA256 calculés sur les archives entières, descripteurs,
configurations et couches ordonnées. Il ne constate aucun transfert ou import.

Depuis l'environnement local autorisé, la mesure doit suivre ces étapes :

1. Confirmer l'espace disponible sur le stockage de staging et celui de Docker,
   relever l'état des conteneurs et vérifier que les deux tags d'import sont
   absents. Arrêter en cas de collision de tag. Les archives totalisent 2,85 Gio ;
   archives, contenus compressés et couches décompressées représentent ensemble
   environ 13,91 Gio, hors métadonnées et sans déduction des couches partagées.
2. Transférer les deux archives intactes dans un répertoire dédié et vérifier
   leurs SHA256 contre le manifeste. Docker 29.1.3 avec containerd prévoit
   [l'import OCI natif](https://github.com/moby/moby/blob/docker-v29.1.3/daemon/containerd/image_exporter.go#L243)
   ; aucune conversion en Docker-archive n'est nécessaire.
3. Charger les archives l'une après l'autre avec `docker --host=unix:///var/run/docker.sock
   image load --platform linux/amd64 --input CHEMIN_ARCHIVE`. Ce chargement
   ajoute des images au stockage, sans démarrer de conteneur.
4. Vérifier le descripteur, la plateforme, la révision et les `diff_ids` ordonnés
   contre le manifeste, puis lancer le collecteur sur le tag `dataops-review`.
   Conserver les tailles `.Size`, les verdicts backend/worker et les couches
   communes. Les plafonds restent 1 400/1 760 Mio.
5. Conserver aussi le retour global du script : les autres images de cette
   qualification partielle sont absentes, donc il peut échouer malgré deux
   verdicts individuels corrects. Ne pas compléter artificiellement la release
   en retaguant des images de production. Relever à nouveau l'état des conteneurs.

Ce protocole ne construit ni ne démarre de service ; aucune commande de bascule,
de redémarrage ou de purge n'y figure. Les archives mesurent l'artefact `bd724044`,
dont les sources applicatives sont identiques à `6d9395e3`, sans le renommer comme
une nouvelle construction de ce dernier commit. Aucun résultat d'import de ces
archives n'est consigné ; le relevé candidat reçu porte sur une autre construction,
faite directement sur la VM à la révision `6dcb0d48`.

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
réponse **HTTP 400** reçue à la place du protocole SAP HANA. `dbapi.connect`
échoue sans retourner de session ; aucune requête SQL n'est exécutée. Le relevé
ne situe pas précisément l'échec dans la négociation et ne qualifie ni les
identifiants ni la confiance TLS propre au pilote. Les indicateurs d'erreur
d'authentification et de certificat du JSON proviennent de recherches de mots
dans l'exception, pas d'une trace des étapes du protocole.

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

La prochaine vérification utile est une lecture du panneau SAP HANA Cloud :
endpoint SQL exact avec son port, identifiant et état de l'instance, exposition
publique/privée et restrictions d'accès. Les événements de connexion ou de routage
du **14 octobre, 09:00–09:05 heure de Paris** peuvent aider à localiser le rejet.
Ces métadonnées ne nécessitent aucun mot de passe SQL. Si elles correspondent
à la configuration enregistrée, il faut diagnostiquer le rejet au point d'entrée
SAP avant de multiplier les tentatives du pilote. Le certificat wildcard valide
ne prouve pas à lui seul que l'instance SQL attendue est disponible.

Le 14 octobre, l'utilisateur indique que l'instance est probablement indisponible
et qu'il s'agissait d'un essai SAP HANA Cloud de 30 jours. L'expiration du trial
devient une hypothèse prioritaire ; elle n'est pas confirmée par un relevé du
panneau SAP.

### Décision du 14 octobre : démo explicite pour Showcase

L'utilisateur choisit **`demo_mode=true`, TLS strict conservé** pour la prochaine
livraison de `agentium-showcase`. Le choix de service est tranché et le contrôle
de budget des images existantes est passé selon le recontrôle rapporté ci-dessus.
L'activation sur la VM reste à effectuer dans le cadre de la livraison. La
configuration effectivement relevée plus haut précède cette décision et n'a
pas été modifiée par les travaux locaux.

| Périmètre | Valeur retenue |
|---|---|
| Workspace | `agentium-showcase` uniquement |
| Configuration du connecteur | `demo_mode=true`, `encrypt=true`, `ssl_validate_certificate=true` |
| Garde serveur | `HANA_ALLOW_INSECURE_TLS=false`, `HANA_WRITES_ENABLED=false` conservés |
| Hôte, port, compte et secret existants | Conservés ; aucun secret de plateforme ajouté |
| Autres workspaces | Aucune activation automatique ; défaut `demo_mode=false` |

Le contrat choisi est un **repli explicite**, pas un mode hors ligne : query et
preview essaient d'abord HANA. Un résultat synthétique porte
`source=demo_dataset`, et l'aperçu l'annonce comme démonstration. Une connexion
qui redevient disponible peut produire `source=hana_live`. `/hana/test` reste
un test de la configuration enregistrée contre HANA réel, sans repli ; son
échec ne doit pas devenir un faux succès de connexion. `demo_mode` n'interdit
pas à lui seul les écritures, d'où le maintien de la garde serveur désactivée.

L'indisponibilité du HANA vivant n'est pas résolue ni présentée comme telle.
La future recette Showcase devra vérifier le repli déclaré, sa persistance à
la sauvegarde et les gardes d'accès, selon la
[procédure d'activation](ops/hana-security-s0.md#showcase--démo-explicite-retenue-le-14-octobre-2026).

Le formulaire HANA a été corrigé pour conserver `demo_mode`, `encrypt` et
`ssl_validate_certificate` au chargement et à la sauvegarde. Il expose le choix
du repli, garde des valeurs strictes pour une ancienne configuration et signale
une éventuelle exception existante sans ajouter de commande pour désactiver TLS.
Le bouton « Tester la connexion enregistrée » annonce son périmètre et n'envoie
aucun champ ni mot de passe non enregistré. Un aperçu synthétique ne transforme
pas un échec HANA en succès de connexion.

La [validation locale de ce correctif](evidence/hana-showcase-demo-2026-10-14/README.md)
comprend 10 tests de composant HANA, inclus dans **2 204 tests frontend réussis**,
les contrôles i18n/navigation/interface et un `build:prod` réussi. **48 tests
backend HANA ciblés** passent également sous garde réseau, sans sollicitation
réseau. Aucun code backend ni Dockerfile n'est modifié pour ce choix. La suite
backend complète n'est pas relancée. Le build frontend ne constitue pas une
mesure de son image Docker ; une livraison doit embarquer et qualifier ce
frontend corrigé, pas lui attribuer les preuves d'un ancien frontend.

Un écart de qualification reste explicitement conservé : la formulation initiale
du runbook S0 promettait qu'une erreur d'authentification/TLS ne déclencherait
jamais la démo. Dans
`backend/app/services/connectors/hana/service.py`, toutes les exceptions de
`dbapi.connect` deviennent pourtant `HANA_CONNECTION_FAILED`, donc peuvent
déclencher le repli si `demo_mode=true`. Les refus de politique réseau et TLS
restent distincts. Le runbook précise cette limite : le choix de démonstration
ne qualifie ni les identifiants ni la confiance TLS du pilote, et ne relâche
pas ses paramètres TLS.

Les sondes passent par les fonctions de service et une transaction PostgreSQL
`READ ONLY`, pas par `/api/v1/hana/config` ou `/hana/test` en HTTP authentifié.
Le [script de reproduction](evidence/dataops-vm-check-2026-10-14/check_hana_vm.py)
conserve seulement la configuration non secrète, `password_set`, les paramètres
TLS et des erreurs expurgées du mot de passe. Les scripts de seed n'ont pas été
utilisés. Les [48 tests HANA ciblés](evidence/dataops-vm-check-2026-10-14/hana-tests.txt)
passent localement ; ce résultat n'est pas une lecture HANA réussie ni une
nouvelle exécution de la suite backend complète.

Aucune exception TLS ni démo n'est activée sur la VM par cette note. Le choix
de l'utilisateur est enregistré et le blocage de budget des images `6dcb0d48`
est levé avec les plafonds de `cd015ed6`. L'activation du workspace et sa recette
restent à effectuer dans le cadre de la livraison ; ce contrôle de budget ne
les remplace pas. Aucune fusion ni aucun déploiement n'est effectué ici.
