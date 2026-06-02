# Andritz data indexing context - 2026-06-02

Cette note fige le contexte data et les diagnostics effectues sur le workspace
`andritz` autour des collections Knowledge, du depot SFTP connecte a Agentium et
des questions de test metier Andritz.

Elle complete le Knowledge Guide SPL :
[`docs/andritz-notices-techniques-spl-knowledge-guide.md`](./andritz-notices-techniques-spl-knowledge-guide.md).

## TL;DR

- La collection indexee `andritz-notices-techniques-spl-pilot` ne couvre pas
  encore correctement les questions metier sur les cardes.
- Le SFTP contient bien de la donnee carde/carding dans `Notices_Techniques_SPL`,
  mais une grande partie est encore au statut `received`, donc non exploitable
  par le chat/retrieval.
- `BHX100` est present dans les fichiers recus non promus, notamment
  `Manual_BHX100_revA-D.zip`. C'est le candidat prioritaire pour les questions
  expert sur carde/TMS/TCF/EXCELLE.
- `COL100`, `KRU001Y` et `DRU006` n'ont pas ete retrouves dans les fichiers
  visibles du depot Andritz au moment du diagnostic. Si les questions associees
  restent dans le jeu de test, il faut demander a Andritz de retransmettre ces
  dossiers ou confirmer leur chemin exact.
- `Manual_ASY100.zip` est marque `promoted` vers
  `andritz-notices-techniques-spl-pilot`, mais Qdrant contient `0` chunk pour
  `archive_name=Manual_ASY100.zip` et `project_code=ASY100`. La promotion est
  donc incomplete ou metadata-only pour le retrieval actuel.
- Le concept `BBA120`, `BHX100`, `AKK200`, etc. doit rester interprete comme une
  reference projet stable, pas comme une machine.

## Rappel du modele metier projet Andritz

Les references de type `XXX123` sont des references projet stables.

- Les trois premieres lettres correspondent au premier buyer/client historique.
- Le nombre correspond a une position ou phase dans la chaine projet.
- Une reference projet represente un agencement de machines et equipements dans
  une ligne, pas une machine unique.
- La reference ne change pas si la ligne est revendue a un autre client.
- Les machines/equipements doivent etre identifies uniquement quand ils sont
  nommes dans les notices : carde, TMS, TCF, EXCELLE, injector, pump, damper,
  sensor, jetlace, etc.

## VM et services a utiliser

VM de demo :

- Host : `agentium.papai.ai`
- SSH : `ubuntu@agentium.papai.ai`
- Repo applicatif : `/home/ubuntu/omnirag`
- Backend container : `agentium-backend`
- Postgres container : `agentium-pg`
- Qdrant container/service : `qdrant`
- SFTP container : `agentium-sftp`
- Stockage depot securise monte dans le backend :
  `/data/secure_deposit/`

Exemple de chemin reel pour une archive recue :

```text
/data/secure_deposit/workspaces/0cce0bee-7e86-485d-95b1-672e82f16600/secure-deposit/I6UUw3U9VbH6dAbBT-Q/20692c03-f9c9-4e90-8d87-52f3f47fbccd/Notices_Techniques_SPL/B/Manual_BHX100_revE.zip
```

Le chemin est reconstruit avec :

```text
/data/secure_deposit/{deposit_files.object_key}
```

Il ne faut pas supposer que les fichiers sont dans le repo Git. Les fichiers SFTP
sont dans le depot securise VM et les index dans Postgres/Qdrant.

## Collections Knowledge observees

Etat releve le 2026-06-02 :

| Collection | Vector collection | Documents | Chunks | Role |
| --- | --- | ---: | ---: | --- |
| `andritz-notices-techniques-spl-pilot` | `andritz__andritz-notices-techniques-spl-pilot` | 2355 | 2693 | Notices SPL projet, collection principale du diagnostic |
| `andritz-manuals-bba120-pilot` | `andritz__andritz-manuals-bba120-pilot` | 22 | 568 | Ancienne collection pilote BBA120 |
| `andritz-non-wovens-france-excel-pilot` | `andritz__andritz-non-wovens-france-excel-pilot` | 25 | 4998 | Excel Non-Wovens France |
| `andritz-non-wovens-pilot-archive` | `andritz__andritz-non-wovens-pilot-archive` | 25 | 45 | Archive pilote non-wovens, utile pour `card settings` |

Commande pour verifier :

