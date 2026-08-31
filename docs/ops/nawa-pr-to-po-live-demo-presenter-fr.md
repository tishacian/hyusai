# Carte présentateur — PR → PO (Fayçal)

Une page. Le bureau est en **anglais**. Les quatre preuves sont **dans ce papier**, pas numérotées à l’écran.

Remettre à Fayçal le Word `docs/ops/nawa-pr-to-po-live-demo-playbook.docx` (ou le markdown EN). Garder cette carte pour soi.

## Ouvrir

```
https://agentium.papai.ai/work/pr-to-po?workspace=nawa&lang=en
```

Hard-reload (`Ctrl+Shift+R`). Compte présentateur `thibaud.ishacian@datategy.net`. Workspace `nawa`. Titre **PR to PO**. SHA live `347311924faba4fc6686a05c3318cb5d2415fa2a`. Write = **Sealed**. Pas de HANA.

## Ce que Fayçal doit voir

| # | Preuve | Où pointer | Phrase |
|---|---|---|---|
| 1 | SAP MCP live | Compteurs, stations, **Read selected requisition**, **Compiled brief** | PR **ZNPR** via `get_A_PurchaseRequisitionItem` / `_by_key`. Tâche `listTaskCollection`. Budget `fi_Validate`. Fournisseur = commande la plus récente sur l’établissement via `get_A_PurchaseOrder`. Compile `python_recipe_v1`. |
| 2 | Tâche agentique | **Summarise** | `azure_llm_v1` résume la justification live en deux phrases. Rien d’inventé. |
| 3 | Package POST PO | carte **Draft / Purchase order composed for SAP** | POST · `bapi_po` · `BAPI_PO_CREATE1` · Send **Sealed**. Type **ZLPO**. `sealed: true`, `called: false`, `testrun: false`. Org achat = établissement. TESTRUN interdit. Succès = BAPI composé, pas un create live. |
| 4 | Nice-to-have | **Ask the factory** / **Open the portal** | Lecture seule. Chip **Write status** → *No. The write station stays sealed.* |

## Script (3 min)

1. Hard-reload. **PR to PO**. Compteurs + 5 stations. Write **Sealed**.
2. **Run the factory** → Compile **Done**. Hero du type *Brief compiled on STICKER WHITE*.
3. **Read selected requisition** (preuve 1). Outils nommés sous chaque fait.
4. **Summarise** (preuve 2).
5. Carte Draft : « voici le BAPI_PO_CREATE1 ZLPO ; il n’est pas envoyé » (preuve 3).
6. Chip **Write status** (preuve 4). Portail seulement s’il reste du temps.

## Exemple live (31 août 2026)

PAPER BAG · fournisseur le plus récent sur l’établissement `1000000018` · PR `2000276449` / `00020` type ZNPR · POST ZLPO sealed · résumé *white stickers*.

## Interdit

Poster un PO. Appeler `BAPI_PO_CREATE1` / `BAPI_TRANSACTION_COMMIT`. Utiliser TESTRUN. Inventer des alias MCP. Allumer HANA. Remettre des tuiles 1–4 à l’écran. Mot de passe / secret OAuth sur une slide.

## Si ça coince

Tuiles « Shown / Play / Success criteria » → hard-reload.  
`token expired` / 407 → redémarrer les apps MCP Hikma (pas le mot de passe Agentium).  
Write **Sealed** après Run → normal.  
Historique portail avec d’anciens *Summarise* → historique de session, pas une écriture.
