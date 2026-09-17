# R0 — Checklist de clôture

17 septembre 2026 · Agentium Showcase (`agentium-showcase`).

**R0 reste ouvert.** Les gates techniques sont documentés ; la recette manuelle
authentifiée a corrigé les liens défectueux et distingue désormais valeur absente et zéro.
Les dix sessions de baseline et la vidéo restent à faire. Design PIH distingue
désormais draft r3 et publication v1 ; son en-tête à 390 px est corrigé et vérifié après défilement.
Dernier runtime attesté : `d05e84b15c53e9a12dc92a9cab6f765be648fead`
sur `demo/agentic`. Bascule, identités publiques frontend/backend et santé
vérifiées ; canaries : **10 réussis, 2 exclusions prévues**. Voir les
[preuves de qualification](../evidence/release-d05e84b1-2026-09-17/README.md).
Ce document référence les vérifications consignées ; il ne vaut pas recette humaine.

Périmètre : [sortie R0 de la roadmap](../agentium-delivery-roadmap.md),
[processus de release](../agentium-release-process.md) et
[protocole de recette R0](agentium-r0-acceptance.md).
Les mentions de SHA et de fonctionnalités dans ce dernier protocole sont
historiques ; le [statut courant](brd-system-roadmap-progress.md) fait référence.

| Critère R0 | Preuve conservée | État |
|---|---|---|
| Gates locaux du candidat d05e84b1 | [Qualification locale et images](../evidence/release-d05e84b1-2026-09-17/README.md) : 1 512 tests frontend ; 137 tests backend ; i18n 8 077 clés, liens, chrome et build réussis | Prouvé localement pour ce candidat |
| Build VM, stockage, santé et identité du runtime | [Release d05e84b1](../evidence/release-d05e84b1-2026-09-17/README.md) : trois images immuables ; SHA public exact côté frontend et backend ; HTTP 200 | Prouvé pour d05e84b1 |
| Canaries requis, dont Work, Studio et accès au Run | [Log carakai d05e84b1](../evidence/release-d05e84b1-2026-09-17/canaries.log) : 10 réussis, 2 contrats locaux volontairement ignorés | Prouvé pour d05e84b1 |
| Exemple Showcase reproductible et configuration consignée | [Inventaire R0](brd-system-roadmap-progress.md#r0-live-qualification--16-september-2026) : System, Experience, Flow publié et binding ; [recette](agentium-r0-acceptance.md) : quatre ordres NorthForge, 120/155/+35 minutes, trois retards, NF-04 +25 | Vérifié dans Chrome : nouveau Run 5369c2b1 sur 4baa9f5d, chiffres attendus et lien exact ; ancien Run 9b73e4e5 inchangé |
| Répétitions et résultat honnête | [Runtime 7532d449](../evidence/runtime-7532d449-2026-09-16/README.md) : cinq répétitions réussies, paire concurrente, redémarrage gracieux, replay sans doublon et absence d'approbation/confiance inventée | Cinq nouvelles exécutions réussies sur 18741f94 : [réponses conservées](../evidence/release-18741f94-2026-09-17/sequential.json). Concurrence et redémarrage restent historiques |
| Parcours manuels, liens et captures actualisées | [Work → Run](../evidence/roadmap-r0-2026-09-16/manual-work-path.md) sur e09bde5c ; [24 captures Work/Studio](../evidence/roadmap-r0-2026-09-16/README.md) sur 196164eb ; [capture du Run](../evidence/runtime-7532d449-2026-09-16/run.png) sur 7532d449 | Work ↔ Studio, invocation et fil d’Ariane corrigés ; [nouveaux résultat, Run, PIH et Quality](../evidence/release-18741f94-2026-09-17/README.md) ; absence/zéro corrigé ; Design et Flow r3 alignés ; en-tête à 390 px corrigé et vérifié sur def0b3cc |
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

Le [smoke Chrome du 17 septembre](../evidence/release-ab15d204-2026-09-17/README.md)
reprend les preuves Work ↔ Studio et des liens d'étapes System ; le Run numérique
conservé a été exécuté sur 4771f15b.
Le parcours Quality → Run → passage est capturé sur 447997ee. Sur ab15d204,
l'invocation ouvre son audit autorisé et conserve le System et le Run, y compris
après rechargement et retour arrière. L'absence est explicite et peut être relue.
Sur 4baa9f5d, la carte affiche — pour la valeur absente et son efficacité, et
qualifie les coûts calculés. Les trois parcours ont été ouverts : nouvelle exécution
Work, Flow/configuration PIH, Quality → Run → passages. Sur 18741f94, Design lit le même draft r3 que le Flow Builder et affiche
explicitement la version publiée v1 ; aucune version n’a été remplacée. Les [captures](../evidence/release-18741f94-2026-09-17/README.md)
sont actualisées ; la vidéo n'a pas été réalisée (commande QuickTime désactivée).

## Actions restantes

- [x] **Distinguer absence et zéro dans la carte de résultat.** Ne pas afficher
  une valeur ni une efficacité mesurée lorsque `value_source` vaut `unset`.
  Conserver les hypothèses déclarées et la provenance des coûts accessibles.

- [x] **Faire le smoke authentifié sur 4baa9f5d.** Nouvelle exécution NorthForge
  depuis Work → résultat → Run → contrôle numérique ; Flow et paramètres PIH
  ouverts sans mutation ; Quality → Run sélectionné → passages examinés. Captures
  et contexte dans la release. Les essais historiques restent attribués à leur SHA.
- [x] **Aligner le résumé Design PIH sur le Flow réel.** Vérifié sur 18741f94 :
  même draft r3, trois nœuds et trois connexions, publication v1 distincte.
- [x] **Libérer le contenu sur écran étroit.** Vérifié sur def0b3cc à 390×844 :
  le résumé draft r3 / publication v1 reste accessible après défilement, sans
  recouvrement par l’en-tête du System. Capture et mesure dans la release.
- [ ] **Enregistrer la courte vidéo.** QuickTime désactivé ; proposition de
  capture alternative en attente de réponse. Aucune vidéo annoncée comme faite.
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
La campagne Giskard avec le fournisseur réel a terminé sur 0f06b4eb : six
réponses évaluées, Runs et usage fournisseur conservés dans les preuves. Le cas
d'observabilité non préparé et la perte brutale du worker restent ouverts dans
leur périmètre. Cette campagne ne remplace pas la baseline humaine de R0.
La génération complète des deux BRD, leurs suites Golden, la revue/reprise,
la publication et la consommation par un second utilisateur relèvent de R1.
Le défaut d'oracle `approved`/`accepted` découvert sur f6b73cff est suivi dans
les preuves R1 ; il n'ajoute pas un gate à cette checklist R0.

**Décision de clôture R0 : en attente.**
