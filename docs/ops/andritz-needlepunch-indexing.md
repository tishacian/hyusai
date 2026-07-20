# Runbook d'indexation transverse Andritz Needlepunch

Ce runbook decrit la promotion controlee du depot
`Notices_Techniques_Needlepunch/` vers la collection autoritative existante
`andritz-notices-techniques-spl-pilot` du workspace `andritz`.

Il ne cree pas une nouvelle collection et ne modifie pas les bindings du chat.
Le chat classique comme le chat Agentic doivent continuer a toucher exactement
`andritz-notices-techniques-spl-pilot`, sans fallback vers une autre collection
du workspace.

## Invariants

- La promotion reste une action operateur. Il n'existe pas d'auto-promotion a
  l'arrivee SFTP.
- Un dry-run inspecte est obligatoire. L'execution exige le SHA-256 complet du
  plan inspecte ; toute derive du corpus invalide l'autorisation.
- Les originaux ne sont pas copies de facon persistante vers MinIO. Le manifeste
  conserve un localisateur `secure_deposit_file` ou
  `secure_deposit_zip_member` et le worker lit `/data/secure_deposit` en lecture
  seule. Un fichier direct est expose au parser par symlink verifie ; un membre
  ZIP est streame dans le repertoire temporaire borne du job. Les derives
  texte/BM25 et les points Qdrant restent, eux, persistants.
- Un fichier reste `received` jusqu'au postflight complet de sa vague. Le succes
  du worker laisse `postflight_status=pending`; seul le runner, apres les gates
  source/Qdrant/capacite, peut passer le depot a `promoted`. Pour un ZIP multi-
  vagues, il attend en plus que tous les membres eligibles soient terminaux.
- Une vague est incrementale. Un echec ne doit ni rendre l'ancienne collection
  indisponible, ni supprimer ses chunks anterieurs.
- Une source promue et referencee par un `source_locator` est une source
  retenue. Son original Secure Deposit ne doit jamais etre traite comme un
  orphelin nettoyable.
- L'identite de deduplication documentaire est
  `(content_sha256, project_code)`. Le meme contenu dans deux projets reste
  citable dans chacun des projets.
- La reprise s'appuie sur `DepositFile`, `WorkerJob`,
  `KnowledgeCollectionSource` et le manifeste de collection, jamais sur une
  liste exhaustive rangee dans `workspace.settings`.
- `baseline_document_names`, `baseline_document_count` et
  `baseline_chunk_count` sont figes ensemble dans le manifeste du job avant la
  mutation. Dispatch echoue, timeout rearmable et rollback doivent restaurer
  cette baseline atomiquement ; une baseline absente ou incoherente met la
  collection en quarantaine, jamais artificiellement `ready`.
- Le lease `postflight=pending` bloque toute vague suivante, mais n'est pas une
  barriere de lecture : la collection reste `ready` et les nouveaux points
  peuvent etre visibles pendant la courte fenetre entre worker et verdict. Le
  runner doit donc rester proprietaire du flux jusqu'a verification ou rollback.

## Identite projet

Deux schemas coexistent dans la meme collection :

| Source | Schema | Exemple | Regle |
| --- | --- | --- | --- |
| SPL historique | alphanumerique | `BAO100`, `BCX200`, `ELM001Y` | Grammaire SPL existante, sans regression |
| Needlepunch | `needlepunch_numeric5` | `61035`, `70170` | Seulement le dossier projet directement sous une plage autoritative |

Un chemin Needlepunch valide est de la forme :

```text
Notices_Techniques_Needlepunch/<borne-basse>-<borne-haute>/<code a 5 chiffres + libelle>/...
```

Le code doit appartenir a la plage parente. Ne jamais chercher un autre nombre
dans les sous-dossiers ou les noms de fichiers. `TTN17829J`, `V10234` et
`10000 rpm` ne sont pas des projets.

La source promue doit porter au minimum :

```text
project_code
project_reference_kind = andritz_project
project_code_scheme = needlepunch_numeric5
business_scope = needlepunch
project_range
project_folder
source_deposit_path
source_deposit_file_id
wave_id
source_locator
```

Ne pas remplir `initial_buyer_code` ou `project_position` pour Needlepunch.

## Etat initial et dispositions

Baseline observee avant campagne : 17 749 lignes de depot, 629 projets et
environ 159 Gio, toutes au statut `received`. Le rapport de campagne doit
classer chaque ligne selectionnee dans une disposition explicite :

