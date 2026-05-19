# SENTINEL-CI Cartographie Ministerielle

## Objectif

La carte SENTINEL-CI est une surface de situation ministerielle, pas un SIG technique. Depuis `situation_map_v3`, elle doit permettre a un utilisateur ministeriel de voir rapidement :

- les zones suivies en Cote d'Ivoire ;
- les signaux qui expliquent le score d'une zone ;
- les sources mobilisees : presse, projets, agenda, observations visuelles, actions cabinet ;
- les actions preventives proposees, toujours sous validation humaine.
- les flux economiques utiles au pilotage gouvernemental, dont ports, douanes et corridors maritimes demo-safe.

La carte reste une primitive Agentium : elle est servie par le workspace, controlee par IAM, pilotable par AYA et auditee via les commandes carte. Elle reprend les bons patterns Worldmonitor sans copier son produit : registre de couches, fraicheur, time range, points sourcés, tooltips, commandes et fallback propre. La V3 ajoute la boucle Mission President `Explorer -> Comprendre -> Decider` et relie la carte au graphe de preuves OSINT du workspace.

## Fonds De Carte

Quatre fonds sont exposes dans le selecteur `Fond` :

- `Commandement` : fond executif contraste par defaut, volontairement plus lisible qu'un dark pur, avec labels et frontieres visibles en salle. C'est le mode recommande pour la demo VP.
- `Administratif` : fond CARTO/OSM contraste par defaut, avec labels et frontieres visibles. C'est le mode de briefing recommande : la geographie doit rester lisible avant les overlays.
- `Sombre` : fond cockpit type situation monitor, utile en salle basse lumiere quand les couches Agentium doivent dominer.
- `Contours` : fond clair desature, utile pour projection ou capture d'ecran quand le contexte geographique doit rester lisible.

Le bouton `Recentrer Cote d'Ivoire` utilise les bornes pays et force une vue 2D plate, sans pitch ni rotation.
Les boutons `+`, `-` et `vue pays` restent disponibles pour une conduite de demo sans molette.

## Donnees Geographiques

Les limites geographiques ne sont plus dessinees a la main. Elles sont versionnees dans `backend/app/resources/geo/civ/` :

- `geoboundaries-civ-adm0.geojson` : contour pays Cote d'Ivoire ;
- `geoboundaries-civ-adm1.geojson` : districts ;
- `geoboundaries-civ-adm2.geojson` : regions ;
- `metadata.json` : source, licence et date d'import.

Source : geoBoundaries Global Database, jeu `gbOpen/CIV`, licence CC BY 4.0. Les zones strategiques Agentium sont des regroupements de districts ADM1 ; les limites regionales ADM2 restent visibles seulement comme contexte administratif fin quand le zoom est suffisant.

Depuis le correctif robustesse SENTINEL-CI, le champ `WorkspaceMap.projection` canonique est `geojson_admin_boundaries_v1`. Le champ historique `workspace_map_zones.polygon` reste present pour compatibilite SVG/fallback, mais il ne doit plus etre la source de rendu principale en MapLibre/deck.gl.

## Situation Map V3

Le contrat V3 expose la carte comme un cockpit de situation, pas seulement comme une liste de polygones :

- `map_version: situation_map_v3` ;
- `rendering_profile: executive_command_v1` ;
- `layer_registry` : registre central des couches, avec groupe, compteur, fraicheur, confiance, source et visibilite ;
- `source_health` : etat de fraicheur par famille de sources ;
- `maritime_snapshot` : ports, corridor Golfe de Guinee, points navires demo-safe, densites, disruptions et statut douanes ;
- `forecast_signals` : signaux prospectifs a horizon court ;
- `scenario_modes` : modes `Explorer`, `Comprendre`, `Decider` utilisés par AYA et le cockpit.

La Mission Room expose aussi `/api/v1/mission-room/evidence-graph`. Ce graphe relie sources, rumeurs, lieux, projets, agenda, ports et actions. Il alimente le Knowledge Scope `vigie` via la collection `sentinel-ci-evidence-graph`, afin qu'AYA puisse citer et expliquer les relations, pas seulement resumer un texte.

