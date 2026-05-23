# SENTINEL-CI Cartographie Ministerielle

## Objectif

La carte SENTINEL-CI est une surface de situation ministerielle, pas un SIG technique. Depuis `situation_map_v3`, elle doit permettre a un utilisateur ministeriel de voir rapidement :

- les zones suivies en Cote d'Ivoire ;
- les signaux qui expliquent le score d'une zone ;
- les sources mobilisees : presse, projets, agenda, observations visuelles, actions cabinet ;
- les actions preventives proposees, toujours sous validation humaine.
- les flux economiques utiles au pilotage gouvernemental, dont ports, douanes et corridors maritimes demo-safe.

La carte reste une primitive Agentium : elle est servie par le workspace, controlee par IAM, pilotable par AYA et auditee via les commandes carte. Elle reprend les bons patterns Worldmonitor sans copier son produit : registre de couches, fraicheur, time range, points sourcés, tooltips, commandes et fallback propre. La V3 ajoute la boucle Mission President `Explorer -> Comprendre -> Decider` et relie la carte au graphe de preuves OSINT du workspace.

## Coherence Narrative VP

La carte ne porte pas un scenario autonome. Elle consomme le `vp_story` unique expose par `mission_room.py`, partage par cockpit, presse/news, briefing, timeline/agenda, carte et monitor. Les ancres narratives canoniques sont :

- `Zone Nord` comme zone prioritaire ;
- `Article L'Inter - critique personnelle sur budget defense` comme signal presse ;
- `Ambassadeur France - dejeuner dans 1h44` comme signal agenda ;
- `Emoi public - rumeur a contenir` comme signal rumeur ;
- `Port d'Abidjan - douanes et flux economiques` comme signal maritime/economique.

Toute evolution cartographique doit preserver cette coherence : les couches, tooltips, commandes AYA et panneaux de decision doivent raconter la meme histoire que le cockpit et la presse. Une information cartographique doit mener a comprendre, ouvrir un dossier, preparer une reponse ou arbitrer ; elle ne doit pas introduire un signal orphelin ou contradictoire.

## Fonds De Carte

Quatre fonds sont exposes dans le selecteur `Fond`. Le fond est un objet de premier rang : il doit rester lisible avant toute couche Agentium.

- `Commandement` : CARTO `dark_all` raster controle, fond executif sombre par defaut. Il privilegie la separation mer/terre, un contour pays fort et des traces operationnelles lisibles en salle basse lumiere, avant le passage futur a PMTiles self-hosted.
- `Administratif` : `voyager` vectoriel, fond clair/desature avec labels et frontieres visibles. C'est le mode recommande pour verifier l'ancrage geographique.
- `Sombre` : `dark-matter` vectoriel, mode cockpit quand les couches Agentium doivent dominer.
- `Contours` : `positron` vectoriel, mode clair minimal pour projection, capture d'ecran ou briefing confidentiel.

Les filtres frontend doivent rester faibles : on ne doit pas rendre une carte illisible en “corrigeant” agressivement le fond. La navigation ne doit pas etre verrouillee par des `maxBounds` regionaux : l'utilisateur doit pouvoir dezoomer jusqu'a CEDEAO, Afrique et monde pour retrouver une lecture Worldmonitor-like. Le bouton `Recentrer Cote d'Ivoire` utilise les bornes pays, force une vue 2D plate, sans pitch ni rotation, et applique un padding symetrique. La carte ne doit jamais compenser son cadrage par un panneau lateral ouvert.
Les boutons `+`, `-` et `vue pays` restent disponibles pour une conduite de demo sans molette. Un changement de fond cartographique doit conserver la camera courante ; seul le bouton `Recentrer Cote d'Ivoire` ou une commande AYA explicite doit recadrer la carte.

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

## Chantier Dedie

La cartographie SENTINEL-CI est traitee comme un moteur produit, pas comme un polish CSS. Les corrections de contraste ou de placement ne suffisent pas si les couches ne sont pas solides. Le chantier dedie suit donc cet ordre :

1. `Donnees` : GeoJSON officiels, regions, villes, ports, sources et metadonnees.
2. `Layer Registry` : statut, fraicheur, compteur, confiance, source, groupe fonctionnel.
3. `Rendu` : ordre de couches, seuils de zoom, labels, halos, tooltips, clustering.
4. `Interaction` : toggles effectifs, recherche, time range, focus zone/port, sources et actions.
5. `AYA` : commandes auditees et reponses courtes qui pilotent la carte sans exposer le provider.

Ce decoupage est la condition pour atteindre un niveau Worldmonitor-like credible : une carte dynamique, lisible, sourcee et explicable, pas une composition graphique decorative.

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

