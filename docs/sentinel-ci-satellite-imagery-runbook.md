# SENTINEL-CI — Runbook imagerie satellite S3

> **Date** : 25 mai 2026
> **Surface** : `/hypervisor/mission-room/securite/monitor`
> **Statut** : Option A baseline démo-safe. Option C live Copernicus non activée.

## Objectif

Le Security Monitor S3 affiche deux scènes satellite cohérentes avec la trame VP :

| Scène | Axe | Message autorisé |
|-------|-----|------------------|
| Couloir frontière Nord — Bouna / Kong | Intérieur | Scène matinale indicative, corrélation avec le démenti officiel, aucune anomalie confirmée. |
| Contexte Sahel — Liptako-Gourma | Extérieur | Lecture OSINT publique contextuelle, corrélation ADS-B advisory only. |

La scène ne doit jamais être présentée comme preuve d'incursion, de troupes visibles, de convoi ou de mouvement hostile confirmé.

## Implémentation Option A

- Fixture : `backend/app/resources/security/satellite-scenes-baseline.json`
- Images : `backend/app/resources/security/satellite/*.webp`
- Service : `backend/app/services/intelligence/satellite_imagery.py`
- Endpoints :
  - `GET /api/v1/mission-room/satellite/scenes`
  - `GET /api/v1/mission-room/satellite/proxy?scene_id=...&variant=thumbnail|asset`
- Surface UI : rail `#satellite-imagery-rail` dans Security Monitor.
- Carte : basemap `satellite` + couche `satellite-footprint`.

Les images sont chargées côté frontend via proxy blob authentifié, pas en URL directe.

## Source des images baseline

Les assets baseline sont des captures Sentinel-2 cloudless publiques, recadrées sur les bboxes S3, exportées en WebP sans annotation opérationnelle.

Attribution affichée : `Contains modified Copernicus Sentinel data via Sentinel-2 cloudless (EOX)`.

## Guard rails

1. `workspace.mode == "demo"` force toujours `CACHE BASELINE`.
2. Aucune détection automatique, aucun hotspot, aucune surbrillance d'anomalie.
3. Le disclaimer reste visible dans le rail et dans le drawer.
4. Les scènes sont advisory / indicative / non classifiées.
5. Le live Copernicus n'est pas appelé en prod démo.

## Option C live Copernicus

Gate de confirmation non validée au 25 mai 2026. Décision d'implémentation actuelle :

- Live jamais activé sur le workspace de démo VP.
- QA et screenshots gate uniquement sur baseline figé.
- Pas de détection automatique ni de claim visuelle.
- Fallback prévu vers baseline si une future API live échoue.
- Usage live réservé à un workspace staging interne post-démo.

Question restante pour une scène live ambiguë : masquer, afficher avec bandeau d'interprétation humaine, ou abort vers baseline. Tant que ce choix n'est pas validé, Option A uniquement.

## Vérifications

```bash
cd /Users/thib/Developer/PAPAI/omnirag
python3 -m json.tool backend/app/resources/security/satellite-scenes-baseline.json >/dev/null
cd backend && poetry run pytest app/tests/api/test_mission_room_api.py::test_mission_room_security_monitor_payload app/tests/api/test_mission_room_api.py::test_mission_room_satellite_scenes_and_proxy -q
cd ../frontend-ng && CI=1 npm run build:prod
```

QA visuelle attendue :

- `V21.5 Imagerie satellite baseline advisory` PASS.
- Deux thumbnails visibles.
- Clic thumbnail ouvre le drawer scène satellite.
- Badge `CACHE BASELINE` visible.
- Disclaimer `aucune interprétation automatique` visible sans scroll.
