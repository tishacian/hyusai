# CR — Cadrage vidéo démo Agentium (scénario "effet wow")

_Compte-rendu structuré du meeting de cadrage de la vidéo démo. But : servir de
script/storyboard partageable pour la production de la vidéo, et de brief pour
l'équipe technique sur ce qui doit exister/être présentable._

---

## 1. Objectif

Produire **une vidéo démo** qui présente Agentium en deux volets complémentaires :

| Volet | Nom | Rôle |
| --- | --- | --- |
| 1 | **Hyperviseur** | Interface "Level" accessible aux décideurs. Comprendre où en est l'organisation et où elle se dirige. Visualisation + pilotage. |
| 2 | **Agent Factory** | Les "coulisses" : comment on connecte les données, capture la connaissance, et construit les agents/systèmes qui font tourner l'hyperviseur. |

Note de méthode (rappelée en meeting) : certains écrans décrits sont une
**"liste au Père Noël"** — un mix de fonctionnalités déjà existantes et
d'éléments à construire/habiller pour la démo. À trier avant script final avec
la dev.

Contrainte de narration : la vidéo doit inclure une **voix off/guidage** à
chaque transition d'écran, car un spectateur qui découvre l'outil pour la
première fois (prospect qui ne fait que regarder la vidéo, sans être guidé en
live) a besoin de repères pour comprendre ce qu'il voit.

---

## 2. Volet 1 — Hyperviseur

### 2.1 Étape 0 — Login

- Écran de login classique, pas d'effet spécial recherché ici.
- **Laïus oral** à caler dessus : sécurité des accès, gestion fine des
  autorisations (plusieurs niveaux d'accès possibles selon data / modules /
  panneaux, etc.).

### 2.2 Étape 1 — Dashboard à la connexion

Premier écran vu après connexion : un tableau de bord "état de l'organisation
à l'instant T", combinant plusieurs types de visualisation sur un même écran :

- Une **carte** (map).
- Une **time series temps réel** (qui bouge, animée).
- Des **KPI** avec :
  - la valeur actuelle,
  - un **mini-graphique d'historique associé** (type "sparkline" à la Google
    Analytics/Stripe) montrant l'évolution récente,
  - un indicateur de tendance (hausse/baisse) avec **code couleur** — attention :
    la couleur "positive/négative" ne doit pas être câblée bêtement sur
    hausse=vert/baisse=rouge, il faut réfléchir métrique par métrique (une
    baisse peut être une bonne nouvelle selon le KPI).
