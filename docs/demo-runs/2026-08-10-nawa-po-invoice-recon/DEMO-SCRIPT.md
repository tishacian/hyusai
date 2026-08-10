# Démo NAWA — Réconciliation PO / Facture (Secure Deposit → System → Audit)

Date de répétition : 10/08/2026 (matin, UTC) · VM : `omnirag-demo` (`https://agentium.papai.ai`) ·
Images backend/worker : commit `7619f0be` (`revision_verified: true` sur `/api/v1/build-info`).

Le scénario : un fournisseur dépose une facture PDF et le registre des bons de commande (xlsx)
dans le Secure Deposit ; l'opérateur promeut les deux fichiers vers une collection ; le System
publié « PO vs Invoice Reconciliation » se déclenche tout seul (événement `deposit.promoted`),
extrait les deux documents, rapproche les lignes à ±2 % de tolérance, tranche via un nœud de
décision, produit un rapport déterministe, journalise un événement d'audit et expose le tout
sur la page Run. Zéro LLM dans le chemin de données : mêmes octets en entrée → mêmes octets en sortie.

---

## 0 · Identifiants de la répétition (état vérifié)

| Objet | Valeur |
|---|---|
| Workspace | `nawa` (id `b337fdbf-2689-436e-a287-2fe903ca47cf`) |
| System | `PO vs Invoice Reconciliation` — id `fe4ab7e5-d472-43b2-8bdb-465d0d51aec8`, status `active` |
| Version publiée | v3 — `6c1b7de9-026f-431e-8a79-aac9c5a254d9` |
| Flow SHA-256 | `d3b03ec6020c965581ab63e921cce25c0a5791e6d98e2d4f5caff8da8108815d` |
| Mode d'exécution | `dag_overlay`, validation `observe` |
| Collection | `po-invoice-recon-demo` (id `2b5c49fc-3002-4d34-9881-1e53ce78fefe`) |
| Lien de dépôt | id `66126488-2ff1-461b-a9da-9f739b671ea8`, access_id `BGBP0F7H4iGC0NQPCzM` (mot de passe : à faire tourner via la page Secure Deposit avant la démo) |
| Planification | `Recon PO/Facture — quotidien`, cron `0 7 * * *` UTC, activée (id `bc1ebae1-ad31-4d80-869d-b21b69fbf6b1`) |
| Fichiers d'exemple | `Invoice_INV-8834_Sample.pdf` + `PO_Register_Sample.xlsx` (fixtures : `backend/app/tests/fixtures/po_invoice_recon/`, worktree VM : `/srv/agentium-data/worktrees/demo-agentic/...`) |

Runs de répétition (tous vérifiés ce matin) :

| Chemin | Run id | Résultat |
|---|---|---|
| Événement (`deposit.promoted`, promotion groupée) | `3ebde9ee-eedc-4f6d-8720-9e0630fbc02a` | completed — Needs Review, 2 flags (v2 du flow) |
| Manuel (ingress `source.manual`) | `907e27cc-b57a-4f13-beac-29f5c987485b` | completed — Needs Review, 2 flags (v3) |
| Cron (`scheduler_tick`) | `dc1e92a9-921b-4b39-a874-8664a9c58511` | completed — Needs Review, 2 flags (v3) |
| Contre-essai négatif (1 seul fichier promu) | `c767a05d-6958-4aef-986f-761eef1afd50` | failed proprement — `file_resolution_no_match`, aucun crash-loop |

Événements d'audit `nawa.po_invoice_recon.completed` : `af758b52…` (événement), `7b3051b9…` (manuel), `ae024145…` (cron).

## Les chiffres attendus à l'écran (les connaître par cœur)

- PO `PO-2026-0451` : 4 lignes, total **9 950,00** QAR.
- Facture `INV-8834` : 4 lignes, total dû **9 860,00** QAR.
- Rapprochement : **2 lignes conformes, 2 signalées** (`flagged_count = 2`) :
  - `Hydraulic Hose 3/4"` — quantité facturée 18 vs 20 commandées → **-10.00 %** (qty_mismatch) ;
  - `Safety Valves DN50` — prix unitaire 365,00 vs 350,00 → **+4.29 %** (price_mismatch).
- Écart total : **-0.90 %** · Tolérance : **±2.0 %** · Verdict : **« Needs Review »**.
- Le rapport se termine par une recommandation par ligne signalée (2 recommandations).

---

## Check-list pré-démo (15 min avant)

