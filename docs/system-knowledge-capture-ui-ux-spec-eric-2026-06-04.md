# Spec UI/UX - System Knowledge Capture

Date: 2026-06-04
Source: transcript de revue UI/UX avec Eric
Surface cible: Agentium / Andritz / System Knowledge Capture

Composants confrontes:
- `frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts`
- `frontend-ng/src/app/features/systems/system-view.component.ts`

## Perimetre Strict

Cette spec traite uniquement de **System Knowledge Capture**: preparer une capture, cadrer un plan, mener l'echange, relire le rapport et publier la connaissance.

Les sujets Chat Quick Ask, Deep Search, historique de conversations et workspace chat settings sont hors perimetre de ce document. Ils peuvent partager certains principes de lisibilite, mais ils ne doivent pas etre acceptes, testes ou priorises ici.

Quand le transcript parle de libelles vus dans le chat ou dans les settings generaux, ces remarques ne sont conservees ici que si elles impactent directement Knowledge Capture. Sinon elles sont classees hors perimetre.

## Objectif

Transformer la capture de connaissances en parcours utilisateur simple, lisible et actionnable. Le produit doit ressembler a une session de travail assistee:

1. preparer;
2. cadrer;
3. capturer;
4. relire;
5. publier.

Le socle fonctionnel existe deja largement dans `KnowledgeCaptureComponent`: sessions, modes, plan fourni, plan co-construit, capture vocale, questions IA, proposition editable, publication et export. Le probleme principal est la surface produit: trop de notions internes, trop d'etapes redondantes, trop de controles concurrents et une destination finale pas assez explicite.

## Principes UX

1. L'utilisateur ne doit pas connaitre l'architecture Agentium pour utiliser Capture.
2. Le libelle principal doit etre simple: "Capture d'information" ou "Capture de connaissances".
3. Un seul CTA primaire par etape, toujours au meme endroit.
4. Le CTA qui fait avancer le parcours s'appelle "Continuer", sauf action finale explicite comme "Publier".
5. L'artefact courant est la source de verite:
   - cadrage: le plan courant;
   - capture: le transcript reformule et le plan;
   - revue: le rapport final;
   - publication: destination + categorie + document final.
6. Les elements techniques restent accessibles en mode admin/dev, mais ne polluent pas l'experience demo/utilisateur.
7. Les questions IA se rafraichissent selon ce qui reste vraiment non resolu; elles ne s'empilent pas.
8. Le rapport final ne perd rien: ce qui ne rentre pas dans le plan est ajoute dans des sections additionnelles en fin de rapport.

## Constat Sur L'UI Actuelle

### Ce Qui Existe Deja

`KnowledgeCaptureComponent` contient deja les briques attendues:
- tableau de bord de sessions;
- creation de session;
- modes de capture;
- plan fourni, plan co-construit, conversation libre;
- champ de plan editable;
- assistant de cadrage;
- capture vocale;
- questions IA / oracle;
- rapport final editable;
- publication;
- export Markdown.

### Probleme Produit

Le transcript decrit une impression de cockpit technique:
- libelles internes: `System`, `Workbench`, `Knowledge`, `Trace`, `Runtime`;
- badges ou metriques qui ne guident pas l'utilisateur;
- preparation et mode de capture trop separes;
- ecran intermediaire qui annonce seulement que la capture est disponible;
- contexte/retrieval visible pendant la capture;
- labels vocaux techniques ou ambigus;
- revue qui ressemble a un panneau de controle plutot qu'a un document final;
- publication sans destination/categorie suffisamment claire.

## Evidence Transcript -> UI Actuelle -> Decision

