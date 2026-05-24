# SENTINEL-CI — Intégration maritime / AIS & webcams publiques

> **Statut** : livré pour la démo VP lundi 25 mai 2026.
> **Périmètre** : ajouter dans le cockpit SENTINEL-CI une couche **navires AIS** centrée
> sur Abidjan / Vridi (ancrant `MV Atlantic Trader`), et **enrichir le pack visual_intelligence**
> avec des webcams **port / météo / trafic** publiques.
> **Garde-fous** : advisory-only, baseline démo-safe systématique, providers live en option
> uniquement via variables d'environnement, ToS respectées (pas de redistribution AIS payante,
> embeds publics avec attribution).

---

## 1. Audit ciblé du dépôt osiris

Exploration **lecture seule** de `/Users/thib/Developer/PAPAI/osiris` (Next.js, App Router).

### 1.1 Sources maritime / AIS

| # | Source osiris | Type | Path | Auth | Couverture | Champs | Note démo /5 |
|---|---------------|------|------|------|------------|--------|--------------|
| 1 | **Maritime route statique** | Dataset hardcodé (TS) | `src/app/api/maritime/route.ts:9-67` | Aucune | 50 ports mondiaux + 10 chokepoints — **Abidjan ABSENT** | `name, country, lat, lng, type, volume, rank, fleet, risk` | 2/5 — pas de Côte d'Ivoire, pas de positions vessels |
| 2 | **AIS placeholder** | Env var | `.env.example:7`, `docker-compose.yml:14` | Clé `AIS_API_KEY` (aisstream.io) | Globale si activé | n/a — pas d'implémentation | 1/5 — placeholder uniquement |
| 3 | **MarineTraffic embed** | (mentionné dans cctv types) | `src/app/api/cctv/types.ts:28` (regex de détection iframe) | Aucune (widget public) | Globale | n/a | 4/5 — pattern réutilisable |

**Conclusion** : osiris **n'a pas de connecteur AIS opérationnel** pour le Golfe de Guinée
ni de jeu de données navires temps réel. Le `maritime/route.ts` est un dataset statique sans
Abidjan ni San Pedro, et `AIS_API_KEY` est documenté mais jamais consommé. Le pattern
embed iframe est documenté côté types CCTV (rtsp.me, windy/embed) mais pas spécifiquement appliqué
aux navires. Pour AIS on **part donc d'une feuille blanche** côté SENTINEL-CI, avec une baseline
JSON démo-safe maison et un provider live optionnel (AISStream.io).

### 1.2 Sources webcams / flux vidéo

osiris dispose d'un **écosystème CCTV très riche** (`src/app/api/cctv/`, ~13 sources nationales)
qui constitue un excellent modèle d'intégration. Pour SENTINEL-CI / Côte d'Ivoire il manque
des sources directes, mais les **patterns** sont directement réutilisables :

| # | Source / pattern osiris | Type | Path | Auth | Notes ToS | Note démo /5 |
|---|-------------------------|------|------|------|-----------|--------------|
| 1 | **Asfinag** (Autriche) | REST JSON + JPG snapshot | `src/app/api/cctv/asfinag.ts` | Header `Authorization: Basic ...` | Public OK, attribution Asfinag | 5/5 pattern (cache TTL + fallback silencieux) |
| 2 | **TfL JamCams** (Londres) | REST JSON + JPG | `src/app/api/cctv/route.ts:21-37` | Aucune | Public OK | 5/5 pattern fetch |
| 3 | **Singapour LTA** | REST JSON + JPG | `route.ts:251-271` | Aucune | data.gov.sg | 5/5 |
| 4 | **Caltrans** (US) | JSON per-district | `route.ts:54-71` | Aucune | Public | 4/5 |
| 5 | **Florida 511** | REST JSON | `route.ts:202-217` | Aucune | Public | 4/5 |
| 6 | **Windy embeds** (helper) | iframe + JPG snapshot | `src/app/api/cctv/turkey.ts:3-12` (`windy()` helper) | Aucune | ToS Windy : embed OK avec attribution | 5/5 pour port-météo |
| 7 | **EarthCam** | iframe externe | `route.ts:196-200` | Aucune (consultation seulement) | ToS : embed officiel uniquement, jamais de scraping | 3/5 |
| 8 | **CameraViewer.tsx** | Composant lecteur multi-stream | `src/components/CameraViewer.tsx` | n/a | Gère `jpg`, `hls` (via hls.js), `iframe` | 5/5 réf. UI |
| 9 | **Pattern types** | `CctvCamera`, `inferStreamType` | `src/app/api/cctv/types.ts` | n/a | Discrimination `jpg | hls | iframe` | 5/5 réf. modèle |

**Pas de source webcam publique directe pour Abidjan / Vridi dans osiris**, mais le pattern
Windy `windy(id)` est immédiatement transposable à un overlay webcam météo pour la Côte d'Ivoire,
et le `CameraViewer` est un modèle d'UI propre (HLS + iframe + JPG refresh 5 s).

### 1.3 Synthèse réutilisable pour SENTINEL-CI

