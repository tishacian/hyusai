# Luma — recette après déploiement du 20 octobre 2026

La recette vise le System `f3ea83de-df89-45ec-8a85-c00d676b2713` et Work
`reclamations`, dans `agentium-showcase`. Les Runs de prévision et d'enquête
confirment `flow_evidence.runtime_revision =
1b36e8a1fcd22f1b61fdd656065e97edd468cc2c`. La migration 141 et la cohérence
des services ont été annoncées par l'opérateur ; aucun déploiement, migration,
drapeau global, accès PostgreSQL ou canal d'alerte n'est changé pendant cette recette.

## État réellement démontré

| Lot | Résultat |
| --- | --- |
| Challenger | Shadow activé à 10 %, délai 30 s, deux comparaisons terminées ; v5 reste champion |
| Préparation | Le Flow publié prépare les données ; le nouvel aperçu temporaire est testé avec le frontend local et les API en service, sur 23 lignes |
| Prévision Work | La prévision produit son dataset ; l'assemblage SQL échoue encore en service. Correctif générique testé localement |
| Événements | Consentement bloqué par HTTP 500 ; défaut reproduit sur PostgreSQL et corrigé localement. Hook et planning restent en pause |
| Judge | Appel fournisseur effectué, mais réponse refusée par la validation. Zéro réponse validée sur cinq ; contrôle humain toujours requis |

Une invocation technique `completed` n'établit pas la réussite du Judge.
Les tests locaux ne sont pas présentés comme des exécutions du binaire déployé.

## Publications et conservation des brouillons

Le Flow v8 est conservé comme historique. Deux publications ajustent seulement
le budget du nœud `quality.review` :

- **v9**, `daffb0f9-e412-4ac6-83a3-82a6f7ef8f2d` : réservation portée de
  40 000 à 42 000 tokens, plafond monétaire inchangé ;
- **v10**, `b8eb64d3-e417-41bf-898a-7b1ad232d64a` : un appel, 48 000 tokens
  réservables, 8 192 tokens de sortie, 0,14 USD maximum et 90 secondes.
  Prompt maximal inchangé : 32 000 octets. Aucun extrait n'est tronqué.

La v10 porte l'empreinte
`77d4d521a3526fce8a25ee125ddf010976d637f2f2335d8afee98f1a4dbd09f0`.
Les trois bindings Work et la configuration de triage pointent vers cette
même version. La release Work est `a82202e4-6116-4267-9bc3-e14923684ba7`.
Les pages de l'application ne changent pas.

Une première préparation de v9 a été interrompue avant publication :
le diff signalait aussi un changement de contrat exécutable. Le brouillon a
été restauré à l'identique avant investigation. La reconstruction du contrat
et de son hash a établi que seules cinq contraintes de citation image
changeaient de `{"const":"image"}` à
`{"type":"string","enum":["image"]}`, sémantiquement équivalentes. Aucun autre
contrat, binding de Skill ou droit n'était changé.

Après publication, le brouillon Flow **r37** conserve le nœud utilisateur
`flow.mv95zi21.1`, ses liaisons et positions ; seul le budget Judge reçoit
l'ajustement décrit ci-dessus. Le nœud isolé n'est pas publié. Le brouillon
Work **r11** conserve ses pages, ses binding keys et leur ordre. Le modèle SLA
v5 et ses épingles ne sont pas remplacés.

## Prévision : défaut de résolution des sources

Depuis **Charge et capacité → Actualiser la prévision → Confirmer**, le Run
`8afc769d-6f53-493f-a1de-5321f87c399d` termine `ml_forecast_v1` et produit
28 prévisions. Le correctif Delta déployé est donc traversé avec succès.
Le Run échoue ensuite dans `forecast.timeline` :
`DATASET_NOT_FOUND: No dataset matched the reference`.

Le résolveur DataOps traitait `model.slug` de l'enveloppe de prévision comme
un dataset supplémentaire. Il distingue maintenant cette provenance via
`model_id`, sans ignorer les références `dataset_id` ou `dataset_slug`
explicites, les sources déclarées ou les références historiques par slug.
Une collision entre nom de modèle et nom de dataset est aussi couverte.

Le test d'intégration exécute le wrapper, le worker, DuckDB et la publication
du dataset : **42 lignes historiques + 28 lignes prévues**, dates, intervalles
et deux parents vérifiés. Il faut encore refaire cette action dans Work après
déploiement et vérifier le graphique. L'historique reste arrêté au 8 octobre ;
la prévision couvre le 9 octobre au 5 novembre, pas « les 28 prochains jours ».

## Préparation : explorer sans changer la source du Flow

