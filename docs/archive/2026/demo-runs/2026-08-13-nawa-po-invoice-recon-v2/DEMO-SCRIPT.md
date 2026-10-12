# Démo NAWA v2 — Créer, construire, exécuter (PO / Facture)

Répété au navigateur le 13/08/2026 (matin, UTC) sur la prod · VM : `omnirag-demo` (`https://agentium.papai.ai`) ·
Images : commit `92b32ce4` (`revision_verified: true`), canaries protégés 6/6.

Ce runbook remplace la [v1 du 10/08](../2026-08-10-nawa-po-invoice-recon/DEMO-SCRIPT.md) comme script
présentateur. La mécanique d'exécution (Secure Deposit, cron, chiffres, pièges) n'a pas changé — la v1
reste la référence pour les preuves des chemins événement/cron. La v2 ajoute deux actes en amont
(créer une skill, construire le flow) et intègre les correctifs UI livrés le 12/08.

## Ce qui a changé depuis la v1 — et quelle plainte ça répond

| Plainte QA | Réponse visible à l'écran |
|---|---|
| 1 · Perte de contexte System → Flow builder | L'entrée nav « Flow builder » est un **brouillon d'esquisse** assumé, qui s'ouvre **vide** (guide premier Flow, plus de gabarit ni de manifest résiduel, **zéro warning**). Le flow d'un System se rejoint par le System (`/systems/:id/flow`) ; le lien verrouillé du system-builder y mène désormais directement. |
| 2 · Pas de création de skill dans l'UI | Page Skills : **+ New skill** (assistant en 4 étapes, sans JSON) et **Import a BRD** (`.docx`, §4/§5). |
| 3 · Pas de delete de nœud | Un bouton **Delete node** par nœud, dans la barre d'outils du nœud. À montrer à zoom ≥ 100 %. |
| 4 · Surcomplexité | Barre auteur réduite à la boucle d'édition (undo/redo, Fit, **SAVE**, **PUBLISH**, **OPERATE**) ; Vérifier / Ranger / zoom rangés sous **« Plus »**. Le repli « contrat de sortie » de l'inspecteur est en langage clair (plus de « fige le schéma catalogue »). |

## Identifiants (état vérifié le 13/08)

| Objet | Valeur |
|---|---|
| Workspace | `nawa` (id `b337fdbf-2689-436e-a287-2fe903ca47cf`) |
| System | `PO vs Invoice Reconciliation` — id `fe4ab7e5-d472-43b2-8bdb-465d0d51aec8`, actif |
| Version publiée | v4 — `9fc3cd0e-2e9a-427b-ae44-4bf301d924e5` ; brouillon serveur r10 aligné |
| Collection | `po-invoice-recon-demo` |
| Lien de dépôt | access_id `BGBP0F7H4iGC0NQPCzM` (secret : `/srv/agentium-data/demo-secrets/…password`, 0600 root sur la VM) |
| Planification | quotidienne `0 7 * * *` UTC, activée — preuve du jour : run `951c838a…` completed à 07:00 |
| Fichiers d'exemple | `Invoice_INV-8834_Sample.pdf` + `PO_Register_Sample.xlsx` (poste présentateur, `~/Downloads/`) |

## Les chiffres à connaître par cœur (inchangés depuis la v1)

- PO `PO-2026-0451` : 4 lignes, total **9 950,00** QAR — le filtre Excel est composé depuis la
  **référence PO extraite du PDF** (namespace `po_filter`), rien n'est codé en dur.
- Facture `INV-8834` : 4 lignes, total dû **9 860,00** QAR, fournisseur `Al Fanar Industrial Supplies W.L.L.`.
- Rapprochement : **2 conformes, 2 signalées** — `Hydraulic Hose 3/4"` qty 18 vs 20 (**-10.00 %**),
  `Safety Valves DN50` prix 365 vs 350 (**+4.29 %**). Écart total **-0.90 %**, tolérance **±2.0 %**.
- Verdict : **« Needs Review »** + 2 recommandations en fin de rapport. Zéro LLM dans le chemin de données.

## Check-list pré-démo (15 min avant)

1. `ssh omnirag-demo "sudo docker ps"` — 13 conteneurs Up (backend, frontend, pg, rabbitmq, minio healthy ;
   worker-cpu, p4-maintenance, beat : « Up » suffit).