- `eligible` : source traitable par la campagne courante et prise dans une
  vague bornee ;
- `deferred_direct` : document direct rencontre pendant une campagne
  `legacy` ou `zip`, a reprendre avec `--campaign direct` ;
- `deferred_legacy` : XLS rencontre pendant une campagne `direct` ou `zip`, a
  reprendre avec `--campaign legacy`. Un PPT reste differe ou unsupported tant
  que sa fixture de conversion n'est pas validee ;
- `deferred_zip` : archive rencontree hors campagne ZIP, a reprendre avec
  `--campaign zip` ;
- `unsupported` : chemin incoherent, fichier vide, format non documentaire,
  executable ou limite de taille depassee, avec une raison durable ;
- deja enregistree : identite `deposit_file_id + SHA` deja presente dans le
  ledger de la collection ; l'execution est un no-op terminal.

Les dispositions `deferred_*` sont relatives a la campagne du plan : elles ne
modifient pas le depot et deviennent `eligible` uniquement dans la campagne
explicitement indiquee, apres un nouveau dry-run et un nouveau hash approuve.

Le rapport final des deux plages doit rendre compte des 17 749 lignes, y compris
les formats non exploitables. Le facet final `project_code` doit correspondre
exactement aux codes eligibles attendus, normalement 629 projets.

## Prerequis de deploiement

Ne lancer aucun canary avant que ces points soient vrais :

1. Le resolver source-aware, l'importeur, les parsers legacy et la resolution
   preview/download sont deployes, sans indexation automatique au demarrage.
2. Le worker CPU monte le meme Secure Deposit que le backend sur
   `/data/secure_deposit`, en lecture seule.
3. LibreOffice Writer et Calc sont disponibles dans l'image worker pour `.doc`
   et `.xls` ; `.ppt` reste differe jusqu'a validation d'une fixture.
4. La collection `andritz-notices-techniques-spl-pilot` existe et reste `ready`.
5. Les bindings du scope/chat pointent toujours vers cette collection exacte.
6. Une sauvegarde Postgres restauree en exercice et un snapshot Qdrant stocke
   hors du disque local existent.
7. Les probes Qdrant sont vertes et aucun job d'ingestion concurrent n'est en
   cours.

Le runner considere comme bulk toute selection `--range`, plusieurs options
`--project`, toute invocation avec `--max-waves` superieur a 1, ou tout plan
calcule contenant plusieurs vagues. Dans ces cas, le preflight exige :

- `--estimated-docker-growth-bytes` et
  `--estimated-deposit-growth-bytes`, mesures a partir des canaries ;
- au moins 250 Gio actuellement libres sur le volume Docker/MinIO/Qdrant et
  250 Gio sur le volume Secure Deposit ;
- une projection de croissance avec marge x2 qui laisse encore au moins 25 %
  libre cote Docker et 15 % libre cote depot.

Une estimation absente ou negative, une croissance Docker nulle, un plancher
absolu non atteint ou un ratio projete sous le seuil bloque le preflight avant
toute mutation.

La baseline observee avant ce chantier etait d'environ 64 Gio libres sur le
volume Docker/local et 54 Gio libres sur le volume Secure Deposit. Elle est
insuffisante pour le bulk. Le no-copy evite une seconde copie des 159 Gio
d'originaux dans MinIO, mais ne supprime ni les points Qdrant, ni les artefacts
derives, ni l'espace temporaire des conversions et membres ZIP.

Les limites applicatives ne sont pas une reservation de capacite : une vague
peut contenir au plus 100 sources et 2 Gio, mais l'operateur doit arreter avant
ces plafonds si les seuils de disque libre ci-dessus seraient franchis. Le
repertoire temporaire du worker vit sur le stockage writable du conteneur ; le
montage `/data/secure_deposit` reste strictement en lecture seule. Preview, raw
et conversion Office reutilisent le meme locator et echouent de facon fermee :
un locator invalide ne retombe jamais sur un original homonyme legacy.

## Dry-run

Depuis un environnement applicatif de developpement configure, le dry-run est
le comportement par defaut. Cette forme locale sert aux fixtures et aux tests ;
elle ne voit le corpus VM que si Postgres et le Secure Deposit sont tous deux
explicitement configures et montes. Ne jamais pointer une copie locale vers la
base de production avec un chemin Secure Deposit absent.