- Pour certains KPI : une **projection/prédiction** (valeur actuelle vs valeur
  prédite en fin d'année, ou courbe sur 12 mois passés + 12 mois projetés),
  éventuellement avec un **indice de confiance**.

But de l'écran : montrer la diversité de visualisation disponible et donner
l'impression d'un vrai centre de pilotage, pas juste un dashboard statique.

### 2.3 Étape 2 — Création d'un KPI custom en langage naturel (effet wow #1)

Démonstration que l'hyperviseur n'est pas un dashboard figé :

1. L'utilisateur demande, en langage naturel, la création d'un **KPI
   volontairement exotique** (ex. "ratio nombre d'utilisateurs / coût cloud") —
   volontairement non-standard pour bien montrer que ce n'est pas un KPI
   natif pré-câblé (un "taux de marge" serait trop générique/déjà présent
   dans un bilan).
2. Idéalement, le système répond en mode conversationnel : propose les
   données d'entrée trouvées, pose des questions de clarification, demande
   validation à l'utilisateur avant de créer le KPI.
3. Au moment de la création, cases à cocher pour choisir :
   - vue instantanée simple vs. **graphique d'évolution**,
   - avec ou sans **prédiction** (pas systématique — certains KPI n'ont pas
     d'intérêt à être prédits).

Message clé : l'utilisateur construit lui-même le tableau de bord "le plus
sexy possible" avec les briques qu'il veut.

### 2.4 Note de positionnement

L'hyperviseur (tel que décrit ci-dessus) reste de la **visualisation + un peu
de prédiction**, pas de l'action autonome comme le ferait un agent IA. Bien
distinguer ce narratif de celui du volet Agent Factory.

---

## 3. Volet 2 — Agent Factory

### 3.1 Étape 0 — Mise en situation abstraite

Avant de rentrer dans l'outil : montrer un **schéma d'une organisation client
abstraite** (pas un vrai client nommé) — "telle base de données, tel
repository PDF, tel repository d'images…". Support hors-outil (slide/schéma)
qui pose le contexte avant de basculer sur les connecteurs réels.

### 3.2 Étape 1 — Connecteurs (preuve d'accès réel aux données)

Séquence proposée :

1. Montrer la **liste des connecteurs existants** (souligner la diversité :
   pas que du Postgres/SQL classique, aussi des sources non structurées —
   fichiers, WhatsApp, etc. — sans forcément tout démontrer).
2. **Créer une connexion en direct** (ex. connecteur SFTP), pas trop long.
3. Naviguer dans les données une fois connecté (illustration : SFTP Andritz).
4. **Ouvrir un fichier concret** (ex. un PDF avec une image mémorable/repérable)
   directement depuis le connecteur → preuve d'accès réel, pas de la donnée
   factice.
5. Ouvrir **le même fichier**, mais cette fois **depuis le chat Agentium**
   (cité comme source) → boucle de preuve : "ce que je viens de montrer en
   brut dans le connecteur est bien ce qui a été interprété/ingéré par
   Agentium".

But : au moins **une source connectée et démontrée en live** pendant la démo,
avec mention qu'il en existe d'autres (diversité de connecteurs) sans devoir
toutes les montrer.

### 3.3 Étape 2 — RAG transverse multi-documents (effet wow #2)

Use case : des centaines/milliers de documents de plusieurs centaines de
pages chacun ; la réponse à une question n'est **pas dans un seul document**
mais nécessite de **combiner des informations éparpillées** dans plusieurs
documents.

- Exemple filmé : question transverse type inventaire sur >100 000 documents
  ("quels sont les projets qui utilisent des pompes Huraka ?") → réponse
  exhaustive avec **liste de projets + sources citées** (PDF ouvrables et
  vérifiables à chaque citation).
- Enchaîner avec une **question de suivi qui garde le contexte de session**
  (ex. "durée de vie moyenne des pompes les plus utilisées") pour montrer la
  mémoire conversationnelle.
- Cas encore plus fort à construire si possible : **combiner une source PDF
  avec une source non-PDF** (ex. base de données d'incidents/pannes de
  maintenance) dans la même réponse → identifié en meeting comme **le vrai
  effet wow** de ce segment.
- À anonymiser/généraliser (ne pas garder l'exemple Andritz brut tel quel
  pour un prospect externe).

### 3.4 Étape 3 — Capture de connaissance vocale (effet wow #3 — le plus fort)

C'est la démonstration jugée en meeting comme **la plus différenciante** :
"notre mérite n'est pas le speech-to-text (on utilise Whisper, rien
d'inventé) — notre mérite est l'orchestration : base de connaissance + RAG +
multi-threading de questions sans interrompre l'expert + gestion de pièces
jointes annotées + synthèse + publication."

Séquence à filmer :

1. L'utilisateur (jouant le rôle d'un **expert qui transmet son savoir**)
   parle au micro ; la transcription apparaît en temps réel (thread 1 :
   speech-to-text).
2. En parallèle (thread 2), le système **génère des questions de clarification**
   à partir de la base de connaissance existante (RAG sur les documents déjà
   indexés) pour aider l'expert à préciser son propos — sans l'interrompre.
   - Effet bonus recherché : si l'oracle détecte une **incohérence** entre ce
     que dit l'expert et la documentation existante (ex. un diamètre
     différent), il peut le signaler.
3. L'expert peut **charger une pièce jointe en direct** (ex. une notice PDF)
   et **naviguer dedans pendant qu'il parle** — le système **marque/annote**
   dans le transcript la page présentée à l'instant où elle est commentée.
4. À la fin de la session : génération d'un **rapport de synthèse** qui
   inclut les informations extraites des pages annotées (transcrites en
   texte).
5. Les **questions ouvertes non répondues** peuvent être :
   - réassignées à un autre expert, ou
   - répondues directement par l'utilisateur avant publication.
6. **Publication vers la base de connaissances partagée** → ré-indexation
   immédiate, disponible pour tout autre utilisateur qui chatterait sur le
   sujet.

Narratif ROI à associer à l'oral : cas d'un **expert qui part à la retraite**
— capture de sa connaissance non documentée, disponible immédiatement pour un
nouvel arrivant/stagiaire "comme s'il était dans le cerveau de l'expert".
Lien direct avec le besoin PIH exprimé sur le service desk (gains
onboarding/offboarding).

Suggestion de montage : mixer la démo vocale avec ce cas d'usage plutôt que
de la présenter isolée ("je peux parler" sans contexte).

### 3.5 Étape 4 — Construction d'agents / Flow Builder (effet wow #4)

Contexte cadrage PIH : dans l'appel d'offres, un "agent" = **un use case**
(≈ 400 use cases attendus côté PIH ↔ appelés "systèmes" côté Agentium). Un
système/use case peut être composé de plusieurs agents/briques atomiques.

Points à démontrer :

1. **Connexion à une source moins conventionnelle** que du SQL classique
   (ex. SAP / SAP HANA — connecteur en cours de livraison, cible mardi 21).
