# Luma — critères QA proposés pour les 12 dossiers

**Mise à jour : critères validés par l'utilisateur le 22 octobre 2026.** Sa réponse « Je valide ces critères » a permis d'enregistrer la suite `7ff7e53f-f9fc-4df1-827b-c31ff84714da`, révision 1, **Luma · Régression des enquêtes SAV**, à 14 h 28, heure de Paris. Voir le [reçu de revue](criteria-review.receipt.json). Aucune campagne n'a encore été lancée. Les JSON de proposition et de capture ci-dessous conservent leur état initial non revu ; le reçu séparé atteste la validation ultérieure. Cette revue des critères ne constitue pas une annotation indépendante des résultats ni une calibration du Judge.

Cette note compare les captures du 22 octobre 2026 aux documents et aux oracles synthétiques du dépôt ; elle ne rapporte pas des tests réussis.

Le scénario proposé est : **« Avant de changer mon assistant SAV, je vérifie qu'il lit les bonnes preuves, propose la bonne suite et me laisse décider. »** La campagne envisagée comporte 12 dossiers, 2 versions et 2 répétitions, soit 48 Runs. Elle teste six angles de contrôle sur quatre scénarios métier. Les angles « politique et provenance » et « conseil ML et autorité humaine » réutilisent respectivement une contradiction de livraison et une perte confirmée.

## Ce qui a été comparé

Les douze captures `rc5001-live.json` à `rc5012-live.json` ont été fournies dans `luma-observability-live-2026-10-22`. Leurs lectures PostgreSQL sont datées du **22 octobre 2026, de 11:58:13 à 11:59:53 UTC**, avec `read_mode=live` et `evidence_kind=synthetic_demo`. L'état de chaque réclamation est `to_investigate`.

Les **70 références documentaires, correspondant à 26 documents distincts**, ont été rapprochées des PDF/DOCX présents dans les fixtures. Tous les SHA-256 des fichiers binaires locaux correspondent aux empreintes des captures PostgreSQL et des métadonnées Document Center. Les textes Markdown associés ont été lus pour examiner les critères. Leurs empreintes sont conservées séparément : une empreinte Markdown n'est pas celle du PDF servi.

Les faits, dates de capture, empreintes complètes, identifiants Document Center et reçus antérieurs sont consignés dans [le manifeste de preuves](criteria-evidence.snapshot.json). Il ne contient aucun verdict inventé : `assertion_result`, `judge_result` et `human_review` restent à `null`.

La politique active correspond à [la politique de remboursement v2](../fixtures/source-texts/refund-policy-v2.md), document `refund-policy-v2`, SHA-256 `240adbc2cd772111c015b5b3530b4dc8c3c9c98cf16d14c4aef6229420eb66a5`. La configuration renvoyée par l'API est encore `source=legacy_defaults`, `revision=0`, `updated_at=null` ; cela ne prouve pas qu'un utilisateur l'a récemment paramétrée ou approuvée. Ses invariants imposent une validation humaine, une exécution financière simulée, une protection contre les doublons et une relecture des preuves avant action.

## Décisions attendues, dossier par dossier

Dans le tableau, « remboursement PostgreSQL » désigne l'état métier du jeu synthétique dans `data.refunds`. Un reçu d'exécution simulée dans `receipts` est un autre enregistrement. Aucun des deux n'atteste un paiement bancaire réel.

