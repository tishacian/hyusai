# Client360 — collection unifiée Installed base

Runbook ops / produit pour la knowledge collection dédiée Client360 PDR
(`andritz-client360-installed-base`).

## Rôle

| Couche | Rôle |
| --- | --- |
| Knowledge collection `andritz-client360-installed-base` | Vault documentaire (xlsx SPL + pilotes), evidence, table facts |
| `Client360DataSource` | Source de vérité structurée pour le moteur d’opportunités |
| Adaptateur SAP → PDR (`sync-from-collection`) | Normalise les fichiers de la collection vers `Client360DataSource` |
| Moteur `engines/opportunities/run` | Produit / met à jour les opportunités à partir des sources structurées |

Les chunks Qdrant de cette collection sont secondaires (Assistant Client360 /
evidence). **Ne pas** y mélanger les notices techniques SPL (ZIP).

## Slug & workspace

| Champ | Valeur |
| --- | --- |
| Workspace | `andritz` |
| Collection slug | `andritz-client360-installed-base` |
| Phase 1 scope | Greece / Turkey (+ allowlist pilote) ; technologies JETLACE / HFR200 / wear parts |

## Fichiers attendus

### Installed_base_SPL (export SAP)

| Fichier | `source_type` cible | Usage |
| --- | --- | --- |
| `Family - Opportunity.xlsx` | `periodicity` + `market_signal` | Périodicités (mois → semaines), IB Turkey, prix |
| `Installed base - Machine.xlsx` | `installed_base` | Arbre client / site / ligne / machine |
| `Installed base - SPC.xlsx` | `installed_base` | Quantités installées Material / Title |
| `Sales_By_Country.xlsx` | `sap_sales_history` | Agrégats ventes (Phase 1 : GR / TR) |
| `Materials_Consumptions.xlsx` | enrichissement | Lead time / prix / stock — Phase 2 |
| `Histo_Achat_Pieces_Machines_Montbonnot.xlsx` | `other` (`metadata.role=purchase_history`) | Enrichissement coût unitaire + délai (Phase 2) — **jamais** `sap_sales_history` |

Préfixe deposit typique : `Installed_base_SPL/`.

### Histo_Achat Montbonnot (`purchase_history`)

Feed d’enrichissement Phase 2 (coût + délai), **pas** d’historique de ventes client.

| Règle | Détail |
| --- | --- |
| Classification | `source_type=other` + `metadata.role=purchase_history` |
| Interdit | Ne **jamais** classer / syncer comme `sap_sales_history` (pas de `sales_known_*`) |
| Court terme ops | Promote **vault only** (collection), **sans** sync Phase 1 |
| Sync enrichissement | Uniquement Phase 2 : `include_purchase_history: true` (ou `scope=all`) |
| Taille | ~46 Mo → exception basename dans le script promote (jusqu’à **60 Mo** pour `histo_achat_pieces_machines_montbonnot.xlsx` uniquement) |

```bash
# Promote vault only (recommandé court terme) — sans --sync
python -m scripts.promote_client360_installed_base \
  --workspace andritz --promote
# Exception taille 60 Mo appliquée automatiquement pour ce basename.

# Sync Phase 2 (enrichissement moteur) — pas le bouton UI Phase 1
POST /api/v1/client360/sources/sync-from-collection
{
  "collection_slug": "andritz-client360-installed-base",
  "dry_run": false,
  "include_purchase_history": true
}
```

Avec `--sync` Phase 1 seul : le fichier peut être promu mais le sync `purchase_history` est **skippé** (attendu). Option script : `--include-purchase-history`.

### Pilotes MVP (référence métier)

| Fichier | `source_type` cible | Usage |
| --- | --- | --- |
| `SEPTONA - Client 360.xlsx` | `installed_base` + `periodicity` | Grain client de référence (valider l’adaptateur) |
| `Base installée TURQUIE.xlsx` | `installed_base` | Portefeuille Turquie actuel |

Préfixe deposit recommandé : `Client360_Pilot/`.

Optionnel (si disponibles) : historique ventes / prix marché Turquie.

## Hors scope

- Notices techniques SPL (ZIP) → collection séparée `andritz-notices-techniques-spl-pilot` (chat RAG uniquement).
- Connecteurs live SAP / CRM.
- Recâblage Client360 dans le chat recherche Andritz.
- Phase 1 monde entier (Machine / SPC / Sales non filtrés).

## Promote vers la collection