L'essai isolé `sav.features`,
`c3a685c0-7921-4ae3-83a6-200fda31d8d6`, échoue avec
`CLAIMS_COMPOSITION_FLOW_REQUIRED`. Ce nœud utilise le contexte de composition
et le point d'entrée pour distinguer un dossier de la file ; le test isolé
ne porte pas ce contexte. Aucun mode « file » n'est déduit artificiellement
de `{}` et aucun contrôle n'est supprimé.

L'atelier reçoit une fonction générique **Données pour cet aperçu**. Elle
permet de choisir temporairement une version disponible du workspace, avec
son nom, sa version et sa provenance. Les actions d'aperçu et de compilation
SQL deviennent disponibles sans épingle et sans sauvegarde. La conversion
en nœud SQL est désactivée avec une source temporaire. Les changements de
workspace, System, entrée ou préparation invalident les résultats périmés,
y compris les réponses HTTP arrivant en retard.

Le build de production local a été utilisé dans un navigateur contre les
vraies API de `agentium.papai.ai`, sans substitution de réponse :

- source `336aed57-8637-42bc-9d81-ab4f820f68f6`,
  **Luma — Faits SAV PostgreSQL v7**, issue de `sav.features` dans le Run
  `e4fe28c1-f9ae-425d-87c1-4c127f6937a0` ;
- aperçu final : 23 lignes, neuf colonnes, `evidence_gap` faux sur les
  23 dossiers et cinq `duplicate_refund_check` vrais ;
- compilation SQL HTTP 200 ; conversion désactivée ;
- brouillon et publication strictement identiques avant/après ouverture,
  sélection, aperçu, compilation et fermeture.