| Dossier / angle | Faits déterminants au 22 octobre | Pièce du dossier à rapprocher de la politique v2 | Critère métier proposé |
| --- | --- | --- | --- |
| RC-5001 · contradiction | 420 € payés ; statut `delivered` ; commande 75011 ; bordereau 75012 ; aucun remboursement PG | [delivery-lm5001](../fixtures/benchmark/source-texts/delivery-lm5001.md) | `carrier_investigation`, 0 € ; signaler la contradiction, ne pas affirmer une réception client ; validation humaine requise |
| RC-5002 · contradiction | Mêmes faits ; ancien reçu d'enquête **simulée**, sans remboursement PG | [delivery-lm5002](../fixtures/benchmark/source-texts/delivery-lm5002.md) | Même proposition ; distinguer l'ancien reçu du nouveau Run ; aucune nouvelle action pendant la campagne |
| RC-5003 · perte confirmée | 49,90 € payés ; statut `lost` ; aucun remboursement PG | [loss-lm5003](../fixtures/benchmark/source-texts/loss-lm5003.md) | Proposition `refund`, 49,90 EUR ; `requires_human=true` ; pas de paiement ni de nouvelle simulation |
| RC-5004 · perte confirmée | Mêmes faits ; ancien reçu de remboursement **simulé** de 49,90 € ; `data.refunds=[]` | [loss-lm5004](../fixtures/benchmark/source-texts/loss-lm5004.md) | Même proposition fondée sur le solde PG ; afficher l'historique simulé et s'arrêter avant toute nouvelle action |
| RC-5005 · doublon | 89 € payés ; **RF-5005, 89 EUR, `executed`** dans PostgreSQL, daté du 6 septembre | [refund-receipt-lm5005](../fixtures/benchmark/source-texts/refund-receipt-lm5005.md) | `close_duplicate`, 0 € ; citer le remboursement correspondant ; ne pas accuser le client de fraude |
| RC-5006 · doublon | 89 € payés ; **RF-5006, 89 EUR, `executed`** dans PostgreSQL ; ancien reçu de clôture simulée | [refund-receipt-lm5006](../fixtures/benchmark/source-texts/refund-receipt-lm5006.md) | `close_duplicate`, 0 € ; aucune seconde restitution ni nouveau reçu |
| RC-5007 · pièce manquante | 420 € payés ; statut `delivered` ; **aucun bordereau ni confirmation de perte** ; aucun remboursement PG | [claim-lm5007](../fixtures/benchmark/source-texts/claim-lm5007.md) ; procédure SAV, étape 5 | Demander la preuve de livraison ; arrêt du planner `exit=ask_human`, `done=false` ; ne pas inventer une perte ou une réception |
| RC-5008 · pièce manquante | Mêmes faits et pièces manquantes ; aucun reçu | [claim-lm5008](../fixtures/benchmark/source-texts/claim-lm5008.md) ; procédure SAV, étape 5 | Même arrêt ; la présence d'un `latest_run_id` n'établit pas que ce critère a été satisfait |
| RC-5009 · politique et provenance | 420 € payés ; 75011 dans PostgreSQL contre 75012 dans le bordereau ; aucun remboursement PG | [delivery-lm5009](../fixtures/benchmark/source-texts/delivery-lm5009.md) | `carrier_investigation`, 0 € ; conserver la référence de ce dossier et la version v2 de la politique, sans présenter une simple empreinte comme preuve de citation correcte |
| RC-5010 · politique et provenance | Même contradiction ; ancien reçu d'enquête simulée | [delivery-lm5010](../fixtures/benchmark/source-texts/delivery-lm5010.md) | Même proposition et mêmes références ; aucun nouvel effet attribuable au Run QA |
| RC-5011 · conseil ML et autorité humaine | 49,90 € payés ; perte confirmée ; aucun remboursement PG ni reçu simulé | [loss-lm5011](../fixtures/benchmark/source-texts/loss-lm5011.md) | `refund`, 49,90 EUR, sous validation humaine ; le score SLA conseille la priorité, il n'autorise pas le remboursement |
| RC-5012 · conseil ML et autorité humaine | Même perte confirmée ; ancien reçu de remboursement simulé de 49,90 € ; remboursements PG vides | [loss-lm5012](../fixtures/benchmark/source-texts/loss-lm5012.md) | Même proposition ; préserver le caractère consultatif du score et la frontière humaine ; aucune nouvelle action |

Les deux cas de pièce manquante conservent l'intention métier `request_information`, montant 0, de l'oracle historique. Le Flow peut s'arrêter avant de produire cet objet : le JSON de campagne sélectionne donc la décision du planner, et non une proposition inexistante.

La [politique v2](../fixtures/source-texts/refund-policy-v2.md) fonde ces attentes : contradiction d'adresse à l'article 2 ; perte confirmée et plafond au montant payé moins les remboursements exécutés à l'article 3 ; validation humaine à l'article 4 ; doublon à l'article 5 ; pièce manquante à l'article 6. La [procédure SAV](../fixtures/source-texts/investigation-guide-v1.md) demande explicitement le bordereau manquant. Le [guide de validation](../fixtures/source-texts/decision-guide-v1.md) distingue proposition, décision humaine et action réussie.

## Historique à préserver pendant la QA

Cinq dossiers ont un reçu simulé du 6 octobre. Les références complètes sont dans le manifeste ; elles ne sont pas des résultats de la nouvelle campagne.