1. **Conteneurs** : `ssh omnirag-demo "sudo docker ps"` — backend, frontend, worker-cpu, pg, rabbitmq, minio healthy.
2. **Build-info** : `ssh omnirag-demo "curl -sk https://localhost/api/v1/build-info"` → `revision 7619f0be…`, `revision_verified: true`.
3. **⚠️ Boucles opérationnelles (non durables — à relancer après tout restart du worker)** :
   - Draineur d'outbox (exécute les runs déclenchés par événement) :
     `ssh omnirag-demo "sudo docker exec -d -e ENABLE_P4_MAINTENANCE=true agentium-worker-cpu python -m app.workers.p4_maintenance"`
   - Celery beat (fait vivre le cron `scheduler_tick`) :
     `ssh omnirag-demo "sudo docker exec -d agentium-worker-cpu python -m celery -A app.workers.celery_app:celery_app beat --loglevel info --schedule /tmp/celerybeat-schedule"`
   - Vérifier : `sudo docker exec agentium-worker-cpu ps aux | grep -E 'p4_maintenance|beat'` → une ligne chacun.
   - (Le conteneur `agentium-p4-maintenance` dédié tourne une image ancienne `07f54a68` qui ne connaît pas
     `trigger_run` : ne PAS s'en servir, il marquerait les dispatches `dead`.)
4. **Skills activés** : page Skills du workspace nawa — `invoice_document_extract_v1`, `spreadsheet_table_extract_v1`, `line_items_reconcile_v1`, `reconciliation_report_v1`, `audit_log_v1` visibles.
5. **System publié** : `/systems` → « PO vs Invoice Reconciliation » actif, v3 ; readiness OK (manuel + événement + cron).
6. **Lien de dépôt prêt** : page Secure Deposit → lien `BGBP0F7H4iGC0NQPCzM` actif ; faire tourner le mot de passe et le noter.
7. **Fichiers sous la main** : les deux fichiers d'exemple sur le poste du présentateur (`~/Downloads/`).
8. Ouvrir en onglets : `/systems/<id>/flow`, `/runs`, `/governance/audit`, `/governance/access`, la page Secure Deposit, le portail public du lien.

---

## Moment 1 — Construire (Flow Builder)

**Click-path** : `/systems` → « PO vs Invoice Reconciliation » → onglet Flow.

À montrer, dans l'ordre du graphe (gauche → droite) :
1. **Trois entrées** : `Déclenchement manuel`, `Dépôt promu (Secure Deposit)`, `Planification (cron)` — un seul graphe sert les trois chemins ; les extracteurs lisent les références de fichiers directement dans l'input du run.
2. **Palette Capabilities** : les 5 skills de la tranche réconciliation, versionnés et liés au catalogue du workspace (binding vérifié à chaque dispatch).
3. **Inspecteur / bindings** : cliquer `3 · Rapprocher les lignes` — `po_lines ← task.extract_po.rows`, `invoice_lines ← task.extract_invoice.line_items`, `tolerance_pct ← system.recon.tolerance_pct` (configuration statique portée par le System, pas par le graphe).
4. **Nœud de décision** `4 · Écarts hors tolérance ?` — branche `approved` si `flagged_count == 0`, branche par défaut `needs_review` : fail-safe, un comptage illisible ne peut jamais approuver.
5. **Publication** : bandeau version v3 + SHA du flow — un run n'exécute jamais autre chose que la version publiée épinglée (version_id + sha vérifiés au dispatch).

## Moment 2 — Lancer (run manuel)

**Click-path** : depuis le Flow Builder / la page System → Run manuel avec le payload :

```json
{"collection_slug": "po-invoice-recon-demo"}
```

Attendu : run `completed` en ~1 s (aucun LLM). Verdict **Needs Review**, `flagged_count 2`.
Répétition : run `907e27cc…`.

## Moment 3 — Automatiser (Secure Deposit + cron)

**Click-path portail fournisseur** : URL publique du lien de dépôt → mot de passe → téléverser
`Invoice_INV-8834_Sample.pdf` **et** `PO_Register_Sample.xlsx`.

**Click-path opérateur** : page Secure Deposit interne → sélectionner **les deux fichiers** →
**Promouvoir (groupé)** vers `po-invoice-recon-demo`.

- Argumentaire gouvernance : la promotion est **volontairement manuelle** — rien de ce qu'un
  externe dépose n'entre dans la connaissance du workspace sans décision d'un opérateur.
  L'automatisation démarre *après* ce geste : l'événement `deposit.promoted` déclenche le run tout seul.
- Aller sur `/runs` : un nouveau run apparaît (trigger `webhook`), même verdict, mêmes chiffres.
- **Cron** : montrer la planification `0 7 * * *` (quotidienne) sur la page System — le même
  graphe tourne chaque matin sans intervention ; run de répétition `dc1e92a9…` (checkpoint `schedule_fired`).

## Moment 4 — Observer

**Click-path** : `/runs/:id` du run fraîchement créé.

- Le canvas « pulse » nœud par nœud pendant l'exécution (relancer un run manuel si besoin — c'est court).
- Terminal SSE : la progression par nœud en direct.
- Onglet invocations : 6 nœuds exécutés, latences en millisecondes, coût 0.0, la branche
  `approved` marquée `skipped` (la décision a routé vers `needs_review`).
