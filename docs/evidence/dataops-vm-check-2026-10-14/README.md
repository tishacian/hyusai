# Relevé SSH DataOps / HANA — 14 octobre 2026

Point de départ : branche DataOps,
commit `a90272c11ecd2ba6770977cb4108aa4c7b1e212a`. Les sources applicatives et
les plafonds sont conservés. Les heures des JSON sont en UTC (Paris : UTC+2).

## Résultats

- `docker-images.json` : Docker 29.1.3, containerd/overlayfs ; budget d'origine
  vert pour les cinq images `ad10dbc2b6cb`. Les tags candidats interrogés sont
  absents ; le retour du collecteur vaut 1 pour cette raison.
- `vm-state.json` : tags et labels de 204 images Agentium inspectés ; aucun
  candidat `bd724044`/`a90272c1` trouvé. Conteneurs et espace disque relevés.
- `containers-after.txt` : mêmes identifiants d'images et dates de démarrage
  pour les cinq conteneurs inspectés après les premières sondes.
- `tls-peer.json` : TCP/443 et TLS 1.3 avec chaîne et nom DNS vérifiés par
  Python/OpenSSL, certificat daté du 8 octobre 2026 au 23 avril 2027.
- `hana-showcase.json` : modules exacts de `a90272c1`, pilote hdbcli 2.29.27
  du backend en service. `test_connection` et la lecture bornée échouent avec
  `HANA_CONNECTION_FAILED` / `-10709` / `RTE:[200121]` / HTTP 400. Le diagnostic
  par nom DNS strict échoue aussi. Aucune ligne SQL vivante obtenue.
- `hana-showcase-a90272c1.json` : première reproduction identique, avant la
  sonde différentielle. Empreintes des deux modules conservées.
- `hana-showcase-sni-diagnostic.json` : essai en mémoire avec la seule addition
  `sslSNIHostname=destination.host` à l'appel `dbapi.connect`. Même HTTP 400 ;
  ce changement n'est pas conservé. Il ne prouve pas une cause SNI.
- `hana-tests.txt` : 48 tests locaux ciblés passent ; ils ne qualifient pas
  l'accès vivant ni l'image candidate complète.

Aucune image construite, tirée, chargée, purgée ou déployée. Aucune modification
de configuration HANA, exception TLS, activation démo, migration ou seed.
Les lectures du secret restent côté serveur ; les messages de pilote sont
expurgés de sa valeur avant sérialisation. La résolution habituelle d'un secret
peut produire un événement d'audit applicatif. La transaction de lecture de la
configuration est explicitement `READ ONLY` et terminée par `rollback`.

## Reproduction des contrôles principaux

Depuis la racine du checkout, sans installer de fichier sur la VM :

```bash
ssh -o BatchMode=yes -o ConnectTimeout=15 omnirag-demo \
  'python3 - --tag ad10dbc2b6cb --tag bd724044 --tag a90272c1' \
  < docs/evidence/dataops-image-reconciliation-2026-10-14/measure_vm_images.py \
  > /tmp/dataops-docker-images.json

python3 docs/evidence/dataops-vm-check-2026-10-14/check_hana_vm.py \
  > /tmp/dataops-hana-showcase.json
```

Les deux commandes renvoient 1 dans l'état observé : images candidates absentes
pour la première, échec vivant HANA pour la seconde. Le JSON est conservé sur
échec. La sonde HANA charge uniquement les modules de politique réseau et de
service du checkout, en mémoire dans un processus séparé ; elle n'est ni un
service déployé ni un test HTTP authentifié. Elle refuse de relâcher la validation
TLS. Ses requêtes sont le test DUMMY du connecteur et `SELECT 1 FROM DUMMY`,
avec transaction HANA en lecture seule pour cette dernière. La connexion DNS
diagnostique désactive seulement l'épinglage dans ce processus, garde TLS strict
et n'est pas une modification du connecteur.

Validation locale, avec le venv existant et une base SQLite temporaire :

```bash
cd backend
/private/tmp/dataops-venv/bin/python -m pytest \
  app/tests/services/test_hana_security.py \
  app/tests/services/test_hana_preview.py \
  app/tests/api/test_hana_rpa_admin_api.py -q
```

Les empreintes de `bundle-index.json` couvrent les fichiers de ce répertoire,
à l'exception de l'index lui-même. Les preuves des reconstructions OCI locales
restent dans leur répertoire d'origine ; aucune valeur de 3 420/3 567 Mio n'est
remplacée par une taille compressée ni présentée comme une mesure du candidat
sur la VM.
