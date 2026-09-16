# R0 — Checklist de clôture

16 septembre 2026 · Agentium Showcase (`agentium-showcase`).

**R0 reste ouvert.** Les gates techniques sont documentés ; la recette manuelle
authentifiée sur le SHA courant et les dix sessions de baseline restent à faire.
Dernier runtime attesté : `b4fde677a75a7a9f6ab30898882104c37582709b`
sur `demo/agentic`. Bascule, identité publique et santé vérifiées ; canaries :
**10 réussis, 2 exclusions prévues**. Voir les
[preuves de qualification](../evidence/brd-work-publication-2026-09-16/README.md).
Ce document référence les vérifications consignées ; il ne vaut pas recette humaine.

Périmètre : [sortie R0 de la roadmap](../agentium-delivery-roadmap.md),
[processus de release](../agentium-release-process.md) et
[protocole de recette R0](agentium-r0-acceptance.md).
Les mentions de SHA et de fonctionnalités dans ce dernier protocole sont
historiques ; le [statut courant](brd-system-roadmap-progress.md) fait référence.

| Critère R0 | Preuve conservée | État |
|---|---|---|
| Gates locaux du candidat b4fde677 | [Qualification locale](../evidence/brd-work-publication-2026-09-16/README.md) : 286 tests backend ; 1 478 tests frontend couverts et réussis après rerun ciblé (1 462 initialement réussis, fichier de 16 tests réussi après correction de l'assertion d'accessibilité) ; i18n 7 992 clés, liens fail-closed, chrome et build réussis | Prouvé localement pour ce candidat |
| Build VM, stockage, santé et identité du runtime | [Release b4fde677](../evidence/brd-work-publication-2026-09-16/README.md) : trois images immuables ; [build-info exact et santé](../evidence/brd-work-publication-2026-09-16/runtime-check.log) | Prouvé pour b4fde677 |
| Canaries requis, dont Work, Studio et accès au Run | [Log carakai b4fde677](../evidence/brd-work-publication-2026-09-16/canaries.log) : 10 réussis, 2 contrats locaux volontairement ignorés | Prouvé pour b4fde677 |
| Exemple Showcase reproductible et configuration consignée | [Inventaire R0](brd-system-roadmap-progress.md#r0-live-qualification--16-september-2026) : System, Experience, Flow publié et binding ; [recette](agentium-r0-acceptance.md) : quatre ordres NorthForge, 120/155/+35 minutes, trois retards, NF-04 +25 | Consigné ; disponibilité actuelle à constater pendant le smoke |
| Répétitions et résultat honnête | [Runtime 7532d449](../evidence/runtime-7532d449-2026-09-16/README.md) : cinq répétitions réussies, paire concurrente, redémarrage gracieux, replay sans doublon et absence d'approbation/confiance inventée | Prouvé historiquement ; ces exécutions ne sont pas attribuées à b4fde677 |
| Parcours manuels, liens et captures actualisées | [Work → Run](../evidence/roadmap-r0-2026-09-16/manual-work-path.md) sur e09bde5c ; [24 captures Work/Studio](../evidence/roadmap-r0-2026-09-16/README.md) sur 196164eb ; [capture du Run](../evidence/runtime-7532d449-2026-09-16/run.png) sur 7532d449 | À actualiser sur le SHA retenu pour la clôture |
| Baseline métier/développeur | [Fiche et consignes](agentium-r0-acceptance.md#baseline-avec-les-participants--à-exécuter) ; aucune session renseignée | 0/5 métier, 0/5 développeur |
| Décision du responsable | Aucune décision de clôture enregistrée | En attente des éléments précédents |

La release ajoute le parcours Flow → activation explicite de la version revue
→ brouillon d'application, réouvrable après fermeture ou rechargement ; les
contraintes de longueur Work ; les manifestes de corpus des nouvelles suites
BRD et leurs gardes de dérive ; la provenance des décisions natives du planner,
sans modifier ses seuils. Ces acquis sont qualifiés localement dans la preuve
liée ci-dessus. Ils ne constituent ni une recette manuelle actuelle ni des
sessions d'adoption et n'ajoutent aucun critère de sortie à R0.

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