## Couches

Chaque couche du panneau `Couches` correspond a un type de source Agentium. Le compteur indique le nombre d'elements visibles et le pourcentage indique la confiance operationnelle estimee.

- `Zones` : partitions territoriales de vigilance, clippees dans le contour pays Cote d'Ivoire. Visible par defaut.
- `Presse` : signaux RSS et syntheses News Lab rattaches a des zones ou villes. Visible par defaut.
- `Projets` : projets sensibles, retards et risques de perception. Visible par defaut.
- `Visuel` : observations issues des flux visuels habilites. Visible par defaut.
- `Maritime / douanes` : ports d'Abidjan et San Pedro, corridor Golfe de Guinee, densite navires indicative et contexte douanier. Masque par defaut, active par AYA quand la question porte sur port, navire, douane ou maritime.
- `Agenda` : fenetres d'action et contraintes issues de l'agenda ministeriel. Optionnel pour eviter la surcharge initiale.
- `Actions` : recommandations et actions cabinet proposees. Optionnel pour eviter de confondre observation et decision.

Desactiver une couche retire ses objets du rendu deck.gl correspondant. Les couches ne sont pas seulement decoratives. Par defaut, `Agenda` et `Actions` restent masques afin d'eviter de confondre observation et decision.

Le contexte regional CEDEAO est disponible mais masque par defaut pour eviter une surcharge ministerielle au premier regard. Il peut etre active par l'operateur ou par AYA via `set_layers`.

Le panneau de couches doit rester operable comme un registre Worldmonitor : recherche, etat visible/masque, groupe fonctionnel, fraicheur, compteur et confiance. Une couche desactivee retire réellement ses `GeoJsonLayer`, `ScatterplotLayer`, `PathLayer` ou `ArcLayer` du rendu deck.gl.

Les groupes V3 sont :

- `Territoire` : contour pays, districts, regions, zones de vigilance.
- `Presse / Rumeurs` : signaux News Lab, origine de rumeur, priorite geographique.
- `Projets` : projets sensibles et retards territoriaux.
- `Agenda` : fenetres d'action et contraintes cabinet.
- `Visuel` : observations de snapshots webcams habilites.
- `Maritime / Douanes` : ports, routes, densite et evenements demo-safe.
- `Actions` : options et recommandations advisory-only.

## Formes Et Couleurs

- Le contour pays suit le GeoJSON ADM0 versionne.
- Les limites internes fines suivent ADM2, visibles comme contexte administratif.
- Les zones de vigilance suivent des regroupements ADM1 : Nord, Ouest, Centre, Sud, Est.
- Les polygones verts indiquent une zone stable ou nominale.
- Les polygones ambre indiquent une zone en vigilance elevee.
- Les polygones rouges sont reserves aux situations critiques.
- Les halos indiquent des points de concentration de signaux.
- Les arcs indiquent un lien d'action ou de coordination depuis Abidjan vers une zone.
- Les points bleus representent des signaux presse ou rumeurs.
- Les points verts representent des projets ou sources institutionnelles.
- Les points orange representent ports, corridors maritimes et douanes.
- Les points violets representent observations visuelles habilitees.

Le score, la couleur et les recommandations sont analytiques. La geometrie de base reste administrative et sourcee ; Agentium n'invente plus les frontieres de zones.

## Maritime Et Douanes

La couche maritime est volontairement `snapshot_demo_safe` tant qu'un provider AIS n'est pas configure. Elle contient :

- deux ports : `Port d'Abidjan` et `Port de San Pedro` ;
- un corridor Golfe de Guinee ;
- des zones de densite : `Densite Abidjan / Vridi` et `Densite San Pedro` ;
- des disruptions demo-safe : fenetre douanes Abidjan et surveillance du corridor Golfe de Guinee ;
- des points de densite ou d'observation navires demonstratifs ;
- des statuts simples : `en route`, `a quai`, `congestion`, `inconnu`.

