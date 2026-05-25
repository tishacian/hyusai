# SENTINEL-CI S3 — Content Polish Review

Date de lecture : 25 mai 2026  
Périmètre : Vagues 2.1 + 2.2, workspace `sentinel-ci`, branche `demo/agentic`

## Verdict global

**GO avec réserves avant patch.** Le scénario S3 est solide sur l'intention produit : 6 actions AYA, surfaces dédiées, drill réputation équilibré, OSINT live avec fallback demo-safe. Les réserves sont éditoriales, pas structurelles : fenêtre temporelle sociale incohérente, dérive 13h45/13h46 sur le démenti FANCI, quelques textes sans accents, quelques labels trop techniques pour une lecture COMEX, et un brouillon de communiqué trop court.

**Cible après patch contenu : GO contenu.** Les corrections proposées restent limitées aux fixtures, textes AYA, libellés UI et supports présentateur. Aucun refactor technique n'est nécessaire.

## Corrections appliquées localement

- P0 pulsation sociale : fenêtre renommée en séquence du jour, sentiments/engagements alignés, textes citoyens/rumeur rendus plus sobres.
- P0 rumeur Nord : chronologie standardisée à FANCI 13h46 puis Préfecture Nord 13h52, verdict DÉMENTI OFFICIEL harmonisé.
- P0 communiqué : brouillon S3.6 étendu en ton cabinet, avec FANCI, Préfecture Nord, CEDEAO et validation humaine.
- P1 OSINT/UI : labels ADS-B reformulés en traces advisory, accents rétablis, badges LIVE / CACHE BASELINE contextualisés.
- P1 supports : trame, walkthrough, cheat-sheet et deck markdown alignés sur une lecture COMEX sans commit hash ni jargon technique en S3.

## Lecture des commits locaux

Les derniers commits locaux ajoutent bien les deux vagues attendues :

| Zone | Commits concernés | Lecture contenu |
|---|---:|---|
| Surfaces S3 v2.1 | `61bb583e`, `18d3c43f`, `5f5b72a6` | Onglet Sécurité, Security Monitor, rail réputation et documents KB présents. Besoin de polish labels/accents et d'enlever le jargon resolver dans les supports. |
| OSINT live v2.2 | `0b358e4d`, `2cd79b22`, `09d10fdd`, `9791830f`, `298d8711` | Architecture demo-safe correcte : RSS whitelist, ADS-B baseline, indice CEDEAO, fallback cache. Les disclaimers sont présents mais doivent être plus lisibles pour un public non technique. |
| UI drawers S3 | `0c35673d`, `e23dd977`, `c9e1a24d`, `32824c13`, `14a934a4` | Les parcours sont complets. Les textes doivent éviter "trafic militaire" comme vérité opérationnelle et préférer "traces ADS-B advisory". |

## Tableau de polish

| Zone | Statut avant | Statut après cible | Problème | Correction proposée |
|---|---|---|---|---|
| Cohérence S1 → S2 → S3 | GO avec réserve | GO | La journée VP est cohérente, mais les supports gardent quelques traces de jargon technique et des heures divergentes. | Réancrer S3 après S2.7, avant Conseil Défense 15h00 ; standardiser le démenti FANCI à 13h46 ; retirer commit hash/action ids des passages présentateur. |
| Pulsation sociale | P0 contenu | GO | `dernière heure` contredit les tweets 07h25-13h58 ; totaux sentiment/engagement non alignés ; quelques textes peu naturels à l'oral. | Renommer la fenêtre en séquence journée VP ; aligner sentiments/engagements ; rendre les tweets citoyens/rumeur plus sobres et pseudonymisés. |
| Théâtre Sahel / ADS-B | P1 | GO | Disclaimer présent, mais "trafic militaire" peut être lu comme confirmation opérationnelle. | Utiliser "traces aériennes advisory" et "snapshot ADS-B" ; garder "aucune donnée classifiée" visible ; corriger les fallback labels. |
| Rumeur frontière Nord | P0 contenu | GO | Verdict visible, mais 13h45/13h46 varie selon les surfaces ; accents et CTA à polir. | Chaîne unique : tweet 11h42 → Telegram 12h08 → blog 12h48 → démenti FANCI 13h46 → Préfecture 13h52 ; CTA "Préparer un communiqué". |
| Réputation 2+/1- | GO | GO | Score 72/100 crédible ; risque léger de ton trop promotionnel sur l'item Jeune Afrique. | Conserver 2 positifs + 1 critique ; reformuler en "lecture favorable" plutôt que "gestion souveraine saluée" si affiché. |
| Communiqué S3.6 | P0 contenu | GO | Fallback trop court pour une prise de parole cabinet ; pas assez explicite sur validation humaine. | Brouillon 150-200 mots, ton souverain, FANCI + Préfecture Nord + coordination CEDEAO, advisory soumis à validation. |
| Réponses AYA | P1 | GO | Certaines réponses sont longues ou trop techniques ("dual-axis", "snapshot") pour une lecture VP. | Réponses 2-3 phrases max, adresse constante "Monsieur le Vice-Président", effet écran explicite dans les supports. |
| UI labels & disclaimers | P1 | GO | Accents manquants ; quelques libellés anglais ou techniques ; "CACHE BASELINE" à contextualiser. | Garder les badges LIVE / CACHE BASELINE mais ajouter un wording clair : "baseline démo", "sources publiques", "advisory only". |
| Trame & deck | P1 | GO | Les supports S3 contiennent encore action ids, last_focus, resolver, et la phrase S3.6 varie. | Version COMEX : phrase à dire, réponse attendue, effet écran, plan B clic. Pas de hash ni jargon technique. |
| KB markdown | GO avec réserve | GO | Contenu sûr et cohérent, mais manque d'accents et quelques formulations "military" trop brutes. | Harmoniser les titres, limites OSINT, et rappeler que le contenu ne vaut pas confirmation opérationnelle. |