```sh
ssh ubuntu@agentium.papai.ai 'docker exec -i agentium-backend python - <<'"'"'PY'"'"'
import os, psycopg2
conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()
cur.execute("""
select slug, vector_collection_name, document_count, chunk_count
from knowledge_collections
where slug like %s
order by slug
""", ("%andritz%",))
for row in cur.fetchall():
    print(row)
PY'
```

## Flux d'indexation observe

Le flux attendu est :

1. Fichier depose via SFTP/portail.
2. Ligne creee dans `deposit_files` avec `status='received'`.
3. Promotion manuelle vers une collection Knowledge.
4. `deposit_files.status` passe a `promoted`, avec :
   - `promoted_collection_slug`
   - `promotion_result`
   - parfois `worker_job_id`
5. Extraction archive + filtrage fichiers supportes.
6. Chunking + embeddings.
7. Points Qdrant crees dans la collection vectorielle.
8. Facts documentaires/tableaux alimentes dans :
   - `knowledge_document_facts`
   - `knowledge_table_facts`
9. `knowledge_collections.document_count` et `chunk_count` sont mis a jour.

Important : `knowledge_collections.document_names` peut contenir des documents qui
ne sont pas effectivement presents dans Qdrant. Le cas `Manual_ASY100.zip` montre
qu'il faut toujours verifier Qdrant, pas seulement `document_names`.

## Etat `Notices_Techniques_SPL`

Releve Postgres sur le workspace `andritz` :

| Statut | Nombre | Taille |
| --- | ---: | ---: |
| `promoted` | 8 fichiers | ~3.2 GB |
| `received` | 47 fichiers | ~51 GB |
| `rejected` | 605 fichiers | ~1.9 TB |

Les `rejected` observes sont principalement des doublons/retry cleanup, pas un
corpus utilisable en l'etat.

Commande de comptage :

```sh
ssh ubuntu@agentium.papai.ai 'docker exec -i agentium-backend python - <<'"'"'PY'"'"'
import os, psycopg2
conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()
cur.execute("""
select status, count(*) as files, sum(size_bytes) as bytes
from deposit_files df
join workspaces w on w.id = df.workspace_id
where w.slug = %s
  and df.filename like %s
group by status
order by status
""", ("andritz", "Notices_Techniques_SPL/%"))
for status, files, bytes_ in cur.fetchall():
    print(status, files, round((bytes_ or 0) / 1024 / 1024, 1), "MB")
PY'
```

## Archives SPL promues

Archives `Notices_Techniques_SPL` observees comme promues :

- `Notices_Techniques_SPL/A/ACO_130.zip`
- `Notices_Techniques_SPL/A/ACO140.zip`
- `Notices_Techniques_SPL/A/ACO150.zip`
- `Notices_Techniques_SPL/A/AKK200.zip`
- `Notices_Techniques_SPL/A/ARA200.zip`
- `Notices_Techniques_SPL/A/Manual_ASY100.zip`
- `Notices_Techniques_SPL/B/Manual_BBA120.zip`
- `Notices_Techniques_SPL/D/DCI 110.zip`

Promotions notables :

- `AKK200.zip` : `promoted`, mode `spl_v2_2`, 394 fichiers supportes.
- `Manual_BBA120.zip` : `promoted`, mode `spl_wave_v1`, 22 fichiers supportes.
- `Manual_ASY100.zip` : `promoted`, mode `spl_v3_1`, 1889 fichiers supportes,
  31 fichiers tronques, mais absence de chunks Qdrant constatee.

## Diagnostic `carde` / `carding`

### Dans la collection indexee

Dans `andritz-notices-techniques-spl-pilot`, les recherches factuelles donnent :

- `carde` : 0 occurrence utile dans `knowledge_document_facts`
- `carding` : 0
- `Card documentation` : 0
- `TMS` : 0 dans les facts documentaires
- `TCF` : 0 dans les facts documentaires
- `EXCELLE` : 0
- `BHX100` : 0
- `ASY100` : 0

Il existe quelques faux positifs ou mentions faibles autour de `card`, notamment :

- `AKK200-Functional analysis revA.pdf` : mention de l'equipement amont
  `(card)`, sans contenu carde detaille.
- `Manual_BBA120 Chapter 01` : faux positif type `protection card`.

Conclusion : le retrieval sur `andritz-notices-techniques-spl-pilot` ne peut pas
repondre correctement aux questions carde/BHX100 avec l'index actuel.