2. `curl -sk https://localhost/api/v1/build-info` (depuis la VM) → `revision 92b32ce4…`, `revision_verified: true`.
3. Page Skills nawa : les 5 skills réconciliation visibles **+ les boutons « + New skill » et « Import a BRD »**.
4. `/orchestration` s'ouvre **vide** (guide premier Flow, zéro warning) — c'est le premier test des correctifs.
5. System actif v4, readiness OK ; lien de dépôt actif ; les 2 fichiers d'exemple sous la main.
6. Onglets pré-ouverts : `/skills`, `/systems/<id>/flow`, `/runs`, `/governance/audit`, page Secure Deposit, portail public du lien.
7. **Zoom navigateur 100 %** (les boutons Delete node se montrent mieux) et thème au choix du public (Dark/Light/System dans la barre).

---

## Acte 1 — Créer une skill sans écrire de JSON (~5 min)

**Click-path** : Build → Skills.

1. **Le registre** : 34 skills, filtres Basic/Production/Enterprise, stats réelles par skill
   (latence, coût, succès) — les 4 skills réconciliation affichent leurs vraies stats de runs.
2. **+ New skill** : l'assistant en 4 étapes — **1 · Intent** (nom, description « au sens BRD » :
   la formulation d'une exigence FR-x convient telle quelle ; catégorie = groupe dans la palette du
   flow builder ; capability porteuse), **2 · Contract** (entrées/sorties construites visuellement),
   **3 · Execution** (trois façons de faire : page blanche, gabarit de prompt LLM, encapsuler une
   skill du socle avec entrées fixées), **4 · Review**. Les garde-fous parlent métier
   (« A local name is required », « Choose how the work gets done »).
3. **Import a BRD** : le `.docx` Datategy (sections §4 objectifs / §5 exigences) pré-remplit des
   propositions de skills — le pont Intake → BRD → TOM → System se voit dans le produit.
4. Pour la démo : dérouler jusqu'à Review puis **créer** une skill d'exemple (slug explicite type
   `demo_à_supprimer`) et la **supprimer** ensuite — ou annuler à Review si on veut zéro résidu.

Argumentaire : la création est gouvernée (certification Basic, workspace-scopée), pas un éditeur
de code libre — on encapsule le socle certifié ou on écrit un prompt, on ne déploie pas du Python arbitraire.

## Acte 2 — Construire et lire le flow (~8 min)