En vue ministerielle, le panneau est replie par defaut. La carte doit d'abord se lire comme un territoire, puis comme un registre de couches quand l'operateur ouvre le panneau. Les couches actives par defaut doivent rester volontairement limitees : zones, presse, projets et visuel. Les marqueurs de zones sont limites au point selectionne ou a la zone prioritaire tant que les couches `Visuel` ou `Actions` ne sont pas activees.

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
- Les arcs indiquent un lien d'action ou de coordination depuis Abidjan vers une zone. Ils restent fins, peu opaques et moins lumineux que les signaux pour ne pas etre confondus avec les corridors maritimes.
- Les points bleus representent des signaux presse ou rumeurs.
- Les points verts representent des projets ou sources institutionnelles.
- Le registre `Maritime / douanes` est bleu, pas orange. Il utilise d'abord une zone maritime de contexte translucide pour rendre la mer lisible, puis des routes bleues/cyan qui suivent uniquement la mer ou l'approche portuaire. Les zones de densite maritime sont cyan translucide. Les ports peuvent garder un accent orange/vert selon leur statut, mais les lignes maritimes ne doivent jamais etre orange.
- Les points violets representent observations visuelles habilitees.

Le score, la couleur et les recommandations sont analytiques. La geometrie de base reste administrative et sourcee ; Agentium n'invente plus les frontieres de zones.

Les objets maritimes portent un role visuel explicite dans le GeoJSON pour eviter les confusions de rendu :

- `operating_area` : surface maritime suivie, cyan tres translucide ;
- `corridor` : route maritime large, bleue, jamais orange ;
- `port_approach` : approche portuaire, cyan plus lumineux, epaisseur limitee ;
- `port` : point de port, accent Abidjan orange et San Pedro vert ;
- `vessel` : observation navire demo-safe, bleu ;
- `density` : halo de densite, cyan ou ambre si elevé ;
- `disruption` : point alerte douanes/economie, orange-rouge seulement quand il y a un signal d'attention.

Cette separation suit le principe Worldmonitor : une couleur correspond a une famille de lecture. Orange ne signifie pas "maritime" ; orange signifie "attention economique/douanes". Bleu signifie flux maritime.

## Maritime Et Douanes

La couche maritime est volontairement `snapshot_demo_safe` tant qu'un provider AIS n'est pas configure. Elle contient :

- deux ports : `Port d'Abidjan` et `Port de San Pedro` ;
- une zone maritime suivie `Golfe de Guinee` pour rendre le domaine maritime lisible, meme sur fond sombre ;
- un corridor Golfe de Guinee, ainsi que des approches portuaires qui restent sur mer ou en rade ;
- des zones de densite : `Densite Abidjan / Vridi` et `Densite San Pedro` ;
- des disruptions demo-safe : fenetre douanes Abidjan et surveillance du corridor Golfe de Guinee ;
- des points de densite ou d'observation navires demonstratifs ;
- des statuts simples : `en route`, `a quai`, `congestion`, `inconnu`.

Elle ne promet pas un suivi live AIS et ne doit pas etre presentee comme un tracking individuel. Son objectif en demo est de montrer comment SENTINEL-CI croise economie, douanes, projets, presse et agenda dans une lecture gouvernementale.
La couche maritime ne doit jamais contenir de ligne inland type `port -> cabinet`. Ces liens appartiennent aux couches `Agenda`, `Actions` ou `Projets`; sinon l'utilisateur confond route maritime, instruction cabinet et trace d'analyse.

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

La carte soutient trois postures de demonstration, mais ces postures sont globales a SENTINEL-CI. Elles ne doivent pas devenir des onglets ou des niveaux meta dans le cadre cartographique lui-meme :

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
- en fond `Commandement`, la Cote d'Ivoire doit sortir du fond par son contour et son masque pays, tandis que la mer reste lisible sous les corridors ;
- fond `Administratif` lisible sans voile gris ni contraste lave ;
- le dezoom CEDEAO/Afrique/monde doit rester possible, sans rebond automatique vers la Cote d'Ivoire ;
- un changement de fond doit conserver la camera courante, notamment apres un dezoom monde ;
- aucun pitch ni bearing par defaut ;
- pays recadre proprement ;
- panneau de couches replie par defaut, ouvrable en un clic ;
- au zoom pays, les labels sont limites aux villes majeures et la zone prioritaire ;
- couche maritime desactivee par defaut mais activable en un clic ;
- `Maritime / douanes` affiche ports, corridor et points navires ;
- `Maritime / douanes` affiche une zone maritime translucide qui permet de voir immediatement ou se situe la mer ;
- `Maritime / douanes` ne partage pas la meme couleur ni la meme epaisseur que les lignes d'agenda/action ;
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