1. Déposer / ré-ingérer les xlsx dans le Secure Deposit workspace `andritz`.
2. Créer la collection vide si besoin : slug `andritz-client360-installed-base`.
3. Promouvoir en batch vers **cette** collection (UI Secure Deposit / API) :

```bash
# Bulk promote (API Secure Deposit / SFTP)
POST /api/v1/sftp/deposits/promote-bulk
{
  "file_ids": ["…"],
  "collection_slug": "andritz-client360-installed-base"
}
```

Service Python équivalent : `promote_files_to_collection_batch` dans
`backend/app/services/secure_deposit.py`.

4. Laisser le worker `document_ingest_index` produire table facts (+ chunks optionnels).

**Attention** : `_records_from_table_facts` a une limite (5000). Pour SPC (~50k+),
l’adaptateur doit écrire des `Client360DataSource` normalisés — ne pas dépendre
uniquement des table facts.

## Sync adaptateur → Client360DataSource

Endpoint produit (UI onglet Données → **Synchroniser les sources**) :

```bash
POST /api/v1/client360/sources/sync-from-collection
{
  "collection_slug": "andritz-client360-installed-base",
  "dry_run": false,
  "scope": {},   # optionnel (filtre pays / tech côté backend)
  "include_purchase_history": false
}
```

- `dry_run: true` — prévisualise sans persister.
- `dry_run: false` — upsert `Client360DataSource` avec `collection_slug`,
  `metadata.records`, `metadata.origin_file`, `metadata.adapter_version`.
- `include_purchase_history: true` — sync le feed Histo_Achat (`other` / `purchase_history`) ;
  défaut `false` (Phase 1 skip). Voir section [Histo_Achat Montbonnot](#histo_achat-montbonnot-purchase_history).

## Moteur d’opportunités

Après sync validée :

```bash
# Dry-run (pas de commit)
POST /api/v1/client360/engines/opportunities/run
{ "dry_run": true }

# Run réel
POST /api/v1/client360/engines/opportunities/run
{ "dry_run": false }
```

Même actions depuis l’UI Client360 → onglet **Données** :
**Dry-run moteur** / **Calculer**.

## Critères de validation vs MVP Septona / Turquie

Baseline actuelle avant unification : ~20 opportunités (9 Septona + 11 portefeuille Turquie),
pilote `pilot_dataset=andritz_client360_pdr_mvp_20260708`.

| Critère | Attendu |
| --- | --- |
| Septona | Familles usure historiques toujours présentes (Injector Strip, O’ring, Filtering cartridge, …) |
| Turquie | Au minimum parité portefeuille ; si Machine le permet, début de résolution clients individuels **sans** casser les opportunités déjà en statut avancé |
| Volume | Pas d’explosion d’opportunités hors wear parts (mapping rules + heuristic) |
| Clé dédoublonnage | `(customer_key, part_family, part_reference, line_label)` |

Séquence recommandée :

1. Sync dry-run → contrôler counts / types.
2. Sync réel.
3. Engine dry-run → comparer aux 20 opportunités MVP.
4. Engine réel une fois validé.
5. Archiver les anciennes sources MVP orphelines de collection
   (`pilot_dataset=…mvp…` sans lien `andritz-client360-installed-base`).

## UI Client360 (onglet Données)

- Statut collection unifiée (slug, sources liées, comptes / `row_count` par `source_type`).
- **Synchroniser les sources** → `POST …/sources/sync-from-collection` (Phase 1 : **pas** de CTA dédié pour Histo_Achat).
- **Dry-run moteur** / **Calculer** → `POST …/engines/opportunities/run`.
- Table des `data_sources` (summary API) avec highlight des lignes liées au slug unifié.
- Colonne Type : `other` + `metadata.role=purchase_history` → label **Achats Montbonnot** (sinon « Autre »).

## Checklist ops rapide

- [ ] Collection `andritz-client360-installed-base` créée (workspace `andritz`)
- [ ] Fichiers Phase 1 `Installed_base_SPL/*` promus + indexés
- [ ] Histo_Achat : promote vault only (exception 60 Mo) ; sync Phase 2 via `include_purchase_history` si besoin
- [ ] Pilotes Septona / Turquie ré-ingérés et promus
- [ ] Sync adaptateur OK (`status=ready` sur sources minimales)
- [ ] Dry-run engine : parité MVP Septona / Turquie
- [ ] Run réel + archive anciennes sources MVP
- [ ] Notices SPL ZIP **absentes** de cette collection
