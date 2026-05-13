# SENTINEL-CI Cartographie Ministerielle

## Objectif

La carte SENTINEL-CI est une surface de decision, pas un SIG technique. Elle doit permettre a un utilisateur ministeriel de voir rapidement :

- les zones suivies en Cote d'Ivoire ;
- les signaux qui expliquent le score d'une zone ;
- les sources mobilisees : presse, projets, agenda, observations visuelles, actions cabinet ;
- les actions preventives proposees, toujours sous validation humaine.

La carte reste une primitive Agentium : elle est servie par le workspace, controlee par IAM, pilotable par VIGIE et auditee via les commandes carte.

## Fonds De Carte

Trois fonds sont exposes dans le selecteur `Fond` :

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

Source : geoBoundaries Global Database, jeu `gbOpen/CIV`, licence CC BY 4.0. Les zones strategiques Agentium sont des regroupements de districts ADM1 ; les limites regionales ADM2 restent visibles comme contexte administratif.

## Couches

Chaque couche du panneau `Couches` correspond a un type de source Agentium. Le compteur indique le nombre d'elements visibles et le pourcentage indique la confiance operationnelle estimee.

- `Zones` : partitions territoriales de vigilance, clippees dans le contour pays Cote d'Ivoire. Visible par defaut.
- `Presse` : signaux RSS et syntheses News Lab rattaches a des zones ou villes. Visible par defaut.
- `Projets` : projets sensibles, retards et risques de perception. Visible par defaut.
- `Visuel` : observations issues des flux visuels habilites. Visible par defaut.
- `Agenda` : fenetres d'action et contraintes issues de l'agenda ministeriel. Optionnel pour eviter la surcharge initiale.
- `Actions` : recommandations et actions cabinet proposees. Optionnel pour eviter de confondre observation et decision.

Desactiver une couche retire ses objets du rendu deck.gl correspondant. Les couches ne sont pas seulement decoratives. Par defaut, `Agenda` et `Actions` restent masques afin d'eviter de confondre observation et decision.

## Formes Et Couleurs

- Le contour pays suit le GeoJSON ADM0 versionne.
- Les limites internes fines suivent ADM2, visibles comme contexte administratif.
- Les zones de vigilance suivent des regroupements ADM1 : Nord, Ouest, Centre, Sud, Est.
- Les polygones verts indiquent une zone stable ou nominale.
- Les polygones ambre indiquent une zone en vigilance elevee.
- Les polygones rouges sont reserves aux situations critiques.
- Les halos indiquent des points de concentration de signaux.
- Les arcs indiquent un lien d'action ou de coordination depuis Abidjan vers une zone.

Le score, la couleur et les recommandations sont analytiques. La geometrie de base reste administrative et sourcee ; Agentium n'invente plus les frontieres de zones.

## Commandes VIGIE

VIGIE peut emettre des commandes carte provider-neutral :

- `focus_zone` : centrer une zone.
- `set_layers` : activer un sous-ensemble de couches.
- `set_basemap` : changer le fond.
- `reset_view` : revenir a la Cote d'Ivoire.
- `show_sources` : ouvrir la lecture des sources.
- `show_action_window` : afficher une fenetre d'action.

Chaque commande est auditee et reste advisory-only.

## Contraintes

- Aucune donnee Andritz ou autre workspace ne doit apparaitre dans SENTINEL-CI.
- Les couches sont workspace-scoped.
- Les donnees cartographiques publiques proviennent de sources OSM/CARTO en v1 ; une v2 peut self-hoster PMTiles/MBTiles.
- Les observations visuelles ne font pas de reconnaissance faciale, pas de suivi individuel et pas de biometrie.