2. Montrer un **flow réellement complexe** ("spaghetti"), pas un pipeline
   linéaire à 3 boîtes — pour prouver la **résistance au monde réel**, qui
   n'est jamais linéaire.
   - Exemple de structure : le flow représente en réalité **le
     comportement du chat** avec plusieurs branches selon le type de requête
     (ex. question triviale → réponse directe courte-circuitée, sans lancer
     une recherche profonde inutile ; requête complexe → recherche approfondie
     avec connecteurs SAP/documentaire/images, etc.).
   - Message clé : pour l'utilisateur final, tout ça reste **un simple chat**
     — mais la démo révèle la complexité orchestrée en dessous, "factorisée"
     par la plateforme.
3. Montrer les capacités de gouvernance/observabilité du flow :
   - **auto-évaluation** (prompts d'évaluation, guides de confiance...),
   - **versioning** (ex. v18 vs v13, **rollback**, **preview** d'une version
     antérieure) → répond directement aux besoins PIH de replay/monitoring/
     maintenance.
   - **Skills packagées et réutilisables** entre workflows (ex. une skill
     SharePoint déjà configurée est réutilisable dans un autre système sans
     refaire le travail).

Message de conception à faire passer : privilégier des **agents/skills
atomiques et factorisés** plutôt qu'un agent monolithique qui fait tout — et
souligner la synergie avec le process delivery (design cards / templates de
prise de besoin côté centre d'excellence, qui pré-dessinent les skills avec
le client avant l'implémentation).

---

## 4. Effets "wow" — classement pour priorisation production

1. **Capture de connaissance vocale** (§3.4) — jugé le plus fort en meeting,
   car il illustre un vrai mérite produit (orchestration), pas juste un
   modèle tiers.
2. **RAG combinant plusieurs sources hétérogènes** (PDF + base non-PDF) dans
   une même réponse (§3.3).
3. **Création de KPI custom en langage naturel** sur l'hyperviseur (§2.3).
4. **Flow complexe non-linéaire + versioning/rollback** (§3.5).

---

## 5. Portée de la démo (ce qui est explicitement hors scope pour cette vidéo)

- Le meeting acte que le scope décrit ci-dessus est **suffisant pour une
  première vidéo à partager**. Le reste (approfondissements, nouveaux
  connecteurs, cas d'usage additionnels) sera traité lors de futurs meetings,
  une fois le scope, la discovery et le budget calés avec le prospect/client
  concerné.
- Les écrans "liste au Père Noël" (predictions par KPI, indices de confiance,
  etc.) sont à confirmer techniquement avant de les scripter fermement.

---

## 6. Actions

| Action | Porteur | Échéance |
| --- | --- | --- |
| Livrer le connecteur SAP HANA (ou équivalent) | — | Mardi 21 (semaine du meeting) |
| Trier la liste "Père Noël" hyperviseur avec la dev (ce qui existe vs. à construire pour la démo) | — | Avant script final |
| Construire/valider l'exemple combinant PDF + source non-PDF (incidents/pannes) pour le RAG multi-sources | — | Avant tournage §3.3 |
| Anonymiser/généraliser les exemples Andritz utilisés dans la démo | — | Avant tournage |
| Arranger un flow "spaghetti" représentatif pour l'écran Flow Builder | — | Avant tournage §3.5 |
| Rédiger le script de voix off/guidage à chaque transition d'écran | — | Avant montage |

---

## 7. Sujet annexe — Prospect Qatar (UDC, quartier La Perle)

- Contact facilitateur : le directeur innovation d'un opérateur télécom déjà
  rencontré (meeting antérieur), positionné non pas pour vendre à l'opérateur
  mais pour introduire auprès de ses propres clients — dont **UDC** (en charge
  du quartier La Perle) est une des pistes identifiées.
- Un **pré-meeting/"répétition"** est proposé le lendemain avec ce
  facilitateur : objectif = recueillir son feedback sur le pitch avant le
  vrai rendez-vous avec l'interlocuteur UDC, et éventuellement sonder des
  centres d'intérêt spécifiques (ex. cas d'usage parking, etc.).
- Format retenu : laisser le facilitateur exprimer d'abord les besoins/le
  contexte client, sans empêcher de montrer en complément des aspects de la
  plateforme pertinents.
- Point de vigilance stratégique : discussions en cours avec **PIH** sur un
  contrat global/exclusivité — rester prudent avec UDC pour ne pas créer de
  contradiction tant que rien n'est signé avec PIH.
- Créneau proposé au facilitateur : **13h ou 14h** (contrainte Andritz/SGP le
  matin côté équipe ; dispo après la pause déjeuner).
- Rendez-vous confirmé séparément à 14h avec un autre contact (Zach /
  propale) — sujet distinct, à ne pas confondre avec le point UDC.