L'option explicite reste recommandee dans les journaux operateur :

```sh
cd backend
python -m scripts.promote_notice_wave \
  --workspace andritz \
  --profile needlepunch \
  --campaign direct \
  --project 61035 \
  --collection andritz-notices-techniques-spl-pilot \
  --dry-run
```

Sur la VM Docker, executer la meme commande dans le conteneur backend deploye,
pas depuis une copie de travail non versionnee :

```sh
docker exec agentium-backend python -m scripts.promote_notice_wave \
  --workspace andritz \
  --profile needlepunch \
  --campaign direct \
  --project 61035 \
  --collection andritz-notices-techniques-spl-pilot \
  --dry-run
```

Inspecter et archiver le JSON complet. Verifier au minimum :

- `collection_slug`, `profile_slug`, `campaign`, `source_prefix`, projets et
  plage ;
- `plan_hash` complet ;
- `disposition_counts` et raisons ;
- chaque `source_count`, `total_bytes` et `large_source_isolated` ;
- maximum 100 sources et 2 Gio par vague ;
- tout fichier de plus de 100 Mio isole dans sa propre vague ;
- noms logiques uniques, extension conservee, longueur inferieure ou egale a
  220 caracteres et suffixe SHA present ;
- aucune classification projet issue d'un nom de piece ou d'un sous-dossier.

`--summary-only` sert a la lecture rapide mais ne remplace pas l'archivage du
plan complet approuve.

## Execution d'une vague

Rejouer le dry-run juste avant l'execution. Copier son hash sans le tronquer :
L'execution exige aussi `--actor-email` : cet utilisateur doit etre actif,
membre du workspace cible, et autorise a promouvoir un depot via un role
`workspace_reviewer`, `workspace_admin` ou `workspace_owner` (les roles legacy
`admin`/`owner` restent compatibles). Il n'existe aucun acteur implicite de
repli.

`scripts.promote_notice_wave` est strictement un planificateur : il ne met
jamais de job en file et n'accepte ni `--execute`, ni `--plan-hash`, ni
`--actor-email`. Toute execution passe exclusivement par
`scripts.run_notice_campaign`, qui applique les gates de capacite, de sante et
de parite, attend le job, effectue le postflight puis borne le rollback au
`wave_id` en cas d'echec.

Executer d'abord le preflight du runner, sans `--execute` :

```sh
docker exec agentium-backend python -m scripts.run_notice_campaign \
  --workspace andritz \
  --profile needlepunch \
  --campaign direct \
  --project 61035 \
  --collection andritz-notices-techniques-spl-pilot \
  --plan-hash <sha256-complet> \
  --start-wave 1 \
  --max-waves 1 \
  --docker-capacity-path /data/object_store \
  --deposit-capacity-path /data/secure_deposit
```

Apres validation du preflight et d'une vraie sauvegarde restauree en exercice,
rejouer la meme commande avec :

```sh
  --execute \
  --actor-email <email-operateur> \
  --snapshot-ref <reference-immuable-reelle>
```

La reference de snapshot doit identifier les artefacts effectivement crees et
verifies ; une valeur fictive contournerait seulement un controle syntaxique et
n'est pas une sauvegarde. Si le plan contient plusieurs vagues, avancer avec
`--start-wave <n> --max-waves 1` et ne lancer qu'une vague a la fois. Un
changement de fichier, SHA, taille, chemin ou selection provoque un refus pour
derive du plan : refaire le dry-run et la revue, ne jamais contourner ce
controle.

L'execution ne doit creer qu'un job `document_ingest_index` avec :

```json
{
  "mode": "incremental",
  "document_names": ["..."],
  "wave_id": "needlepunch-...",
  "source_profile": "needlepunch"
}
```

Une vague ne contenant que des doublons est un succes terminal. Elle ne doit pas
lancer un rebuild complet de la collection.

Si le broker worker est indisponible, le dispatch echoue immediatement, sans
fallback inline : le `WorkerJob` passe `failed` au stage `dispatch_failed`, les
sources passent `error`, les depots restent `received` et la collection reste
`ready`. Cette erreur est rearmable : apres retablissement du broker, rejouer le
meme plan approuve cree un nouveau job et remet les sources concernees en
`queued`. Ne jamais laisser ni transformer manuellement l'ancien job en
`queued`.

## Validation apres chaque vague

