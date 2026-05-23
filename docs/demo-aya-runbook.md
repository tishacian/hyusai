# Runbook — Démonstration AYA (S1 + S2)

Ce runbook récapitule le déroulé de démonstration SENTINEL-CI / AYA après les
enrichissements `demo_aya_enrichments_s1_s2_85eea55f` (phases A–I).

> Document **advisory-only**. Aucune décision opérationnelle ne doit découler de
> la démonstration. Toutes les actions AYA passent par une validation Cabinet
> avant exposition publique.

## 1. Préparation (pré-flight)

### 1.1 Build des PDF démo (~70 pages)

```bash
cd backend
poetry run python -m app.cli.build_sentinel_reports --force
# Sortie : rapport Préfet Nawa généré + copié dans l'object store du workspace
```

Le binaire `weasyprint` doit être installé (groupe `build` du `pyproject.toml`).
Le script est **idempotent** : la regénération est skippée si le hash du
markdown n'a pas changé.

### 1.2 Rafraîchissement des indicateurs macro (Banque mondiale)

```bash
poetry run python -m app.cli.refresh_macro_indicators --force
# Cache écrit dans workspace_macro_indicators (TTL 24h)
# Celery: tâche périodique agentium.refresh_macro_indicators (24h)
```

Si le réseau est gated, le fallback `backend/app/resources/macro/civ-indicators-baseline.json`
est utilisé automatiquement (status = `fallback`).

### 1.3 PV douanes OCR (Phase D)

```bash
poetry run python scripts/generate_customs_pdf.py --force
# Sortie : backend/app/resources/sentinel_ci_customs/proces-verbal-douanes-non-conformite-2026-05-18.pdf
```

La collection `sentinel-ci-customs-records` ingère le markdown source au boot
via `sync_mission_room_fixtures_to_knowledge`. Le PDF flattened sert d'OCR via
`tesseract_local`.

### 1.4 Smoke-tests minimum

```bash
poetry run pytest \
  app/tests/services/test_macro_indicators.py \
  app/tests/api/test_evidence_graph_trace.py \
  app/tests/api/test_meetings.py \
  app/tests/services/test_actions_resolver.py \
  app/tests/api/test_chat_stream_hardening.py \
  app/tests/api/test_mission_room_api.py \
  -p no:warnings -q
# Attendu : 56 tests passés
```

## 2. Trame S1 — chaîne causale (≈5 minutes)

| t (s) | Prompt VP | Action AYA | Effet UI attendu |
|------|-----------|------------|------------------|
| 0    | Ouvrir le cockpit Mission Room |  | Sparkline macro (Phase B), KPIs |
| 25   | « Pourquoi la situation Nord est-elle tendue ? » | `aya.explain_why` (caused_by) | navigation `strategie` focus zone-nord + project |
| 60   | « Et pourquoi ce projet est en retard ? » | `aya.explain_why` (drill) | focus cargo MV Atlantic Trader |
| 95   | « Pourquoi cette cargaison est-elle bloquée ? » | `aya.explain_why` + proposal | drawer "Voir le PV douanes ?" |
| 130  | « Oui » | `aya.show_customs_record` | drawer document_preview p.2 + proposal "Préparer dérogation ?" |
| 175  | « Oui » | `aya.draft_customs_email` (template `customs_derogation`) | drawer brouillon email distinguant cargo Nord vs cargo non-conforme, citant PV p.2 |
| 230  | Validation Cabinet (advisory) | aucune écriture sortante | bandeau "advisory-only" |

**Plan B (si offline)** :

- Si l'API Banque mondiale est gated → KPI sparkline en mode `fallback` (badge
  "cache baseline"), pas de blocage démo.
- Si Tesseract indisponible → PV affiché en mode markdown sans OCR, citation
  page 2 conservée via metadata seedée.

## 3. Trame S2 — meeting live (≈7 minutes)

| t (s) | Prompt VP | Action AYA | Effet UI attendu |
|------|-----------|------------|------------------|
| 0    | « Quel est mon prochain RDV ? » | `aya.open_next_meeting` | navigation `agenda`, highlight Préfet Nawa |
| 30   | « Résumé du rapport préfet » | `aya.summarize_last_exchanges` | synthèse + proposal "Préconisations cacao ?" |
| 80   | « Oui » | `aya.recommend_cacao` (topic=cacao_diversification) | 3 options sourcées, navigation `decisions` |
| 145  | « Génère le rapport complet » | `aya.draft_strategic_report` → POST `/api/v1/reports/generate` | drawer rapport stratégique + signed URL ObjectStore |
| 220  | « Ajoute le point cacao à l'ordre du jour » | `aya.update_meeting_agenda` (confirm) | drawer calendar_agenda_patch (validation requise) |
| 280  | « Oui, valide » → PATCH `/api/v1/calendar/events/{id}` | écriture metadata.agenda_items + history versionné | agenda mis à jour, history visible |
| 320  | « Démarre la réunion » | `aya.start_meeting` | navigation `/agenda/meeting/{id}` |
| 360  | « Décide option B » | `aya.log_decision` | POST `/api/v1/meetings/{id}/decisions` → registre logué + audit |
| 410  | « Qu'avons-nous décidé la dernière fois ? » | `aya.recall_past_decisions` | rappel RAG sur `meeting_decisions` |

**Plan B (si offline)** :

- Si la WebCam APM Apapa (`apmterminals.com`) ne répond pas → fallback statique
  via le `demo_fallback=True` dans `WorkspaceVisualSource.meta_data`.
- Si la génération PDF échoue → `_stub_pdf_bytes` fournit un PDF minimal valide
  pour ne pas casser le download flow ; l'UI affiche la même bannière advisory.

## 4. Chips Plan B (pendant la démo)

- **Macro indicators** : `source=Banque mondiale (cache baseline)` quand offline.
- **Webcam APM** : disclaimer "Démo : Apapa (Lagos)" affiché sur le tuile.
- **PV douanes** : si l'OCR est skippé, citation page 2 reste valide via metadata.
- **Rapport 70p** : si WeasyPrint absent, stub PDF + bannière "demo-safe".
- **Meeting decisions** : registre persistant en `meeting_decisions` (workspace-
  scoped), récupérable même après redémarrage.

## 5. Vérifications post-démo

```bash
# Audit logs des actions AYA
psql sentinel-ci-demo -c "select event_type, count(*) from audit_logs where event_type like 'action.aya.%' or event_type like 'meeting.%' or event_type like 'macro_indicators.%' group by event_type;"
```

- `action.aya.explain_why` : ≥ 3 (drill causal)
- `action.aya.show_customs_record` : 1
- `action.aya.draft_customs_email` : 1
- `meeting.decision.logged` : 1 (S2)
- `report.strategic.generated` : 1 (S2)
- `macro_indicators.refreshed` : 1 (pre-flight)

## 6. Annexes

- Plan source : `.cursor/plans/demo_aya_enrichments_s1_s2_85eea55f.plan.md`
- Mémo transverse : `docs/sentinel-ci-agentium-transverse-handoff-2026-05-23.md`
- Guide expert cacao : `backend/app/resources/sentinel_ci_guides/sentinel-ci-anacarde-diversification-v1.md`
- Markdown du PV douanes : `docs/demo-data/sentinel-ci-kb/proces-verbal-douanes-non-conformite-2026-05-18.md`
- Sources des phrases AYA : `backend/app/services/actions/registry.py` (pack `sentinel_ci_aya_v1`).
