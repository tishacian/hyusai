# System Design — draft and publication / draft et publication

## FR — Retrouver la configuration à modifier

En tant que développeur, j’ouvre Conception pour lire le draft du System,
puis son Flow Builder pour préparer une modification. Je vois aussi la version
publiée qui continue de servir les utilisateurs. Une modification du draft ne
change pas les anciens Runs ni la publication.

Recette sur PIH, Showcase, 18741f94 : Conception indique draft r3 / version publiée
v1, trois nœuds et trois connexions. « Ouvrir le Flow builder » retrouve r3 et les
mêmes nœuds. Retour arrière conserve le System. Aucun bouton de publication n’a
été utilisé. Une lecture indisponible doit proposer une reprise, pas un pipeline
inventé. Les autorisations et l’opt-out existants restent applicables.

![Conception réelle — français](../evidence/release-18741f94-2026-09-17/pih-design-fr-light.png)

## EN — Find the configuration to change

As a developer, I open Design to inspect the System draft, then its Flow Builder
to prepare a change. The published version remains explicit: editing a draft
does not change earlier Runs or the version currently serving users.

Live PIH acceptance on 18741f94: Design shows draft r3 / published v1, three nodes
and three connections. “Open in flow builder” opens the same r3 and nodes. Back
returns to the same System. No publication was submitted. An unavailable draft
must show a retry rather than an invented pipeline. Existing access and explicit
feature opt-out remain enforced.

![Actual Design — English](../evidence/release-18741f94-2026-09-17/pih-design-en-dark.png)

[Qualification and remaining limits](../evidence/release-18741f94-2026-09-17/README.md):
new block translated, existing header partly English. The sticky header obstruction
is corrected on def0b3cc: the draft/publication summary is visible after scrolling
at 390×844. No whole-screen/mobile acceptance or R1 closure claimed.

![Actual narrow Design after correction](../evidence/release-def0b3cc-2026-09-17/pih-design-390.png)

## Accès direct au Flow — octobre 2026

Les cartes des systèmes portant un Flow enregistré proposent **Ouvrir le Flow**,
à côté de l'accès à leur fiche. Le même lien figure dans l'en-tête du système
et dans Conception ; il ouvre `/systems/:systemId/flow` dans la zone Créer.
Les cartes du chat transversal et les brouillons locaux ne proposent pas cet
accès à un graphe exécutable.

Dans le sommaire Créer, **Flow du système** ouvre le système vérifié dans le
workspace courant. Cette entrée est sélectionnée dans l'éditeur. En revenant à
une liste générale, **+ Nouveau flux** ouvre le brouillon libre. Pendant le
chargement d'un système, le lien attend sa résolution ; une ancienne sélection
ou un paramètre d'URL non vérifié ne choisit pas un autre flow.

La QA locale couvre les accès depuis la carte, l'en-tête au clavier et le
sommaire, en français sombre (1440 px), français clair (390 px) et anglais clair
(1440 px). Les API sont simulées et la navigation est vérifiée sans sauvegarde,
publication ni exécution. Le build frontend doit être déployé via le miroir
Bitbucket avant la recette sur `agentium.papai.ai`.