Cette recette qualifie l'interface locale avec le backend en service.
Le nouveau sélecteur doit encore être déployé sur le frontend public.
Le [parcours d'atelier](../demo-runs/showcase-ecommerce/fixtures/showcase_visual_prep/README.md)
remplace l'ancienne instruction de test isolé pour Luma.

## Événements : consentement avant activation

Dans le Flow, sélectionner la source webhook, ouvrir **Accès d'exécution**,
puis **Utiliser mes accès** renvoie HTTP 500. Le PATCH API reproduit le refus ;
aucune délégation n'est enregistrée. Les sources restent désactivées :

- hook `f7f54df5-2af7-4114-bec0-af8b150126f9` ;
- planning `1feaa7f7-ca60-408f-95f2-ddf4d182646c`,
  `0 8 * * 1-5`, **Europe/Paris** ;
- System en mode `dry_run`.

Le défaut est reproduit sur PostgreSQL 16 : le verrou `FOR UPDATE` s'appliquait
aussi à la jointure optionnelle de Capability, ce que PostgreSQL refuse.
Le verrou cible maintenant `OF systems`. Les vérifications de droits,
de publication consentie et de révocation restent inchangées.
Les tests PostgreSQL couvrent les deux PATCH, la livraison signée, la
déduplication, le planning et la révocation. Aucun test live de hook ou de tick
n'est annoncé comme réussi.

## Judge : consommation visible, qualité non établie

| Run | Configuration | Résultat |
| --- | --- | --- |
| `834365dd-ea11-4d9a-9db8-18d6bd1b700c` | v8, 40 000 tokens | `JUDGE_BUDGET_EXHAUSTED`, zéro appel |
| `e5152367-2b8d-4241-851e-be460ca4cfdd` | v9, 42 000 tokens, sortie 2 048 | `JUDGE_RESPONSE_INVALID`, un appel, 10 754 tokens |
| `ebb99328-f345-4650-8cd6-5ddd0e465e21` | v10, sortie 8 192 | `JUDGE_RESPONSE_INVALID`, un appel, 14 223 tokens |

Pour le premier Run, la réservation reconstituée est exactement
**40 290 tokens / 0,0682825 USD** : le plafond de tokens bloquait avant appel.
La v9 atteint exactement 2 048 tokens de sortie. Ce compteur suggère une
limite atteinte mais ne prouve pas, seul, une troncature.
La v10 consomme **8 706 tokens de prompt + 5 517 de sortie**, sous son
nouveau plafond, et reste invalide : augmenter encore le budget n'est pas
une correction établie.

Les coûts calculés au tarif déclaré sont respectivement **0,0313625 USD**
et **0,0660525 USD**, avec compteurs fournisseur complets ; ce ne sont pas
des montants de facture. La réservation maximale de v10 est
47 753 tokens / 0,13137125 USD. Les échecs et leurs coûts restent conservés.
Les trois Runs s'arrêtent à la revue humaine. Aucune proposition n'est
approuvée et aucun reçu supplémentaire n'est créé par cette recette.

Le contenu brut du fournisseur n'est pas conservé. Le correctif générique
transmet l'indicateur fournisseur de fin par limite et distingue
`JUDGE_OUTPUT_TRUNCATED` sans l'inférer du compteur. La validation reste
stricte ; aucune citation, plage de caractères ou décision n'est réparée
automatiquement pour obtenir artificiellement une réussite.
Pour les autres refus, `response_diagnostic` conserve une catégorie fixe et
des indices de question/citation, sans contenu fournisseur ni message brut
du validateur. Il faut une nouvelle enquête après déploiement pour connaître
la catégorie du refus actuel ; les anciens résultats ne la contiennent pas.

## Challenger et lecture UI

Voir la [qualification shadow](../demo-runs/showcase-ecommerce/SHADOW-QUALIFICATION-2026-10-20.md).
Le panneau **Modèle v5 → Suivi → Scoring du challenger en parallèle** est
également contrôlé dans le navigateur : v6 sélectionnée, deux exclusions
legacy, 10 % / 30 s, deux traitements terminés et trois dépassements du délai
initial conservés. L'exactitude reste indisponible faute de résultats connus.
TreeSHAP avait été qualifié sur v6 le 19 octobre ; aucune promotion n'a lieu.

## Qualité de l'interface

L'aperçu temporaire sépare maintenant clairement l'exploration et le choix
de source du Flow. La provenance reste visible près du sélecteur, et les
actions indisponibles sont désactivées avec une explication. La recette sur
les données réelles a aussi révélé une fenêtre SQL mal dimensionnée :
les en-têtes du tableau passaient devant et l'éditeur occupait trop peu de
hauteur. La correction ajoute un panneau opaque, un titre, une action de
fermeture en haut à droite, une zone de code défilante et une gestion du focus.

Des limites restent visibles dans le produit en service :

- « Contrôle qualité · Terminé » décrit l'invocation, alors que le résultat
  métier indique « Non évalué ». Cette juxtaposition peut faire croire à
  une validation ; elle ne doit pas être utilisée pour présenter une réussite.
- Le reçu simulé historique du 2 octobre reste près d'une nouvelle proposition.
  Il faut encore rendre la distinction entre enquête et action antérieure
  plus immédiate.
- Dans le Flow dense, le plan accessible permet de retrouver un nœud plus
  facilement que le canevas ajusté à toute la page. Le nœud utilisateur isolé
  reste volontairement visible et ne doit pas être supprimé pour la démo.

## Vérifications de la livraison

Les suites couvrent le résolveur SQL et ses autres utilisateurs DataOps,
Polars et dbt ; la délégation avec SQLite et un vrai PostgreSQL 16 ; le
transport du modèle, les réponses du Judge, leurs coûts et les diagnostics
sans contenu sensible ; enfin l'atelier, les changements de contexte et les
réponses tardives.
Les huit parcours navigateur en français et anglais contrôlent l'absence de
sauvegarde ou d'épingle implicite, ainsi que la superposition et le clavier
dans le panneau SQL. Les 41 tests unitaires UI, les contrôles de langue et
de chrome et la compilation Angular de production passent sur les fichiers
finaux. Les avertissements de budget CSS Work/Studio et dagre
ne concernent pas les changements de cette livraison.

## Déploiement et reprise

Déployer la nouvelle révision sur l'API, le frontend et les workers CPU,
DataOps et `ml-ts`, avec les processus de contrôle qui consomment les
vérifications de délégation. **Aucune nouvelle migration ni aucun nouveau
drapeau**. Ne pas rejouer l'installation Luma ni restaurer la v8.

Après déploiement :

1. Vérifier v10, les trois bindings, r37 et le brouillon Work r11.
2. Actualiser la prévision dans Work ; vérifier les 70 lignes et le graphique.
3. Ouvrir l'atelier et choisir le dataset v7 ci-dessus uniquement pour l'aperçu.
4. Relancer une enquête et examiner le résultat métier du Judge et son
   diagnostic avant d'annoncer sa qualification.
5. Consentir les deux délégations sur la publication courante. Qualifier une
   livraison signée et sa répétition, puis un tick cron borné. Conserver
   ensuite l'horaire ouvré à 8 h Europe/Paris ; ne pas laisser de cron fréquent.
6. Confirmer les brouillons, le champion v5, le shadow à 10 % / 30 s et
   l'absence de validation humaine prise par la recette.

Les captures, snapshots et journaux de tests sont conservés hors dépôt dans
`/workspace/scratch/luma-acceptance-2026-10-20/`. Aucun jeton, mot de passe ou
secret de webhook n'est ajouté à cette documentation.
