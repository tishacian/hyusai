# R0 — Checklist de clôture

16 septembre 2026 · Agentium Showcase (`agentium-showcase`).

**R0 reste ouvert.** Les gates techniques sont documentés ; la recette manuelle
authentifiée sur le SHA courant et les dix sessions de baseline restent à faire.
Dernier runtime attesté dans les preuves consultées :
`cd8f23f27af68b54022e281df4930eed4c02573b` sur `demo/agentic`.
Ce document audite les preuves conservées ; il ne constitue pas une nouvelle
vérification en direct.

Périmètre : [sortie R0 de la roadmap](../agentium-delivery-roadmap.md),
[processus de release](../agentium-release-process.md) et
[protocole de recette R0](agentium-r0-acceptance.md).
Les mentions de SHA et de fonctionnalités dans ce dernier protocole sont
historiques ; le [statut courant](brd-system-roadmap-progress.md) fait référence.

| Critère R0 | Preuve conservée | État |
|---|---|---|
| Gates locaux, build VM, stockage, santé et identité du runtime | [Release cd8f23f2](../evidence/brd-durable-tools-2026-09-16/README.md) : 333 tests backend concernés, 1 467 tests frontend, i18n/liens/chrome/build réussis ; trois images immuables ; [build-info exact et santé](../evidence/brd-durable-tools-2026-09-16/vm-health.log) | Prouvé pour ce SHA |
| Canaries requis, dont Work, Studio et accès au Run | [Log carakai cd8f23f2](../evidence/brd-durable-tools-2026-09-16/canaries.log) : 10 réussis, 2 contrats locaux volontairement ignorés | Prouvé pour ce SHA |
| Exemple Showcase reproductible et configuration consignée | [Inventaire R0](brd-system-roadmap-progress.md#r0-live-qualification--16-september-2026) : System, Experience, Flow publié et binding ; [recette](agentium-r0-acceptance.md) : quatre ordres NorthForge, 120/155/+35 minutes, trois retards, NF-04 +25 | Consigné ; disponibilité actuelle à constater pendant le smoke |
| Répétitions et résultat honnête | [Runtime 7532d449](../evidence/runtime-7532d449-2026-09-16/README.md) : cinq répétitions réussies, paire concurrente, redémarrage gracieux, replay sans doublon et absence d'approbation/confiance inventée | Prouvé historiquement ; ces exécutions ne sont pas attribuées à cd8f23f2 |
| Parcours manuels, liens et captures actualisées | [Work → Run](../evidence/roadmap-r0-2026-09-16/manual-work-path.md) sur e09bde5c ; [24 captures Work/Studio](../evidence/roadmap-r0-2026-09-16/README.md) sur 196164eb ; [capture du Run](../evidence/runtime-7532d449-2026-09-16/run.png) sur 7532d449 | À actualiser sur le SHA retenu pour la clôture |
| Baseline métier/développeur | [Fiche et consignes](agentium-r0-acceptance.md#baseline-avec-les-participants--à-exécuter) ; aucune session renseignée | 0/5 métier, 0/5 développeur |
| Décision du responsable | Aucune décision de clôture enregistrée | En attente des éléments précédents |

## Actions restantes

- [ ] **Faire le smoke authentifié sur le SHA retenu.** Recharger complètement
  le navigateur, sélectionner Showcase et consigner SHA, date, permissions,
  flags et langue. Suivre les trois parcours de la fiche R0 : Operational
  Analysis → résultat → Run exact ; exemple PIH existant ; Quality → Run.
  Vérifier le résultat NorthForge attendu, l'état réel, la prochaine action et
  les preuves accessibles. Ouvrir Work et Studio et conserver des captures
  actuelles ainsi que la courte vidéo prévue par la roadmap. Les captures
  historiques restent datées de leur propre SHA. Consigner tout échec observé.
- [ ] **Conduire les dix sessions humaines.** Cinq participants métier et cinq
  développeurs extérieurs à la conception, selon la fiche existante. Une ligne
  par participant : tâche, réussite sans aide, durée, aide demandée et blocage,
  avec le contexte de session. Reporter les résultats face aux cibles initiales
  de la roadmap : 4/5 métier trouvent résultat et preuve en moins de dix minutes ;
  4/5 développeurs adaptent et expliquent l'exemple en moins de trente minutes.
  Ces cibles servent à lire la baseline ; aucun résultat n'est présumé.
- [ ] **Consigner la décision de Thibaud.** Examiner les blocages réellement
  observés, leurs corrections ou réserves acceptées, puis dater la décision
  R0 et actualiser le statut de la roadmap. La réussite des canaries seule ne
  clôt pas cette étape.

## Limites conservées sans élargir R0

Aucune CI distante n'est active ; aucune attestation GitLab n'est attendue.
Les réserves historiques sur une campagne Giskard avec fournisseur réel,
un cas d'observabilité non préparé ou une perte brutale du worker restent
documentées dans leur périmètre ; elles ne sont pas marquées réussies ici.
La génération complète des deux BRD, leurs suites Golden, la revue/reprise,
la publication et la consommation par un second utilisateur relèvent de R1.
Le défaut d'oracle `approved`/`accepted` découvert sur f6b73cff est suivi dans
les preuves R1 ; il n'ajoute pas un gate à cette checklist R0.

**Décision de clôture R0 : en attente.**