## Phrases AYA finales

| # | Phrase à dire | Réponse vocale AYA polishée | Effet écran attendu |
|---:|---|---|---|
| S3.1 | `AYA, montre-moi la posture sécuritaire du jour.` | Monsieur le Vice-Président, la posture du jour est en vigilance intérieure et élevée sur l'axe Sahel. La rumeur frontière Nord est démentie, les postes restent nominaux, et je prépare la lecture pour le Conseil Défense de 15h00. | Bloc Posture sécuritaire mis en avant dans le cockpit. |
| S3.2 | `AYA, montre la pulsation sociale à Abidjan.` | Monsieur le Vice-Président, j'affiche 18 signaux publics sur la séquence du jour : canaux vérifiés, citoyens pseudonymisés et rumeurs suivies. Le volume reste maîtrisé après les démentis officiels. | Couche sociale activée + drawer tweets Abidjan. |
| S3.3 | `AYA, d'où vient la rumeur frontière Nord ?` | Monsieur le Vice-Président, la rumeur part d'un tweet citoyen à 11h42, puis circule via Telegram et un blog avant le démenti FANCI de 13h46. La Préfecture Nord confirme à 13h52 ; je peux préparer le communiqué. | Timeline rumeur avec verdict DÉMENTI OFFICIEL. |
| S3.4 | `AYA, montre les mouvements de troupes au Sahel.` | Monsieur le Vice-Président, j'affiche uniquement un snapshot ADS-B advisory : 10 traces publiques sur Bamako, Ouagadougou, Niamey et Abidjan. Aucun élément affiché ne constitue une donnée classifiée ni une confirmation opérationnelle. | Drawer théâtre Sahel + couches ADS-B advisory. |
| S3.5 | `AYA, montre le drill de réputation 2 positifs et 1 critique.` | Monsieur le Vice-Président, le score réputation est à 72 sur 100 cette semaine. Deux lectures sont favorables, sur la gestion Nord et la réponse Nawa ; la critique à surveiller porte sur le budget défense. | Vue Réputation avec 3 cartes presse. |
| S3.6 | `AYA, prépare un communiqué de sécurité sur la rumeur Nord.` | Monsieur le Vice-Président, je prépare un brouillon cabinet qui cite le démenti FANCI, la mise au point de la Préfecture Nord et la coordination CEDEAO. Le texte reste advisory et devra être validé avant diffusion. | Drawer brouillon communiqué, validation humaine. |
| S3.3 bis | `AYA, trace la rumeur frontière Nord.` | Monsieur le Vice-Président, je remonte la chaîne publique et j'isole les relais non vérifiés. Le verdict officiel est déjà visible pour éviter toute ambiguïté en salle. | Timeline rumeur ouverte directement. |
| S3.4 bis | `AYA, montre l'activité aérienne Sahel.` | Monsieur le Vice-Président, voici la lecture ADS-B advisory du théâtre Sahel. Elle sert à contextualiser la posture, pas à confirmer des mouvements militaires. | Carte Sahel + drawer ADS-B advisory. |
| S3.5 bis | `AYA, montre le détail réputation.` | Monsieur le Vice-Président, j'ouvre le détail 2 positifs et 1 critique. Les sources sont séparées pour garder une lecture équilibrée, sans gommer le point budgétaire. | Rail réputation détaillé. |
| S3.6 bis | `AYA, rédige le communiqué démentant la rumeur Nord.` | Monsieur le Vice-Président, je rédige une version sobre, factuelle et validable. Elle ne promet aucune action opérationnelle et renvoie vers les canaux publics compétents. | Drawer communiqué prêt à valider. |

## Checklist démo-safe

- Même journée partout : lundi 25 mai 2026, Abidjan.
- S3 placé après la décision Nawa S2.7 et avant le Conseil Défense restreint de 15h00.
- Aucun nom réel de citoyen ou relais rumeur ; handles pseudonymisés.
- Rumeur frontière Nord alarmiste mais non diffamatoire, sans cible personnelle.
- Verdict DÉMENTI OFFICIEL visible dès l'ouverture de la timeline.
- ADS-B toujours "advisory only", sans donnée classifiée ni confirmation de mouvement de troupes.
- Réputation équilibrée : deux lectures favorables, une critique budgétaire, score 72/100.
- Communiqué S3.6 soumis à validation humaine, ton cabinet souverain, pas de promesse opérationnelle.
- Supports présentateur sans commit hash, resolver, action id ou jargon dev.
- Badges LIVE / CACHE BASELINE compréhensibles comme mode de démonstration reproductible.
