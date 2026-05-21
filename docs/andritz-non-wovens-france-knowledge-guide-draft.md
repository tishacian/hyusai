# ANDRITZ NON-WOVENS France - Knowledge Guide

Statut : brouillon pret pour upload apres validation minimale

Target scope : `andritz_non_wovens_france_excel_pilot`

Target collection : `andritz-non-wovens-france-excel-pilot`

Objectif : aider Agentium a interpreter les classeurs d'essais non-tisses, sans transformer un fichier particulier en referentiel global.

Cette note est un contexte d'interpretation. Elle ne remplace jamais les documents sources. Lorsqu'une valeur est donnee, la reponse doit citer le classeur, la feuille et la ligne quand ces metadonnees sont disponibles.

## Principes d'interpretation

- Ne pas generaliser une valeur observee dans un classeur a tout le workspace.
- Ne pas transformer une table locale en referentiel transverse sans indication explicite.
- Ne pas inventer d'unite quand elle n'est pas explicitement portee par la feuille source.
- Distinguer parametres de reglage machine, mesures laboratoire, resultats client et commentaires operateur.
- Distinguer feuilles visibles et feuilles cachees quand l'information provient d'une feuille cachee.
- Quand plusieurs valeurs semblent possibles, repondre par source : classeur, feuille, ligne, contexte d'essai.

## Familles de contenus

Les classeurs non-tisses France peuvent contenir plusieurs types d'information :

- protocoles d'essais pilote ;
- resultats de laboratoire ;
- mesures de traction ;
- mesures MD/CD ou sens production/sens travers ;
- essais de dewatering, exprimage ou squeezing ;
- mesures d'emport ;
- donnees de grammage, epaisseur, permeabilite ou laize ;
- reglages machine : vitesse, pression, vide, temperature, belt/tapis, cardage, winder ;
- notes de production ou de rouleaux ;
- tables locales de correspondance entre labels et valeurs.

Ces familles peuvent coexister dans un meme classeur. Agentium doit eviter de melanger une mesure de resultat avec un parametre de configuration.

## Labels, diametres et tables de correspondance

Certains classeurs peuvent contenir une feuille de type `Def strips` ou une table similaire associant des labels (`A`, `B`, `C`, etc.) a des valeurs numeriques.

Regles :

- Une table label -> valeur doit etre consideree comme locale au classeur ou a l'essai, sauf indication explicite qu'elle est transverse.
- Le Knowledge Guide ne doit pas porter la table complete des valeurs : les valeurs doivent rester dans les documents sources.
- Si l'utilisateur demande "diametre B", "label B", "valeur B" ou "strip B", rechercher une table source citee, par exemple une feuille `Def strips`.
- Repondre avec la valeur trouvee uniquement si elle est presente dans la source.
- Si l'unite n'est pas visible dans la source, dire que l'unite n'est pas explicitee.
- Les labels vides ou absents ne doivent pas etre interpretes comme zero.
- Les labels composes ou atypiques ne doivent pas etre ramenes automatiquement a la sequence alphabetique simple.

Vocabulaire utile :

- diametre ;
- label ;
- code ;
- definition strip ;
- `Def strips` ;
- filet / mesh ;
- ouverture ;
- buse / jet ;
- slot / fente.

## Rouissage, roui et non roui

Dans les essais sur fibres naturelles, notamment chanvre ou lin, le terme `roui` renvoie generalement au rouissage : une preparation qui aide a separer les fibres de la tige en degradant partiellement les liants naturels comme les pectines.

Regles :

- `non roui` designe probablement une fibre n'ayant pas subi cette preparation.
- `roui` / `non roui` doit etre traite comme un attribut matiere ou preparation fibre, pas comme un resultat de test.
- Une fibre rouie ou non rouie peut influencer ouverture, cardage, formation de voile, liaison, dewatering, traction ou toucher.
- Les reponses doivent citer la feuille source quand elles utilisent ce statut.
- Ne pas comparer directement fibres rouies et non rouies si le protocole source n'est pas equivalent.

## MD, CD, sens production et sens travers

Interpretation usuelle :

- `MD` signifie souvent Machine Direction, le sens de marche de la nappe.
- `CD` signifie souvent Cross Direction, le sens travers.
- `sens production` est proche de MD dans de nombreux contextes.
- `sens travers` est proche de CD dans de nombreux contextes.