### Dans le SFTP non promu

Le scan des noms de fichiers internes ZIP, sans extraction complete, montre que
le corpus non promu contient bien de la donnee carde/carding.

Archives prioritaires detectees :

| Archive | Statut | Entries | Hits card/carding | Hits spare/wire | Hits techniques |
| --- | --- | ---: | ---: | ---: | ---: |
| `Notices_Techniques_SPL/A/Manual_ACJ200-revA.zip` | received | 1324 | 106 | 86 | 78 |
| `Notices_Techniques_SPL/B/Manual_BHX100_revD.zip` | received | 3339 | 96 | 78 | 116 |
| `Notices_Techniques_SPL/B/Manual_BCX300 rev C.zip` | received | 2500 | 90 | 82 | 94 |
| `Notices_Techniques_SPL/A/AVA500.zip` | received | 889 | 69 | 5 | 25 |
| `Notices_Techniques_SPL/B/Manual_BAO100.zip` | received | 1779 | 66 | 64 | 64 |
| `Notices_Techniques_SPL/A/Manual_ASY200.zip` | received | 2009 | 64 | 52 | 52 |
| `Notices_Techniques_SPL/B/Manual_BHX100_revA.zip` | received | 2042 | 58 | 78 | 94 |
| `Notices_Techniques_SPL/B/Manual_BHX100_revB.zip` | received | 2042 | 58 | 78 | 94 |
| `Notices_Techniques_SPL/B/Manual_BHX100_revC.zip` | received | 2094 | 58 | 78 | 94 |
| `Notices_Techniques_SPL/A/Manual_ASY100.zip` | promoted | 2081 | 54 | 70 | 42 |
| `Notices_Techniques_SPL/B/Manual_BIO100 rev A.zip` | received | 2830 | 54 | 60 | 80 |
| `Notices_Techniques_SPL/A/Manual_AKI500_revA.zip` | received | 1824 | 48 | 68 | 46 |

Exemples de chemins internes trouves dans `Manual_BHX100_revD.zip` :

```text
Manual_BHX100_revD/HTML version/Documentation/Carding documentation/
Manual_BHX100_revD/HTML version/Documentation/Carding documentation/01 - TMS 1750 133419754/
Manual_BHX100_revD/HTML version/Documentation/Carding documentation/01 - TMS 1750 133419754/TTN22065K-Manuel Opérateur TMS & TCF.pdf
Manual_BHX100_revD/HTML version/Documentation/Carding documentation/01 - TMS 1750 133419754/TTN22066K-TMS & TCF Operator Manual.pdf
Manual_BHX100_revD/HTML version/Documentation/Carding documentation/03 - TCF 3750 133419755/
Manual_BHX100_revD/HTML version/Documentation/Carding documentation/07 - EXCELLE®  S5PP6TT 3750 133419757/TTN22072K - Manuel opérateur Carde 133419757.pdf
Manual_BHX100_revD/HTML version/Documentation/Carding documentation/07 - EXCELLE®  S5PP6TT 3750 133419757/TTN22086J Spare parts list Excelle S5PP6TT 133419757-400547915.pdf
Manual_BHX100_revD/HTML version/Documentation/Carding documentation/08 - EXCELLE®  S5PP6TT 3750 133419784/TTN23060J-Manuel Opérateur Carde.pdf
Manual_BHX100_revD/HTML version/Documentation/Carding documentation/10 - CONTROL DESK/TTN22077J Card control desk.pdf
Manual_BHX100_revD/HTML version/Documentation/Carding documentation/TTN22515J-Card - Feeder Assembly instructions .pdf
```

`Manual_BHX100_revE.zip` est present mais illisible :

```text
error BadZipFile File is not a zip file
```

Il faut donc l'ecarter du pilote ou demander un retransfert propre.

## Couverture des questions expert

Jeu de questions expert fourni et couverture observee :

