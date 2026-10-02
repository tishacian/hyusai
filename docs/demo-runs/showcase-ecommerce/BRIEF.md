# Showcase — réclamations et remboursements e-commerce

Date : 1er octobre 2026. Secteur et famille de cas d’usage retenus avec le demandeur : **commerce en ligne — réclamations et remboursements**. Le scénario détaillé ci-dessous constitue le cadrage proposé avant implémentation ; aucune application ni donnée de ce nouveau scénario n’est encore déployée.

Exigences ajoutées par le demandeur : **Document Center/OmniRAG + PostgreSQL + orchestration agentique explicable + application métier soignée + ROI démontré dans Impact**. Elles structurent le [parcours et les sources](PARCOURS-SOURCES.md) et le [protocole ROI](ROI-PROTOCOL.md). Le premier [pack de données](fixtures/README.md) prépare les documents et les tables ; il ne contient aucune mesure de gain inventée.

## La promesse métier

**Aider une responsable SAV à résoudre une réclamation de livraison et à décider d’un remboursement, avec les preuves sous les yeux.**

L’objectif est de réduire le travail de recherche et de rapprochement, accélérer la résolution et maîtriser les remboursements. La démonstration doit rendre ces actions visibles ; elle ne doit pas annoncer un gain de temps ou d’argent sans mesure et méthode de comparaison.

Le cadre proposé est **Luma Maison**, une enseigne fictive de décoration et d’équipement de la maison vendant en ligne en France. Le workspace est `agentium-showcase`. Commandes, clients, preuves, politiques commerciales et échanges sont synthétiques et cohérents entre eux. Ce scénario a ses propres fixtures, objets et vocabulaire métier. La préparation initialement envisagée avec les seeds PR to PO et Data Demo est remplacée par un seed e-commerce dédié, désormais préparé.

## Le cas principal : une livraison contestée à 420 €

Une cliente conteste la livraison de sa lampe, commande **LM-1042**, montant **420 €**. Le transporteur indique « livré ». Le bordereau de livraison comporte un code postal différent de celui de la commande. Le service client doit décider s’il demande une enquête, propose une réexpédition ou recommande un remboursement.

1. La responsable ouvre **Réclamations** depuis Work et repère le dossier à traiter.
2. Elle consulte la demande, la commande et les preuves disponibles dans une même fiche.
3. Elle lance **Analyser le dossier**. Agentium rapproche les données, applique la politique commerciale et relève la contradiction d’adresse avec ses sources.
4. Le résultat distingue les faits établis, les informations manquantes et les options de résolution. Un statut « livré » ne suffit pas à établir que la cliente a reçu le colis.
5. Agentium prépare une recommandation motivée et un message de réponse. La responsable peut les modifier, demander une information ou prendre une décision.
6. Elle valide l’action retenue. L’action de démonstration est exécutée par un service simulé, puis un reçu relie dossier, décision humaine, action et exécution.
7. Elle retrouve les preuves et l’historique sans quitter le contexte métier. Le présentateur peut ensuite ouvrir la trace technique et l’audit du même dossier.

Le moment clé est le rapprochement des deux preuves contradictoires, suivi d’une décision humaine visible et d’un reçu d’action vérifiable. La démo ne dépend pas d’une réponse libre spectaculaire du modèle.

## Trois dossiers pour la répétition

| Dossier | Données prévues | Résultat à démontrer |
| --- | --- | --- |
| Livraison contestée | 420 €, statut livré, adresse de livraison contradictoire | Contradiction sourcée, options motivées, décision de la responsable. |
| Colis perdu | 49,90 €, perte confirmée par le transporteur, aucun remboursement antérieur | Recommandation simple, validation humaine et reçu du remboursement simulé. |
| Nouvelle demande après remboursement | 89 €, remboursement déjà enregistré pour la même commande | Détection du remboursement antérieur et blocage d’une seconde action identique, sans accuser le client de fraude. |

Les montants sont des valeurs de fixtures, pas des résultats métier observés. La règle des trois dossiers doit produire un résultat reproductible ; les textes explicatifs du modèle peuvent varier.

## Le produit vu par l’utilisateur

Une application Work **Réclamations**, avec trois vues principales :

- **À traiter** : dossier, motif, montant, ancienneté, priorité expliquée et prochaine action ; filtres utiles et recherche.
- **Dossier** : demande client, commande, preuves ouvrables, analyse structurée et décision. Les informations nécessaires à la décision restent visibles ensemble.
- **Historique** : décisions, actions, reçus et liens vers les preuves. Une action préparée, approuvée et exécutée a trois états distincts.

