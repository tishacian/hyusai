# SENTINEL-CI — Runbook OSINT Sécurité (Vague 2.2)

> **Date** : 25 mai 2026  
> **Périmètre** : RSS sécurité francophone, ADS-B Sahel, indice tension CEDEAO  
> **Statut** : post-démo VP — feature flag **off** par défaut sur le workspace demo

## Vue d'ensemble

La Vague 2.2 ajoute trois pipelines OSINT backend alimentant le cockpit S3 (Posture sécuritaire, Troupes Sahel, indice CEDEAO) avec bascule transparente **LIVE** / **CACHE BASELINE**.

| Pipeline | Service | Cache Redis | Cadence scheduler | Fallback |
|----------|---------|-------------|-------------------|----------|
| RSS sécurité | `rss_security.py` | `intelligence:security:rss:v1` (15 min) | 15 min | fixtures `SECURITY_POSTURE` |
| ADS-B Sahel | `adsb_sahel.py` | `intelligence:security:adsb:v1` (60 s) | 5 min | `resources/security/adsb-sahel-baseline.json` |
| Indice CEDEAO | `cedeao_index.py` | `intelligence:security:cedeao:v1` (30 min) | 30 min | `sovereign-indicators-baseline.json` |

Si Redis est indisponible, un **cache mémoire process** prend le relais (`intelligence/cache.py`).

## Guard rails demo-safe

1. **`workspace.mode == "demo"`** → force toujours baseline (reproductibilité VP).
2. **`feature_flag.security_live_osint`** dans `workspace.settings` → **off** par défaut sur `sentinel-ci`.
3. Feeds RSS **whitelistés** dans `resources/security/security-feeds.json` (pas de Telegram live).
4. ADS-B porte le disclaimer **advisory only** — aucune donnée opérationnelle classifiée.

### Activer le live (interne uniquement)

```json
{
  "feature_flag": {
    "security_live_osint": true
  }
}
```

Et s'assurer que `workspace.mode` n'est **pas** `"demo"` (ex. workspace staging interne).

## Sources

### RSS sécurité (whitelist)

| Feed | URL |
|------|-----|
| RFI Afrique | `https://www.rfi.fr/fr/afrique/rss` |
| Jeune Afrique | `https://www.jeuneafrique.com/feed/` |
| Abidjan.net | `https://news.abidjan.net/rss/` |
| Fraternité Matin | `https://www.fratmat.info/feed` |

Scoring mots-clés FR/EN (sécurité, défense, Sahel, tension…). Déduplication hash titre SHA-256.

### ADS-B Sahel

- API publique : `https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{dist}`
- Hubs : Bamako, Ouagadougou, Niamey, Abidjan
- Classification military : callsigns `RCH`/`KING`/`CHARLY`, `dbFlags`, types C-130/CN-235/C-17/AT-6

### Indice CEDEAO

Composite 0–100 (4 composantes) :

- **Unrest** (30 %) — baseline ACLED-like + RSS
- **Conflict** (25 %) — baseline demo
- **Security advisories** (25 %) — RSS scoring
- **Information** (20 %) — rumeur demo (snapshot S3)

## Endpoints

| Route | Description |
|-------|-------------|
| `GET /api/v1/mission-room/cockpit` | Posture + troupes + badges OSINT |
| `GET /api/v1/mission-room/cedeao-index` | Indice composite seul |

Champs payload utiles :

- `security_posture.osint_sources.rss|cedeao_index`
- `troops_sahel.source_badge` (`LIVE` | `CACHE BASELINE`)
- `security_osint_badges` (cockpit)
- `cedeao_index.score`, `delta_7d`, `components`

## Scheduler

Jobs OSINT intégrés dans `intelligence/scheduler.py` (thread daemon). Démarrage conditionné par :

```env
INTELLIGENCE_SCHEDULER_ENABLED=true
```

Jobs batch RSS existant (12 h) + 3 jobs OSINT (15 min / 5 min / 30 min).

## Bascule live / baseline

```
Requête cockpit
    │
    ├─ demo mode OR flag off → fixtures / baseline JSON
    │
    └─ flag on + non-demo
           ├─ cache Redis hit + live=true → payload LIVE
           └─ cache miss / live=false → baseline JSON
```