| Commentaire Eric | UI actuelle observee | Decision produit |
| --- | --- | --- |
| "Capture console" / entree pas evidente | `system-view.component.ts:127-135` affiche `Capture console` dans l'ecran systeme | Renommer l'entree visible en "Capture d'information" ou "Capture de connaissances" |
| "Preserver le savoir terrain" trop marketing / pas assez direct | `knowledge-capture.component.ts:327-338` affiche `Capture expert` puis `Préserver le savoir terrain` | Titre direct: "Capture de connaissances"; pas de subtitle long en demo |
| "Revue humaine" ressemble a un badge interne | `knowledge-capture.component.ts:347-350` | Supprimer du header utilisateur; conserver seulement en audit/admin si utile |
| Ecran de depart trop vide et trop long | `knowledge-capture.component.ts:397-461` puis champs plus bas | Fusionner preparation + choix du mode; garder titre, duree, mode |
| "Sujet optionnel" inutile | `knowledge-capture.component.ts:419-435` | Supprimer en MVP; le titre + mode suffisent |
| Domaine/contexte avances encombrent | `knowledge-capture.component.ts:439-461`, puis advanced setup | Cacher en mode utilisateur; deplacer en admin/avance |
| Cartes dashboard affichent des metriques sans sens utilisateur | `knowledge-capture.component.ts:649-731`, notamment `faits` et `couverture` | Cartes: titre, statut simple, resume 2 lignes, derniere activite |
| Header de capture trop charge | `knowledge-capture.component.ts:786-826` | Header compact: titre, etape, temps, pause/reprise |
| Le contexte/retrieval n'est pas utile en capture | `knowledge-capture.component.ts:985-1022` affiche `Contexte retrouvé` meme en demo | Cacher en mode utilisateur; garder comme debug/admin |
| Les questions IA s'accumulent | `knowledge-capture.component.ts:953-983` affiche questions oracle sans actions | Modeler actions: repondre, fermer, plus tard; recalculer les actives |
| Labels vocaux techniques | `knowledge-capture.component.ts:3832-3844` affiche `Contexte en parallèle`, `Lecture IA`, `Évaluation` | Remplacer par etats utilisateur: `Ecoute en cours`, `Transcription`, `En pause` |
| "Terminer la capture" rompt le flow | `knowledge-capture.component.ts:1298-1307` | CTA de progression: "Continuer"; action technique reste secondaire si besoin |
| Plan builder ressemble a un fil de cadrage autonome | `knowledge-capture.component.ts:2052-2117` | Panneau "Modifier le plan"; instruction appliquee au plan courant; pas d'historique visible |
| Revue trop technique | `knowledge-capture.component.ts:2122-2287` affiche preuves, resume executif, points qualite, validation/publish ensemble | Surface "Relire le rapport": rapport editable + questions ouvertes + instruction de modification |
| Publication pas assez explicite | `knowledge-capture.component.ts:2230-2254` valide puis publie dans le meme aside | Ajouter une surface/panneau final "Publier" avec categorie + destination |

## Parcours Cible

### 1. Entree Et Navigation

Aujourd'hui:
- l'entree passe par `Systems`, puis `Capture console`;
- le header expose `System · Workbench`, `Knowledge · Capture`, `Trace & revue humaine`;
- ces termes sont utiles pour l'equipe produit, pas pour l'utilisateur final.

Decision:
- Renommer l'action en "Capture de connaissances" ou "Capture d'information".
- Dans un workspace Andritz demo/end-user, placer l'entree au niveau attendu par l'utilisateur, pas seulement dans un workbench systeme.
- Garder le routage system-scoped en interne.
- Masquer `System`, `Workbench`, `Runtime`, `Trace` dans la surface utilisateur.

Acceptance:
- Un utilisateur Andritz lance une capture sans connaitre `System`, `Workbench`, `Capability`, `Runtime` ou `Knowledge`.

### 2. Dashboard Sessions

Aujourd'hui:
- les cartes affichent titre, objectif, statut, metriques, auteur, couverture, faits;
- les statuts sont ambigus: `planifiée`, `active`, `à relire`, etc.;
- les "faits" et la "couverture" ne disent pas quelle session reprendre.

Decision:
- Statuts utilisateur:
  - `en cours`;
  - `terminée`;
  - `terminée avec questions ouvertes`.
- Chaque carte affiche:
  - titre;
  - statut;
  - resume 2 lignes de ce qui a ete discute;
  - derniere activite;
  - action principale: `Ouvrir` ou `Reprendre`.
- Les metriques techniques sont cachees en MVP.
- Les questions ouvertes peuvent apparaitre comme badge utile: `3 questions ouvertes`.

Contrat data:
- `session.summary_short?: string`;
- `session.open_questions_count?: number`;
- `session.last_activity`;
- `session.status` mappe vers statut utilisateur via fonction dediee, pas via `workflowStatusLabel` brut.