Elle ne promet pas un suivi live AIS et ne doit pas etre presentee comme un tracking individuel. Son objectif en demo est de montrer comment SENTINEL-CI croise economie, douanes, projets, presse et agenda dans une lecture gouvernementale.

## Commandes AYA

AYA peut emettre des commandes carte provider-neutral :

- `focus_zone` : centrer une zone.
- `focus_port` : centrer un port ou corridor maritime.
- `set_layers` : activer un sous-ensemble de couches.
- `set_basemap` : changer le fond.
- `set_time_range` : changer la fenetre temporelle.
- `reset_view` : revenir a la Cote d'Ivoire.
- `show_sources` : ouvrir la lecture des sources.
- `show_action_window` : afficher une fenetre d'action.
- `show_vessel_snapshot` : afficher le snapshot maritime demo-safe.
- `show_disruption` : rapprocher maritime, douanes, presse et actions.

Chaque commande est auditee et reste advisory-only.

## Explorer, Comprendre, Decider

La carte doit soutenir trois postures de demonstration :

- `Explorer` : voir la posture nationale, les couches actives, les zones et la fraicheur des sources.
- `Comprendre` : ouvrir les sources, le graphe de preuves, la chronologie et les facteurs de risque.
- `Decider` : comparer options, cout/impact/confiance, echeance et brouillon d'action ou email.

Toute carte du cockpit doit repondre a quatre questions : `quoi`, `pourquoi`, `quand`, `quelle action`.

## Robustesse Et Runtime

La carte consomme `/api/v1/maps/{map_id}`. Ce payload expose :

- `map_version: situation_map_v3`, `projection`, `time_range`, `available_time_ranges` ;
- `rendering_profile: executive_command_v1` ;
- `basemap_options`, `layer_catalog`, `layer_registry`, `default_map_state` ;
- `country_boundary`, `district_boundaries`, `admin_boundaries`, `cities` ;
- `region_scores`, `event_points`, `maritime_snapshot`, `source_health`, `forecast_signals`, `scenario_modes` ;
- `default_layer_groups` et `tooltip_templates` pour aligner UI, AYA et rendu deck.gl ;
- `geojson_sources` pour les zones, marqueurs, signaux, lignes de contexte, ports, routes et densites maritimes ;
- `source_counts` pour afficher des compteurs utiles dans le panneau `Couches`.
- `/api/v1/mission-room/evidence-graph` pour relier sources, lieux, rumeurs, ports, projets, agenda et actions dans AYA.

Checklist visuelle avant demo :

- fond `Commandement` lisible a 1440px ;
- aucun pitch ni bearing par defaut ;
- pays recadre proprement ;
- couche maritime desactivee par defaut mais activable en un clic ;
- `Maritime / douanes` affiche ports, corridor et points navires ;
- la legende stable / surveillance / eleve / critique reste visible ;
- chaque point ou zone ouvre une source, une action ou une explication.

Le backend distingue maintenant :

- `/health/live` : sonde ultra legere, sans DB, Qdrant, MinIO ou provider externe ;
- `/health/ready` : sonde operateur avec DB/Qdrant/ObjectStore et timeouts courts ;
- `/api/v1/health` : contrat public historique, volontairement leger pour eviter de bloquer le login.

La capture visuelle n'est plus une operation HTTP longue : `POST /api/v1/visual-intelligence/sources/{id}/capture` cree un `WorkspaceJob` et retourne `202` avec `{ job_id, status }`. Le worker execute capture, analyse VLM et synchronisation Knowledge, puis le tableau de bord expose `freshness_status`, `last_capture_at`, `last_analysis_at` et `next_capture_at`.

## Contraintes

- Aucune donnee Andritz ou autre workspace ne doit apparaitre dans SENTINEL-CI.
- Les couches sont workspace-scoped.
- Les donnees cartographiques publiques proviennent de sources OSM/CARTO en v1 ; une v2 peut self-hoster PMTiles/MBTiles.
- Les observations visuelles ne font pas de reconnaissance faciale, pas de suivi individuel et pas de biometrie.