Ne passer au canary suivant que lorsque tous ces controles sont verts :

1. Le `WorkerJob` est `completed`, son manifeste contient le `wave_id`
   attendu et le runner l'a ensuite passe a `postflight_status=verified` /
   `stage=postflight_verified`. `completed` seul n'est pas une approbation.
2. La collection reste `ready`; son corpus historique est toujours
   interrogeable.
3. Apres ce postflight seulement, chaque `DepositFile` reussi est `promoted`
   vers `andritz-notices-techniques-spl-pilot`. Pendant le lease pending il
   reste `received`; un echec ou un rollback reste `received`.
4. Chaque `KnowledgeCollectionSource` est `ready` ou `deduplicated` avec toutes
   les metadonnees projet et son `source_locator`.
5. Le nombre de chunks Postgres/ledger et Qdrant est coherent ; aucun document
   eligibile n'a zero chunk sans raison explicite.
6. Un filtre Qdrant exact `project_code=<code>` ne retourne aucun chunk d'un
   autre projet.
7. Preview et telechargement fonctionnent depuis la source no-copy pour un PDF,
   un document Office et, lors de la campagne ZIP, un membre d'archive. Les
   routes raw et conversion Office servent un fichier verifie/borne et ne
   chargent pas un original de plusieurs centaines de Mio en memoire API.
8. Le chat classique et le chat Agentic retournent
   `collections_touched = ["andritz-notices-techniques-spl-pilot"]` exactement.
9. La latence p95 se degrade de moins de 20 % et Qdrant reste vert.
10. Sont releves : octets de chunks, artefacts derives, pic temporaire, duree et
    cout d'embedding de la vague.

Jeu fonctionnel minimal :

```text
resume 61038
resume le projet 61038
compare les projets 61038 et 61035
inventaire du projet 61038
et ses pieces ?
```

Verifier egalement que `TTN17829J`, `V10234` et `10000 rpm` ne declenchent pas
de filtre projet, et que `BAO100`, `BCX200` et `ELM001Y` restent reconnus.

## Canaries et campagne

Ordre impose :

1. `61035` : deux PDF ; prouver que `TTN17829J` n'est jamais un projet.
2. `61001` : seize PDF et un DOC.
3. `61009` : corpus DOC legacy.
4. `61119`, puis `61121` : verifier que le contenu partage reste accessible et
   cite dans les deux projets.
5. `70380` : stress 70xxx/2 Gio, seulement apres extension de capacite.

Apres les canaries : plage `60000-69999`, golden complet, soak de 24 heures,
puis plage `70000-79999`. Utiliser un seul worker d'ingestion. Les ZIP et formats
legacy non encore qualifies forment une campagne separee.

Le runner fail-closed est `python -m scripts.run_notice_campaign`. Il revalide
avant et apres chaque vague : hash du plan, snapshot hors hote reference,
collection `ready`, Qdrant vert, parite de chunks PostgreSQL/Qdrant, absence de
fuite sur le filtre exact `project_code`, zero-chunk inexplique et seuils disque.
Il s'arrete au premier ecart ou job non `completed`. Par securite il ne lance
qu'une vague par invocation par defaut ; augmenter `--max-waves` est une action
operateur explicite (maximum 100).

`--start-wave N` n'est pas un saut libre. Avant d'accepter `N > 1`, le runner
prouve chacune des vagues `1..N-1` avec un job `document_ingest_index`
`completed`, le `wave_id` exact du plan, les sources terminales attendues,
l'absence de zero-chunk inexplique et les gates Qdrant/collection courants. Une
preuve manquante ou obsolete bloque la reprise.

Le timeout `--job-timeout-seconds` vaut 7200 secondes par defaut. Si le job est
encore strictement `queued` et que la portee job/wave/sources/depots ainsi que
la baseline sont prouvees, le runner effectue atomiquement CAS
`queued -> failed`, marque les sources en erreur, remet les depots `received`
et restaure la baseline ; le meme plan peut alors creer un nouveau job. Un job
`running` n'est jamais annule ni rearme : l'inspecter ou attendre, puis rejouer
la meme vague. Si un job queued ne peut pas etre rearme sans preuve complete,
la collection est mise en quarantaine.

Un job termine Needlepunch dont `postflight_status=pending` bloque egalement la
vague suivante, y compris pour les campagnes ZIP. Le runner reste proprietaire
du verdict ; ce lease n'empeche pas la lecture transitoire de la collection.

