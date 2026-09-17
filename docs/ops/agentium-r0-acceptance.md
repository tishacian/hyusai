# R0 — Recette et décision de clôture

16 septembre 2026 · Workspace : **Agentium Showcase** (`agentium-showcase`).

**La clôture produit attend la baseline utilisateurs et la décision de Thibaud.**
Pour le runtime courant, ses gates et les derniers défauts observés, utiliser la
[checklist de clôture](agentium-r0-closure.md). Les consignes ci-dessous restent
les parcours à tester ; les preuves du 16 septembre conservent leur propre SHA.
Aucune acceptation utilisateur n’est présumée.

## Preuves historiques — runtime 7532d449 du 16 septembre

| Gate | Résultat et portée |
|---|---|
| Frontend | 1 460 tests, i18n, liens, chrome UI et build production réussis ; suite exécutée en lots après saturation du disque temporaire |
| Backend | 216 tests réussis |
| Build et identité | Trois images immuables construites sur omnirag-demo ; frontend/backend identifient le SHA candidat |
| Stockage et santé | Contrôles de stockage réussis ; HTTP 200 ; aucune exception backend dans la fenêtre inspectée |
| Canaries carakai | 10 réussis, 2 contrats locaux/mock volontairement ignorés ; sources et runtime au même SHA |
| Exécution réelle | Cinq répétitions séquentielles, deux Runs concurrents, puis deux Runs pendant un redémarrage gracieux du worker : réussis ; rejouer la clé ne duplique pas le Run |
| Lisibilité | Capture réelle inspectée : exécution terminée, aucune approbation ni confiance inventée ; opérations Python et LLM visibles |
| FR/EN et thèmes | Matrice Work/Studio de 24 captures sur le frontend précédent ; corrections runtime suivantes sans modification de ces écrans |

[Résultats et capture du runtime](../evidence/runtime-7532d449-2026-09-16/README.md).
[Matrice visuelle Work/Studio](../evidence/roadmap-r0-2026-09-16/README.md).

Le dépôt est sur Bitbucket. **Aucune CI distante n'est active**, selon confirmation
du responsable le 16 septembre. Une attestation GitLab n'est donc pas attendue.
Les gates applicables sont ceux du [processus de release](../agentium-release-process.md).

## Parcours de recette

Ouvrir une session fraîche et sélectionner Agentium Showcase. Les liens exigent
les permissions correspondantes. Ne pas exécuter ces exercices dans un workspace client.

### 1. Obtenir un résultat et retrouver son traitement

