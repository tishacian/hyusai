"""Workspace visual intelligence for provider-neutral situation monitoring."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import uuid4

import httpx
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.knowledge_collection import KnowledgeCollection
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_visual import (
    WorkspaceVisualCapture,
    WorkspaceVisualObservation,
    WorkspaceVisualSource,
)
from app.services.audit_logger import emit_audit_event
from app.services.iam.app_entitlements import (
    WorkspaceEntitlementMutationConflictError,
    lock_workspace_for_app_entitlement_mutation,
)
from app.services.object_store import get_object_store
from app.services.workspace_jobs import create_workspace_job, serialize_job, transition_job

VISUAL_COLLECTION_SLUG = "sentinel-ci-visual-intelligence"
LEGACY_DEFAULT_SOURCE_NAMES = (
    "Abidjan - couche webcam publique",
    "Abidjan Plateau - veille visuelle",
)
ABIDJAN_NET_VISUAL_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "name": "Abidjan.net - Pont General-de-Gaulle",
        "description": "Flux live public Abidjan.net/Nest pour veille trafic et meteo urbaine.",
        "source_url": "https://media-files.abidjan.net/camera/__medium/PontGeneral-de-Gaulle.jpg",
        "source_page": "https://www.abidjan.net/trafic-routier/23-pont-general-de-gaulle",
        "embed_url": "https://video.nest.com/embedded/live/F9fa32yXTo?autoplay=1",
        "nest_token": "F9fa32yXTo",
        "region": "Abidjan / Pont General-de-Gaulle",
        "map_location": {
            "label": "Pont General-de-Gaulle · Abidjan",
            "longitude": -4.016,
            "latitude": 5.315,
            "zone_id": "zone-sud",
            "zoom": 11.1,
        },
        "priority": 1,
        "default_vigilance_score": 42,
    },
    {
        "name": "Abidjan.net - Boulevard Lagunaire Plateau",
        "description": "Flux live public Abidjan.net/Nest sur le Plateau et la lagune.",
        "source_url": "https://media-files.abidjan.net/camera/__medium/Boulevard_Lagunaire.png",
        "source_page": "https://www.abidjan.net/trafic-routier/1-boulevard-lagunaire-plateau",
        "embed_url": "https://video.nest.com/embedded/live/v4xT9u9Elg?autoplay=1",
        "nest_token": "v4xT9u9Elg",
        "region": "Abidjan / Plateau",
        "map_location": {
            "label": "Boulevard Lagunaire · Plateau",
            "longitude": -4.020,
            "latitude": 5.321,
            "zone_id": "zone-sud",
            "zoom": 11.2,
        },
        "priority": 2,
        "default_vigilance_score": 40,
    },
    {
        "name": "Abidjan.net - Echangeur de Marcory",
        "description": "Flux live public Abidjan.net/Nest pour veille de mobilite a Marcory.",
        "source_url": "https://media-files.abidjan.net/camera/__medium/CamEchangeurMarcoryTOA.jpg",
        "source_page": "https://www.abidjan.net/trafic-routier/27-echangeur-de-marcory-esprit-lounge-bar-le-toa",
        "embed_url": "https://video.nest.com/embedded/live/9KPnrmunvf?autoplay=1",
        "nest_token": "9KPnrmunvf",
        "region": "Abidjan / Marcory",
        "map_location": {
            "label": "Echangeur de Marcory · Abidjan",
            "longitude": -3.993,
            "latitude": 5.300,
            "zone_id": "zone-sud",
            "zoom": 11.2,
        },
        "priority": 3,
        "default_vigilance_score": 44,
    },
    {
        "name": "Abidjan.net - Grand carrefour de Treichville",
        "description": "Flux live public Abidjan.net/Nest pour veille du carrefour Treichville.",
        "source_url": "https://media-files.abidjan.net/camera/__medium/Gd_carrefour_tech_cacomif.jpg",
        "source_page": "https://www.abidjan.net/trafic-routier/25-grand-carrefour-de-treichville-cacomiaf",
        "embed_url": "https://video.nest.com/embedded/live/7kMbTt?autoplay=1",
        "nest_token": "7kMbTt",
        "region": "Abidjan / Treichville",
        "map_location": {
            "label": "Grand carrefour Treichville · Abidjan",
            "longitude": -4.002,
            "latitude": 5.295,
            "zone_id": "zone-sud",
            "zoom": 11.0,
        },
        "priority": 4,
        "default_vigilance_score": 45,
    },
    {
        "name": "Abidjan.net - Grand carrefour de Koumassi",
        "description": "Flux live public Abidjan.net/Nest pour veille du carrefour Koumassi.",
        "source_url": "https://media-files.abidjan.net/camera/__medium/Gd_carrefour_Koumassi.jpg",
        "source_page": "https://www.abidjan.net/trafic-routier/22-grand-carrefour-de-koumassi",
        "embed_url": "https://video.nest.com/embedded/live/kRwGtt?autoplay=1",
        "nest_token": "kRwGtt",
        "region": "Abidjan / Koumassi",
        "map_location": {
            "label": "Grand carrefour Koumassi · Abidjan",
            "longitude": -3.948,
            "latitude": 5.296,
            "zone_id": "zone-sud",
            "zoom": 11.0,
        },
        "priority": 5,
        "default_vigilance_score": 43,
    },
    {
        "name": "Abidjan.net - Carrefour Sococe 2 Plateaux",
        "description": "Flux live public Abidjan.net/Nest pour veille du carrefour Sococe Latrille.",
        "source_url": "https://media-files.abidjan.net/camera/__medium/Carrefour_Sococe_2Plx.jpg",
        "source_page": "https://www.abidjan.net/trafic-routier/21-carrefour-sococe-2-plateaux-latrille",
        "embed_url": "https://video.nest.com/embedded/live/aI5d42?autoplay=1",
        "nest_token": "aI5d42",
        "region": "Abidjan / Cocody",
        "map_location": {
            "label": "Carrefour Sococe 2 Plateaux · Cocody",
            "longitude": -3.991,
            "latitude": 5.378,
            "zone_id": "zone-sud",
            "zoom": 11.0,
        },
        "priority": 6,
        "default_vigilance_score": 39,
    },
    {
        "name": "Abidjan.net - Yopougon Sable",
        "description": "Flux live public Abidjan.net/Nest pour veille du carrefour Yopougon Sable.",
        "source_url": "https://media-files.abidjan.net/camera/__medium/yopougon-sable.jpg",
        "source_page": "https://www.abidjan.net/trafic-routier/28-yopougon-sable-lartisan",
        "embed_url": "https://video.nest.com/embedded/live/qESphtavfu?autoplay=1",
        "nest_token": "qESphtavfu",
        "region": "Abidjan / Yopougon",
        "map_location": {
            "label": "Yopougon Sable · Abidjan",
            "longitude": -4.083,
            "latitude": 5.334,
            "zone_id": "zone-sud",
            "zoom": 11.0,
        },
        "priority": 7,
        "default_vigilance_score": 46,
    },
    {
        "name": "Abidjan.net - Plage d'Assinie",
        "description": "Flux live public Abidjan.net/Nest pour veille meteo cotiere a Assinie.",
        "source_url": "https://media-files.abidjan.net/camera/__medium/PlageAssinieKame.jpg",
        "source_page": "https://www.abidjan.net/trafic-routier/26-plage-dassinie-kame-surf-camp-school",
        "embed_url": "https://video.nest.com/embedded/live/3SWh5rcBTO?autoplay=1",
        "nest_token": "3SWh5rcBTO",
        "region": "Cote d'Ivoire / Assinie",
        "map_location": {
            "label": "Plage d'Assinie · littoral",
            "longitude": -3.289,
            "latitude": 5.132,
            "zone_id": "zone-est",
            "zoom": 10.3,
        },
        "priority": 8,
        "default_vigilance_score": 34,
    },
    {
        # APM Terminals Apapa gate-cameras (Lagos) — utilisée comme reference
        # visuelle demo pour le port d'Abidjan (page corporate publique de gate
        # cameras). La page principale https://www.apmterminals.com/en/apapa/
        # practical-information/gate-cameras impose ``frame-ancestors 'self'``
        # via CSP : impossible de l'iframer directement. En revanche les deux
        # snapshots JPG sont publics (TTL 5 min cote CDN) — on les sert via le
        # endpoint proxy `/api/v1/mission-room/webcams/proxy?source_id=apm-apapa-gate-1`.
        "name": "APM Terminals · Apapa Gate Camera 1 (demo Abidjan)",
        "description": (
            "Snapshot CCTV public APM Terminals Apapa (Lagos), gate-camera #1, "
            "utilise comme reference visuelle demo pour le port d'Abidjan. "
            "Page CSP-bloquee en iframe ; le snapshot JPG est servi via le "
            "proxy SENTINEL-CI (cache 30 s, fallback statique embarque)."
        ),
        "source_url": "/api/v1/mission-room/webcams/proxy?source_id=apm-apapa-gate-1",
        "source_page": "https://www.apmterminals.com/en/apapa/practical-information/gate-cameras",
        "embed_url": "/api/v1/mission-room/webcams/proxy?source_id=apm-apapa-gate-1",
        "region": "Demo : Apapa (Lagos)",
        "map_location": {
            "label": "Port d'Abidjan - Vridi (vue demo Apapa gate #1)",
            "longitude": -4.018,
            "latitude": 5.244,
            "zone_id": "zone-sud",
            "zoom": 12.0,
        },
        "priority": 9,
        "default_vigilance_score": 41,
        "label_disclaimer": "Reference visuelle - demo Abidjan (source : APM Terminals Apapa, Lagos)",
        "stream_kind": "port_webcam_proxy",
        "best_use": "port_traffic_observation",
        "evidence_grade": "demo_reference",
        "attribution": "APM Terminals (Apapa) - snapshot public",
        "adapter": "http_image",
        "metadata_overrides": {
            "provider": "apm_terminals_apapa",
            "video_provider": "apm_terminals_cctv_api",
            "preferred_render": "snapshot",
            "embed_status": "csp_blocked_use_proxy",
            "fallback_reason": "page_cps_frame_ancestors_self",
            "layer_kind": "port_webcam",
            "stream_kind": "port_webcam_proxy",
            "refresh_seconds": 30,
            "resolution_tier": "public_cctv_jpg",
            "resolution_label": "Snapshot CCTV public 800x600",
            "evidence_grade": "demo_reference",
            "best_use": "Vignette port pour drill cargo (MV Atlantic Trader / Vridi).",
            "analysis_mode": "snapshot_to_vlm_ready",
            "attribution": "APM Terminals Apapa CCTV - reference visuelle demo Abidjan",
            "timelapse_policy": "no_recording_30s_cache",
            "kind": "port_webcam",
            "proxy_source_id": "apm-apapa-gate-1",
            "auto_select_for_mmsis": ["627012345"],
            "auto_select_for_cargo_ids": ["cargo-abidjan-supply-001"],
        },
    },
    {
        # APM Terminals Apapa gate-cameras (Lagos) — deuxième angle gate
        # camera. Source HD 800x450 publique, servie via le meme proxy.
        "name": "APM Terminals · Apapa Gate Camera 2 (demo Abidjan)",
        "description": (
            "Snapshot CCTV public APM Terminals Apapa (Lagos), gate-camera #2, "
            "vue complementaire de la gate #1. Servi via le proxy SENTINEL-CI "
            "(cache 30 s, fallback statique embarque)."
        ),
        "source_url": "/api/v1/mission-room/webcams/proxy?source_id=apm-apapa-gate-2",
        "source_page": "https://www.apmterminals.com/en/apapa/practical-information/gate-cameras",
        "embed_url": "/api/v1/mission-room/webcams/proxy?source_id=apm-apapa-gate-2",
        "region": "Demo : Apapa (Lagos) · gate cam #2",
        "map_location": {
            "label": "Port d'Abidjan - Vridi (vue demo Apapa gate #2)",
            "longitude": -4.020,
            "latitude": 5.245,
            "zone_id": "zone-sud",
            "zoom": 12.0,
        },
        "priority": 13,
        "default_vigilance_score": 39,
        "label_disclaimer": "Reference visuelle - demo Abidjan (source : APM Terminals Apapa, Lagos)",
        "stream_kind": "port_webcam_proxy",
        "best_use": "port_traffic_observation",
        "evidence_grade": "demo_reference",
        "attribution": "APM Terminals (Apapa) - snapshot public",
        "adapter": "http_image",
        "metadata_overrides": {
            "provider": "apm_terminals_apapa",
            "video_provider": "apm_terminals_cctv_api",
            "preferred_render": "snapshot",
            "embed_status": "csp_blocked_use_proxy",
            "fallback_reason": "page_cps_frame_ancestors_self",
            "layer_kind": "port_webcam",
            "stream_kind": "port_webcam_proxy",
            "refresh_seconds": 30,
            "resolution_tier": "public_cctv_jpg",
            "resolution_label": "Snapshot CCTV public 800x450",
            "evidence_grade": "demo_reference",
            "best_use": "Angle complementaire pour la vignette port (drill cargo).",
            "analysis_mode": "snapshot_to_vlm_ready",
            "attribution": "APM Terminals Apapa CCTV - reference visuelle demo Abidjan",
            "timelapse_policy": "no_recording_30s_cache",
            "kind": "port_webcam",
            "proxy_source_id": "apm-apapa-gate-2",
        },
    },
    {
        # Port Autonome d'Abidjan (PAA) — phototheque officielle. Aucune
        # webcam live publique trouvee sur portabidjan.ci, mais 3 photos
        # haute resolution sont seedees comme reference visuelle stable.
        "name": "PAA · Vue aerienne port d'Abidjan (galerie officielle)",
        "description": (
            "Vue aerienne du port autonome d'Abidjan publiee par le PAA. "
            "Reference visuelle stable pour le drill cargo / Vridi en l'absence "
            "de webcam live publique cote PAA. Servie via proxy SENTINEL-CI "
            "(cache 5 min, fallback embarque)."
        ),
        "source_url": "/api/v1/mission-room/webcams/proxy?source_id=paa-aerial-vue",
        "source_page": "https://portabidjan.ci/fr/visite-virtuelle/phototheque",
        "embed_url": "/api/v1/mission-room/webcams/proxy?source_id=paa-aerial-vue",
        "region": "Abidjan / Vridi - vue aerienne PAA",
        "map_location": {
            "label": "Port d'Abidjan - vue aerienne (PAA)",
            "longitude": -4.010,
            "latitude": 5.246,
            "zone_id": "zone-sud",
            "zoom": 11.5,
        },
        "priority": 14,
        "default_vigilance_score": 33,
        "label_disclaimer": "Phototheque officielle PAA - reference visuelle (pas de live)",
        "stream_kind": "port_reference_photo",
        "best_use": "port_overview",
        "evidence_grade": "context_reference",
        "attribution": "Port Autonome d'Abidjan (PAA) - phototheque officielle",
        "adapter": "http_image",
        "metadata_overrides": {
            "provider": "port_autonome_abidjan",
            "video_provider": "paa_static_gallery",
            "preferred_render": "snapshot",
            "embed_status": "stable_static",
            "fallback_reason": None,
            "layer_kind": "port_webcam",
            "stream_kind": "port_reference_photo",
            "refresh_seconds": 300,
            "resolution_tier": "public_hd_static",
            "resolution_label": "Photo HD officielle 924x457",
            "evidence_grade": "context_reference",
            "best_use": "Anchor visuel d'ouverture du drill port d'Abidjan.",
            "analysis_mode": "static_reference",
            "attribution": "Port Autonome d'Abidjan - phototheque",
            "timelapse_policy": "no_live_static_reference",
            "kind": "port_webcam",
            "proxy_source_id": "paa-aerial-vue",
        },
    },
    {
        # PAA - Terminal petrolier
        "name": "PAA · Terminal petrolier (galerie officielle)",
        "description": (
            "Photo officielle du terminal petrolier du port d'Abidjan, "
            "phototheque PAA. Reference visuelle complementaire au snapshot "
            "principal pour le drill maritime."
        ),
        "source_url": "/api/v1/mission-room/webcams/proxy?source_id=paa-terminal-petrolier",
        "source_page": "https://portabidjan.ci/fr/visite-virtuelle/phototheque",
        "embed_url": "/api/v1/mission-room/webcams/proxy?source_id=paa-terminal-petrolier",
        "region": "Abidjan / Vridi - terminal petrolier",
        "map_location": {
            "label": "Terminal petrolier - Port d'Abidjan",
            "longitude": -4.022,
            "latitude": 5.241,
            "zone_id": "zone-sud",
            "zoom": 13.0,
        },
        "priority": 15,
        "default_vigilance_score": 31,
        "label_disclaimer": "Phototheque officielle PAA - reference visuelle (pas de live)",
        "stream_kind": "port_reference_photo",
        "best_use": "port_terminal_reference",
        "evidence_grade": "context_reference",
        "attribution": "Port Autonome d'Abidjan (PAA) - phototheque officielle",
        "adapter": "http_image",
        "metadata_overrides": {
            "provider": "port_autonome_abidjan",
            "video_provider": "paa_static_gallery",
            "preferred_render": "snapshot",
            "embed_status": "stable_static",
            "fallback_reason": None,
            "layer_kind": "port_webcam",
            "stream_kind": "port_reference_photo",
            "refresh_seconds": 300,
            "resolution_tier": "public_hd_static",
            "resolution_label": "Photo HD officielle 924x457",
            "evidence_grade": "context_reference",
            "best_use": "Reference terminal petrolier (cargaisons sensibles).",
            "analysis_mode": "static_reference",
            "attribution": "Port Autonome d'Abidjan - phototheque",
            "timelapse_policy": "no_live_static_reference",
            "kind": "port_webcam",
            "proxy_source_id": "paa-terminal-petrolier",
        },
    },
    {
        # VesselFinder iframe — embed public sans clé, page /aismap ne pose
        # pas de X-Frame-Options. Centre sur Abidjan / Vridi.
        "name": "VesselFinder · Port d'Abidjan (overlay AIS embed)",
        "description": (
            "Iframe public VesselFinder centre sur Abidjan / Vridi. La page "
            "/aismap accepte l'embed (pas de X-Frame-Options), attribution dans "
            "le widget. Complement de l'overlay AIS MarineTraffic existant."
        ),
        "source_url": "https://www.vesselfinder.com/aismap?zoom=11&lat=5.25&lon=-3.99&names=true&track=true",
        "source_page": "https://www.vesselfinder.com/?bbox=-4.10,5.20,-3.90,5.30",
        "embed_url": "https://www.vesselfinder.com/aismap?zoom=11&lat=5.25&lon=-3.99&names=true&track=true",
        "region": "Abidjan / Vridi · overlay AIS VesselFinder",
        "map_location": {
            "label": "Port d'Abidjan - overlay VesselFinder",
            "longitude": -3.99,
            "latitude": 5.25,
            "zone_id": "zone-sud",
            "zoom": 11.0,
        },
        "priority": 16,
        "default_vigilance_score": 36,
        "label_disclaimer": "Source publique VesselFinder - attribution dans l'iframe",
        "stream_kind": "ais_iframe_embed",
        "best_use": "port_ais_overlay",
        "evidence_grade": "context_only",
        "attribution": "VesselFinder.com - embed public",
        "metadata_overrides": {
            "provider": "vesselfinder",
            "video_provider": "vesselfinder_public_iframe",
            "preferred_render": "iframe",
            "embed_status": "stable",
            "fallback_reason": None,
            "layer_kind": "port_webcam",
            "stream_kind": "ais_iframe_embed",
            "refresh_seconds": 30,
            "resolution_tier": "public_widget",
            "resolution_label": "Widget AIS public",
            "evidence_grade": "context_only",
            "analysis_constraints": [
                "iframe AIS, pas une preuve documentaire",
                "ne pas redistribuer les snapshots",
                "respecter les ToS VesselFinder",
            ],
            "best_use": "Overlay AIS Abidjan / Vridi, complementaire de MarineTraffic.",
            "analysis_mode": "iframe_only",
            "attribution": "VesselFinder.com - embed public",
            "timelapse_policy": "iframe_live_only",
            "demo_fallback": True,
            "kind": "port_webcam",
        },
    },
    {
        # MarineTraffic public iframe widget — gratuit, sans cle, attribution
        # affichee dans l'iframe. Sert d'overlay AIS visuel sur le port d'Abidjan.
        "name": "MarineTraffic - Port d'Abidjan (overlay AIS)",
        "description": "Iframe public MarineTraffic centre sur Abidjan / Vridi pour visualiser les navires AIS en temps reel.",
        "source_url": (
            "https://www.marinetraffic.com/en/ais/embed/"
            "zoom:11/centery:5.247/centerx:-3.998/maptype:0/shownames:false/"
            "mmsi:0/shipid:0/fleet:/fleet_id:/vtypes:/showmenu:/remember:false"
        ),
        "source_page": "https://www.marinetraffic.com/en/ais/home/centerx:-3.998/centery:5.247/zoom:11",
        "embed_url": (
            "https://www.marinetraffic.com/en/ais/embed/"
            "zoom:11/centery:5.247/centerx:-3.998/maptype:0/shownames:false/"
            "mmsi:0/shipid:0/fleet:/fleet_id:/vtypes:/showmenu:/remember:false"
        ),
        "region": "Abidjan / Vridi · couche AIS MarineTraffic",
        "map_location": {
            "label": "Port d'Abidjan - couche MarineTraffic",
            "longitude": -3.998,
            "latitude": 5.247,
            "zone_id": "zone-sud",
            "zoom": 11.0,
        },
        "priority": 10,
        "default_vigilance_score": 42,
        "label_disclaimer": "Source publique MarineTraffic - attribution dans l'iframe",
        "stream_kind": "ais_iframe_embed",
        "best_use": "port_ais_overlay",
        "evidence_grade": "context_only",
        "attribution": "MarineTraffic",
        "metadata_overrides": {
            "provider": "marinetraffic",
            "video_provider": "marinetraffic_public_iframe",
            "preferred_render": "iframe",
            "embed_status": "stable",
            "fallback_reason": None,
            "layer_kind": "port_webcam",
            "stream_kind": "ais_iframe_embed",
            "refresh_seconds": 30,
            "resolution_tier": "public_widget",
            "resolution_label": "Widget AIS public",
            "evidence_grade": "context_only",
            "analysis_constraints": [
                "iframe AIS, pas une preuve documentaire",
                "ne pas redistribuer les snapshots",
                "respecter les ToS MarineTraffic",
            ],
            "best_use": "Overlay AIS Abidjan / Vridi sur la carte demo, support visuel pour la chaine causale S1.",
            "analysis_mode": "iframe_only",
            "attribution": "MarineTraffic.com - public embed",
            "timelapse_policy": "iframe_live_only",
            "demo_fallback": True,
            "kind": "port_webcam",
        },
    },
    {
        # Windy snapshot — caméra méteo / cotière sur la côte ivoirienne.
        # Pattern repris de osiris (`src/app/api/cctv/turkey.ts` helper windy()).
        "name": "Windy - Cote d'Ivoire (meteo / cotier)",
        "description": "Iframe public Windy pour ancrer la lecture meteo / mer cotiere autour d'Abidjan.",
        "source_url": "https://www.windy.com/-Webcams/webcams/1701788000?5.247,-3.998,7",
        "source_page": "https://www.windy.com/-Webcams/webcams?5.247,-3.998,7",
        "embed_url": "https://embed.windy.com/embed2.html?lat=5.247&lon=-3.998&detailLat=5.247&detailLon=-3.998&width=640&height=360&zoom=7&level=surface&overlay=wind&product=ecmwf&menu=&message=true&marker=&calendar=now&pressure=&type=map&location=coordinates&detail=&metricWind=default&metricTemp=default&radarRange=-1",
        "region": "Cote d'Ivoire / cotier",
        "map_location": {
            "label": "Cote d'Ivoire - veille meteo cotiere",
            "longitude": -3.998,
            "latitude": 5.247,
            "zone_id": "zone-sud",
            "zoom": 9.0,
        },
        "priority": 11,
        "default_vigilance_score": 30,
        "label_disclaimer": "Source publique Windy.com",
        "stream_kind": "weather_iframe_embed",
        "best_use": "weather_overlay",
        "evidence_grade": "context_only",
        "attribution": "Windy.com",
        "metadata_overrides": {
            "provider": "windy",
            "video_provider": "windy_public_iframe",
            "preferred_render": "iframe",
            "embed_status": "stable",
            "fallback_reason": None,
            "layer_kind": "weather_webcam",
            "stream_kind": "weather_iframe_embed",
            "refresh_seconds": 600,
            "resolution_tier": "public_widget",
            "resolution_label": "Widget meteo public",
            "evidence_grade": "context_only",
            "analysis_constraints": [
                "iframe meteo, pas de capture image officielle",
                "respecter les ToS Windy.com",
            ],
            "best_use": "Lecture meteo cotiere Golfe de Guinee.",
            "analysis_mode": "iframe_only",
            "attribution": "Windy.com - public embed",
            "timelapse_policy": "iframe_live_only",
            "demo_fallback": True,
            "kind": "weather_webcam",
        },
    },
    {
        # Aeroport Felix Houphouet-Boigny / Port Bouet — caméra trafic indicative
        # (snapshot statique demo-safe fourni par le moteur, pas de live).
        "name": "Aeroport FHB - veille acces (demo-safe)",
        "description": "Vue indicative de l'acces Aeroport Felix Houphouet-Boigny / Port Bouet pour relier mobilite et logistique.",
        "source_url": "demo://aeroport-fhb-portbouet",
        "source_page": "https://www.aeria.ci/",
        "embed_url": "demo://aeroport-fhb-portbouet",
        "region": "Abidjan / Port Bouet",
        "map_location": {
            "label": "Aeroport FHB - Port Bouet",
            "longitude": -3.926,
            "latitude": 5.262,
            "zone_id": "zone-sud",
            "zoom": 12.0,
        },
        "priority": 12,
        "default_vigilance_score": 35,
        "label_disclaimer": "Snapshot demo-safe",
        "stream_kind": "demo_snapshot",
        "best_use": "mobility_overlay",
        "evidence_grade": "demo_reference",
        "attribution": "AERIA (operateur aeroportuaire) - reference contextuelle",
        "adapter": "demo_static",
        "metadata_overrides": {
            "provider": "sentinel_ci_demo",
            "video_provider": "sentinel_ci_demo",
            "preferred_render": "snapshot",
            "embed_status": "stable",
            "fallback_reason": None,
            "layer_kind": "traffic_webcam",
            "stream_kind": "demo_snapshot",
            "refresh_seconds": 900,
            "resolution_tier": "demo_static",
            "resolution_label": "Snapshot demo",
            "evidence_grade": "demo_reference",
            "best_use": "Anchor visuel pour le trafic Aeroport FHB / Port Bouet.",
            "analysis_mode": "demo_only",
            "attribution": "Snapshot demo SENTINEL-CI",
            "timelapse_policy": "no_recording",
            "demo_fallback": True,
            "kind": "traffic_webcam",
        },
    },
)
DEFAULT_SOURCE_NAME = ABIDJAN_NET_VISUAL_SOURCES[0]["name"]
DEFAULT_SOURCE_URL = ABIDJAN_NET_VISUAL_SOURCES[0]["source_url"]
DEFAULT_SOURCE_PAGE = ABIDJAN_NET_VISUAL_SOURCES[0]["source_page"]


def visual_intelligence_enabled(workspace: Workspace) -> bool:
    """Resolve the explicit workspace feature without tenant-name inference."""

    raw_settings = getattr(workspace, "settings", None)
    if not isinstance(raw_settings, Mapping):
        return False
    visual_settings = raw_settings.get("visual_intelligence")
    return bool(isinstance(visual_settings, Mapping) and visual_settings.get("enabled") is True)


def _visual_chat_profile_enabled(
    workspace: Workspace,
    assistant_profile: Optional[str],
) -> bool:
    """Require a declared profile backed by a canonical Mission Room pack."""

    # Imported lazily because ``mission_room`` imports this service while the
    # actions package exports the executor, which itself presents Mission Room
    # payloads. Keeping the contract lookup at call time avoids that cycle.
    from app.services.actions.contracts import ActionPack
    from app.services.actions.registry import effective_action_manifests

    if not assistant_profile:
        return False
    raw_settings = getattr(workspace, "settings", None)
    if not isinstance(raw_settings, Mapping):
        return False
    profiles = raw_settings.get("assistant_profiles")
    if not isinstance(profiles, list) or not any(
        isinstance(profile, Mapping) and profile.get("key") == assistant_profile
        for profile in profiles
    ):
        return False
    packs = {
        manifest.pack
        for manifest in effective_action_manifests(
            workspace,
            surface="chat",
            assistant_profile=assistant_profile,
        )
    }
    has_sentinel = bool(
        packs.intersection(
            {
                ActionPack.sentinel_ci_aya_v1.value,
                ActionPack.sentinel_ci_aya_security_v1.value,
            }
        )
    )
    has_octave = bool(
        packs.intersection(
            {
                ActionPack.octave_mission_room_v1.value,
                ActionPack.octave_security_v1.value,
            }
        )
    )
    return has_sentinel != has_octave


def ensure_visual_intelligence_seed(
    db: DBSession,
    workspace: Workspace,
    *,
    system_id: Optional[str] = None,
) -> dict[str, Any]:
    """Seed the visual connector and Knowledge target for demo workspaces."""
    collection = ensure_visual_collection(db, workspace)
    source_created = 0
    seeded_source_ids: list[str] = []
    default_policy = _default_visual_policy()
    legacy_source = (
        db.query(WorkspaceVisualSource)
        .filter(
            WorkspaceVisualSource.workspace_id == workspace.id,
            WorkspaceVisualSource.name.in_(LEGACY_DEFAULT_SOURCE_NAMES),
        )
        .first()
    )
    for index, spec in enumerate(ABIDJAN_NET_VISUAL_SOURCES):
        existing = (
            db.query(WorkspaceVisualSource)
            .filter(
                WorkspaceVisualSource.workspace_id == workspace.id,
                WorkspaceVisualSource.name == spec["name"],
            )
            .first()
        )
        if not existing and index == 0 and legacy_source:
            existing = legacy_source
        if not existing:
            existing = WorkspaceVisualSource(
                id=str(uuid4()),
                workspace_id=workspace.id,
                system_id=system_id,
                name=spec["name"],
                description=spec["description"],
                source_url=spec["source_url"],
                source_type="stream_embed",
                adapter=spec.get("adapter", "http_image"),
                region=spec["region"],
                status="active",
                enabled=True,
                capture_cadence_minutes=spec.get("capture_cadence_minutes", 60),
                policy=default_policy,
                meta_data=_webcam_metadata(spec),
            )
            db.add(existing)
            db.flush()
            source_created += 1
            emit_audit_event(
                db=db,
                workspace_id=workspace.id,
                event_type="visual.source.seeded",
                actor="system",
                details={
                    "source_id": existing.id,
                    "adapter": existing.adapter,
                    "collection": collection.slug,
                },
            )
        else:
            _apply_seed_source(existing, spec, default_policy, system_id=system_id)
            db.flush()
        seeded_source_ids.append(existing.id)
    return {
        "collection": collection.slug,
        "source_id": seeded_source_ids[0],
        "source_created": source_created,
    }


def _default_visual_policy() -> dict[str, Any]:
    return {
        "capture": "manual_or_scheduled_snapshot",
        "allowed_use": "situational_briefing",
        "pii_policy": "no_identification_no_biometrics",
        "human_validation_required": True,
        "recording": "no_continuous_recording",
    }


def _apply_seed_source(
    source: WorkspaceVisualSource,
    spec: dict[str, Any],
    default_policy: dict[str, Any],
    *,
    system_id: Optional[str],
) -> None:
    metadata = dict(source.meta_data or {})
    seeded_metadata = _webcam_metadata(spec)
    metadata.update(
        {
            key: value
            for key, value in seeded_metadata.items()
            if key not in metadata
            or key
            in {
                "provider",
                "video_provider",
                "layer_kind",
                "stream_kind",
                "embed_url",
                "player_url",
                "preview_url",
                "source_page",
                "preferred_render",
                "embed_status",
                "fallback_reason",
                "analysis_mode",
                "attribution",
                "timelapse_policy",
                "priority",
                "nest_public_token",
                "refresh_seconds",
                "resolution_tier",
                "resolution_label",
                "native_resolution_hint",
                "evidence_grade",
                "analysis_constraints",
                "best_use",
                "map_location",
                "zone_id",
                "camera_label",
                "map_zoom",
            }
        }
    )
    source.name = spec["name"]
    source.description = spec["description"]
    source.source_url = spec["source_url"]
    source.source_type = "stream_embed"
    source.adapter = spec.get("adapter", source.adapter or "http_image")
    source.region = spec["region"]
    source.enabled = True
    if source.status not in {"active", "paused"}:
        source.status = "active"
    source.capture_cadence_minutes = source.capture_cadence_minutes or 60
    source.policy = {**default_policy, **(source.policy or {})}
    source.meta_data = metadata
    source.system_id = source.system_id or system_id
    source.updated_at = datetime.utcnow()


def ensure_visual_collection(db: DBSession, workspace: Workspace) -> KnowledgeCollection:
    existing = (
        db.query(KnowledgeCollection)
        .filter(
            KnowledgeCollection.workspace_id == workspace.id,
            KnowledgeCollection.slug == VISUAL_COLLECTION_SLUG,
        )
        .first()
    )
    if existing:
        existing.name = "SENTINEL-CI Visual Intelligence"
        existing.description = "Visual snapshots, observations and posture summaries from authorized workspace visual streams."
        return existing
    collection = KnowledgeCollection(
        id=str(uuid4()),
        workspace_id=workspace.id,
        slug=VISUAL_COLLECTION_SLUG,
        name="SENTINEL-CI Visual Intelligence",
        description="Visual snapshots, observations and posture summaries from authorized workspace visual streams.",
        status="ready",
        document_names=[],
        vector_collection_name=f"{workspace.slug}__{VISUAL_COLLECTION_SLUG}",
        artifact_prefix=f"workspaces/{workspace.id}/collections/{VISUAL_COLLECTION_SLUG}",
        embedding_model="text-embedding-3-small",
        chunking_method="semantic",
        chunking_params={"source": "visual_intelligence", "demo_safe": True},
    )
    db.add(collection)
    db.flush()
    return collection


def list_sources(db: DBSession, workspace: Workspace) -> list[WorkspaceVisualSource]:
    rows = (
        db.query(WorkspaceVisualSource)
        .filter(WorkspaceVisualSource.workspace_id == workspace.id)
        .order_by(WorkspaceVisualSource.created_at.asc())
        .all()
    )
    return sorted(rows, key=_source_priority)


def _source_priority(source: WorkspaceVisualSource) -> int:
    value = (source.meta_data or {}).get("priority")
    return value if isinstance(value, int) else 999


def get_source(db: DBSession, workspace: Workspace, source_id: str) -> WorkspaceVisualSource:
    row = (
        db.query(WorkspaceVisualSource)
        .filter(
            WorkspaceVisualSource.id == source_id,
            WorkspaceVisualSource.workspace_id == workspace.id,
        )
        .first()
    )
    if not row:
        raise LookupError("visual_source_not_found")
    return row


def create_source(
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    *,
    name: str,
    source_url: str,
    description: str = "",
    source_type: str = "webcam",
    adapter: str = "http_image",
    region: str = "",
    capture_cadence_minutes: int = 60,
    enabled: bool = True,
    policy: Optional[dict[str, Any]] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> WorkspaceVisualSource:
    row = WorkspaceVisualSource(
        id=str(uuid4()),
        workspace_id=workspace.id,
        created_by_user_id=user.id if user else None,
        name=name,
        description=description,
        source_url=source_url,
        source_type=source_type,
        adapter=adapter,
        region=region,
        enabled=enabled,
        status="active" if enabled else "paused",
        capture_cadence_minutes=max(1, min(int(capture_cadence_minutes or 60), 1440)),
        policy=policy
        or {
            "capture": "manual_or_scheduled_snapshot",
            "allowed_use": "situational_briefing",
            "pii_policy": "no_identification_no_biometrics",
        },
        meta_data=metadata or {},
    )
    db.add(row)
    db.flush()
    _audit(
        db, workspace, user, "visual.source.created", {"source_id": row.id, "adapter": row.adapter}
    )
    return row


def update_source(
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    source_id: str,
    updates: dict[str, Any],
) -> WorkspaceVisualSource:
    row = get_source(db, workspace, source_id)
    allowed = {
        "name",
        "description",
        "source_url",
        "source_type",
        "adapter",
        "region",
        "status",
        "enabled",
        "capture_cadence_minutes",
        "policy",
        "metadata",
    }
    touched: list[str] = []
    for key, value in updates.items():
        if key not in allowed:
            continue
        attr = "meta_data" if key == "metadata" else key
        if key == "capture_cadence_minutes" and value is not None:
            value = max(1, min(int(value), 1440))
        setattr(row, attr, value)
        touched.append(key)
    row.updated_at = datetime.utcnow()
    db.flush()
    _audit(
        db,
        workspace,
        user,
        "visual.source.updated",
        {"source_id": row.id, "updates": sorted(touched)},
    )
    return row


def queue_visual_capture(
    db: DBSession,
    workspace: Workspace,
    source: WorkspaceVisualSource,
    user: Optional[User] = None,
) -> Any:
    if source.workspace_id != workspace.id:
        raise LookupError("visual_source_not_found")
    if not source.enabled or source.status != "active":
        raise RuntimeError("visual_source_not_active")
    job = create_workspace_job(
        db,
        workspace,
        user,
        kind="visual_snapshot_capture",
        title=f"Capture visuelle · {source.name}",
        input_ref={"source_id": source.id, "adapter": source.adapter},
        status="queued",
    )
    _audit(db, workspace, user, "visual.capture.queued", {"source_id": source.id, "job_id": job.id})
    return job


def dispatch_visual_capture_job(
    db: DBSession,
    workspace: Workspace,
    job: Any,
    source: WorkspaceVisualSource,
    user: Optional[User] = None,
) -> str:
    """Dispatch a visual capture without blocking the request path.

    Tests and local demos can keep ``WORKER_EAGER_MODE=true``; production uses
    Celery so HTTP returns as soon as the WorkspaceJob is persisted.
    """
    if settings.worker_eager_mode:
        capture_source(db, workspace, source, user=user, job=job)
        return f"eager:{job.id}"
    from app.workers.tasks import visual_snapshot_capture

    result = visual_snapshot_capture.apply_async(
        args=(job.id,), queue=settings.celery_task_default_queue
    )
    job.result = {**(job.result or {}), "celery_task_id": result.id}
    db.flush()
    return result.id


def run_visual_capture_job(job_id: str) -> dict[str, Any]:
    """Worker entrypoint for ``agentium.visual_snapshot_capture``."""
    with SessionLocal() as db:
        from app.models.workspace_job import WorkspaceJob

        job = db.query(WorkspaceJob).filter(WorkspaceJob.id == job_id).first()
        if not job:
            raise LookupError("visual_capture_job_not_found")
        workspace = db.query(Workspace).filter(Workspace.id == job.workspace_id).first()
        if not workspace:
            raise LookupError("visual_capture_workspace_not_found")
        source_id = (job.input_ref or {}).get("source_id")
        source = (
            db.query(WorkspaceVisualSource)
            .filter(
                WorkspaceVisualSource.id == source_id,
                WorkspaceVisualSource.workspace_id == workspace.id,
            )
            .first()
        )
        if not source:
            raise LookupError("visual_source_not_found")
        try:
            result = capture_source(db, workspace, source, user=None, job=job)
            db.commit()
            return result
        except Exception:
            db.commit()
            raise


def capture_source(
    db: DBSession,
    workspace: Workspace,
    source: WorkspaceVisualSource,
    user: Optional[User] = None,
    *,
    job: Optional[Any] = None,
) -> dict[str, Any]:
    if source.workspace_id != workspace.id:
        raise LookupError("visual_source_not_found")
    if not source.enabled or source.status != "active":
        raise RuntimeError("visual_source_not_active")
    if job is None:
        job = queue_visual_capture(db, workspace, source, user=user)
    transition_job(db, workspace, job, "running", progress=25, stage="capture_snapshot", user=user)
    capture_id = str(uuid4())
    try:
        content, mime_type, capture_meta = _capture_bytes(source)
        digest = hashlib.sha256(content).hexdigest()
        ext = _extension_for_mime(mime_type)
        store = get_object_store()
        object_key = store.key(
            "workspaces", workspace.id, "visual-intelligence", source.id, f"{capture_id}.{ext}"
        )
        store.write_bytes(object_key, content)
        capture = WorkspaceVisualCapture(
            id=capture_id,
            workspace_id=workspace.id,
            source_id=source.id,
            job_id=job.id,
            status="captured",
            object_key=object_key,
            mime_type=mime_type,
            size_bytes=len(content),
            sha256=digest,
            width=capture_meta.get("width"),
            height=capture_meta.get("height"),
            meta_data=capture_meta,
            captured_at=datetime.utcnow(),
        )
        db.add(capture)
        db.flush()
        transition_job(
            db, workspace, job, "running", progress=70, stage="analyze_snapshot", user=user
        )
        observation = _analyze_capture(
            db, workspace, source, capture, capture_meta, content, mime_type
        )
        capture.status = "analyzed"
        source.last_captured_at = capture.captured_at
        source.status = "active"
        source.updated_at = datetime.utcnow()
        sync_key = sync_observation_to_knowledge(db, workspace, observation)
        transition_job(
            db,
            workspace,
            job,
            "completed",
            progress=100,
            stage="synced_to_knowledge",
            result={
                "capture_id": capture.id,
                "observation_id": observation.id,
                "knowledge_object_key": sync_key,
            },
            user=user,
        )
        _audit(
            db,
            workspace,
            user,
            "visual.capture.completed",
            {
                "source_id": source.id,
                "capture_id": capture.id,
                "observation_id": observation.id,
                "object_key": capture.object_key,
                "vigilance_score": observation.vigilance_score,
            },
        )
        db.flush()
        return {
            "job": serialize_job(job),
            "source": serialize_source(source),
            "capture": serialize_capture(capture),
            "observation": serialize_observation(observation),
        }
    except Exception as exc:  # noqa: BLE001
        source.status = "error"
        transition_job(
            db, workspace, job, "failed", progress=100, stage="failed", error=str(exc), user=user
        )
        failed = WorkspaceVisualCapture(
            id=capture_id,
            workspace_id=workspace.id,
            source_id=source.id,
            job_id=job.id,
            status="failed",
            object_key="",
            mime_type="application/octet-stream",
            size_bytes=0,
            sha256="",
            error=str(exc),
            meta_data={"adapter": source.adapter},
            captured_at=datetime.utcnow(),
        )
        db.add(failed)
        _audit(
            db,
            workspace,
            user,
            "visual.capture.failed",
            {"source_id": source.id, "job_id": job.id, "error": str(exc)},
        )
        db.flush()
        raise


def list_captures(
    db: DBSession, workspace: Workspace, source_id: str, *, limit: int = 50
) -> list[WorkspaceVisualCapture]:
    return (
        db.query(WorkspaceVisualCapture)
        .filter(
            WorkspaceVisualCapture.workspace_id == workspace.id,
            WorkspaceVisualCapture.source_id == source_id,
        )
        .order_by(WorkspaceVisualCapture.captured_at.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )


def get_capture(db: DBSession, workspace: Workspace, capture_id: str) -> WorkspaceVisualCapture:
    row = (
        db.query(WorkspaceVisualCapture)
        .filter(
            WorkspaceVisualCapture.id == capture_id,
            WorkspaceVisualCapture.workspace_id == workspace.id,
        )
        .first()
    )
    if not row:
        raise LookupError("visual_capture_not_found")
    return row


def latest_observations(
    db: DBSession, workspace: Workspace, *, limit: int = 5
) -> list[WorkspaceVisualObservation]:
    return (
        db.query(WorkspaceVisualObservation)
        .filter(WorkspaceVisualObservation.workspace_id == workspace.id)
        .order_by(WorkspaceVisualObservation.created_at.desc())
        .limit(max(1, min(limit, 20)))
        .all()
    )


def dashboard_payload(db: DBSession, workspace: Workspace) -> dict[str, Any]:
    sources = list_sources(db, workspace)
    captures = (
        db.query(WorkspaceVisualCapture)
        .filter(WorkspaceVisualCapture.workspace_id == workspace.id)
        .order_by(WorkspaceVisualCapture.captured_at.desc())
        .limit(25)
        .all()
    )
    observations = latest_observations(db, workspace, limit=8)
    active_sources = [source for source in sources if source.enabled and source.status == "active"]
    latest = observations[0] if observations else None
    latest_capture = captures[0] if captures else None
    posture = strategic_visual_posture(observations)
    cadence = min((source.capture_cadence_minutes or 60 for source in active_sources), default=60)
    freshness = _freshness_status(latest_capture.captured_at if latest_capture else None, cadence)
    next_capture_at = (
        latest_capture.captured_at + timedelta(minutes=cadence)
        if latest_capture and latest_capture.captured_at
        else None
    )
    return {
        "connector": {
            "id": "visual_streams",
            "label": "Flux visuels institutionnels",
            "status": "connected" if active_sources else "configured",
            "mode": "live_webcam_embed_layer",
            "policy": "no_identification_no_biometrics",
        },
        "source_health": {
            "active_sources": len(active_sources),
            "total_sources": len(sources),
            "captures": len(captures),
            "observations": len(observations),
            "last_capture_at": latest_capture.captured_at.isoformat()
            if latest_capture and latest_capture.captured_at
            else None,
            "last_analysis_at": latest.created_at.isoformat()
            if latest and latest.created_at
            else None,
            "freshness_status": freshness,
            "next_capture_at": next_capture_at.isoformat() if next_capture_at else None,
            "coverage_label": "Flux visuels habilites"
            if active_sources
            else "Aucune source active",
        },
        "posture": posture,
        "sources": [serialize_source(source) for source in sources],
        "captures": [serialize_capture(capture) for capture in captures[:10]],
        "observations": [serialize_observation(observation) for observation in observations],
        "latest_observation": serialize_observation(latest) if latest else None,
    }


def strategic_visual_posture(observations: list[WorkspaceVisualObservation]) -> dict[str, Any]:
    score = max((obs.vigilance_score for obs in observations), default=32)
    label = _level_label(score)
    return {
        "label": label,
        "score": score,
        "trend": "stable" if score < 55 else "a surveiller",
        "summary": _posture_summary(label, score),
    }


def visual_context_for_chat(db: DBSession, workspace: Workspace) -> str:
    observations = latest_observations(db, workspace, limit=4)
    if not observations:
        return "Aucune observation visuelle recente n'est disponible dans ce workspace."
    lines = ["Observations visuelles recentes:"]
    for obs in observations:
        lines.append(
            f"- {obs.created_at.isoformat()}: {obs.summary} "
            f"(vigilance {obs.vigilance_score}/100, confiance {round(obs.confidence * 100)}%, tags {', '.join(obs.tags or [])})"
        )
    return "\n".join(lines)


def handle_visual_chat_query(
    db: DBSession,
    workspace: Workspace,
    user: User,
    *,
    query: str,
    assistant_profile: Optional[str],
) -> Optional[dict[str, Any]]:
    lowered = (query or "").lower()
    triggers = (
        "visuel",
        "visuelle",
        "webcam",
        "camera",
        "caméra",
        "capture",
        "image",
        "flux",
        "observation",
    )
    if not any(token in lowered for token in triggers):
        return None
    if not visual_intelligence_enabled(workspace) or not _visual_chat_profile_enabled(
        workspace,
        assistant_profile,
    ):
        return None
    try:
        workspace = lock_workspace_for_app_entitlement_mutation(db, workspace.id)
    except WorkspaceEntitlementMutationConflictError:
        return None
    if not visual_intelligence_enabled(workspace) or not _visual_chat_profile_enabled(
        workspace,
        assistant_profile,
    ):
        return None
    ensure_visual_intelligence_seed(db, workspace)
    dashboard = dashboard_payload(db, workspace)
    observations = dashboard.get("observations") or []
    if not observations:
        content = (
            "Aucune observation visuelle recente n'est encore disponible. "
            "Je peux demander une capture d'un flux visuel habilite avant de consolider la synthese."
        )
    else:
        latest = observations[0]
        content = (
            "Derniere lecture visuelle disponible : "
            f"{latest.get('summary')} Niveau de vigilance {latest.get('vigilance_score')}/100, "
            f"confiance {round((latest.get('confidence') or 0) * 100)}%. "
            "Cette lecture reste indicative : elle soutient le briefing, mais ne remplace pas une validation humaine."
        )
    _audit(
        db,
        workspace,
        user,
        "visual.chat.context_used",
        {"observations": len(observations), "assistant_profile": assistant_profile},
    )
    return {
        "action": "visual_observation_read",
        "applied": False,
        "content": content,
        "dashboard": dashboard,
    }


def sync_observation_to_knowledge(
    db: DBSession,
    workspace: Workspace,
    observation: WorkspaceVisualObservation,
) -> str:
    collection = ensure_visual_collection(db, workspace)
    store = get_object_store()
    filename = f"visual-observation-{observation.id}.md"
    markdown = _observation_markdown(observation)
    original_key = store.key(collection.artifact_prefix, "original", filename)
    object_key = store.key(collection.artifact_prefix, "ingested", filename)
    store.write_text(original_key, markdown)
    store.write_text(object_key, markdown)
    docs = list(collection.document_names or [])
    if filename not in docs:
        docs.append(filename)
    collection.document_names = docs
    collection.document_count = len(docs)
    collection.chunk_count = max(collection.chunk_count or 0, len(docs))
    collection.status = "ready"
    collection.updated_at = datetime.utcnow()
    db.flush()
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="visual.observation.synced_to_knowledge",
        actor="system",
        details={
            "observation_id": observation.id,
            "collection": collection.slug,
            "object_key": object_key,
            "original_key": original_key,
        },
    )
    return object_key


def serialize_source(source: WorkspaceVisualSource) -> dict[str, Any]:
    freshness = _freshness_status(source.last_captured_at, source.capture_cadence_minutes or 60)
    next_capture_at = (
        source.last_captured_at + timedelta(minutes=source.capture_cadence_minutes or 60)
        if source.last_captured_at
        else None
    )
    return {
        "id": source.id,
        "name": source.name,
        "description": source.description,
        "source_url": source.source_url,
        "source_type": source.source_type,
        "adapter": source.adapter,
        "region": source.region,
        "status": source.status,
        "enabled": source.enabled,
        "capture_cadence_minutes": source.capture_cadence_minutes,
        "policy": source.policy or {},
        "metadata": source.meta_data or {},
        "last_captured_at": source.last_captured_at.isoformat()
        if source.last_captured_at
        else None,
        "freshness_status": freshness,
        "next_capture_at": next_capture_at.isoformat() if next_capture_at else None,
        "created_at": source.created_at.isoformat() if source.created_at else None,
        "updated_at": source.updated_at.isoformat() if source.updated_at else None,
    }


def _freshness_status(timestamp: Optional[datetime], cadence_minutes: int) -> str:
    if not timestamp:
        return "missing"
    age = datetime.utcnow() - timestamp
    cadence = max(1, cadence_minutes)
    if age <= timedelta(minutes=cadence * 1.5):
        return "fresh"
    if age <= timedelta(minutes=cadence * 3):
        return "aging"
    return "stale"


def serialize_capture(capture: WorkspaceVisualCapture) -> dict[str, Any]:
    return {
        "id": capture.id,
        "source_id": capture.source_id,
        "job_id": capture.job_id,
        "status": capture.status,
        "object_key": capture.object_key,
        "mime_type": capture.mime_type,
        "size_bytes": capture.size_bytes,
        "sha256": capture.sha256,
        "width": capture.width,
        "height": capture.height,
        "error": capture.error,
        "metadata": capture.meta_data or {},
        "captured_at": capture.captured_at.isoformat() if capture.captured_at else None,
    }


def serialize_observation(observation: WorkspaceVisualObservation) -> dict[str, Any]:
    return {
        "id": observation.id,
        "source_id": observation.source_id,
        "capture_id": observation.capture_id,
        "summary": observation.summary,
        "tags": observation.tags or [],
        "confidence": observation.confidence,
        "vigilance_score": observation.vigilance_score,
        "level_label": observation.level_label,
        "source_refs": observation.source_refs or [],
        "provider": observation.provider,
        "model": observation.model,
        "metadata": observation.meta_data or {},
        "created_at": observation.created_at.isoformat() if observation.created_at else None,
    }


def _default_webcam_metadata() -> dict[str, Any]:
    return _webcam_metadata(ABIDJAN_NET_VISUAL_SOURCES[0])


def _webcam_metadata(spec: dict[str, Any]) -> dict[str, Any]:
    base = {
        "demo_fallback": True,
        "provider_neutral": True,
        "provider": "abidjan.net",
        "video_provider": "google_nest_public_embed",
        "preferred_render": "snapshot",
        "embed_status": "unstable",
        "fallback_reason": "nest_public_embed_can_return_missing_in_action",
        "country": "Cote d'Ivoire",
        "default_vigilance_score": spec["default_vigilance_score"],
        "layer": "visual_streams",
        "layer_kind": "live_webcam_snapshot",
        "stream_kind": "abidjan_net_public_snapshot",
        "embed_url": spec["embed_url"],
        "player_url": spec["embed_url"],
        "preview_url": spec["source_url"],
        "source_page": spec["source_page"],
        "map_location": spec.get("map_location"),
        "zone_id": (spec.get("map_location") or {}).get("zone_id"),
        "camera_label": (spec.get("map_location") or {}).get("label") or spec["region"],
        "map_zoom": (spec.get("map_location") or {}).get("zoom", 10.8),
        "refresh_seconds": 60,
        "resolution_tier": "public_medium",
        "resolution_label": "Basse resolution publique",
        "native_resolution_hint": "Image Abidjan.net __medium ; le live Nest public peut etre indisponible ou moins stable que le snapshot.",
        "evidence_grade": "macro_context_only",
        "analysis_constraints": [
            "pas d'identification individuelle",
            "pas de lecture plaque",
            "pas de comptage fin fiable",
            "resolution insuffisante pour preuve detaillee",
        ],
        "best_use": "Contexte macro : trafic, meteo visible, densite generale, coherence avec presse/carte/agenda.",
        "analysis_mode": "public_snapshot_to_vlm_ready",
        "attribution": "Abidjan.net Trafic routier & Meteo, image publique avec fallback hors embed Nest",
        "timelapse_policy": "public_snapshot_refreshed_without_continuous_recording",
        "priority": spec["priority"],
        "nest_public_token": spec.get("nest_token"),
        "label_disclaimer": spec.get("label_disclaimer"),
        "kind": "traffic_webcam",
    }
    overrides = spec.get("metadata_overrides") or {}
    if overrides:
        base.update({key: value for key, value in overrides.items() if value is not None})
    return base


def _capture_bytes(source: WorkspaceVisualSource) -> tuple[bytes, str, dict[str, Any]]:
    if source.adapter == "demo_static" or source.source_url.startswith("demo://"):
        return (
            _demo_snapshot(source),
            "image/svg+xml",
            {"adapter": source.adapter, "width": 960, "height": 540, "demo_safe": True},
        )
    if source.adapter == "http_image" and (source.meta_data or {}).get("provider") == "windy":
        try:
            return _capture_windy_webcam(source)
        except Exception:
            if (source.meta_data or {}).get("demo_fallback"):
                return (
                    _demo_snapshot(source),
                    "image/svg+xml",
                    {
                        "adapter": source.adapter,
                        "width": 960,
                        "height": 540,
                        "demo_safe": True,
                        "fallback": "windy_unavailable",
                    },
                )
            raise
    if source.adapter == "browser_screenshot":
        if not settings.visual_capture_browser_enabled:
            raise RuntimeError("browser_screenshot_disabled")
        if not source.source_url.startswith(("http://", "https://")):
            raise RuntimeError("browser_screenshot_requires_http_url")
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("browser_screenshot_adapter_missing_playwright") from exc
        timeout_ms = int(settings.visual_capture_http_timeout_seconds * 1000)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            try:
                page = browser.new_page(
                    viewport={"width": 1280, "height": 720}, device_scale_factor=1
                )
                page.goto(source.source_url, wait_until="networkidle", timeout=timeout_ms)
                content = page.screenshot(type="png", full_page=False)
            finally:
                browser.close()
        return (
            content,
            "image/png",
            {
                "adapter": source.adapter,
                "source_url": source.source_url,
                "width": 1280,
                "height": 720,
            },
        )
    if source.adapter != "http_image":
        raise RuntimeError(f"unsupported_visual_adapter:{source.adapter}")
    if not source.source_url.startswith(("http://", "https://")):
        raise RuntimeError("http_image_requires_http_url")
    try:
        content, mime_type = _fetch_http_image(source.source_url)
    except Exception:
        if (source.meta_data or {}).get("demo_fallback"):
            return (
                _demo_snapshot(source),
                "image/svg+xml",
                {
                    "adapter": source.adapter,
                    "width": 960,
                    "height": 540,
                    "demo_safe": True,
                    "fallback": "http_image_unavailable",
                },
            )
        raise
    return (
        content,
        mime_type,
        {
            "adapter": source.adapter,
            "source_url": source.source_url,
            "provider": (source.meta_data or {}).get("provider"),
        },
    )


def _fetch_http_image(url: str) -> tuple[bytes, str]:
    with httpx.Client(
        timeout=settings.visual_capture_http_timeout_seconds, follow_redirects=True
    ) as client:
        response = client.get(url, headers={"User-Agent": "AgentiumVisualIntelligence/1.0"})
        response.raise_for_status()
    mime_type = (
        response.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
    )
    if not mime_type.startswith("image/"):
        raise RuntimeError(f"visual_source_not_image:{mime_type}")
    return response.content, mime_type


def _capture_windy_webcam(source: WorkspaceVisualSource) -> tuple[bytes, str, dict[str, Any]]:
    metadata = source.meta_data or {}
    webcam_id = metadata.get("webcam_id")
    if not webcam_id:
        raise RuntimeError("windy_webcam_id_required")
    if not settings.visual_capture_windy_api_key:
        raise RuntimeError("windy_api_key_missing")
    url = f"https://api.windy.com/webcams/api/v3/webcams/{webcam_id}?include=images,urls"
    with httpx.Client(
        timeout=settings.visual_capture_http_timeout_seconds, follow_redirects=True
    ) as client:
        response = client.get(
            url, headers={"x-windy-api-key": settings.visual_capture_windy_api_key}
        )
        response.raise_for_status()
    payload = response.json()
    webcam = (payload.get("webcams") or [payload])[0]
    images = webcam.get("images") or webcam.get("image") or {}
    image_url = (
        ((images.get("current") or {}).get("preview"))
        or ((images.get("current") or {}).get("thumbnail"))
        or metadata.get("preview_url")
    )
    if not image_url:
        raise RuntimeError("windy_preview_unavailable")
    content, mime_type = _fetch_http_image(image_url)
    return (
        content,
        mime_type,
        {
            "adapter": source.adapter,
            "provider": "windy",
            "webcam_id": webcam_id,
            "source_url": image_url,
            "player_url": (webcam.get("urls") or {}).get("player") or metadata.get("player_url"),
            "last_updated": webcam.get("lastUpdatedOn"),
        },
    )


def _analyze_capture(
    db: DBSession,
    workspace: Workspace,
    source: WorkspaceVisualSource,
    capture: WorkspaceVisualCapture,
    capture_meta: dict[str, Any],
    content: bytes,
    mime_type: str,
) -> WorkspaceVisualObservation:
    default_score = int((source.meta_data or {}).get("default_vigilance_score") or 35)
    source_name = source.name or "Source visuelle"
    region = source.region or "zone suivie"
    analysis = _run_visual_analysis(source, capture, capture_meta, content, mime_type)
    summary = str(
        analysis.get("summary")
        or (
            f"{source_name}: capture exploitable sur {region}. "
            "Activite visuelle compatible avec une surveillance institutionnelle nominale ; "
            "aucun signal critique automatise n'est retenu sans confirmation operateur."
        )
    )
    raw_tags = analysis.get("tags") if isinstance(analysis.get("tags"), list) else []
    tags = [str(tag)[:48] for tag in raw_tags if str(tag).strip()][:8] or [
        "flux-visuel",
        "observation",
        "cote-ivoire",
        "validation-humaine",
    ]
    confidence = _bounded_float(
        analysis.get("confidence"), default=0.68 if capture_meta.get("demo_safe") else 0.62
    )
    score = _bounded_int(analysis.get("vigilance_score"), default=default_score, lower=0, upper=100)
    level = str(analysis.get("level_label") or _level_label(score)).lower()
    if level not in {"stable", "monitoring", "elevated", "critical"}:
        level = _level_label(score)
    provider = str(analysis.get("provider") or "rule_based")[:80]
    model = analysis.get("model")
    observation = WorkspaceVisualObservation(
        id=str(uuid4()),
        workspace_id=workspace.id,
        source_id=source.id,
        capture_id=capture.id,
        summary=summary,
        tags=tags,
        confidence=confidence,
        vigilance_score=score,
        level_label=level,
        source_refs=[f"visual:{source.id}", f"capture:{capture.id}"],
        provider=provider,
        model=str(model)[:160] if model else None,
        meta_data={
            "adapter": source.adapter,
            "source_region": region,
            "no_biometrics": True,
            "advisory_only": True,
            "analysis": analysis.get("analysis") or "rule_based",
            "observations": analysis.get("observations") or [],
            "recommended_next_step": analysis.get("recommended_next_step"),
            "analysis_error": analysis.get("error"),
        },
        created_at=datetime.utcnow(),
    )
    db.add(observation)
    db.flush()
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="visual.observation.created",
        actor="system",
        details={
            "source_id": source.id,
            "capture_id": capture.id,
            "observation_id": observation.id,
        },
    )
    return observation


def _run_visual_analysis(
    source: WorkspaceVisualSource,
    capture: WorkspaceVisualCapture,
    capture_meta: dict[str, Any],
    content: bytes,
    mime_type: str,
) -> dict[str, Any]:
    if (
        not settings.visual_analysis_enabled
        or capture_meta.get("demo_safe")
        or not mime_type.startswith("image/")
    ):
        return {"analysis": "rule_based", "provider": "rule_based"}
    provider = (settings.visual_analysis_provider or "openai").lower()
    try:
        if provider == "openai":
            return _run_openai_visual_analysis(source, capture, content, mime_type)
        if provider in {"local_http", "http"}:
            return _run_http_visual_analysis(source, capture, content, mime_type)
        return {
            "analysis": "rule_based",
            "provider": "rule_based",
            "error": f"unsupported_visual_analysis_provider:{provider}",
        }
    except Exception as exc:  # noqa: BLE001
        return {"analysis": "rule_based", "provider": "rule_based", "error": str(exc)[:240]}


def _run_openai_visual_analysis(
    source: WorkspaceVisualSource,
    capture: WorkspaceVisualCapture,
    content: bytes,
    mime_type: str,
) -> dict[str, Any]:
    if not settings.openai_api_key:
        return {
            "analysis": "rule_based",
            "provider": "rule_based",
            "error": "openai_api_key_missing",
        }
    try:
        from openai import OpenAI
    except Exception as exc:  # noqa: BLE001
        return {
            "analysis": "rule_based",
            "provider": "rule_based",
            "error": f"openai_sdk_unavailable:{exc}",
        }

    client = OpenAI(
        api_key=settings.openai_api_key, timeout=settings.visual_analysis_timeout_seconds
    )
    image_b64 = base64.b64encode(content).decode("ascii")
    prompt = _visual_analysis_prompt(source, capture)
    response = client.chat.completions.create(
        model=settings.visual_analysis_model,
        temperature=0,
        max_tokens=360,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "Tu analyses des snapshots webcam institutionnels pour un briefing executif. "
                    "Tu ne fais jamais d'identification de personnes, biometrie, plaques ou suivi individuel. "
                    "Tu restes prudent, sourcé par l'image seulement, et advisory-only."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{image_b64}",
                            "detail": "low",
                        },
                    },
                ],
            },
        ],
    )
    raw = response.choices[0].message.content or "{}"
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        payload = {}
    payload["analysis"] = "vlm"
    payload["provider"] = "openai"
    payload["model"] = getattr(response, "model", settings.visual_analysis_model)
    return payload


def _run_http_visual_analysis(
    source: WorkspaceVisualSource,
    capture: WorkspaceVisualCapture,
    content: bytes,
    mime_type: str,
) -> dict[str, Any]:
    if not settings.visual_analysis_endpoint_url:
        return {
            "analysis": "rule_based",
            "provider": "rule_based",
            "error": "visual_analysis_endpoint_missing",
        }
    payload = {
        "image_base64": base64.b64encode(content).decode("ascii"),
        "mime_type": mime_type,
        "prompt": _visual_analysis_prompt(source, capture),
        "source": {"id": source.id, "name": source.name, "region": source.region},
    }
    with httpx.Client(
        timeout=settings.visual_analysis_timeout_seconds, follow_redirects=True
    ) as client:
        response = client.post(settings.visual_analysis_endpoint_url, json=payload)
        response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("visual_analysis_endpoint_invalid_response")
    data.setdefault("analysis", "vlm")
    data.setdefault("provider", "local_http")
    return data


def _visual_analysis_prompt(source: WorkspaceVisualSource, capture: WorkspaceVisualCapture) -> str:
    return (
        "Observe l'image et produis uniquement un JSON avec les clés: "
        "summary (phrase courte en français), observations (liste courte), tags (liste), "
        "confidence (0-1), vigilance_score (0-100), level_label (stable|monitoring|elevated|critical), "
        "recommended_next_step (phrase). "
        f"Contexte: source={source.name}, region={source.region}, capture_id={capture.id}. "
        "Ne décris pas ou n'identifie pas les personnes. Mentionne explicitement si l'image est peu exploitable."
    )


def _bounded_float(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(parsed, 1.0))


def _bounded_int(value: Any, *, default: int, lower: int, upper: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(lower, min(parsed, upper))


def _demo_snapshot(source: WorkspaceVisualSource) -> bytes:
    region = (source.region or "Abidjan").replace("&", "&amp;")
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540">
  <defs>
    <linearGradient id="sky" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0" stop-color="#061018"/>
      <stop offset="1" stop-color="#142334"/>
    </linearGradient>
    <linearGradient id="road" x1="0" x2="1">
      <stop offset="0" stop-color="#10202d"/>
      <stop offset="1" stop-color="#070c12"/>
    </linearGradient>
  </defs>
  <rect width="960" height="540" fill="url(#sky)"/>
  <circle cx="770" cy="108" r="46" fill="#8ed8ff" opacity="0.18"/>
  <path d="M0 360 C160 310 250 375 382 338 C532 295 615 362 960 302 L960 540 L0 540Z" fill="url(#road)"/>
  <g fill="#162c3a">
    <rect x="72" y="198" width="54" height="155"/>
    <rect x="148" y="150" width="82" height="207"/>
    <rect x="270" y="226" width="60" height="126"/>
    <rect x="690" y="185" width="88" height="165"/>
    <rect x="808" y="245" width="48" height="106"/>
  </g>
  <g fill="#7dd3fc" opacity="0.58">
    <circle cx="175" cy="314" r="5"/>
    <circle cx="610" cy="340" r="4"/>
    <circle cx="720" cy="296" r="5"/>
    <circle cx="835" cy="344" r="4"/>
  </g>
  <rect x="28" y="28" width="396" height="82" rx="10" fill="#071019" opacity="0.82" stroke="#244257"/>
  <text x="50" y="61" font-family="Inter,Arial" font-size="18" fill="#bdeaff" font-weight="700">{region}</text>
  <text x="50" y="88" font-family="Inter,Arial" font-size="13" fill="#7b8da3">{now} · snapshot demo-safe · no biometrics</text>
</svg>"""
    return svg.encode("utf-8")