| Domaine | Réutilisé d'osiris | Original SENTINEL-CI |
|---------|-------------------|----------------------|
| **AIS** | Pattern provider + env key (`AIS_API_KEY` → `SENTINEL_AISSTREAM_API_KEY`) | Service `maritime_tracking.py`, baseline JSON, modèle `VesselPosition` (Pydantic), endpoint `/mission-room/maritime/*` |
| **Webcams port** | Pattern Windy embed + helper iframe + `CameraViewer` UX | Iframe MarineTraffic public + snapshot demo APM (déjà présent), webcam météo Windy cote ivoirienne |
| **Webcams trafic** | Pattern Asfinag (cache 1h + Promise pending) | Conservation des 8 webcams Abidjan.net déjà seedées (Pont Gen-de-Gaulle, Plateau, Marcory, etc.) |

---

## 2. Implémentation livrée

### 2.1 Backend

#### Service `backend/app/services/maritime_tracking.py` *(nouveau, 350 lignes)*

- Modèles Pydantic : `BBox`, `VesselPosition`, `VesselSnapshot`.
- Providers enregistrés : `baseline`, `aisstream`, `aishub`, `marinetraffic_embed`.
- API publique :
  ```python
  fetch_snapshot(bbox: BBox | None, *, provider: str | None = None, use_cache: bool = True) -> VesselSnapshot
  fetch_vessels_in_bbox(bbox: BBox | None, limit: int = 50, *, vessel_types: list[str] | None = None) -> list[VesselPosition]
  find_vessel_by_mmsi(mmsi: str) -> VesselPosition | None
  find_vessel_by_imo(imo: str) -> VesselPosition | None
  serialize_snapshot(snapshot) -> dict
  serialize_vessel(vessel) -> dict
  ```
- Cache TTL (60-300 s) par provider, clé bbox-quantifiée.
- Tri stable : navires `highlight` (chaîne narrative) → puis `linked_cargo_id` → puis MMSI.
- Tous les providers live **dégradent silencieusement vers baseline** si la clé est manquante
  ou si l'appel échoue. Pas de bruit dans les logs critiques.
- AISStream et AISHub sont volontairement *stubbés* : ils valident le câblage et exposent une
  trace `logger.info`, mais ne montent pas (encore) de consommateur WebSocket / REST. Voir §3
  ci-dessous pour activer la consommation live.

#### Baseline démo-safe `backend/app/resources/maritime/abidjan-vessels-baseline.json` *(nouveau)*

- 15 navires positionnés autour de la rade d'Abidjan / Vridi (5.25°N, 4°W env), couvrant :
  cargo, container (Maersk, CMA CGM, MSC), tankers (Stolt, BW), RoRo (Grimaldi), bulker,
  fishing, tugs (pilote / remorqueurs portuaires).
- `MV ATLANTIC TRADER` (MMSI `627012345`, IMO `9876543`) positionné `lat 5.2530, lon -4.0124`,
  `nav_status="at_anchor"`, lié au cargo `cargo-abidjan-supply-001` et au projet
  `proj-drone-centre-napie`. Champ `demo_role` documente son ancrage narratif S1.
- bbox de référence : `west=-4.25, south=5.05, east=-3.75, north=5.40`.
- Attribution démo explicite, TTL 300 s.

#### Endpoint `backend/app/api/v1/endpoints/maritime.py` *(nouveau)*

Routes (préfixe `/api/v1/mission-room/maritime/`) :

- `GET /vessels?bbox=west,south,east,north&limit=50&vessel_types=cargo,tanker` →
  `{ vessels: [...], bbox, source, provider, fetched_at, embed_url, attribution, limitations,
  count, filters, workspace, policy: "advisory_only", demo_safe }`
- `GET /vessels/{mmsi}` → `{ vessel, snapshot, linked_cargo?, workspace, policy }` ;
  404 si MMSI inconnu, 400 si non-numérique.
- `GET /snapshot` → métadonnées seulement (sans vessels), utile pour le footer UI.

Tous les endpoints émettent `maritime.vessels.listed`, `maritime.vessel.viewed`,
`maritime.snapshot.viewed` dans l'audit log (acteur = user.email, workspace scopé).

Wiring : `backend/app/api/v1/router.py` ajoute `from app.api.v1.endpoints import maritime`
+ `api_router.include_router(maritime.router, prefix="/mission-room/maritime", ...)`.

#### Extension `backend/app/services/workspace_maps.py`

- Nouveau helper `_maritime_vessel_features()` : convertit le snapshot baseline en
  GeoJSON `FeatureCollection` (clé `maritime_vessels` dans `geojson_sources`).
- `_maritime_snapshot_payload()` enrichi avec `vessels`, `vessels_provider`, `vessels_source`,
  `vessels_embed_url`, `vessels_attribution`, `vessels_fetched_at`. Les limitations du provider
  sont concaténées sans doublon.
- `_source_counts()` ajoute `len(vessels)` au compteur de la couche `maritime-traffic`.
- L'identifiant `cargo-abidjan-supply-001` reste **un seul objet narratif** : la carte expose
  désormais à la fois la `vessel_snapshot` cargo (MARITIME_EVENTS) **et** le point AIS du navire
  (MMSI 627012345). Les deux pointent vers la même cible (même MMSI, même IMO).

#### Extension `backend/app/services/visual_intelligence.py`