Acceptance:
- En ouvrant la liste, l'utilisateur sait immediatement quelle session reprendre et pourquoi.

### 3. Preparation Nouvelle Session

Aujourd'hui:
- titre: "Definir le sujet de capture";
- champ "Sujet optionnel";
- champ "Personne interrogee / Expert";
- duree;
- domaine et contexte avances;
- CTA "Choisir le mode de capture";
- choix du mode dans une logique separee.

Retour Eric:
- le champ sujet est redondant;
- le champ expert/personne n'est pas necessaire en MVP;
- l'ecran doit rester compact;
- le choix du mode doit etre dans la preparation;
- le CTA doit etre "Continuer".

Decision MVP:
- Champs visibles:
  - `Titre de session`;
  - `Durée estimée`;
  - `Mode de capture`.
- Modes visibles:
  - `Avec plan`;
  - `Sans plan`;
  - `Importer un plan`.
- Champs caches en avance/admin:
  - expert/personne;
  - domaine;
  - contexte;
  - collection/source technique.
- CTA primaire: `Continuer`.

Acceptance:
- La creation d'une session tient sur un seul ecran compact.
- Aucun champ visible n'est "optionnel" sans utilite claire.

### 4. Source De Plan

Aujourd'hui:
- le choix de mode et l'apport de texte/fichier sont separes;
- les breadcrumbs rendent le retour possible, mais le parcours reste peu naturel;
- l'utilisateur ne voit pas toujours ce que le systeme a compris du fichier ou du texte.

Decision:
- La surface "Plan de capture" accepte:
  - texte colle;
  - conversation brute;
  - fichier source unique;
  - plan tape a la main.
- Un seul fichier de plan source a la fois.
- Si un fichier est ajoute alors qu'un plan existe:
  - afficher une confirmation: "Ce fichier remplacera le plan courant. Continuer ?";
- Afficher:
  - nom du fichier source;
  - interpretation extraite;
  - plan editable.

Contrat data:
- `plan_source.kind: "manual" | "pasted_text" | "uploaded_file" | "conversation"`;
- `plan_source.filename?`;
- `plan_source.extracted_outline`;
- `plan_source.replaces_existing_plan: boolean`.

Acceptance:
- Le plan apparait sur la meme surface que la source et peut etre corrige sans changer d'ecran.

### 5. Construction / Edition Du Plan

Aujourd'hui:
- le plan est un textarea;
- le panneau droite s'appelle "Assistant de cadrage";
- un historique "Aucun échange pour l'instant" apparait;
- les boutons `Envoyer` et `Valider le plan` se concurrencent.

Retour Eric:
- le panneau doit etre une consigne de modification du plan;
- l'historique n'est pas utile;
- le plan courant est la source de verite;
- l'editeur doit aider l'indentation et les listes;
- le bouton d'avancement reste `Continuer`.

Decision:
- Layout:
  - gauche: plan courant editable;
  - droite: instructions text/voice pour modifier ce plan.
- Renommer:
  - `Assistant de cadrage` -> `Modifier le plan`;
  - placeholder -> `Indiquez quoi ajouter, déplacer ou reformuler...`;
  - `Envoyer` -> `Appliquer`;
  - `Valider le plan` -> `Continuer`.
- Supprimer l'historique visible.
- L'instruction applique un patch au plan courant, pas une conversation autonome.

P1:
- remplacer le textarea par un editeur de plan:
  - tabulation / desindentation;
  - listes Markdown;
  - reorder simple;
  - validation de niveaux.

Acceptance:
- L'utilisateur comprend que sa consigne modifie le plan visible.

### 6. Suppression De L'Ecran Intermediaire

Aujourd'hui:
- apres validation du plan, un ecran indique que la capture est disponible.

Retour Eric:
- cet ecran repete l'information et ralentit le parcours.

Decision:
- Supprimer l'ecran intermediaire.
- Apres `Continuer` sur le plan, aller directement a la capture.

Acceptance:
- Aucun ecran ne dit seulement que l'etape suivante est possible.

### 7. Capture Conversationnelle

Aujourd'hui:
- header volumineux avec statut, timer, progres, faits, scope, auteur;
- plan visible mais concurrence avec d'autres panneaux;
- contexte/retrieval visible;
- labels vocaux techniques;
- transcript encore organise en blocs/tours;
- `Terminer la capture` n'est pas coherent avec le CTA de progression.