def _observation_markdown(observation: WorkspaceVisualObservation) -> str:
    tags = ", ".join(observation.tags or [])
    return (
        f"# Observation visuelle {observation.id}\n\n"
        f"- Date: {observation.created_at.isoformat()}\n"
        f"- Niveau: {observation.level_label} ({observation.vigilance_score}/100)\n"
        f"- Confiance: {round(observation.confidence * 100)}%\n"
        f"- Tags: {tags}\n"
        f"- Sources: {', '.join(observation.source_refs or [])}\n\n"
        f"{observation.summary}\n\n"
        "Politique: observation indicative, sans reconnaissance faciale ni identification individuelle. "
        "Toute action reste advisory-only et soumise a validation humaine.\n"
    )


def _extension_for_mime(mime_type: str) -> str:
    if mime_type == "image/svg+xml":
        return "svg"
    if mime_type in {"image/jpeg", "image/jpg"}:
        return "jpg"
    if mime_type == "image/png":
        return "png"
    if mime_type == "image/webp":
        return "webp"
    return "bin"


def _level_label(score: int) -> str:
    if score >= 75:
        return "critical"
    if score >= 55:
        return "elevated"
    if score >= 35:
        return "monitoring"
    return "stable"


def _posture_summary(label: str, score: int) -> str:
    if label == "critical":
        return f"Posture critique ({score}/100) : confirmation operateur immediate recommandee."
    if label == "elevated":
        return (
            f"Posture elevee ({score}/100) : observation a rapprocher des signaux presse et agenda."
        )
    if label == "monitoring":
        return f"Posture en surveillance ({score}/100) : source exploitable, aucun signal visuel critique automatise."
    return f"Posture stable ({score}/100) : veille visuelle nominale."


def _audit(
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    event_type: str,
    details: dict[str, Any],
) -> None:
    actor = "system"
    if user:
        actor = user.email or user.username or user.id
    emit_audit_event(
        db=db, workspace_id=workspace.id, event_type=event_type, actor=actor, details=details
    )