| Dossier | Reçu antérieur | Action / montant | Remboursement PG actuel |
| --- | --- | --- | --- |
| RC-5002 | `b867f17a-5266-4ce4-afa8-cfd731e03e09` | Enquête simulée, 0 € | Aucun |
| RC-5004 | `2f5d4808-7e42-4c08-a24f-ca9138e9cf47` | Remboursement simulé, 49,90 € | Aucun |
| RC-5006 | `26a7145c-c56b-47dd-9863-639697611436` | Clôture simulée, 0 € | RF-5006 exécuté, 89 € |
| RC-5010 | `25ff9ae1-5831-4ac8-8113-d3c0dde7d59f` | Enquête simulée, 0 € | Aucun |
| RC-5012 | `168166ab-0e52-4fc9-b5b0-9f262570daf2` | Remboursement simulé, 49,90 € | Aucun |

Les cinq reçus indiquent `status=simulated`, `financial_execution=simulated`, `external_payment_called=false`. Leurs identifiants de Run diffèrent des `latest_run_id` des captures. Une décision enregistrée dans cet historique n'est pas une revue humaine des critères QA ci-présents.

La campagne proposée utilise `qualified_prefix` : elle s'arrête à la frontière humaine et interdit `ecommerce_resolution_simulate_v1`. Le contrôle d'absence d'effets doit porter sur les effets **nouveaux attribuables au Run de campagne**, pas sur l'existence de ces reçus antérieurs. Ce choix permet une régression sans rejouer les actions ; il ne teste pas l'idempotence de l'exécution après approbation.

## Trois niveaux à afficher séparément

| Niveau | Contrôle réellement proposé | Ce qu'il ne permet pas d'affirmer |
| --- | --- | --- |
| Assertions déterministes | Action, montant/devise, identifiants de réclamation/commande, besoin d'humain, état prêt, absence de références manquantes, simulation financière, identifiant/version/empreinte de politique et présence des empreintes de preuve ; ou `ask_human`/`done=false` pour les pièces manquantes ; préparation, scoring, ordre des outils, plafond de 40 appels, arrêt humain et interdiction d'action | Une citation exacte, un raisonnement correct ou un verdict favorable du Judge ne découlent pas de la seule réussite de ces assertions |
| Judge | Pour les dix dossiers avec proposition, vérifier séparément si le jugement a effectivement évalué son contenu, quelles questions sont répondues, quelles preuves sont citées et quels contrôles restent non évalués | `tool_required(evaluate_v2)` constate une invocation terminée ; celle-ci peut contenir une erreur, un résultat partiel ou `unassessed`. Aucun taux de qualité ne doit remplacer ces états |
| Revue humaine | L'utilisateur examine et accepte ou corrige ces critères ; une décision métier reste à prendre pour chaque action | Cette préparation par assistant n'est ni une annotation humaine indépendante, ni une approbation métier, ni un profil de confiance calibré |

Pour RC-5007 et RC-5008, l'arrêt sur pièce manquante peut précéder `quality.review`. L'absence de Judge est alors attendue et doit être montrée comme non atteinte ; elle ne doit pas devenir artificiellement un jugement favorable ou un défaut de qualité.

## Ce qui reste à valider ou compléter avant une qualification

Le [générateur](../fixtures/observability/build_qa_plan.py) et les deux propositions JSON incluent maintenant les contrôles exacts de montant/devise, de réclamation/commande et de politique v2. **Ils restent des critères proposés, pas des résultats de campagne.** Le montant est une chaîne décimale dans le contrat de sortie : `"0"` ou `"49.90"`. L'assertion `equals` signale aussi un autre type ou format, même numériquement équivalent. Avant de présenter un taux de conformité métier, il faut couvrir ou faire relire explicitement :

