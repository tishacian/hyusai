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

## Couches

Chaque couche du panneau `Couches` correspond a un type de source Agentium. Le compteur indique le nombre d'elements visibles et le pourcentage indique la confiance operationnelle estimee.

- `Zones` : polygones territoriaux de vigilance, calcules a partir des scores workspace. Visible par defaut.
- `Presse` : signaux RSS et syntheses News Lab rattaches a des zones ou villes. Visible par defaut.
- `Projets` : projets sensibles, retards et risques de perception. Visible par defaut.
- `Visuel` : observations issues des flux visuels habilites. Visible par defaut.
- `Agenda` : fenetres d'action et contraintes issues de l'agenda ministeriel. Optionnel pour eviter la surcharge initiale.
- `Actions` : recommandations et actions cabinet proposees. Optionnel pour eviter de confondre observation et decision.

Desactiver une couche retire ses objets du rendu deck.gl correspondant. Les couches ne sont pas seulement decoratives. Par defaut, `Agenda` et `Actions` restent masques afin d'eviter de confondre observation et decision.

## Formes Et Couleurs

- Les contours cyan representent le perimetre territorial et les limites administratives simplifiees.
- Les polygones verts indiquent une zone stable ou nominale.
- Les polygones ambre indiquent une zone en vigilance elevee.
- Les polygones rouges sont reserves aux situations critiques.
- Les halos indiquent des points de concentration de signaux.
- Les arcs indiquent un lien d'action ou de coordination depuis Abidjan vers une zone.

Les zones sont des envelopes strategiques non chevauchantes superposees au territoire et au contour pays reel. Elles ne remplacent pas une reference administrative officielle ; elles servent a relier signaux, sources et decisions sans donner une precision trompeuse.

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