| Question / theme | Etat data |
| --- | --- |
| Liste de garniture carde numero 1 du projet `COL100` | `COL100` non retrouve dans les fichiers visibles du depot Andritz. Demander retransfert ou chemin exact. |
| Puissance totale carde numero 2 du projet `BHX100` | `BHX100` present dans SFTP non promu. Probable source : `Manual_BHX100_revD.zip` et revisions A-C. Non exploitable dans l'index actuel. |
| Poids d'un tambour Ø1500 sur machine laize 3m | A verifier dans manuels carding non promus. Le terme `drum/tambour` apparait dans certains ZIP, mais pas encore qualifie. |
| Frequence nettoyage/remplacement brosses de nettoyage de toile | A verifier apres promotion des manuels carding ou documents Non-Wovens. |
| Reference/quantite garniture avant-train carde `COL100` | Bloque par absence `COL100`. |
| Plan de charges `BHX100` | `BHX100` present dans SFTP et Non-Wovens recu, non garanti dans SPL indexe. |
| Nombre de rouleaux de transfert sur machine `COL100` | Bloque par absence `COL100`. |
| Nettoyage cartouches d'injecteurs | Sources probables dans `BEX200-RevB` (`IN 07 A- EXH injector cartridge cleaning.pdf`) et plusieurs ZIP avec notices injecteur. |
| Recommandations de stockage entrepot | A verifier selon source famille ; pas valide avec l'index actuel seul. |
| Quantite de graisse dans palier moteur diametre 60 | A verifier dans documents fournisseurs/moteurs ; pas qualifie. |
| `KRU001Y` pompes HP avec injecteurs dedies | `KRU001Y` non retrouve. Demander retransfert ou chemin exact. |
| `DRU006` fournisseur `PRJ2S` | `DRU006` non retrouve. `PRJ2S` apparait dans `BAX140` (`PRJ2S sand piper SA2A svc man.pdf`), mais pas rattache a DRU006. |
| Sous-traitant utilisant une nacelle elevatrice | Sujet securite/site ; pas confirme dans SPL indexe. |
| Nombre de filtres a sable pour debit 220 m3/h | Sources possibles dans `AKI200`, `AVA100`, `AVA200`, `BAL100`, `BAN400` via `sand filter(s)`, mais a indexer/valider. |

## Pourquoi la recherche utilisateur echoue

Les echecs observes viennent de plusieurs causes distinctes :

1. Donnee non indexee : `BHX100` est present dans le SFTP, mais les ZIP pertinents
   sont au statut `received`.
2. Donnee absente : `COL100`, `KRU001Y`, `DRU006` ne ressortent pas dans le depot
   visible.
3. Promotion incomplete : `Manual_ASY100.zip` est marque promu mais absent de
   Qdrant.
4. Rewriting dangereux : une question metier doit preserver les termes exacts
   (`carde`, `COL100`, `BHX100`, references pieces). Remplacer `carde` par
   `carte` detruit la requete.
5. HTML et menus : certains manuels contiennent beaucoup de pages HTML de
   navigation. Elles doivent rester indexables quand elles portent du contenu,
   mais etre depriorisees comme preuve quand elles ne sont que des menus.
6. Knowledge large par design : le scope Andritz peut etre transverse et pollue,
   mais le retrieval doit savoir retrouver dans la foret sans hardcoder un jeu de
   questions.

## Recommandation de prochaine vague d'indexation

Priorite 1 - rendre les questions BHX100 testables :

- Promouvoir/indexer `Notices_Techniques_SPL/B/Manual_BHX100_revD.zip`.
- Garder les revisions A-C comme sources de comparaison si besoin.
- Ecarter `Manual_BHX100_revE.zip` tant que le ZIP est invalide.

Priorite 2 - enrichir le domaine carding/carde transverse :

- `Notices_Techniques_SPL/A/Manual_ACJ200-revA.zip`
- `Notices_Techniques_SPL/B/Manual_BCX300 rev C.zip`
- `Notices_Techniques_SPL/B/Manual_BAO100.zip`
- `Notices_Techniques_SPL/A/Manual_AKI500_revA.zip`
- `Notices_Techniques_SPL/A/Manual_ASY200.zip`
- `Notices_Techniques_SPL/A/AVA500.zip`

Priorite 3 - corriger les promotions incompletes :

- Investiguer `Manual_ASY100.zip` :
  - present dans `document_names`
  - `archive_name=Manual_ASY100.zip` absent de Qdrant
  - `project_code=ASY100` absent de Qdrant
  - facts documentaires/tableaux absents pour `ASY100`, `TMS`, `TCF`, `EXCELLE`

Priorite 4 - demander retransfert ou chemin exact :

- `COL100`
- `KRU001Y`
- `DRU006`
- dossier `C` sous `Notices_Techniques_SPL` si Andritz confirme son existence :
  l'UI actuelle montrait `A` et `B` dans ce dossier au moment du diagnostic.