**Click-path** : Build → Systems → « PO vs Invoice Reconciliation » → Flow builder (ou l'onglet Flow).
L'URL est canonique : `/systems/<id>/flow` — on revient de n'importe où (Skills compris) sans perdre le contexte.

1. **Contexte affiché** : fil d'Ariane `Systems / PO vs Invoice Reconciliation / Flow builder`,
   chips `11 NODES · SAVED · Draft r10 · Published v4`.
2. **Barre auteur épurée** : undo/redo, FIT, SAVE, PUBLISH, OPERATE. Ouvrir **« Plus »** pour montrer
   que rien n'a disparu : zoom avant/arrière, Ranger les nœuds, **Vérifier le flow** (la validation
   à la demande, plus de warnings imposés à l'ouverture).
3. **Le graphe, gauche → droite** : 3 entrées (manuel, dépôt promu, cron) → extraction registre PO →
   extraction facture PDF → rapprochement ±2 % → décision → 2 branches de rapport → journal d'audit → résultat.
4. **Palette** : groupes « Used in this workspace » et « Capabilities » (Document Reconciliation : 5) —
   plus une liste à la Prévert, un catalogue rangé par ce que le workspace utilise vraiment.
5. **Inspecteur** : cliquer `3 · Rapprocher les lignes` — bindings lisibles
   (`po_lines ← 2 · Extraire le registre PO.rows`, `invoice_lines ← …line_items`), tolérance ±2 %,
   et le contrat de sortie en langage clair : « Aucun schéma déclaré : à la publication, cette étape
   reprend le contrat de sortie de la Skill liée et le conserve tel quel pour cette version. »
6. **Le geste star** : le nœud facture publie `po_reference` extrait du PDF vers le namespace
   `po_filter`, que le nœud Excel consomme comme filtre — **c'est le PDF qui pilote la lecture du
   registre Excel**.
7. **Décision fail-safe** : `4 · Écarts hors tolérance ?` — `approved` seulement si `flagged_count == 0`,
   défaut `needs_review` : un comptage illisible ne peut jamais approuver.
8. **Delete node** : survoler un nœud, montrer sa barre d'outils (delete par nœud, plus besoin de reset macro).
9. Au passage, si la question de la nav vient : l'entrée « Flow builder » de la barre Build est le
   **brouillon d'esquisse** partagé — il s'ouvre vide, on y prototype, et on repart vers un System
   pour le travail réel.

## Acte 3 — Exécuter, observer, gouverner (~7 min)

### 3a · Test du brouillon, en direct (répété ce matin)

**Click-path** : OPERATE → « Execute on backend » → payload :

```json
{"collection_slug": "po-invoice-recon-demo"}
```

- Le bandeau dit exactement ce qui se passe : « Test draft runs this saved revision. The operator
  runner and the entry point keep serving Published v4 until you publish explicitly. » — on teste
  le brouillon **sans toucher** ce que sert la prod.
- Terminal d'exécution en direct : progression nœud par nœud, branche `approved` **skipped**,
  rapport Needs Review, journal d'audit, `Run finished · status=completed` en ~1 s.
- Répétition du 13/08 : run `4648085f-bf68-44e4-85fa-70a81790604d` (surface `draft_test`) —
  completed, Needs Review, en-tête facture complet, audit `938e5860…` (status `recorded`), **0 provider_calls**.

### 3b · Le chemin fournisseur (l'automatisation)

Comme en v1 (Moments 3–6, inchangés) :

1. **Portail public** du lien de dépôt → mot de passe → téléverser **les deux fichiers**.
2. Page Secure Deposit interne → sélectionner les deux → **Promouvoir (groupé)** vers
   `po-invoice-recon-demo`. Argumentaire : rien de ce qu'un externe dépose n'entre dans le
   workspace sans le geste d'un opérateur — l'automatisation démarre *après*.
3. `/runs` : le run événementiel apparaît en 5–10 s (outbox durable), mêmes chiffres.
4. **Cron** : la planification quotidienne 07:00 UTC tourne réellement — montrer dans `/runs`
   les runs `scheduler` du 12/08 et du 13/08, tous Needs Review. La preuve que ça vit sans nous.
5. `/runs/:id` : invocations (6 nœuds, latences ms, coût 0), checkpoints
   (`ingress_accepted` → `decision_resolution` → `run_end`), payload final avec `report_text` intégral.
6. `/governance/audit` : filtrer `nawa.po_invoice_recon.completed` — un événement par run, acteur
   `system` (événement/cron) vs utilisateur (manuel), export CSV.

## Pièges connus

1. **Promotion groupée obligatoire** — deux promotions séparées = un run en échec propre
   (`file_resolution_no_match`). Présentable comme contre-essai de robustesse si la question vient.
2. **Simulate n'exécute rien** : c'est une lecture topologique côté client. Pour prouver l'exécution,
   toujours **Test draft** (brouillon) ou **Execute** (publié).
3. **Dédoublonnage** : re-promouvoir les mêmes fichiers ne re-déclenche pas ; re-téléverser d'abord
   (nouveaux file_ids), puis promouvoir.
4. **Delete node et zoom** : les commandes par nœud se montrent à zoom ≥ 100 % ; utiliser FIT puis
   zoomer sur un nœud avant de montrer la suppression.
5. **Latence événementielle** : 5–10 s entre promotion et run (draineur d'outbox) — meubler avec
   l'argumentaire gouvernance.
6. **Résidus de démo** : si une skill d'exemple a été créée à l'acte 1, la supprimer ; le brouillon
   d'esquisse (`/orchestration`) se remet à zéro par workspace.

## Preuves de répétition (13/08, matin UTC)

| Vérification | Résultat |
|---|---|
| `/orchestration` s'ouvre vide, zéro warning | OK (guide premier Flow affiché) |
| Barre auteur épurée + « Plus » complet | OK (zoom ×2, Ranger, Vérifier relogés) |
| Lien Skills → retour System `/systems/<id>/flow` | OK (contexte conservé) |
| Inspecteur `3 · Rapprocher les lignes`, copy adoucie | OK (FR/EN) |
| Delete node visible par nœud | OK (à zoom ≥ 100 %) |
| Wizard « + New skill » (4 étapes, 3 presets, aides BRD) | OK (ouvert puis annulé, zéro résidu) |
| Test draft `{"collection_slug": …}` | run `4648085f…` completed, Needs Review, ~1 s, 0 LLM |
| Cron quotidien | runs `951c838a…` (13/08 07:00) et `e5668f9e…` (12/08 07:00) completed |