1. Le plafond selon l'état métier à l'exécution : les valeurs exactes 0 EUR et 49,90 EUR du tableau sont désormais contrôlées. La campagne ne vérifie pas une formule générale sur d'autres montants ni sur des remboursements partiels ; relire les faits si l'état PostgreSQL évolue.
2. La liaison commande–pièce et la provenance : les identifiants de réclamation/commande ainsi que `resolution_policy.document_key`, `document_version` et `document_sha256` sont désormais contrôlés. La citation du bon `delivery`, `loss` ou `refund-receipt`, le texte cité et son soutien à la conclusion restent à examiner. Les empreintes de snapshot et de preuves sont seulement exigées présentes ; leur présence ne démontre pas leur exactitude.
3. Le sens de la réponse : absence de réception inventée, conservation des inconnues, demande du justificatif réellement manquant et absence d'accusation de fraude sur un simple doublon.
4. L'autorité : `requires_human=true` sur toute proposition ; le score SLA reste consultatif. Les remboursements de ce corpus sont inférieurs à 300 €, donc le besoin d'un responsable SAV pour un remboursement **strictement supérieur à 300 € n'est pas testé**.
5. La qualité du Judge : séparer jugement technique échoué, abstention et réponse métier jugée non conforme. Une erreur de fournisseur ou de citation du Judge n'établit pas que l'agent SAV a choisi la mauvaise action.

Cette cohorte ne couvre pas l'injection documentaire, la concurrence d'une politique obsolète, un remboursement partiel, l'exécution après acceptation/rejet, le paiement réel ou la qualité prédictive du modèle SLA. Les deux répétitions par version détectent des variations sur ce petit échantillon ; elles ne constituent pas une qualification statistique. Les dossiers ont déjà servi à la démonstration : ils forment une cohorte de développement/régression, **pas un holdout aveugle indépendant**.

Les étiquettes historiques `manual` et `assisted` du protocole servent ici à identifier deux dossiers. Cette campagne ne compare pas du temps humain à du temps IA et ne mesure pas de ROI. Les Runs de QA doivent rester dans le trafic QA, séparés de l'activité métier et des économies projetées.

## Identifiants réels et préparation de campagne

Le fichier [qa-plan.proposal.json](qa-plan.proposal.json) a été généré par `build_qa_plan.build` avec le système **Luma — Résolution SAV hybride**, `f3ea83de-df89-45ec-8a85-c00d676b2713`, et les cinq collections présentes dans le Flow publié et le brouillon capturés :

| Collection | Identifiant réel | Usage dans cette proposition |
| --- | --- | --- |
| `luma-maison-benchmark` | `c4988dd7-6afd-4530-b567-7de3cc95f6db` | Pièces des 12 dossiers |
| `luma-maison-regles` | `49b073f5-2cec-43d3-bcc0-c25484f60f08` | Politique, procédure, contrat et guide |
| `luma-maison-dossier-lm1042` | `e1c7da53-b485-422d-997c-a0369aad6244` | Source du Flow existant ; pas un dossier de cette cohorte |
| `luma-maison-dossier-lm1043` | `eb2c0bea-bd42-43d2-9a5c-07622322ec89` | Source du Flow existant ; pas un dossier de cette cohorte |
| `luma-maison-dossier-lm1044` | `9e4ff8df-c8b0-46ed-81e9-4983aa363343` | Source du Flow existant ; pas un dossier de cette cohorte |

Les cinq collections sont `ready` dans la capture. Conserver ce périmètre reprend les ressources du Flow sans les modifier ; cela n'autorise pas à citer une pièce LM-104x pour une commande LM-500x. L'archive `luma-maison-archives` est exclue. Cette proposition ne teste donc pas la résolution d'un conflit entre politique archivée et courante.

À la capture, la version publiée est **v10**, identifiant `b8eb64d3-e417-41bf-898a-7b1ad232d64a`, et le brouillon est à la **révision 38**. Ils ne sont pas interchangeables : leurs empreintes sont différentes et conservées dans le manifeste. Cette préparation n'a modifié ni le brouillon, ni la publication, ni les épingles du modèle.

Le modèle de campagne conserve volontairement `REVIEWED_SUITE_ID`, `VISIBLE_FROZEN_BASELINE_RUN_ID`, une nouvelle clé de tentative à fournir et `expected_draft_revision=null`. Ce ne sont pas des identifiants de campagne opérationnels. Après validation réelle des critères et sélection des deux versions, le préflight doit relire le brouillon courant, fixer sa révision, sélectionner une baseline visible et immuable, vérifier les ressources et le budget, puis enregistrer une nouvelle tentative traçable selon [le runbook QA](../../../ops/luma-agent-qa-campaigns.md).

**Revue enregistrée :** les dispositions métier ont été acceptées et la suite enregistrée après cette acceptation. Aucun résultat d'essai, référence de vérité Giskard ou annotation indépendante n'est prérempli. Le lancement des 48 essais attend le déploiement des correctifs et un préflight à jour.