## Commandes utiles de diagnostic

### Lister les fichiers `Notices_Techniques_SPL`

```sh
ssh ubuntu@agentium.papai.ai 'docker exec -i agentium-backend python - <<'"'"'PY'"'"'
import os, psycopg2
conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()
cur.execute("""
select df.status, df.filename, df.size_bytes, df.object_key
from deposit_files df
join workspaces w on w.id = df.workspace_id
where w.slug = %s
  and df.filename like %s
order by df.status, df.filename
""", ("andritz", "Notices_Techniques_SPL/%"))
for status, filename, size, object_key in cur.fetchall():
    print(status, round((size or 0) / 1024 / 1024, 1), "MB", filename, object_key)
PY'
```

### Scanner les noms internes d'un ZIP sans extraire

```sh
ssh ubuntu@agentium.papai.ai 'docker exec -i agentium-backend python - <<'"'"'PY'"'"'
import zipfile, re
path = "/data/secure_deposit/<OBJECT_KEY>"
pat = re.compile(r"(carde|carding|TMS|TCF|EXCELLE|garniture|wire|spare parts|injector|pump|sand filter)", re.I)
with zipfile.ZipFile(path) as z:
    hits = [n for n in z.namelist() if pat.search(n)]
print("hits", len(hits))
for n in hits[:100]:
    print(n)
PY'
```

### Verifier la presence d'une archive dans Qdrant

```sh
ssh ubuntu@agentium.papai.ai 'docker exec -i agentium-backend python - <<'"'"'PY'"'"'
import json, urllib.request
collection = "andritz__andritz-notices-techniques-spl-pilot"
body = {
    "exact": True,
    "filter": {"must": [{"key": "archive_name", "match": {"value": "Manual_ASY100.zip"}}]},
}
req = urllib.request.Request(
    f"http://qdrant:6333/collections/{collection}/points/count",
    data=json.dumps(body).encode(),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(req, timeout=10) as r:
    print(json.load(r)["result"]["count"])
PY'
```

### Verifier les facts indexes

```sh
ssh ubuntu@agentium.papai.ai 'docker exec -i agentium-backend python - <<'"'"'PY'"'"'
import os, psycopg2
conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()
collection = "andritz-notices-techniques-spl-pilot"
terms = ["carde", "carding", "TMS", "TCF", "EXCELLE", "BHX100", "ASY100"]
for table in ["knowledge_document_facts", "knowledge_table_facts"]:
    print("TABLE", table)
    for term in terms:
        cur.execute(f"""
        select count(*)
        from {table}
        where collection_slug = %s
          and (
            content ilike %s
            or document_filename ilike %s
            or source_path ilike %s
          )
        """, (collection, f"%{term}%", f"%{term}%", f"%{term}%"))
        print(term, cur.fetchone()[0])
PY'
```

## Notes produit / retrieval

- Ne pas hardcoder un routeur Andritz specifique aux questions de test.
- Le KnowledgeGuide doit fournir des instructions de retrieval/reponse :
  preservation des termes exacts, synonymes controles, source families
  preferees, depriorisation des pages de navigation.
- Les termes projet et pieces doivent etre proteges contre le rewriting :
  `COL100`, `BHX100`, `BBA120`, `AKK200`, `KD724`, `PRJ2S`, `TMS`, `TCF`,
  `EXCELLE`, `carde`.
- La distinction a supporter dans le produit est :
  - reponse documentaire stricte avec sources exactes ;
  - interpretation metier avec sources preferees et incertitudes explicites.
- Pour les questions trop larges, il faut clarifier sans inventer :
  exemple, "Voulez-vous les capteurs de proximite, pression, securite ou
  automatisme ?"

## Handoff court

Si une nouvelle instance doit reprendre :

1. Se connecter a `ubuntu@agentium.papai.ai`.
2. Verifier `deposit_files` pour `Notices_Techniques_SPL/%`.
3. Promouvoir/indexer d'abord `Manual_BHX100_revD.zip`.
4. Confirmer que Qdrant contient des points avec :
   - `archive_name=Manual_BHX100_revD.zip`
   - `project_code=BHX100`
   - `inner_document_path` contenant `Carding documentation`
5. Rejouer les questions BHX100.
6. Demander a Andritz le retransfert ou le chemin exact pour `COL100`,
   `KRU001Y`, `DRU006` et l'eventuel dossier `C`.