- Checkpoints : `ingress_accepted` → `node_start/node_end` par nœud → `decision_resolution`
  (les deux conditions évaluées, `needs_review` retenue) → `run_end`.

## Moment 5 — Auditer

**Click-path** : `/governance/audit` → filtrer `nawa.po_invoice_recon.completed`.

- Un événement par run, portant verdict, `flagged_count` et le rapport complet dans `details` ; export CSV.
- L'acteur diffère selon le chemin : `system` pour l'événement/cron, l'utilisateur pour le manuel — la provenance est traçable.
- `/governance/access` : qui a le droit de lire l'audit, de promouvoir des dépôts, de publier des flows (IAM).

## Moment 6 — Consommer

**Click-path** : `/runs/:id` → onglet Payloads (Run.output_ref) + carte outcome.

- `report_text` : rapport à largeur fixe — verdict, référence PO, tableau des 4 lignes avec
  `<-- FLAG` sur les 2 écarts, totaux `PO 9,950.00 | Invoice 9,860.00 | Variance -0.90%`,
  2 recommandations actionnables.
- `verdict`, `flagged_count`, `po_reference`, `audit_event_id`, l'objet `reconciliation` complet :
  tout est structuré, consommable par un humain comme par un système aval.

---

## Pièges connus (et comment les présenter)

1. **Promotion groupée obligatoire** : toujours promouvoir les DEUX fichiers en une seule action.
   Deux promotions séparées = deux événements = le premier run échoue (`file_resolution_no_match`,
   l'autre fichier n'est pas encore là). C'est le contre-essai négatif : l'échec est propre,
   un seul run, pas de boucle — présentable comme preuve de robustesse si la question vient.
2. **Latence** : run ~1 s une fois dispatché ; le dispatch événementiel passe par l'outbox durable,
   compter 5–10 s entre la promotion et l'apparition du run (intervalle du draineur). Meubler avec
   le récit gouvernance de la promotion.
3. **En-tête PDF** : l'extraction pdfplumber de l'image live fusionne les colonnes d'en-tête du PDF
   d'exemple ; les champs `invoice_number`/`vendor`/`due_date` ressortent vides (les **nombres**, eux,
   sont extraits exactement). Choix documenté : la référence PO du rapport est portée par la
   configuration du System (`settings.recon.po_filters`), et le rapport n'affiche pas de ligne fournisseur.
   Un checkpoint `execution_contract_violation` (`/due_date`, mode observe) reste visible — c'est
   l'observabilité des contrats en action, pas un incident.
4. **Boucles opérationnelles non durables** : draineur P4 et celery beat sont lancés en `docker exec`
   (voir check-list) ; un restart du conteneur worker les tue. Sans draineur : les runs événementiels
   restent `pending`. Sans beat : le cron ne tire pas. Les runs manuels, eux, marchent toujours.
5. **Dédoublonnage** : re-promouvoir exactement les mêmes fichiers déjà promus ne re-déclenche pas
   (claim d'événement) ; pour rejouer la démo, re-téléverser les fichiers (nouveaux file_ids) puis promouvoir.

## État laissé après la répétition

- System actif, v3 publiée ; mode event trigger `live` ; readiness OK (manuel + événement + cron).
- Planification : quotidienne `0 7 * * *` UTC, **activée** (elle produira un run « Needs Review » par jour tant que la collection existe ; désactiver après la démo si indésirable).
- Collection `po-invoice-recon-demo` : 3 fichiers promus (xlsx, pdf, + 1 pdf du contre-essai négatif — la résolution prend le plus récent, sans incidence).
- 4 runs (3 réussis, 1 échec volontaire) + 3 événements d'audit.
- Réglages workspace nawa modifiés (avant → après) : `enabled_skills` + 4 slugs réconciliation ;
  `features.flow_workbench_v1` ∅ → true ; `features.enable_event_triggers` ∅ → true ;
  `features.secure_deposit` ∅ → true. System : `settings.event_trigger` ∅ → `{"mode": "live"}`.
- Une écriture SQL directe (documentée) : ligne `run_dispatch_outbox` `b64ae1ff…` repassée
  `dead` → `pending` après l'incident du draineur à image ancienne (cause corrigée en déplaçant
  le draineur dans `agentium-worker-cpu`).
- Boucles lancées en `docker exec` dans `agentium-worker-cpu` : draineur P4 (intervalle 5 s) + celery beat.