Badges UI : `vp-cockpit.component.ts` (RSS + CEDEAO), `vp-troops-theater-drawer` (ADS-B).

## curl (staging interne)

```bash
# Cockpit avec badges (demo → baseline)
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE/api/v1/mission-room/cockpit?workspace=sentinel-ci" \
  | jq '{badges: .security_osint_badges, troops: .troops_sahel.source_badge}'

# Indice CEDEAO
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE/api/v1/mission-room/cedeao-index?workspace=sentinel-ci" \
  | jq '{score, delta_7d, source_badge, live, components}'

# Forcer refresh scheduler (Redis) — appeler sync depuis shell Python si besoin
cd backend && PYTHONPATH=. python -c "
from app.services.intelligence.rss_security import sync_rss_security
from app.services.intelligence.adsb_sahel import sync_adsb_sahel
from app.services.intelligence.cedeao_index import sync_cedeao_index
print('rss', sync_rss_security(force=True)['live'])
print('adsb', sync_adsb_sahel(force=True)['source_badge'])
print('cedeao', sync_cedeao_index(force=True)['score'])
"
```

## Plan de bascule post-démo

1. **J+0** : laisser flag off, valider QA trame S3 inchangée (baseline).
2. **J+1** : activer scheduler + flag sur workspace staging ; vérifier badges LIVE.
3. **J+2** : monitorer cadences Redis, ajuster TTL si rate-limit feeds.
4. **Go prod interne** : activer flag sur workspace cabinet (non-demo) après revue juridique RSS/ADS-B.

## Rollback

1. `feature_flag.security_live_osint = false`
2. Purger caches : `DEL intelligence:security:rss:v1 intelligence:security:adsb:v1 intelligence:security:cedeao:v1`
3. Redémarrer API → retour immédiat aux fixtures demo.

## Tests

```bash
cd backend
pytest app/tests/services/test_intelligence_rss_security.py \
       app/tests/services/test_intelligence_adsb_sahel.py \
       app/tests/services/test_intelligence_cedeao_index.py -q
```

## Fichiers clés

- `backend/app/services/intelligence/rss_security.py`
- `backend/app/services/intelligence/adsb_sahel.py`
- `backend/app/services/intelligence/cedeao_index.py`
- `backend/app/services/intelligence/cache.py`
- `backend/app/services/intelligence/scheduler.py`
- `backend/app/services/mission_room.py` (`_resolve_security_posture`, `_resolve_troops_sahel`)
- `backend/app/resources/security/security-feeds.json`
- `backend/app/resources/security/adsb-sahel-baseline.json`

## Probe ops (post-deploy)

Script Python autonome `scripts/probe_cedeao_index.py` (read-only, mirroring `test_s3_resolver.py`) :

```bash
AGENTIUM_HOST=https://agentium.papai.ai \
AGENTIUM_EMAIL=thibaud.ishacian@datategy.net \
AGENTIUM_PASSWORD='<mot-de-passe-test>' \
WORKSPACE_SLUG=sentinel-ci \
python3 scripts/probe_cedeao_index.py
```

Sortie attendue :

```
[OK] /cedeao-index workspace=sentinel-ci badge=CACHE BASELINE live=False score=72 delta_7d=0.5
[OK] wrote docs/status-screenshots/cedeao-index-probe.json
```

Le probe valide le shape du payload (score 0-100, 4 composantes, badge `LIVE`/`CACHE BASELINE`, `policy=advisory_only`) et dump la réponse JSON pour traçabilité.

## Risques résiduels et conformité

### Rate limits / fiabilité externes

| Source | Quota effectif | Stratégie | Mitigation |
|--------|----------------|-----------|------------|
| RFI / Jeune Afrique / Abidjan.net / Fraternité Matin (RSS) | non documenté (publicly syndicated) | 1 fetch / feed / 15 min depuis 1 IP | Cache 15 min + baseline si HTTP non-200, User-Agent identifié `Agentium-SENTINEL-CI/1.0` |
| `api.adsb.lol` (ADS-B) | ~1 req/s par IP officiel, soft-throttled | 4 hubs × 1 fetch / 60 s = 4 req/min | Cache 60 s + fallback baseline JSON ; switch vers `api.airplanes.live` si rate-limit |
| Composite CEDEAO (interne) | dépend RSS | recalcul toutes les 30 min | Cache 30 min + baseline série `sovereign-indicators-baseline.json` |