Preflight sans mutation :

```sh
docker exec agentium-backend python -m scripts.run_notice_campaign \
  --workspace andritz \
  --campaign direct \
  --project 61035 \
  --plan-hash <sha256-complet> \
  --docker-capacity-path /data/object_store \
  --deposit-capacity-path /data/secure_deposit
```

Execution d'une seule vague apres preflight :

```sh
docker exec agentium-backend python -m scripts.run_notice_campaign \
  --workspace andritz \
  --campaign direct \
  --project 61035 \
  --plan-hash <sha256-complet> \
  --start-wave 1 \
  --max-waves 1 \
  --execute \
  --actor-email <email-reviewer-ou-admin-workspace> \
  --snapshot-ref <reference-backup-postgres-qdrant-hors-hote> \
  --docker-capacity-path /data/object_store \
  --deposit-capacity-path /data/secure_deposit
```

Preflight bulk d'une plage, avec estimations exprimees en octets avant la marge
x2 :

```sh
docker exec agentium-backend python -m scripts.run_notice_campaign \
  --workspace andritz \
  --campaign direct \
  --range 60000-69999 \
  --plan-hash <sha256-complet> \
  --start-wave 1 \
  --max-waves 2 \
  --estimated-docker-growth-bytes <croissance-docker-mesuree-en-octets> \
  --estimated-deposit-growth-bytes <croissance-depot-mesuree-en-octets> \
  --docker-capacity-path /data/object_store \
  --deposit-capacity-path /data/secure_deposit
```

Conserver exactement les memes estimations, selecteurs et chemins lors de
l'execution approuvee ; ajouter alors `--execute`, `--actor-email` et
`--snapshot-ref`.

Le controle de latence p95 et le soak de 24 heures restent des gates de
campagne externes : ne pas enchainer la plage suivante avant leur validation.

## ZIP et formats non directs

Les campagnes sont explicites : `--campaign direct` (defaut),
`--campaign legacy` ou `--campaign zip`. Le type de campagne et le prefixe
optionnel `--prefix` font partie du plan hashe ; ils doivent etre identiques au
dry-run et a l'execution.

Les ZIP ne sont pas promus par la campagne directe. La campagne ZIP doit d'abord
inspecter l'index central, rejeter traversal, chiffrement et zip-bombs, puis
extraire temporairement un membre valide a la fois. Il n'y a pas de recursion
automatique dans une archive imbriquee.

L'inspection ZIP applique les bornes suivantes avant execution : au plus 10 000
membres non-repertoires, au plus 4 Gio non compresses au total, ratio de
compression au plus 500, et au plus 512 Mio pour un membre. Les membres
imbriques ZIP, les liens symboliques, les membres proteges par chiffrement, les
chemins dupliques ou dangereux et les formats non documentaires restent
`unsupported` avec leur raison.

Une archive sure peut couvrir plusieurs vagues bornees. Ses membres ne sont
jamais melanges avec ceux d'une autre archive dans la meme vague. Le
`DepositFile` reste `received` apres chaque vague partielle et ne devient
`promoted` que lorsque le nombre cumule de sources `ready` ou `deduplicated`
atteint la couverture eligible approuvee pour le SHA immuable de l'archive.
Executer les vagues sequentiellement avec
`--start-wave <n> --max-waves 1` ; le verrou de collection refuse toute seconde
ingestion encore `queued` ou `running`.

Pour une source directe ou legacy, `size_bytes` doit tenir dans le champ
PostgreSQL `INTEGER`, soit au plus `2^31 - 1` octets (2 147 483 647). Une source
individuelle au-dela reste `unsupported` avec
`source_exceeds_source_ledger_limit`, meme si le budget agrege d'une vague est
de 2 Gio. Un ZIP est un conteneur Secure Deposit et peut lui-meme depasser cette
limite sans inscrire sa taille dans le ledger des sources : seuls ses membres
valides y sont inscrits. Chaque membre reste borne a 512 Mio, le total
decompresse a 4 Gio et chaque vague de membres a 100 sources/2 Gio.

Le dry-run ZIP lit et hash le contenu de l'archive et de ses membres eligibles,
mais ne les extrait pas de facon persistante. Il peut donc etre couteux en I/O
meme s'il n'ecrit ni chunks ni originaux.

Exemple d'inspection ZIP sans execution :