Retour Eric:
- la capture doit etre prete a demarrer/ecouter;
- le plan doit rester visible et scrollable;
- le contexte/retrieval n'est pas utile pour l'utilisateur;
- le transcript doit etre un texte continu;
- le brut apparait au fil de l'eau, puis est remplace/ameliore par blocs de 3-5 lignes;
- pause/reprise doit etre clair;
- l'avancement vers la revue doit etre `Continuer`.

Decision:
- Layout cible:
  - gauche: plan scrollable + progression simple;
  - centre: transcript continu;
  - droite: questions IA utiles, ou panneau replie;
  - pas de contexte/retrieval visible en mode utilisateur.
- Header compact:
  - titre;
  - etape;
  - temps restant;
  - pause/reprise.
- Controls:
  - `Démarrer`;
  - `Pause`;
  - `Reprendre`;
  - `Ne plus poser de questions`;
  - `Continuer`.
- Libelles:
  - `Ecoute en cours`;
  - `Transcription`;
  - `Texte reformulé`;
  - `En pause`;
  - eviter `runtime`, `conversation armée`, `lecture IA`, `contexte en parallèle`.

Contrat transcript:
- `raw_segment`: texte live temporaire;
- `refined_segment`: bloc reformule validable;
- `segment.status: live | refined | amended`;
- l'UI affiche un flux continu, pas les evenements internes.

Acceptance:
- La capture ressemble a une prise de notes assistee, pas a un debugger de voice pipeline.

### 8. Questions IA / Oracle

Aujourd'hui:
- les questions apparaissent comme backlog interne;
- elles peuvent s'accumuler;
- elles n'ont pas d'actions utilisateur suffisantes;
- elles sont reprises en fin de session mais de facon trop cachee.

Retour Eric:
- les questions doivent se rafraichir;
- une question repondue dans la conversation doit disparaitre;
- l'utilisateur doit pouvoir ne plus recevoir de questions;
- chaque question doit pouvoir etre traitee maintenant, fermee, ou reportee.

Decision:
- Etats:
  - `active`;
  - `answered`;
  - `dismissed`;
  - `deferred`.
- Actions par question:
  - `Répondre`;
  - `Fermer`;
  - `Plus tard`.
- Action globale:
  - `Traiter les questions plus tard`;
  - ou `Ne plus poser de questions`.
- Recalculer les questions actives apres analyse du transcript.
- Afficher seulement les questions encore utiles.

Contrat data:
- `question.id`;
- `question.text`;
- `question.priority`;
- `question.status`;
- `question.related_plan_item_id?`;
- `question.resolution_reason?`.

Acceptance:
- Les questions aident la capture au lieu de devenir une liste anxiogene.

### 9. Revue / Rapport

Aujourd'hui:
- l'ecran affiche `Proposition Knowledge`;
- rapport editable;
- controle de revue;
- metriques rapport/preuves/relances/etat;
- resume executif;
- points qualite;
- boutons valider/publier/export/enregistrer/regenerer/reprendre.

Retour Eric:
- "Proposition" et le sous-texte sont inutiles;
- le rapport final doit etre structure selon le plan valide;
- le contenu hors plan va dans des sections additionnelles;
- le rapport doit etre editable;
- l'utilisateur doit pouvoir donner des instructions de modification;
- les questions ouvertes doivent etre visibles par importance;
- resume executif, preuves et metriques qualite ne sont pas utiles en MVP.

Decision:
- Renommer surface: `Relire le rapport`.
- Layout:
  - gauche: rapport final editable;
  - droite: questions ouvertes + instruction de modification;
  - bas droite: `Continuer`.
- Supprimer en MVP:
  - resume executif separe;
  - metriques preuves;
  - points qualite techniques;
  - `Régénérer` comme action principale.
- Ajouter:
  - champ/micro `Modifier le rapport`;
  - actions sur questions ouvertes;
  - questions non resolues integrees a la fin du rapport final.

Contrat rapport:
- sections alignees sur le plan valide;
- section finale `Points hors plan`;
- section finale `Questions ouvertes`;
- instructions appliquees au rapport courant.