- Tuple `ABIDJAN_NET_VISUAL_SOURCES` étendu de 9 → **12 entrées** :
  - `MarineTraffic - Port d'Abidjan (overlay AIS)` : iframe public sans clé, attribution dans
    le widget (`kind: port_webcam`).
  - `Windy - Cote d'Ivoire (meteo / cotier)` : embed Windy météo (`kind: weather_webcam`).
  - `Aeroport FHB - veille acces (demo-safe)` : snapshot démo statique pour le trafic
    aéroport / Port Bouët (`kind: traffic_webcam`, `adapter: demo_static`).
- Helper `_webcam_metadata(spec)` accepte désormais `spec["metadata_overrides"]` : chaque
  source peut écraser `provider`, `layer_kind`, `kind`, etc. sans casser les défauts.
- `_apply_seed_source()` respecte aussi `spec.get("adapter")` (utile pour `demo_static`).

#### Configuration `backend/app/core/config.py`

Nouvelles options (toutes optionnelles, valeurs par défaut sûres) :

```python
sentinel_ais_provider: str = "baseline"
sentinel_aisstream_api_key: Optional[str] = None
sentinel_aishub_username: Optional[str] = None
sentinel_marinetraffic_embed_default_zoom: int = 11
```

Variables d'environnement correspondantes : `SENTINEL_AIS_PROVIDER`,
`SENTINEL_AISSTREAM_API_KEY`, `SENTINEL_AISHUB_USERNAME`,
`SENTINEL_MARINETRAFFIC_EMBED_DEFAULT_ZOOM`.

### 2.2 Frontend

#### `frontend-ng/src/app/features/mission-room/vp-map-preview.component.ts`

- Composant existant étendu avec une **section overlay vessels** (SVG schématique 100×60).
- Inject `ApiService`, fetch `/mission-room/maritime/vessels?bbox=-4.25,5.05,-3.75,5.40&limit=50`
  au `ngOnInit()`.
- Markers SVG :
  - Triangle orienté selon `heading` (fallback `cog`).
  - Couleur par `vessel_type` : cargo/container (vert), tanker (ambre), Ro-Ro (cyan),
    passenger (violet), fishing/tug/other (gris).
  - Navires `highlight` ou `linked_cargo_id` rendus en **violet AYA** (`#B488FF`)
    avec un halo dropshadow et une bordure renforcée.
- Tooltip on-click : `MV NAME · MMSI · IMO · destination · ETA · provider · type`.
- Si `linked_cargo_id` présent → badge violet "Cargo lié au projet Centre Drones Napié".
- Légende fixe en pied : Cargo / Tanker / Ro-Ro / Passager / Pêche / Autre / Cargo lié projet.
- Fallback : `vesselErrorMessage = 'AIS indisponible — mode baseline démo'` affiché si la
  réponse est vide ou en erreur.
- Outputs : `vesselSelected` permet aux parents de réagir au click (ex. ouvrir un drawer).

#### Réutilisation par l'action AYA existante

L'action `aya.show_vessel_evidence` (`backend/app/services/actions/executor.py:338-392`)
peut désormais hydrater son payload via :

```http
GET /api/v1/mission-room/maritime/vessels/627012345
```

et y trouver le bloc `linked_cargo: { id, project_ref, narrative_role }` pour enrichir
l'effet UI sans dupliquer les données navire dans l'action elle-même.

### 2.3 Tests

`backend/app/tests/api/test_maritime_api.py` (16 tests) :

- baseline contient bien `MV Atlantic Trader` lié au cargo et au projet ;
- filtre bbox limite aux navires à l'intérieur, retourne `[]` hors zone ;
- filtre `vessel_types` ;
- endpoint `/vessels` : envelope (`source/provider/policy/demo_safe/count/filters`) + audit ;
- endpoint `/vessels/{mmsi}` : succès (avec `linked_cargo`), 404 inconnu, 400 non numérique ;
- erreurs bbox (4 valeurs, west<east, south<north) ;
- endpoint `/snapshot` ;
- provider `marinetraffic_embed` → expose `embed_url` MarineTraffic ;
- provider `aisstream` sans clé → fallback baseline + limitation ;
- cache identité ;
- serialize_snapshot porte attribution + limitations ;
- provider inconnu → fallback baseline ;
- importlib.reload safe.

**Régressions vérifiées** : `pytest backend/app/tests/api/ backend/app/tests/services/test_mission_room.py -q` → **72 tests passent** (visual_intelligence, mission_room, maps, evidence_graph_trace, meetings, etc.).

---

## 3. Mode d'emploi : activer un provider live

Tous les providers live **doivent rester optionnels** et dégrader vers la baseline si
indisponibles. Aucun ne casse la démo offline.

### 3.1 Provider `baseline` (par défaut)

```bash
# Aucune variable nécessaire — le service lit
# backend/app/resources/maritime/abidjan-vessels-baseline.json
```

→ 15 navires Abidjan, TTL 300 s, attribution démo, MV Atlantic Trader lié au cargo.

### 3.2 Provider `marinetraffic_embed` (live overlay sans clé)

```bash
export SENTINEL_AIS_PROVIDER=marinetraffic_embed
```

→ Le snapshot continue de servir les 15 vessels baseline (positions stables pour le drill),
mais le champ `embed_url` retourne l'iframe public MarineTraffic centré sur Abidjan/Vridi
zoom 11. À embedder dans une `<iframe>` 16:9. **ToS** : pas de scraping, attribution
affichée par MarineTraffic dans l'iframe.

### 3.3 Provider `aisstream` (WebSocket gratuit avec clé)