Regles :

- Conserver le terme source dans la reponse.
- Si un mapping MD/CD est ajoute, le presenter comme interpretation, sauf si la source le donne explicitement.

## Grammage, poids et masse surfacique

Termes proches :

- `gsm` ;
- `g/m2` ;
- `grammage` ;
- `poids` ;
- `basis weight` ;
- `masse surfacique`.

Regles :

- Ces termes renvoient generalement a la masse surfacique du non-tisse.
- Conserver l'unite source.
- Ne pas confondre valeur brute, moyenne, min, max, ecart-type ou CV.

## Traction, allongement et strips

Termes proches :

- resistance en traction ;
- tensile strength ;
- allongement ;
- elongation ;
- N/50 mm ;
- daN ;
- strip ;
- echantillon ;
- sens production ;
- sens travers.

Regles :

- `strip` peut designer une eprouvette d'essai dans un contexte laboratoire.
- `strip` peut aussi designer un code ou parametre de configuration dans d'autres feuilles.
- Utiliser le contexte de feuille et les en-tetes pour choisir l'interpretation.

## Dewatering, exprimage, squeezing et emport

Termes proches :

- dewatering ;
- pre-dewatering ;
- high dewatering ;
- exprimage ;
- squeezing ;
- squeezer ;
- vide / vacuum ;
- pression ;
- fente / slot ;
- mouillage ;
- humide ;
- sec ;
- emport.

Regles :

- Ces feuilles decrivent souvent l'elimination d'eau et les reglages associes.
- `emport` peut designer une quantite ou un ratio d'eau emportee/retenue ; la formule peut varier selon le classeur.
- Ne pas comparer des valeurs d'emport entre classeurs sans verifier la methode de calcul.

## Rouleaux, winder et progression process

Termes proches :

- roll ;
- rolls ;
- rouleau ;
- bobine ;
- winder ;
- baseweb roll ;
- avancee rouleau.

Regles :

- `roll` peut designer un rouleau produit, un rouleau d'entree, un lot envoye ou une progression le long d'un rouleau.
- `winder` est plutot un equipement ou point machine.
- `avancee rouleau` peut designer une evolution de mesure selon la position dans le rouleau.
- Ne pas fusionner ces usages sans contexte source.

## Reglages machine

Exemples de parametres de configuration :

- vitesse / speed / m/min ;
- pression / pressure / bar ;
- vide / vacuum / mbar ;
- belt type / tapis / courroie ;
- carding speed ;
- machine width ;
- dryer temperature ;
- pattern ;
- number of nozzles / buses ;
- fiber blend ratio.

Regle :

- Ces champs decrivent souvent comment l'essai a ete conduit.
- Ils ne doivent pas etre presentes comme des resultats qualite, sauf si la feuille les relie explicitement a un resultat.

## Guidance de retrieval

Pour les questions sur des labels ou diametres :

- chercher `Def strips`, `strip`, `label`, `diametre`, `filet`, `mesh`, `ouverture`, `buse`, `jet`, `slot`, `fente` ;
- ne pas utiliser une valeur de label provenant d'un autre classeur sans le dire ;
- si plusieurs valeurs sont trouvees, lister les valeurs par source.

Pour les questions sur les resultats d'essais :

- rechercher les en-tetes d'unite ;
- distinguer valeur brute, moyenne, minimum, maximum, ecart-type, CV ;
- citer la direction MD/CD ou sens production/sens travers.

Pour les questions sur le process :

- distinguer parametre machine, condition matiere et resultat mesure ;
- citer le protocole ou la feuille de resultats qui porte l'information.

## Termes d'expansion utiles

- diametre, label, code, definition strip, `Def strips`
- roui, non roui, rouissage, chanvre, lin, fibre naturelle
- MD, machine direction, sens production
- CD, cross direction, sens travers
- grammage, gsm, g/m2, masse surfacique, basis weight, poids
- traction, resistance, tensile strength, N/50 mm, daN
- allongement, elongation
- dewatering, exprimage, squeezing, squeezer, vide, vacuum, mbar
- pression, pressure, bar
- emport, humidite, sec, humide
- roll, rolls, rouleau, bobine, winder
- belt type, tapis, courroie
- vitesse, speed, m/min
- laize, width, machine width
- epaisseur, thickness, mm