Acceptance:
- L'utilisateur corrige le document qui sera publie, pas une synthese technique de controle.

### 10. Publication

Aujourd'hui:
- `Valider la proposition` et `Publier dans Knowledge` sont proches dans le meme aside;
- l'utilisateur ne voit pas assez clairement la destination/categorie.

Retour Eric:
- il faut afficher destination et categorie;
- la categorie peut etre technique, commerciale, innovation, etc.;
- la categorie est suggeree par l'IA et editable;
- la validation arrive avant publication;
- export/download reste disponible;
- retour arriere explicite.

Decision:
- Ajouter une surface ou un panneau final `Publier`.
- Champs:
  - categorie suggeree;
  - destination;
  - titre final;
  - resume de ce qui sera publie;
  - mention des questions non resolues incluses.
- Actions:
  - `Retour`;
  - `Télécharger`;
  - `Publier`.
- Categories initiales:
  - technique;
  - commercial;
  - innovation;
  - maintenance;
  - operation;
  - autre.

Contrat data:
- `publication.category`;
- `publication.destination_scope`;
- `publication.final_title`;
- `publication.include_unresolved_questions: true`;
- `publication.export_urls?`.

Acceptance:
- Avant publication, l'utilisateur sait ou part le document et peut corriger la destination.

## Architecture UI Cible

Surface nav cible:
- `Sessions`;
- `Préparer`;
- `Plan`;
- `Capture`;
- `Rapport`;
- `Publier`.

Regle:
- `Sessions` peut etre visible comme tableau de bord.
- Pendant une capture active, le parcours principal est lineaire.
- Les retours sont explicites (`Retour au plan`, `Retour au rapport`), pas seulement implicites via breadcrumbs.

Mode utilisateur:
- cache les diagnostics;
- cache les sources/retrieval;
- cache les badges systeme;
- cache les termes `Knowledge`, `Runtime`, `Trace`, `Workbench`.

Mode admin/dev:
- peut afficher details techniques dans un panneau `Avancé` replie.

## Plan D'Implementation

### Changements Frontend P0

`frontend-ng/src/app/features/systems/system-view.component.ts`
- Remplacer le libelle `Capture console` par `Capture de connaissances`.
- Remplacer le title `Open this system's dedicated capture UI` par un texte utilisateur.
- Garder la route `/systems/:systemId/capture`.

`frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts`
- Header:
  - remplacer `Capture expert` / `Préserver le savoir terrain` par `Capture de connaissances`;
  - supprimer le sous-texte long en demo;
  - cacher `Revue humaine`, `Trace & revue humaine`, `System · Workbench` en mode utilisateur.
- Type/navigation:
  - etendre `CaptureSurfaceView` avec `publish`;
  - remplacer `review` label par `Rapport`;
  - ajouter `Publier` dans `surfaceNav`;
  - mettre a jour `canNavigateTo`, `goSurface`, `stepIsComplete`.
- Preparation:
  - fusionner selection de mode dans l'ecran `prep`;
  - retirer `objective` visible et `expertProfile` visible en MVP;
  - deplacer domaine/contexte/source technique sous panneau `Avancé`;
  - normaliser `planModeActionLabel()` vers `Continuer`.
- Plan source:
  - afficher fichier source courant;
  - ajouter confirmation avant remplacement;
  - garder un seul fichier source actif.
- Plan builder:
  - remplacer `Assistant de cadrage` par `Modifier le plan`;
  - supprimer l'historique visible;
  - remplacer `Envoyer` par `Appliquer`;
  - remplacer `Valider le plan` par `Continuer`.
- Capture:
  - cacher `Contexte retrouvé` en mode demo/end-user;
  - reduire le header aux elements essentiels;
  - remplacer `Terminer la capture` par `Continuer`;
  - remplacer les labels `Lecture IA`, `Contexte en parallèle`, `Évaluation` par des etats utilisateur.
- Questions IA:
  - ajouter actions visibles `Répondre`, `Fermer`, `Plus tard`;
  - ajouter controle global `Ne plus poser de questions`;
  - ne montrer que les questions actives.