Ouvrir [Operational Analysis](https://agentium.papai.ai/work/operational-analysis/analysis).
Lancer l'analyse du jeu synthétique, puis ouvrir « Inspect this result ».

Résultat attendu : quatre ordres, 120 minutes prévues, 155 réalisées, écart net
+35 minutes, trois ordres en retard ; NF-04 porte le plus grand dépassement (+25).
Le lien doit ouvrir exactement le Run de ce résultat, avec deux opérations Python
et une invocation LLM. Le contrôle numérique doit réussir. Une exécution terminée
ne signifie ni validation humaine ni économie réalisée.

[Run déjà qualifié](https://agentium.papai.ai/runs/f29982f7-8583-4993-84f8-d394c286cfbd).
L'évaluation sémantique automatique est ignorée pour cette entrée fixe ; la langue
de réponse du modèle ne suit pas nécessairement celle de l'interface.

### 2. Comprendre ce qui existe déjà dans le parcours BRD

Ouvrir la [Skill PIH Document Summary Demo](https://agentium.papai.ai/skills/ws.e2ed9e40-5fa6-4e32-8948-3e1220134fd3.demo_pih_spark089_summary),
puis le [System PIH](https://agentium.papai.ai/systems/a021f6c3-fed5-4940-a3e1-53d5a7617f57?lens=build&facet=design).
Repérer les entrées documentaires, la synthèse et ses contraintes.

[Exécution de référence historique](https://agentium.papai.ai/runs/bcab9754-ac5c-491f-80f2-ab86f535307e).
Le livrable synthétise titres et grades actuels/proposés, date, informations manquantes
et citations. Il n'approuve pas une transaction. Ce Run est un test de draft
antérieur au SHA candidat ; il ne prouve pas une application PIH publiée.

Le Flow de cette démonstration historique a été assemblé. Les propositions BRD →
System et leur traçabilité sont désormais implémentées, avec une qualification R1
encore ouverte : voir le [statut de livraison](brd-system-roadmap-progress.md).
Cette démonstration R0 ne prouve pas la recette ni la publication des Systems générés.

### 3. Retrouver les preuves depuis l'observabilité

Ouvrir [Quality pour NorthForge](https://agentium.papai.ai/observability/quality?system_id=a1cd8c00-6474-48bd-9d87-dba29f017e92&since=30d),
puis sélectionner un résultat et vérifier que le lien conserve son Run.
Le canary du SHA candidat vérifie la liaison graphique → Run.

La [comparaison NorthForge existante](https://agentium.papai.ai/runs/c1e805a9-6578-4777-b502-d34661737234?campaign=62dec64e-0391-4550-833b-84224dfb8f9f)
est une référence historique distincte : ne pas la présenter comme une nouvelle
campagne Giskard qualifiée sur ce SHA. Les chiffres du corpus réel sont 700 bar
et 735 bar ; le scénario illustratif 6/8 bar des maquettes n'est pas une preuve.

## Baseline avec les participants — à exécuter

Cinq participants métier et cinq développeurs n'ayant pas conçu ces parcours.
Aucun résultat de session n'est encore enregistré. Les essais automatisés ne les
remplacent pas. Ces dix sessions servent à identifier les blocages, pas à produire
une mesure statistique de l'adoption.

Donner les consignes suivantes sans montrer les clics. Chronométrer jusqu'à un
résultat vérifié, noter chaque demande d'aide et arrêter à la limite convenue.
Ne pas enregistrer le contenu des documents ni des conversations dans la fiche.

- Métier : obtenir une réponse avec sa source ; ouvrir le passage qui la soutient.
- Métier : retrouver une demande en attente et expliquer qui doit agir. Utiliser
  une attente synthétique préparée ; ne pas approuver une opération client.
- Développeur : retrouver le Flow d'un exemple et expliquer une entrée, une
  opération et son résultat ; utiliser un draft dédié pour toute adaptation.
- Tous : expliquer un indicateur, sa provenance et s'il est mesuré ou projeté.

| Participant | Profil | Tâche | Réussite sans aide | Temps | Demandes d'aide | Blocage / observation |
|---|---|---|---|---|---|---|
| M1 | Métier | À renseigner | NOT RUN | — | — | — |
| M2 | Métier | À renseigner | NOT RUN | — | — | — |
| M3 | Métier | À renseigner | NOT RUN | — | — | — |
| M4 | Métier | À renseigner | NOT RUN | — | — | — |
| M5 | Métier | À renseigner | NOT RUN | — | — | — |
| D1 | Développeur | À renseigner | NOT RUN | — | — | — |
| D2 | Développeur | À renseigner | NOT RUN | — | — | — |
| D3 | Développeur | À renseigner | NOT RUN | — | — | — |
| D4 | Développeur | À renseigner | NOT RUN | — | — | — |
| D5 | Développeur | À renseigner | NOT RUN | — | — | — |

Pour chaque session, consigner également le SHA, les permissions, les flags,
le point de départ et la langue. Un scénario indisponible est un blocage constaté,
pas un succès ni une ligne supprimée du protocole.

## Décision restante

R0 peut être clos après les premières sessions, l'analyse de leurs blocages et
la décision explicite du responsable sur les réserves. La release technique
n'attend plus une CI inexistante. Les développements R1 peuvent avancer ; ses approbations, publications et
consommations par un second utilisateur doivent conserver leurs preuves propres.

Restent distinctement non qualifiés : campagne Giskard avec fournisseur réel,
cas observabilité non préparé, perte brutale/redélivrance du worker et essais
humains. Les tests de redémarrage gracieux ne couvrent pas une perte brutale.
La publication, les preuves économiques et les anciennes décisions historiques
ne sont pas réinterprétées par cette recette.

**Décision de clôture : en attente.** Date et réserves acceptées : à renseigner
après examen des résultats humains. Aucune bascule de flag ni activation client
n'est demandée par ce document.
