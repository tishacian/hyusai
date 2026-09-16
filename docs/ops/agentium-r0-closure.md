# R0 — Checklist de clôture

17 septembre 2026 · Agentium Showcase (`agentium-showcase`).

**R0 reste ouvert.** Les gates techniques sont documentés ; la recette manuelle
authentifiée sur le SHA courant et les dix sessions de baseline restent à faire.
Dernier runtime attesté : `37056391d6cc315c72495f973fb6fe0e2072ed68`
sur `demo/agentic`. Bascule, identités publiques frontend/backend et santé
vérifiées ; canaries : **10 réussis, 2 exclusions prévues**. Voir les
[preuves de qualification](../evidence/release-37056391-2026-09-17/README.md).
Ce document référence les vérifications consignées ; il ne vaut pas recette humaine.

Périmètre : [sortie R0 de la roadmap](../agentium-delivery-roadmap.md),
[processus de release](../agentium-release-process.md) et
[protocole de recette R0](agentium-r0-acceptance.md).
Les mentions de SHA et de fonctionnalités dans ce dernier protocole sont
historiques ; le [statut courant](brd-system-roadmap-progress.md) fait référence.

| Critère R0 | Preuve conservée | État |
|---|---|---|
| Gates locaux du candidat 37056391 | [Qualification locale et images](../evidence/release-37056391-2026-09-17/README.md) : 75 tests backend ; 1 487 tests frontend ; i18n 8 048 clés, liens, chrome et build réussis | Prouvé localement pour ce candidat |
| Build VM, stockage, santé et identité du runtime | [Release 37056391](../evidence/release-37056391-2026-09-17/README.md) : trois images immuables ; SHA public exact côté frontend et backend ; HTTP 200 | Prouvé pour 37056391 |
| Canaries requis, dont Work, Studio et accès au Run | [Log carakai 37056391](../evidence/release-37056391-2026-09-17/canaries.log) : 10 réussis, 2 contrats locaux volontairement ignorés | Prouvé pour 37056391 |
| Exemple Showcase reproductible et configuration consignée | [Inventaire R0](brd-system-roadmap-progress.md#r0-live-qualification--16-september-2026) : System, Experience, Flow publié et binding ; [recette](agentium-r0-acceptance.md) : quatre ordres NorthForge, 120/155/+35 minutes, trois retards, NF-04 +25 | Consigné ; disponibilité actuelle à constater pendant le smoke |
| Répétitions et résultat honnête | [Runtime 7532d449](../evidence/runtime-7532d449-2026-09-16/README.md) : cinq répétitions réussies, paire concurrente, redémarrage gracieux, replay sans doublon et absence d'approbation/confiance inventée | Prouvé historiquement ; ces exécutions ne sont pas attribuées à 37056391 |
| Parcours manuels, liens et captures actualisées | [Work → Run](../evidence/roadmap-r0-2026-09-16/manual-work-path.md) sur e09bde5c ; [24 captures Work/Studio](../evidence/roadmap-r0-2026-09-16/README.md) sur 196164eb ; [capture du Run](../evidence/runtime-7532d449-2026-09-16/run.png) sur 7532d449 | À actualiser sur le SHA retenu pour la clôture |
| Baseline métier/développeur | [Fiche et consignes](agentium-r0-acceptance.md#baseline-avec-les-participants--à-exécuter) ; aucune session renseignée | 0/5 métier, 0/5 développeur |
| Décision du responsable | Aucune décision de clôture enregistrée | En attente des éléments précédents |

La release 6f8f8169 ajoute l’ouverture des cellules citées et des verdicts
Golden calculés côté serveur. Trois Runs réels terminés produisent respectivement
un contrôle réussi, un contrôle volontairement échoué et un résultat non évalué
sans oracle. Leur rejeu ne crée pas de doublon. Les captures Excel sont des
vérifications locales du composant réel, pas une recette utilisateur en production.
Les acquis antérieurs de publication explicite et de provenance sont conservés.
Aucun de ces éléments n’ajoute de critère de sortie à R0 ni ne remplace les sessions.

La release c399f2be ajoute la reprise d’indexation, qualifiée techniquement sur
une collection synthétique dédiée : échec, restauration de l’original, même job
repris, passage retrouvé et absence de duplication. Cette preuve ne remplace ni
le smoke manuel, ni les sessions humaines, ni la recette complète de R2.

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