### Conditions d'utilisation (ToS)

| Source | Licence / ToS | Obligation | Restriction |
|--------|---------------|------------|-------------|
| RFI Afrique | RSS public Radio France | Lien source + titre conservés | Pas de reproduction du corps d'article |
| Jeune Afrique | RSS commercial | Lien source obligatoire | Diffusion gratuite uniquement (pas de revente) |
| Abidjan.net | RSS public | Citation source | Pas de scraping massif des pages |
| Fraternité Matin | RSS public CI | Citation source | Pas de redistribution intégrale |
| adsb.lol | Open data ADS-B amateur | Attribution recommandée | **Disclaimer advisory-only obligatoire** — données non militaires officielles |
| ACLED-like baseline | Fixture interne | — | Pas de redistribution comme "données ACLED" sans clé officielle |

### Risques de fiabilité

1. **Feed RSS down** → cache 15 min absorbe ; au-delà, payload `live=false` avec source RSS marquée baseline.
2. **adsb.lol coupé** → fallback `adsb-sahel-baseline.json` (10 traces fixtures) ; UI affiche `CACHE BASELINE`.
3. **Redis indisponible** → mémoire process (`intelligence/cache.py:_MEMORY`) prend le relais ; perte du partage entre workers Uvicorn mais demo-safe.
4. **Scheduler thread crash** → loggué `Scheduled OSINT job failed` ; thread daemon, peut être relancé via redémarrage API.
5. **Faux positifs scoring sécurité** → seuil `>=30` filtre les articles non pertinents ; ajustable via `score_security_text` (FR/EN).

### Risques juridiques / éthiques

- **Aucune redistribution** du corps d'article RSS — seul le titre + URL est conservé en signal `sources`.
- **ADS-B advisory-only** : le disclaimer `aucune donnée opérationnelle classifiée` est inscrit dans le payload `troops_sahel.disclaimer` et le widget UI.
- **Feeds Telegram non intégrés** en v2.2 (volonté explicite — risque de désinformation non maîtrisée). Reste snapshot S3.
- **Pas de profilage** ni d'enrichissement nominatif (RGPD / CDP-CI) — seules les zones géographiques et titres sont conservés.

## Coordonnées (v2.1)

Les surfaces frontend (onglet Sécurité, Security Monitor plein écran, page Veille sociale, Réputation rail) sont livrées par la Vague 2.1 et consomment les badges OSINT exposés ici via :

- `cockpit.security_osint_badges` (clés `rss_security` / `adsb_sahel` / `cedeao_index`)
- `cockpit.security_posture.osint_sources` (badges in-card)
- `cockpit.troops_sahel.source_badge` (`LIVE` | `CACHE BASELINE`)
- `cockpit.cedeao_index` (composite + composantes pour le widget dédié)

## Tests v2.2 (verdict)

| Suite | Nombre | Statut |
|-------|--------|--------|
| `test_intelligence_rss_security.py` | 8 | PASS |
| `test_intelligence_adsb_sahel.py` | 8 | PASS |
| `test_intelligence_cedeao_index.py` | 9 | PASS |
| `test_intelligence_scheduler_osint.py` | 7 | PASS |
| `test_cedeao_index_api.py` | 3 | PASS |
| **Total v2.2** | **35** | **PASS** |

Pré-existants hors v2.2 (issus de la Vague 2.1 territoire) :

- `test_mission_room.test_sentinel_ci_seed_is_idempotent_and_demo_scoped` — assertion NAV_ITEMS à mettre à jour par v2.1.
- `test_mission_room_api.test_mission_room_navigation_cockpit_and_search_are_audited` — idem.
- `test_mission_room_knowledge_sync.test_mission_room_fixture_sync_indexes_all_vigie_scope_collections` — collection `sentinel-ci-security-briefs` à intégrer dans la liste attendue par v2.1.
