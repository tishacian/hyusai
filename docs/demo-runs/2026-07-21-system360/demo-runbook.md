# Agentium — déroulé de démo System 360

Production gelée et testée sur `cfa3f616050bb5f75c9a3709219b52939e7ec0bd`. Ne déployer aucun changement pendant la démo.

## Préparation immédiate

- Garder la session authentifiée et le System canari Showcase déjà ouvert ; ne saisir aucun ID ou slug à la main.
- Ouvrir un second onglet sur Hypervisor et un troisième sur Andritz.
- Vérifier rapidement les captures du dossier [`screenshots/`](screenshots/) et les garder accessibles localement.
- Si une donnée manque, dire « non mesuré » ou « non configuré » ; ne jamais la transformer en zéro.

## Démo principale — 8 à 10 minutes

| Temps | Action | Message à faire passer |
|---|---|---|
| 0:00–0:45 | Partir du même System Showcase | « Un objet métier, quatre perspectives ; l'identité ne change jamais. » |
| 0:45–2:00 | Ouvrir **Build** | Montrer objectif, Capability, flow, Skills, Context et configuration effective. |
| 2:00–3:15 | Passer à **Operate** | Montrer Runs, santé, latence/coût/erreurs et tâches ou HITL réellement disponibles. |
| 3:15–4:30 | Passer à **Steer** | Montrer outcomes, décisions, policies et simulation ; distinguer explicitement simulation et mesure. |
| 4:30–5:45 | Passer à **Govern** | Montrer actions autorisées par le resolver, contraintes Membrane, audit et versions. |
| 5:45–6:45 | Utiliser retour/avance puis recharger | Faire constater que System, header, breadcrumb et facette restent invariants. Hypervisor reste le home Portfolio, pas une lens objet. |
| 6:45–8:00 | Basculer vers Andritz | Montrer les trois applications historiques **plus FSE**, soit quatre applications intentionnelles, sans changement de leurs APIs. |
| 8:00–9:15 | Montrer Sentinel puis Octocity | Souligner l'isolation du branding, des action packs et l'absence de termes croisés. |
| 9:15–10:00 | Revenir au System canari | Résumer : construire, opérer, piloter et gouverner le même System sans perdre le contexte. |

## Mode secours — 90 secondes

Annoncer clairement que les images sont les captures du SHA testé, puis les dérouler localement :

1. System 360 : dérouler [`Build`](screenshots/system360-build.png),
   [`Operate`](screenshots/system360-operate.png),
   [`Steer`](screenshots/system360-steer.png) et
   [`Govern`](screenshots/system360-govern.png).
2. Andritz : ouvrir le [business shell](screenshots/andritz-business-shell.png),
   puis les captures Recherche, Client360, Capture et FSE du même dossier.
3. Sentinel et Octocity : utiliser
   [`sentinel-mission-room.png`](screenshots/sentinel-mission-room.png) et
   [`octocity-mission-room.png`](screenshots/octocity-mission-room.png).
4. Pour une question de preuve : montrer les observations
   [behavior](observations/lot6-system360-behavior-local.json),
   [runner](observations/lot6-system360-runner-local.json) et le
   [JUnit smoke](observations/workspace-smoke-junit.xml), sans les présenter
   comme des attestations GitLab protégées.

Le mode secours démontre l'état testé ; il ne doit pas être présenté comme une navigation live. Si seule l'IA ralentit, continuer la navigation et s'appuyer sur les états déjà calculés plutôt que de relancer un Run.

## Limites connues, non bloquantes pour la démo

- La garde console stricte a identifié un `422` de télémétrie sur `POST /api/v1/audit`
  lors du passage par l'app FSE Andritz. La navigation et les quatre applications restent
  fonctionnelles ; ne pas présenter la console comme totalement propre.
- Sentinel et Octocity rendent correctement leurs Mission Rooms, mais l'appel secondaire
  `GET /api/v1/meetings/decisions-log` répond encore `404` et le composant affiche son état
  vide prévu. Ce point est à corriger après la démo, sans redéploiement avant 15 h.
- L'attestation locale protégée refuse volontairement de se générer hors GitLab ; la preuve
  formelle `deployed_verified` reste donc le travail prévu demain après activation du miroir.