1. Créer un compte sur https://aisstream.io et générer une clé API gratuite.
2. Configurer :
   ```bash
   export SENTINEL_AIS_PROVIDER=aisstream
   export SENTINEL_AISSTREAM_API_KEY=<votre-clé>
   ```
3. Wirer un consommateur WebSocket (à faire pour aller au-delà du stub livré).
   Pattern recommandé : worker `app/workers/maritime_aisstream_consumer.py` qui :
   - Ouvre `wss://stream.aisstream.io/v0/stream`
   - Envoie un message JSON `{ APIKey, BoundingBoxes: [[[5.0,-4.5],[5.5,-3.5]]], FiltersShipMMSI: [...] }`
   - Pour chaque `PositionReport` reçu, met à jour un cache Redis ou un store en mémoire
     (clé `maritime:vessel:{mmsi}`)
   - Le service `maritime_tracking._aisstream_snapshot` lit ce cache et le combine au
     baseline (les navires non vus dans le live restent baseline).
4. Dépendance Python à ajouter dans `backend/pyproject.toml` si l'on monte le worker :
   ```toml
   websockets = "^12.0"  # commenté : optionnel, uniquement pour le worker AISStream
   ```
   À ce stade, **rien à installer** côté demo (le stub ne consomme pas de WebSocket).

**ToS AISStream** : usage non commercial, attribution `"AISStream.io"`. Live tagged
`source: "aisstream"` dans la réponse. La baseline reste appelée silencieusement tant
que le worker n'est pas démarré.

### 3.4 Provider `aishub` (REST gratuit limité)

1. S'inscrire sur https://www.aishub.net et obtenir un username.
2. Configurer :
   ```bash
   export SENTINEL_AIS_PROVIDER=aishub
   export SENTINEL_AISHUB_USERNAME=<votre-user>
   ```
3. Wirer (à faire) un adapter qui appelle
   ```
   https://data.aishub.net/ws.php?username=<user>&format=1&output=json&latmin=...&latmax=...&lonmin=...&lonmax=...
   ```
   Cache TTL 120 s. Quota gratuit limité — ne pas exposer en POST.

---

## 4. Lien avec la trame storytelling

### Scénario S1 (Nord — cargo bloqué)

Quand le VP demande **« Pourquoi cette cargaison est-elle bloquée ? »**, l'effet UI peut
maintenant :

1. Appeler `GET /api/v1/mission-room/maritime/vessels/627012345`
2. Ouvrir le drawer vessel-evidence existant (`aya.show_vessel_evidence`)
3. Forcer la carte sur la position AIS (`lat 5.2530, lon -4.0124`) — la `vessel_snapshot`
   cargo existante reste la source de vérité, le point AIS est l'**ancrage visuel**.
4. Afficher la vignette MarineTraffic iframe en bas du panneau maritime via la source visual
   `MarineTraffic - Port d'Abidjan (overlay AIS)`.

Le badge UI **« Cargo lié au projet Centre Drones Napié »** (violet AYA) confirme visuellement
le lien à la chaîne causale (`proj-drone-centre-napie` → `cargo-abidjan-supply-001`
→ `customs-record-non-conformite-2026-05`).

### Scénario S2 (Nawa — corridors cacao)

La même API supporte un drill San Pedro :

```http
GET /api/v1/mission-room/maritime/vessels?bbox=-7.0,4.4,-6.0,5.0
```

Pour la démo lundi, ces vessels ne sont pas seedés dans la baseline (le scope est Abidjan).
À ajouter en S+1 (extension du JSON baseline avec quelques navires San Pedro / corridor
export cacao).

---

## 5. Garde-fous et conformité

