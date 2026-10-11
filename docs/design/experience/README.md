# Experience — mockups UI/UX (Paper)

Maquettes du concept `Experience` (affiché « Application métier ») : la projection métier publiée d'un ou plusieurs Systems. Produites dans Paper, inspirées de références Refero (Retool, FlutterFlow, Manus, Lovable, Squarespace, Doppler).

## Mental model

- Le modèle interne reste **System-centric** (`System → Capability → Skill → Knowledge → Flow`).
- L'utilisateur métier vit dans un monde **Application-centric** : `/work/:appSlug`, zéro jargon interne.
- Le pont entre les deux : `SystemBinding` — une clé stable (`expenses.submit`) verrouillée sur une version publiée d'un Flow et son contrat (schémas + hashes).
- Publication : `Brouillon → Vérifications → Release immuable → Pilote → En service`, rollback atomique.

## Parcours couverts

| # | Fichier | Écran | Rôle dans le parcours |
|---|---------|-------|----------------------|
| 01 | `01-mes-applications-work.png` | Mes applications (`/work`) | Lanceur business — ce que voit l'utilisateur final |
| 02 | `02-studio-editeur.png` | Studio · Éditeur d'application | No-code : arbre pages, preview, inspecteur Action (binding) |
| 03 | `03-system-home-generee.png` | System Home générée | Page d'usage auto-générée à la publication d'un Flow |
| 04 | `04-studio-creer-hub.png` | Studio · Créer (hub) | Entrée « Créer » orientée intention : Application / System / Knowledge + Bibliothèque avancée + schéma d'articulation |
| 05 | `05-studio-applications-metier.png` | Studio · Applications métier | Inventaire (états, releases, audiences) + bandeau cycle de vie |
| 06 | `06-nouvelle-app-etape1-modele.png` | Nouvelle application · Étape 1 | Choix du modèle (6 patterns + départ depuis une System Home) |
| 07 | `07-nouvelle-app-etape2-liaisons.png` | Nouvelle application · Étape 2 | Relier les actions aux Systems publiés (SystemBinding lisible) |
| 08 | `08-publier-release.png` | Publier · Release | Ready-check, contenu verrouillé, déploiement Pilote/En service |

## Décisions de design clés

- **Deux espaces, un produit** : `/work` (clair, sans jargon) vs Studio (sombre, technique) — reliés par « Modifier dans le Studio » / « Voir l'application ».
- **Flow Builder** relégué en facette d'un System ; scratchpad accessible via ⌘K uniquement.
- **Liaison lisible** : « Appelle / Entrées / Confirmation / Après succès / Si indisponible » — le JSON, les versions et les hashes restent sous « Avancé ».
- **Seules les versions publiées** sont proposées au binding ; la mise à jour d'un System dans une app est une action explicite.
- **La release verrouille tout** : pages, liaisons (versions + hashes), accès, langues, thème, version du renderer certifié.
