# Carte présentateur — PR → PO (Fayçal)

Une page. Le bureau est en **anglais**. Les quatre preuves sont **dans ce papier**, pas numérotées à l’écran.

Remettre à Fayçal le Word `docs/ops/nawa-pr-to-po-live-demo-playbook.docx` (ou le markdown EN). Garder cette carte pour soi.

## Ouvrir

```
https://agentium.papai.ai/work/pr-to-po?workspace=nawa&lang=en
```

Hard-reload (`Ctrl+Shift+R`). Compte présentateur `thibaud.ishacian@datategy.net`. Workspace `nawa`. Titre **PR to PO**. SHA live `cd40fe337285058120ec7236d587b1853ca72c42`. Write = **Sealed**. Pas de HANA.

## Ce que Fayçal doit voir

| # | Preuve | Où pointer | Phrase |
|---|---|---|---|
| 1 | SAP MCP live | Compteurs, stations, **Read selected requisition**, **Compiled brief** | Vraie PR via `get_A_PurchaseRequisitionItem` / `_by_key`. Tâche `listTaskCollection`. Budget `fi_Validate`. Commandes / fournisseur `get_A_PurchaseOrder*`. Compile `python_recipe_v1`. |
| 2 | Tâche agentique | **Summarise** | `azure_llm_v1` résume la justification live en deux phrases. Rien d’inventé. |
| 3 | Package POST PO | carte **Draft / Purchase order composed for SAP** | POST · hikma · `post_A_PurchaseOrder` · Send **Sealed**. Type **NB**. `sealed: true`, `called: false`. Client 300 n’a pas de range NB ; ZAPO refusé. Succès = POST composé, pas un create live. |
| 4 | Nice-to-have | **Ask the factory** / **Open the portal** | Lecture seule. Chip **Write status** → *No. The write station stays sealed.* |

## Script (3 min)

1. Hard-reload. **PR to PO**. Compteurs + 5 stations. Write **Sealed**.
2. **Run the factory** → Compile **Done**. Hero du type *Brief compiled on STICKER WHITE*.
3. **Read selected requisition** (preuve 1). Outils nommés sous chaque fait.
4. **Summarise** (preuve 2).
5. Carte Draft : « voici le POST ; il n’est pas envoyé » (preuve 3).
6. Chip **Write status** (preuve 4). Portail seulement s’il reste du temps.

## Exemple live (31 août 2026)

STICKER WHITE · fournisseur `1000001737` · 50 / 2 / 5 / 0 · PR `2000276449` · POST NB sealed · résumé *white stickers*.

## Interdit

Poster un PO. Inventer des alias MCP. Allumer HANA. Remettre des tuiles 1–4 à l’écran. Mot de passe / secret OAuth sur une slide.

## Si ça coince

Tuiles « Shown / Play / Success criteria » → hard-reload.  
`token expired` / 407 → redémarrer les apps MCP Hikma (pas le mot de passe Agentium).  
Write **Sealed** après Run → normal.  
Historique portail avec d’anciens *Summarise* → historique de session, pas une écriture.
