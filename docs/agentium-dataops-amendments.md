# Amendements demandés au plan DataOps et état de la branche

Ce document accompagne le [plan DataOps d’origine](agentium-dataops-plan.md),
restauré à l’identique de `ad10dbc2`. Il consigne les demandes de cette conversation
et les écarts de l’implémentation `45ccc915`. Le code n’est pas une autorité qui
permet de redéfinir après coup un critère de recette.

## Origine des amendements

Dans cette conversation, l’utilisateur a demandé, avant l’implémentation :

- finir la restructuration puis S0 et la reprise de D0 sur les nouveaux packages ;
- conserver le moteur de préparation, le Flow, son interface et le stockage en parts ;
- ajouter une promesse de service par System, des actifs documentaires/référentiels
  versionnés et un juge typé, avec une approbation humaine gouvernée ;
- repousser Kubernetes éphémère, Spark, D6 et la plupart des connecteurs jusqu’à
  un besoin et un volume mesurés ; conserver Helm pour le déploiement permanent ;
- utiliser le workspace Showcase sans exiger de client pilote, avec un scoring
  de 2 à 3 millions de lignes par jour et plusieurs centaines de pages/images ;
- laisser ensuite narration de côté ; Gemini via OpenRouter sera raccordé plus tard.

Ces demandes expliquent les extensions au périmètre du document d’origine. Elles
ne prouvent ni leur complétude ni leur conformité : leur recette est distincte.
Les décisions D-1 à D-25 et les règles de fusion restent dans le plan d’origine.
Aucune fusion, modification de VM ou activation de service n’est autorisée par
ce document.

## Plans et contrats distincts

- [Juge typé](agentium-typed-judge-plan.md) : contrat proposé, état du code et
  critères de qualification ; ce document a été écrit pendant l’implémentation,
  pas avant elle. Aucun fournisseur ni corpus réel n’est qualifié.
- [Actifs et promesses](ops/service-contracts.md) et
  [budgets](ops/service-window-budget.md) : contrat de la nouvelle extension,
  incluant responsable, fraîcheur, complétude, revue et reçu vérifiable.
- [Scoring Showcase](agentium-showcase-scoring-contract.md) : recette visée et
  destination Work, qui ne vaut pas intégration à un système client externe.
- [Narration](agentium-showcase-narration-contract.md) : brouillon différé,
  sans activation ni promesse de livraison dans le lot actif.

## Écarts constatés, à fermer par des preuves

La [revue de la branche](codex-review-dataops-typed-judge.md) conserve les constats
sur `45ccc915`. Son historique ne doit pas être réécrit pour effacer les erreurs.

| Domaine | État et critère restant |
|---|---|
| R0/S0/D0 | Structure reprise et garde-fous en code ; le déploiement, son build-info et HANA vivant ne sont pas qualifiés par les tests locaux. |
| D1a | Opérations et actions implémentées ; écarts de spec, typage, formules et corpus golden signalés par la revue. D1a n’est pas déclaré intégralement reçu. |
| D1b | API/Flow présents ; publication et drapeaux nécessitent les corrections de la revue puis leurs tests. |
| D2 | Formulaires et inspecteurs présents ; palette, ateliers et recette navigateur du plan restent à livrer. D2 n’est pas terminé. |
| D3 | Versions Delta immuables et scoring en batches présents ; les lecteurs historiques matérialisent encore un Parquet unique, sans prouver une lecture multi-parts native partout. Téléchargement dataset et purge restent à recevoir. D3 n’est pas terminé. |
| Actifs/promesses/juge | Extension demandée, implémentée sur la branche et soumise à la revue ; aucun statut de production ni qualification fournisseur ne découle du nombre de tests. |
| Narration | Différée. Le catalogue et les chemins actifs doivent respecter ce choix. |
| D4/D5/D6/D7/I1/I2 | Différés par demande explicite ; leur absence reste visible dans le plan d’origine et n’est pas présentée comme une implémentation. |

Les suites ciblées du premier lot ne remplaçaient pas une suite complète. Les
rapports de tests, les comparaisons avec la base et les constructions d’images
seront consignés dans le suivi de correction de la revue. Les mesures locales
antérieures de volume ne qualifient ni la branche corrigée, ni une VM/limite
cgroup, ni S3. La décision sur HANA Showcase reste ouverte avant déploiement :
certificat valide, démonstration explicite ou exception TLS précise. Le
durcissement n’est pas retiré pour rétablir implicitement une démonstration.