```sh
docker exec agentium-backend python -m scripts.promote_notice_wave \
  --workspace andritz \
  --profile needlepunch \
  --campaign zip \
  --project 61035 \
  --collection andritz-notices-techniques-spl-pilot \
  --dry-run
```

Formats de la campagne directe : PDF, DOC, DOCX, HTML, TXT, XLSX et images OCR.
La campagne legacy traite XLS apres conversion LibreOffice Calc. Les rares PPT
restent `received` jusqu'a validation d'une conversion. Les formats industriels
et executables restent eux aussi `received`, avec la raison durable
`unsupported`.

## Reprise et rollback

Pour reprendre une execution interrompue :

1. retrouver le `WorkerJob` et le `wave_id` ;
2. comparer le manifeste, les `KnowledgeCollectionSource` et les
   `DepositFile` ;
3. refaire un dry-run ;
4. si la vague est deja enregistree, accepter le no-op terminal ;
5. sinon, n'executer le nouveau plan qu'apres une nouvelle revue operateur.

Un echec de dispatch broker n'est pas une vague partiellement indexee : une fois
le broker retabli, la reprise reexecute le meme hash et rearme les sources dans
un nouveau job, comme decrit dans la section d'execution.

Lorsqu'une vague incrementale echoue apres un upsert partiel, le rollback
automatique du worker supprime d'abord les points Qdrant par filtre exact
`wave_id`. Si le backend vectoriel ne confirme pas cette suppression filtree,
il se replie sur les `document_id` effectivement retournes par cette vague. Les
facts SQL de ces memes documents sont egalement retires, les sources passent en
`error`, les depots restent `received` et la collection precedente revient a
`ready` uniquement si la suppression est confirmee. Si ni le filtre `wave_id`
ni le fallback par `document_id` ne confirment le rollback, la collection passe
en `error` pour ne jamais exposer une vague partielle : stopper la campagne et
restaurer/resoudre depuis le snapshot avant toute reprise.

Ce rollback automatique par `wave_id` est implemente pour la vague courante en
echec ; il ne constitue pas une commande de suppression d'une vague deja
validee. Un rollback operateur d'une vague validee ne doit viser que la derniere
vague et doit suivre une procedure revue. Un rollback plus ancien exige le
snapshot ou la resolution prealable des dependances de deduplication.

Cas distinct : si le worker termine mais que le postflight du runner rejette la
vague (parite, isolation, zero-chunk ou capacite), la collection est d'abord
mise en quarantaine `error`. Le recovery tente ensuite une suppression Qdrant
strictement bornee par le `wave_id` rejete et exige le retour au nombre exact de
chunks d'avant vague. Si cette preuve reussit, facts, ledger, depots et sidecar
de collection BM25 sont nettoyes ou invalides pour ne pas servir les hits
rejetes, puis la baseline `document_names`, `document_count` et
`chunk_count` est restauree ensemble et la collection revient `ready`. Le job
reste `failed` avec le stage `postflight_rolled_back` et les depots redeviennent
`received`. Si la
suppression ou la cardinalite n'est pas confirmee, la quarantaine reste active,
le job devient `failed`/`postflight_rollback_unconfirmed` et aucune vague
suivante ne doit etre lancee avant restauration ou resolution depuis le
snapshot.

Une baseline manquante, mal typee ou incoherente est elle-meme un echec de
postflight : ne jamais reconstruire les compteurs a partir d'une collection
partiellement modifiee et ne jamais forcer `ready`.

## Tests locaux avant deploiement

```sh
backend/.venv/bin/python -m pytest -q \
  backend/app/tests/services/test_project_references.py \
  backend/app/tests/services/test_secure_deposit.py \
  backend/app/tests/services/test_notice_wave_importer.py \
  backend/app/tests/services/test_notice_campaign_guard.py \
  backend/app/tests/services/test_collection_source_backing.py \
  backend/app/tests/services/test_spreadsheet_parser.py \
  backend/app/tests/services/test_knowledge_collections_worker.py \
  backend/app/tests/services/test_notice_campaign_recovery.py \
  backend/app/tests/api/test_documents_preview_chunks.py \
  backend/app/tests/scripts/test_promote_notice_wave_cli.py \
  backend/app/tests/scripts/test_run_notice_campaign.py
```

Ces tests ne remplacent ni les snapshots, ni les controles de capacite, ni les
goldens chat sur la collection reelle.