La fiche dossier associe une synthèse de la commande et des remboursements lus dans PostgreSQL, des passages documentaires cités et ouvrables dans Document Center, puis une recommandation et une zone de décision. La progression de l’enquête doit montrer ce que les agents cherchent, ce qu’ils ont établi et ce qui manque. Un accès à Impact retrouve l’expérimentation et les mesures du même périmètre.

États proposés : **À instruire**, **En attente d’information**, **À décider**, **Résolue**. Une résolution conserve son résultat : enquête demandée, réexpédition, remboursement ou demande déjà traitée. L’application doit proposer un prochain geste utile pour chaque état.

Le présentateur utilise un seul compte owner du workspace. La différence entre conseil et décision relève du scénario et de la politique réellement appliquée ; des étiquettes de persona seules ne constituent pas une preuve d’autorisation.

## Politique de décision proposée

- L’agent peut consulter les pièces, analyser, proposer et préparer une réponse.
- Toute action monétaire du premier scénario exige une validation humaine enregistrée. Le montant de 420 € est présenté comme une exception nécessitant l’examen de la responsable.
- Un remboursement antérieur bloque le doublon ; la même validation rejouée ne crée pas une seconde action.
- Une preuve manquante ou contradictoire est explicitement signalée ; elle ne devient pas un fait établi.
- L’action réellement autorisée, son statut et son résultat sont conservés dans le reçu. Une recommandation affichée ne constitue pas une action exécutée.
- Les appels transporteur, boutique et remboursement utilisent des fixtures identifiées. Aucun remboursement financier réel n’est nécessaire à cette démo.

Ces règles sont des exigences à implémenter et à vérifier. La présence d’un bandeau de mandat ou d’un bouton de validation ne prouve pas, à elle seule, leur application.

## Les capacités Agentium à raconter

Le parcours métier est le fil rouge. Les étapes de construction montrent ensuite comment il fonctionne : sources commandes/livraisons/remboursements, politique commerciale documentée, rapprochement et nettoyage des données, système composé de skills, mandat, décision humaine, action simulée, trace, audit et Impact.

Une extension DataOps/ML pourra porter sur **le risque de dépasser le délai de résolution du SAV**, à partir d’un historique synthétique distinct des trois dossiers. Un modèle entraîné et évalué devra avoir son dataset, sa séparation entraînement/test, ses métriques et sa version. Un tri par règles doit rester présenté comme un tri par règles. Ce volet sera cadré après validation du parcours métier principal.

Dans Impact, séparer le montant des commandes et remboursements, le coût enregistré de l’exécution, les hypothèses de valeur déclarées et les éventuelles mesures observées. Un remboursement bloqué ne devient pas automatiquement une économie attribuable à Agentium.

Le ROI demandé sera fondé sur un traitement manuel et un traitement assisté réellement chronométrés, à qualité comparable, avec une convention de coût horaire affichée et les coûts Agentium couverts. Il mesure une performance sur les données de démonstration. La conversion du temps en euros est une valorisation de capacité ; un gain financier réalisé exige une preuve financière supplémentaire. Le détail, les formules et les conditions d’affichage sont dans le protocole ROI.

## Qualification visuelle et utilisateur

La répétition part de Work, en français, avec un dossier neuf. À 1440 px et 1024 px, en thèmes clair et sombre, vérifier : lisibilité, hiérarchie, clavier, noms accessibles, défilement, chargement, erreurs, preuves ouvrables, retour au dossier et absence de jargon technique dans la décision métier.

La preuve de réussite est : **le dossier sélectionné conduit à une décision compréhensible, son action conserve le bon statut, et le reçu retrouve les mêmes dossier, commande et exécution**. Vérifier aussi le cas sans preuve, le doublon, un échec de l’action et une double validation. Les données de démonstration restent identifiées sur les vues concernées.

La prochaine étape est de confronter ce cadrage aux composants Experience et aux contrats d’exécution existants, puis de définir le premier parcours réalisable. Aucun seed historique ne doit être lancé pour préparer ce nouveau scénario par défaut.

La livraison comprend le [runbook opérateur](OPERATOR-RUNBOOK.md) et le [rapport de QA](QA-2026-10-02.md). Les sources sont indexées dans Showcase ; l’activation du nouveau runtime et le benchmark humain restent à réaliser après déploiement.
