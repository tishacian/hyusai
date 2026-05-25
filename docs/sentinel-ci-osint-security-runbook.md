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