- Rapport:
  - renommer `Proposition Knowledge` en `Relire le rapport`;
  - supprimer les metriques `Preuves`, `Résumé exécutif`, `Points qualité` du MVP utilisateur;
  - ajouter instruction de modification du rapport courant;
  - `Continuer` ouvre la surface `Publier`.
- Publication:
  - creer le bloc `activeSurface() === 'publish'`;
  - afficher categorie, destination, titre final;
  - actions `Retour`, `Télécharger`, `Publier`;
  - `publishToKnowledge()` ne doit plus etre appele depuis le panneau de revue sans confirmation destination.

### Changements Backend/API P0

Les endpoints existants peuvent rester, mais le frontend a besoin de champs stables:
- session list:
  - `summary_short`;
  - `open_questions_count`;
  - `last_activity`;
  - statut lisible ou statut brut mappe cote UI.
- capture questions:
  - etat par question `active | answered | dismissed | deferred`;
  - endpoint ou action pour `dismiss/defer/answer`.
- proposal/report:
  - instruction de modification appliquee au rapport courant;
  - questions non resolues exposees avec priorite.
- publication:
  - categorie suggeree;
  - destination suggeree;
  - publication apres confirmation explicite.

Si les champs backend ne sont pas encore disponibles, P0 frontend peut demarrer avec adaptation locale, mais les contrats ci-dessus doivent etre ajoutes avant de qualifier le flow comme stable.

### Ordre De Livraison Recommande

1. Nettoyage libelles/header/navigation: faible risque, impact UX immediat.
2. Prep + mode fusionnes: retire une etape confuse sans toucher au backend lourd.
3. Plan builder: clarifie la relation instruction -> plan courant.
4. Capture: cacher debug, compacter header, CTA `Continuer`.
5. Rapport: renommer/simplifier, retirer metriques MVP.
6. Publication: ajouter surface finale et confirmation destination.
7. Questions IA: actions et etats, probablement le plus dependant backend.

### Risques Et Garde-Fous

- Risque: casser les usages admin en cachant trop de diagnostics.
  - Garde-fou: panneau `Avancé` replie, visible seulement admin/dev.
- Risque: `Continue` partout peut masquer une action irreversible.
  - Garde-fou: `Publier` reste le seul CTA final irreversible.
- Risque: questions IA sans backend d'etats deviennent cosmethiques.
  - Garde-fou: ne livrer actions question que si l'etat persiste.
- Risque: surface `publish` ajoutee cote UI sans contrat destination.
  - Garde-fou: afficher `destination a confirmer` et bloquer publication si inconnue.
- Risque: transcript continu demande de revoir le modele d'evenements.
  - Garde-fou: P0 peut garder les evenements existants mais changer leur presentation; P2 seulement pour le vrai modele raw/refined.

### Definition De "Ready To Build"

La spec est prete a passer en implementation quand ces choix sont confirmes:
- nom final de la feature: `Capture de connaissances` ou `Capture d'information`;
- categories de publication officielles;
- destination de publication exacte;
- visibilite admin des diagnostics;
- action attendue quand l'utilisateur clique `Continuer` depuis la capture:
  - generer directement le rapport;
  - ou ouvrir un etat de preparation du rapport.

## Backlog Priorise

### P0 - Nettoyage Du Parcours MVP

- Renommer l'entree `Capture console` en "Capture de connaissances" ou "Capture d'information".
- Remplacer le header "Préserver le savoir terrain" par un titre direct.
- Supprimer ou cacher les badges systeme dans le header utilisateur.
- Fusionner preparation + choix du mode.
- Supprimer `Sujet optionnel` et `Expert/personne interrogée` en MVP.
- Cacher domaine/contexte avances en mode utilisateur.
- Remplacer tous les CTAs d'avancement par `Continuer`.
- Supprimer l'ecran intermediaire apres validation du plan.
- Renommer `Assistant de cadrage` en `Modifier le plan`.
- Supprimer l'historique visible du plan builder.
- Cacher `Contexte retrouvé` / retrieval pendant la capture utilisateur.
- Compacter le header de capture.
- Afficher le plan scrollable pendant la capture.
- Mettre les questions IA dans un panneau utile, rafraichi, avec actions.
- Simplifier la revue: rapport + questions + modification.
- Ajouter une etape publication claire avec destination + categorie.

### P1 - Interaction Plan/Rapport

