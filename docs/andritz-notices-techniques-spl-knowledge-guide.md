# ANDRITZ Notices Techniques SPL - Knowledge Guide

Statut : brouillon pret a publier comme Knowledge Guide apres creation de la collection pilote.

Target scope : `andritz-spl-knowledge-experiment`

Target collection : `andritz-notices-techniques-spl-pilot`

Objectif : aider Agentium a lire les notices techniques SPL sans confondre reference projet, ligne, machine, equipement et piece.

Ce guide est un contexte d'interpretation. Il ne remplace jamais les notices sources. Les reponses doivent citer le projet, l'archive, le document interne et la page ou section quand ces metadonnees sont disponibles.

## Modele projet Andritz

Les references comme `BBA120`, `ACO140`, `DCI110`, `BIO100` ou `BHX100` sont des references projet stables.

- Les trois premieres lettres designent le premier buyer/client historique du projet.
- Le nombre indique la position ou phase dans la chaine du projet, par exemple `100`, `120`, `200`.
- Un projet correspond a un agencement de machines et equipements dans une ligne, pas a une machine unique.
- La reference projet reste stable meme si la ligne est revendue a un autre client.
- Ne pas interpreter automatiquement `BBA120` comme une machine. Les machines et equipements doivent etre identifies uniquement quand ils sont nommes dans la notice.

## Niveaux a distinguer

- Projet : reference stable de type `XXX123`.
- Ligne : ensemble industriel vendu, deplace ou revendu.
- Machine : machine nommee dans la notice.
- Equipement : injector, pump, damper, sensor, jetlace, winder, etc.
- Sous-ensemble : strip-carrier, jaw, cartridge, body, distribution chamber, O-ring seal, etc.
- Piece detachee : item de spare parts list ou annexe fournisseur.

## Familles de documents

Les archives `Notices_Techniques_SPL` peuvent contenir :

- operating manual ou user manual ;
- spare parts list ;
- annexes et certificats ;
- commissioning checklist ;
- maintenance ou service manual ;
- pages HTML de navigation ;
- images et schemas ;
- fichiers techniques non textuels.

Regles :

- Les PDF et documents bureautiques sont des sources documentaires primaires.
- Les pages HTML peuvent etre des menus ou tables des matieres ; ne pas les citer comme preuve procedurale si elles ne portent pas le contenu.
- Les images seules ne suffisent pas sans OCR ou texte associe.
- Les executables, bases locales, icones et fichiers systeme ne sont pas des sources de connaissance.

## Regles de reponse

- Citer la reference projet et le document source.
- Ne pas transferer une procedure d'un projet vers un autre sans source explicite.
- Ne pas generaliser une notice projet en regle gamme.
- Distinguer procedure, avertissement securite, liste de pieces et parametre machine.
- Si le proprietaire actuel de la ligne differe du premier buyer, conserver la reference projet historique.
- Quand plusieurs projets mentionnent le meme equipement, repondre par projet et par source.

## Vocabulaire utile

- project reference, buyer, first buyer, project position
- operating manual, user manual, service manual
- spare parts list, annex, declaration of conformity
- injector, prewetting injector, autoclamped injector
- strip, strip-carrier, cartridge, jaw, body
- O-ring, seal, nozzle, distribution chamber
- jetlace, pump, damper, sensor, winder

## Guidance retrieval

Pour une question sur un code `XXX123`, chercher d'abord ce code comme projet. Ensuite seulement identifier les equipements nommes dans les chunks retournes.

Pour une question procedurale, preferer les chunks avec `source_family = operating_manual`, `maintenance` ou `commissioning`.

Pour une question pieces detachees, preferer `source_family = spare_parts_list`.

Pour une question de securite ou conformite, preferer `source_family = safety`.

Pour Knowledge Capture, les notices servent de contexte documentaire. Une connaissance issue d'un expert doit rester une proposition relue par HITL avant integration.