- **Lecture seule sur osiris** : aucune écriture, aucune copie de clé en clair.
- **Aucune nouvelle dépendance pip / npm obligatoire**. `websockets` reste commenté dans
  `pyproject.toml` (seulement nécessaire si l'on monte le worker AISStream).
- **Tous les fetchers ont un fallback baseline** : démo offline OK.
- **ToS** :
  - MarineTraffic embed = OK (widget public, attribution intégrée). API MarineTraffic =
    payante et non utilisée.
  - AISStream / AISHub = clés gratuites OK avec attribution. **Tagged** dans le payload.
  - Windy = embed officiel uniquement, jamais de capture intermédiaire.
  - Abidjan.net = inchangé (image publique + Nest embed officiel).
- **Coordination merge** : ce travail ne touche **pas** `workspace_calendar.py`,
  `demo_time_context.py`, `registry.py`, `executor.py`, `mission_room.py::cockpit_payload`.
  Seules modifications partagées : `workspace_maps.py` (ajout vessels GeoJSON et compteurs),
  `visual_intelligence.py` (ajout 3 sources + override metadata), `core/config.py` (ajout
  block "Maritime / AIS"), `api/v1/router.py` (ajout de l'import et include).

---

## 6. Fichiers créés / modifiés (résumé diff)

### Créés

| Path | Lignes | Rôle |
|------|--------|------|
| `backend/app/services/maritime_tracking.py` | 388 | Service provider-agnostic vessels |
| `backend/app/api/v1/endpoints/maritime.py` | 161 | Routes `/mission-room/maritime/*` |
| `backend/app/resources/maritime/abidjan-vessels-baseline.json` | 196 | Snapshot 15 navires Abidjan |
| `backend/app/tests/api/test_maritime_api.py` | 188 | 16 tests (unitaires + API) |
| `docs/sentinel-ci-maritime-webcams-integration.md` | ce fichier | Doc audit + intégration + mode d'emploi |

### Modifiés

| Path | Δ | Rôle |
|------|---|------|
| `backend/app/api/v1/router.py` | +2 lignes | Import + include `maritime` |
| `backend/app/core/config.py` | +12 lignes | Block "Maritime / AIS" (4 settings) |
| `backend/app/services/workspace_maps.py` | +60 lignes | `_maritime_vessel_features`, vessels dans snapshot, comptage couche `maritime-traffic` |
| `backend/app/services/visual_intelligence.py` | +120 lignes | 3 sources (MarineTraffic, Windy, FHB) + helper `metadata_overrides` |
| `frontend-ng/src/app/features/mission-room/vp-map-preview.component.ts` | +220 lignes | Overlay vessels SVG + légende + tooltip + badge AYA |

---

## 7. Sample réponse `GET /maritime/vessels?bbox=-4.1,5.20,-3.9,5.30` (baseline)

```json
{
  "vessels": [
    {
      "mmsi": "627012345",
      "imo": "9876543",
      "name": "MV ATLANTIC TRADER",
      "callsign": "TUMA9",
      "lat": 5.253,
      "lon": -4.0124,
      "sog": 0.0,
      "cog": 215.0,
      "heading": 220.0,
      "vessel_type": "cargo",
      "nav_status": "at_anchor",
      "destination": "ABIDJAN",
      "eta": "2026-05-17T18:00:00Z",
      "length": 198.0,
      "beam": 32.0,
      "draught": 11.4,
      "flag": "LR",
      "last_seen": "2026-05-25T08:15:00Z",
      "source": "baseline",
      "demo_safe": true,
      "linked_cargo_id": "cargo-abidjan-supply-001",
      "linked_project_ref": "proj-drone-centre-napie",
      "highlight": "anchor_collateral_customs_pv",
      "demo_role": "S1 — cargo bloque a Vridi (composants drones Aerostar Dynamics pour le Centre Napie)"
    },
    {
      "mmsi": "636019287",
      "imo": "9456127",
      "name": "MAERSK ABIDJAN",
      "lat": 5.2535,
      "lon": -4.0009,
      "sog": 0.2,
      "heading": 92.0,
      "vessel_type": "container",
      "nav_status": "moored",
      "destination": "ABIDJAN",
      "source": "baseline",
      "demo_safe": true
    }
    // … 11 autres navires (Grimaldi Ro-Ro, Stolt tanker, BW tanker, CMA CGM,
    //   MSC, Pilot Vridi, tugs locaux, fishing TULG…) tronqués
  ],
  "bbox": {"west": -4.1, "south": 5.2, "east": -3.9, "north": 5.3},
  "source": "baseline",
  "provider": "baseline",
  "fetched_at": "2026-05-25T08:15:00Z",
  "ttl_seconds": 300,
  "embed_url": null,
  "attribution": "demo SENTINEL-CI, baseline statique cale sur la trame storytelling AYA (2026-05-25). A remplacer par un provider AIS (aisstream.io / aishub) en production.",
  "limitations": [
    "Snapshot demo-safe : positions cohérentes mais non temps réel.",
    "Aucun appel a un provider AIS payant."
  ],
  "policy": "advisory_only",
  "demo_safe": true,
  "count": 13,
  "filters": {
    "bbox": {"west": -4.1, "south": 5.2, "east": -3.9, "north": 5.3},
    "vessel_types": [],
    "limit": 50
  },
  "workspace": {"id": "workspace-sentinel", "slug": "sentinel-ci"}
}
```

---

## 8. Itération webcams port — audit + proxy + auto-sélection (24 mai 2026)

> **Patch C** : couche webcam port renforcée pour la démo VP du lundi 25 mai —
> 4 sources solides (APM Apapa ×2, PAA aérienne, VesselFinder), un proxy
> snapshot serveur pour neutraliser le CSP `frame-ancestors 'self'` d'APM,
> et l'auto-sélection de la webcam port quand AYA drill sur `MV Atlantic Trader`.

### 8.1 Audit d'accessibilité des sources (24 mai 2026)

Tests exécutés via `curl -I`/`curl -L` depuis le poste de démo (Cote d'Ivoire-friendly user agent, TLS 1.3).

| # | Source candidate | Statut HTTP | Verdict embed | Décision SENTINEL-CI |
|---|------------------|-------------|---------------|----------------------|
| 1 | `https://www.apmterminals.com/en/apapa/practical-information/gate-cameras` | 200 (HTML 7 KB) | **NON** — CSP `frame-ancestors 'self'`, iframe externe refusée | Page CSP-bloquée ; on extrait les 2 endpoints JPG directs |
| 1a | `https://cms-cd.apmterminals.com/apm/api/v1/gatecameras/gate-camera?id=13b8ab33-…` (gate-cam #1) | 200 `image/jpeg` 86 KB 800×600 | OK (asset direct, `Cache-Control: max-age=300`) | **SEED via proxy** `apm-apapa-gate-1` |
| 1b | `…?id=10f6ae28-…` (gate-cam #2) | 200 `image/jpeg` 87 KB 800×450 | OK | **SEED via proxy** `apm-apapa-gate-2` |
| 2 | `https://www.paa-ci.org` | DNS introuvable | — | Domaine officiel inaccessible |
| 2b | `https://portabidjan.ci` (domaine PAA réel) | 200 (HTML 99 KB Drupal) | N/A (pas de live) | **SEED 3 photos officielles** servies via proxy (`paa-aerial-vue`, `paa-terminal-petrolier`, `paa-terminal-fruitier`) |
| 3 | `https://www.aglgroup.com` (AGL Africa Global Logistics) | 200 (HTML 1.3 MB) | À explorer — pas de CCTV publique repérée dans le landing | **Écarté pour cette itération** (priorité aux 4 sources solides) |
| 3b | `https://cotedivoireterminal.com` | TLS handshake failure | — | **Écarté** (TLS instable, pas de fallback) |
| 4 | `https://www.vesselfinder.com/aismap?zoom=11&lat=5.25&lon=-3.99` | 200 (HTML widget, **pas de X-Frame-Options ni de CSP frame-ancestors**) | OK iframe | **SEED iframe** `vesselfinder.aismap.public` |
| 4b | `https://www.vesselfinder.com/` (home) | 200 + `X-Frame-Options: DENY` | NON | Écarté pour iframe |
| 5 | `https://www.marinetraffic.com/en/photos/of/ports/portid:…` | 403 (Cloudflare anti-bot) | NON (scraping bloqué) | On garde l'iframe AIS MarineTraffic existant ; pas de page « photos » exploitable |
| 6 | `https://www.webcamtaxi.com/en/africa/ivory-coast.html` | 403 (Cloudflare) | — | **Écarté** (aucun contenu Abidjan repéré dans les sitemaps publics) |

**Total : 4 sources port seedées (APM ×2, PAA aérienne, VesselFinder)** plus
2 PAA optionnelles (terminal pétrolier / fruitier) pour cycler.

### 8.2 Nouveau service `backend/app/services/webcam_proxy.py`

Un proxy snapshot serveur publie un JPG/PNG par `source_id` whitelisté. Le
proxy résout, dans l'ordre :

1. **Cache process-local** `dict[source_id] → bytes + TTL` (positif 30-300 s,
   négatif 60 s pour ne pas marteler après un échec). Verrou `threading.Lock`
   pour rester safe sous Gunicorn workers.
2. **Fetch upstream** via `httpx.Client` (timeout 12 s, follow redirects,
   User-Agent `SENTINEL-CI/1.0`). Si statut ≥ 400 ou `Content-Type` non
   `image/*` → fallback.
3. **Fallback statique** : JPG/PNG embarqué dans
   `backend/app/resources/webcams/` (téléchargé une fois pour la démo
   offline). Dernier recours : un PNG 1×1 transparent généré en mémoire.

```python
WebcamSourceSpec(
    source_id="apm-apapa-gate-1",
    upstream_url="https://cms-cd.apmterminals.com/apm/api/v1/gatecameras/gate-camera?id=13b8ab33-…",
    fallback_filename="apm-apapa-gate-1.jpg",
    fallback_mime="image/jpeg",
    ttl_seconds=30,
    attribution="APM Terminals (Apapa) - snapshot public",
    label_disclaimer="Reference visuelle - demo Abidjan",
)
```

#### Auto-sélection

```python
recommended_webcam_for_vessel(mmsi="627012345")        # → "apm-apapa-gate-1"
recommended_webcam_for_vessel(cargo_id="cargo-abidjan-supply-001")  # → "apm-apapa-gate-1"
webcam_cycle_for_vessel(mmsi="627012345")
# → ["apm-apapa-gate-1", "apm-apapa-gate-2", "paa-aerial-vue", "paa-terminal-petrolier", "paa-terminal-fruitier"]
```

Le module centralise les mappings MMSI/cargo → `source_id` pour que le
backend (`maritime.py`, `executor.py`) et le frontend partagent la même
politique, sans duplication de constants.

### 8.3 Endpoint `backend/app/api/v1/endpoints/webcam_proxy.py`

Préfixe : `/api/v1/mission-room/webcams`.

| Route | Description |
|-------|-------------|
| `GET /proxy?source_id=apm-apapa-gate-1&force_refresh=false` | Renvoie le JPG/PNG ; headers `X-Webcam-Source` (`upstream` ou `fallback`), `X-Webcam-Cache` (`hit`/`miss`), `X-Webcam-Source-Id`, `X-Webcam-Attribution`, `X-Webcam-Disclaimer`, `X-Webcam-Upstream-Status`. `Cache-Control: private, max-age=<TTL>`. |
| `GET /sources` | Inventaire JSON des sources whitelistées (UI debug + frontend cycle). |

#### Audit log

Chaque appel émet exactement un événement :

- `webcam.proxy.served` → upstream OK
- `webcam.proxy.fallback` → degraded (fallback statique)
- `webcam.proxy.error` → `source_id` inconnu / interdit
- `webcam.proxy.listed` → appel de `/sources`

Les détails (`source_id`, `cache`, `source`, `upstream_status`, `mime`,
`bytes`) sont scopés au workspace + actor (`user.email`).

#### Sécurité

* **Whitelist** : seul `_WHITELIST` est servi. Un `source_id` inconnu
  retourne `404 webcam_source_not_whitelisted`.
* **Pas de redirection ouverte**. Le JPG est ré-émis depuis le backend,
  pas un `301` vers l'upstream.
* **Pas de scraping abusif** : `min_fetch_interval_seconds=10` côté cache,
  TTL upstream natif 5 min côté APM.

### 8.4 Exemple curl (proxy snapshot)

```bash
$ curl -sS -I "$API/api/v1/mission-room/webcams/proxy?source_id=apm-apapa-gate-1" -H "Authorization: Bearer $TOKEN"
HTTP/2 200
content-type: image/jpeg
cache-control: private, max-age=30
x-webcam-source-id: apm-apapa-gate-1
x-webcam-source: upstream
x-webcam-cache: miss
x-webcam-upstream-status: 200
x-webcam-attribution: APM Terminals (Apapa) - snapshot public
x-webcam-disclaimer: Reference visuelle - demo Abidjan
content-disposition: inline; filename="apm-apapa-gate-1.jpg"
content-length: 89707
```

Validation locale (Python REPL, hors auth, mêmes appels en process) :

```text
>>> from app.services.webcam_proxy import fetch_snapshot, list_whitelisted_source_ids
>>> list_whitelisted_source_ids()
['apm-apapa-gate-1', 'apm-apapa-gate-2', 'paa-aerial-vue',
 'paa-terminal-fruitier', 'paa-terminal-petrolier']
>>> r = fetch_snapshot('apm-apapa-gate-1')
>>> r.source, r.cache, r.mime_type, len(r.content), r.upstream_status
('upstream', 'miss', 'image/jpeg', 89707, 200)
```

### 8.5 Auto-sélection cargo → webcam dans le maritime API

`GET /api/v1/mission-room/maritime/vessels/627012345` retourne maintenant :

```json
{
  "vessel": {
    "mmsi": "627012345",
    "imo": "9876543",
    "name": "MV ATLANTIC TRADER",
    "linked_cargo_id": "cargo-abidjan-supply-001",
    "recommended_webcam_source_id": "apm-apapa-gate-1",
    "…": "…"
  },
  "recommended_webcam": {
    "source_id": "apm-apapa-gate-1",
    "proxy_url": "/api/v1/mission-room/webcams/proxy?source_id=apm-apapa-gate-1",
    "label": "APM Terminals · Apapa Gate Camera 1",
    "attribution": "APM Terminals (Apapa) - snapshot public",
    "label_disclaimer": "Reference visuelle - demo Abidjan",
    "cycle": [
      {"source_id": "apm-apapa-gate-1", "proxy_url": "/api/v1/mission-room/webcams/proxy?source_id=apm-apapa-gate-1"},
      {"source_id": "apm-apapa-gate-2", "proxy_url": "…"},
      {"source_id": "paa-aerial-vue", "proxy_url": "…"},
      {"source_id": "paa-terminal-petrolier", "proxy_url": "…"},
      {"source_id": "paa-terminal-fruitier", "proxy_url": "…"}
    ]
  },
  "linked_cargo": {
    "id": "cargo-abidjan-supply-001",
    "project_ref": "proj-drone-centre-napie",
    "narrative_role": "S1 — cargo bloque a Vridi (composants drones Aerostar Dynamics pour le Centre Napie)"
  },
  "snapshot": {"provider": "baseline", "source": "baseline"},
  "policy": "advisory_only"
}
```

Les navires sans rôle narratif (Maersk, Stolt, CMA CGM…) **n'ont pas** de
`recommended_webcam_source_id` — seul `MV Atlantic Trader` déclenche la
vignette automatique côté UI.

### 8.6 Effet `assistant-show-webcam` (executor.py)

Deux handlers émettent désormais l'effet :

* `aya.show_vessel_evidence` (cargo drill direct) — déjà responsable de la
  navigation maritime + map command. On y ajoute le `assistant-show-webcam`
  pointant sur la webcam APM Apapa gate #1 avec le cycle complet.
* `aya.explain_why` (drill causal) **quand `next_focus == "cargo-abidjan-supply-001"`**.
  Ce point d'entrée est emprunté quand le VP demande « Pourquoi cette
  cargaison est-elle bloquée ? » et que le graph cause-conséquence pose le
  cargo comme nœud courant.

Forme du chunk emis (spread d'`_action_effect`) :

```json
{
  "chunk_type": "action_effect",
  "effect": "assistant-show-webcam",
  "source_id": "apm-apapa-gate-1",
  "vessel_mmsi": "627012345",
  "vessel_name": "MV Atlantic Trader",
  "cargo_id": "cargo-abidjan-supply-001",
  "label": "APM Terminals · Apapa Gate Camera 1",
  "attribution": "APM Terminals (Apapa) - snapshot public",
  "label_disclaimer": "Reference visuelle - demo Abidjan",
  "proxy_url": "/api/v1/mission-room/webcams/proxy?source_id=apm-apapa-gate-1",
  "cycle": [ … ]
}
```

### 8.7 Workflow narratif S1 (chat → effet → UI)

```
VP: « Pourquoi cette cargaison est-elle bloquée ? »
  → aya.explain_why (target = cargo-abidjan-supply-001)
  → emit chunk action_effect{ assistant-navigate → /strategie }
  → emit chunk action_effect{ assistant-show-webcam → apm-apapa-gate-1 }
  → emit chunk action_effect{ assistant-propose → PV douanes }
  ↓ (browser)
ChatPanel: forward chunk to AssistantEffectsService.handleActionEffect()
  → dispatchShowWebcam → window event 'agentium:assistant-show-webcam'
  ↓
VpMapPreview: showWebcamListener picks up the event
  → set activeWebcam = { source_id, cycle, label, … }
  → render 240×135 vignette next to the AIS marker (MMSI 627012345)
  → clic vignette → drawer plein écran avec image proxy
  → bascule de source via les pills (cycle APM #1 / #2 / PAA aérienne / …)
```

### 8.8 Plan de fallback si APM bloque tout

* **TTL négatif côté proxy** : 60 s — empêche le hammering quand l'API APM
  renvoie 403/5xx ou un payload non-image (page CAPTCHA Akamai).
* **Fallback statique** : si l'upstream est inaccessible, on sert le JPG
  embarqué dans `backend/app/resources/webcams/apm-apapa-gate-1.jpg`. Les
  tests le couvrent (`test_upstream_failure_falls_back_to_static_asset`).
* **Bascule UI** : la vignette propose des pills `paa-aerial-vue`,
  `paa-terminal-petrolier`, `paa-terminal-fruitier` (toutes statiques mais
  bien d'Abidjan). VesselFinder iframe reste embarqué côté
  `visual_intelligence` pour un overlay AIS complémentaire si la couche
  vignette est désactivée.
* **Déclencheurs** :
  - L'opérateur (cabinet) peut cliquer manuellement n'importe quelle pill.
  - L'effet `assistant-show-webcam` peut être ré-émis avec un `source_id`
    différent par l'executor si on veut forcer un autre angle pendant la
    démo (ex. `paa-aerial-vue` pour ouvrir l'arc cargo).

### 8.9 Fichiers livrés (Patch C)

| Path | Δ | Rôle |
|------|---|------|
| `backend/app/services/webcam_proxy.py` | **nouveau** ≈300 lignes | Whitelist, cache, fallback statique, helpers auto-select |
| `backend/app/api/v1/endpoints/webcam_proxy.py` | **nouveau** ≈150 lignes | Routes `/mission-room/webcams/proxy` + `/sources` |
| `backend/app/api/v1/router.py` | +2 lignes | Import + include `webcam_proxy` |
| `backend/app/api/v1/endpoints/maritime.py` | +50 lignes | `recommended_webcam_source_id` dans `vessels` + `vessels/{mmsi}` + audit |
| `backend/app/services/visual_intelligence.py` | +200 lignes | Remplace APM marketing par 2 gate-cams via proxy ; +3 PAA ; +VesselFinder |
| `backend/app/services/actions/executor.py` | +90 lignes | `show_vessel_evidence` + `explain_why` (cargo) émettent `assistant-show-webcam` |
| `backend/app/resources/webcams/*.jpg / *.png` | **nouveau** 5 fichiers | Fallback offline (téléchargés une fois pour la démo) |
| `backend/app/tests/api/test_webcam_proxy.py` | **nouveau** 8 tests | Whitelist, cache hit/miss, force_refresh, fallback, inventory, auto-select |
| `backend/app/tests/api/test_maritime_api.py` | +30 lignes | 2 tests `recommended_webcam` sur `/vessels` et `/vessels/{mmsi}` |
| `frontend-ng/src/app/core/assistant-effects.service.ts` | +60 lignes | `AssistantShowWebcamEffect` + `dispatchShowWebcam` + `normalizeShowWebcam` |
| `frontend-ng/src/app/features/chat/chat-panel.component.ts` | +1 ligne logique | Forward chunk complet (avec `effect` kind string) à `handleActionEffect` |
| `frontend-ng/src/app/features/mission-room/vp-map-preview.component.ts` | +200 lignes | Vignette 240×135 ; listener `assistant-show-webcam` ; drawer plein écran ; pills cycle ; disclaimer obligatoire |

### 8.10 Tests

```bash
$ poetry run pytest app/tests/api/test_webcam_proxy.py \
                    app/tests/api/test_maritime_api.py \
                    app/tests/api/test_visual_intelligence_api.py -q
8 passed (webcam_proxy)
16 passed (maritime_api, dont +2 auto-select)
4 passed (visual_intelligence_api)
```

Régression élargie (actions + mission-room) : **39 passed** (sans regression).

---

## 9. Backlog (post-démo lundi)

- [ ] Worker AISStream WebSocket → store partagé → live `MV Atlantic Trader` + tout le trafic
      bbox Abidjan. Premier providing live, gratuit, avec attribution.
- [ ] Étendre la baseline avec ~10 navires San Pedro pour le drill cacao S2.
- [ ] Ajouter un adapter `portwatch_imf` pour les métriques trafic port (TEU/j) cohérent avec
      la fiche KPI 8 de `sentinel-ci-osint-sources-from-osiris.md`.
- [ ] Wirer le drawer `aya.show_vessel_evidence` pour appeler `/maritime/vessels/{mmsi}`
      au lieu de la donnée statique seedée dans `executor.py`.
- [ ] Refondre la couche `maritime_vessels` côté `workspace-map.component.ts` (rendu MapLibre
      réel) plutôt qu'overlay SVG schématique dans `vp-map-preview`. L'overlay SVG actuel reste
      utile pour le preview du cockpit.
- [ ] Refondre `visual_intelligence` pour distinguer `source.kind` au niveau modèle (et plus
      seulement dans `meta_data["kind"]`).