- Editeur de plan avec indentation et listes.
- Upload source unique avec avertissement de remplacement.
- Instruction text/voice appliquee au plan courant.
- Instruction text/voice appliquee au rapport courant.
- Classification de categorie de publication.
- Actions `Répondre / Fermer / Plus tard` sur chaque question IA.
- Resume 2 lignes automatique pour les cartes dashboard.
- Persistance fine des etats de questions oracle.

### P2 - Produit Durable Et Voice

- Transcript continu brut + reformule, sans exposer les tours internes.
- Amelioration qualite TTS/voix.
- Historisation durable des captures si le produit veut retrouver les sessions comme objets metier.
- Panneau admin `Avancé` pour diagnostics capture/retrieval/audit.
- Mockup Client 360 avant implementation, afin d'eviter le meme empilement de features.

## Besoins De Precision - "De Quoi Parle-T-On ?"

Ces points du transcript designent probablement des elements reels, mais il faut confirmer l'ecran exact avant implementation:

1. "Revue humaine":
   - Vu dans le header de `KnowledgeCaptureComponent`.
   - De quoi parle-t-on: doit-il disparaitre seulement du mode demo ou etre remplace partout par un statut plus explicite ?

2. "Interet", "runtime", "auteur":
   - Probablement badges/metadonnees du header de capture.
   - De quoi parle-t-on: quels badges restent utiles pour un admin ou un auditeur ?

3. "Capture disponible" repete plusieurs fois:
   - Probablement l'ecran intermediaire apres validation du plan.
   - De quoi parle-t-on: confirmer le screenshot/ecran exact pour suppression totale.

4. "La ligne deux fois":
   - Peut venir d'un plan dont section et sous-section ont le meme titre.
   - De quoi parle-t-on: faut-il corriger l'UI pour dedupliquer visuellement, ou corriger le generateur de plan ?

5. "La voix ne marche pas":
   - Peut etre un probleme runtime modele/transcription/TTS ou un probleme UI.
   - De quoi parle-t-on: reproduire avec logs voice session, navigateur, permissions micro, backend.

6. "Bouton valide grise":
   - Le transcript dit que l'ecran va changer drastiquement.
   - De quoi parle-t-on: ne pas traiter comme bug prioritaire sans screenshot/repro.

7. "Contexte":
   - Peut designer le panneau retrieval pendant capture ou le scope de preparation.
   - De quoi parle-t-on: en mode utilisateur, cacher retrieval; garder le scope seulement en admin/settings si necessaire.

8. Categories de publication:
   - Le transcript cite technique/commercial/innovation comme exemples.
   - De quoi parle-t-on: quelles categories Andritz sont officielles et lesquelles sont seulement des suggestions MVP ?

9. Destination de publication:
   - La publication doit montrer ou part le document.
   - De quoi parle-t-on: destination = collection Knowledge, scope systeme, categorie documentaire, ou combinaison des trois ?

## Tests D'Acceptation

- Un utilisateur lance une capture Andritz en moins de 2 clics depuis l'espace Andritz.
- La creation de session tient sur un seul ecran.
- Le mode de capture est choisi dans la preparation.
- Tous les boutons d'avancement s'appellent `Continuer`.
- Le plan est visible, editable et modifiable par instruction.
- L'upload d'un fichier source remplace le plan seulement apres confirmation.
- Aucun ecran intermediaire ne dit seulement que la capture est disponible.
- La capture affiche un plan scrollable et un transcript continu.
- Le panneau `Contexte retrouvé` n'apparait pas en mode utilisateur.
- Les questions IA se rafraichissent et peuvent etre fermees/reportees.
- La revue affiche le rapport final editable et les questions ouvertes.
- Les instructions de modification s'appliquent au rapport courant.
- La publication affiche categorie et destination avant envoi.
- Les questions non resolues sont incluses dans le document final.

## Non-Objectifs MVP

- Ne pas exposer un cockpit de debugging dans le parcours utilisateur.
- Ne pas refaire toute l'architecture backend de Knowledge Capture.
- Ne pas ajouter Client 360 avant une session de mockup dediee.
- Ne pas rendre tous les parametres workspace visibles dans l'ecran de capture.
- Ne pas traiter Chat Quick Ask, Deep Search ou l'historique chat dans cette spec.
