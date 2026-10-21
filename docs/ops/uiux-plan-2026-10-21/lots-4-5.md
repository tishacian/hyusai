# Lots 4 et 5 — état réel au 21 octobre 2026

Ce bilan décrit le travail local non commité. Il ne vaut ni recette utilisateur,
ni validation sur la pile de production, ni autorisation de déploiement.

## Lot 4 — départ vierge

Les contributions reconstruites ont été conservées : activation administrateur
sans activation implicite des espaces existants, page d’état d’accès, inventaire
des prérequis, import d’exemple, assistant adressable et progression persistée
(migration 142), contrat d’action Studio, aperçu sur un résultat identifié, reçu
de déploiement avec canal/audience et ouverture dans Work. Les specs navigateur
71 à 75 couvrent ces parcours, dont 71 sur la pile de recette avec création puis
suppression d’un espace dédié.

Aucune nouvelle validation avec trois comptes réels ni sur un second corpus n’a
été faite dans ce passage. Les tests navigateur locaux de ce lot restent à
exécuter sur le bundle final. Il ne faut donc pas déclarer la recette du lot 4
terminée sur la seule présence de ces fichiers.

## Lot 5 — compléments implémentés

| Critère | Implémentation locale | Preuve et limite |
| --- | --- | --- |
| Flow publié en lecture | Chargement de la version publiée indépendamment du brouillon ; bouton Modifier recharge le brouillon ; mutations du store, autosauvegarde, alignement du corps haché, validation POST et raccourcis bloqués en lecture. | Tests du service de persistance, y compris brouillon malformé et absence d’écriture. Test navigateur zéro écriture FR/EN ajouté à 53, non exécuté. |
| Diagnostics attribués | Chaque ligne du panneau de validation porte sa version publiée ou sa révision de brouillon. | Contrats UI mis à jour ; bundle final et recette visuelle à vérifier. |
| Judge guidé | Identité dérivée System/nœud, proposition de version, sélecteurs des étapes/Skills du graphe, chemins JSON issus du contrat de sortie, JSON avancé validé, erreur explicite de lecture du catalogue. | Tests des identités, versions et chemins. Le résultat « non évalué » demeure distinct du contrôle terminé dans les helpers de résultat existants, vérifiés avec le lot 6. |
| Journal de livraisons accepté | Endpoint GET autorisé, ACL de Run avant pagination, couverture `accepted_only`, distinction acceptation/état d’exécution, aucune donnée d’entrée ni secret, lien Run ; disponible en lecture via `?tab=triggers` et dans l’inspecteur. | Tests API ajoutés pour isolation, pagination, absence de données sensibles et coupe-circuit. Ils ont été collectés mais pas validés : TestClient bloqué par le sandbox réseau avant le premier test existant. |
| État des Capabilities | Déclarée, Systems associés, compatibilité, appelabilité et dernière invocation sont séparés ; toute valeur non attestée est inconnue. Le backend expose déclaration, compte réel et dernière invocation observée. | Suite capability-view passe. Les dimensions compatibles/appelables restent inconnues si la projection ne fournit pas de preuve ; elles ne sont pas déduites de l’association à un System. |
| Conflit Studio | Trois versions affichées après 409 : base, locale et collègue. Choix explicite garder la leur/réappliquer ; fusion des changements disjoints, signalement des collisions et réordonnancements ; restauration historique également préservée en cas de conflit. | Suite de fusion pure passe. Tests navigateur FR/EN ajoutés à 75, non exécutés. |
| Réglage/intégration | Palette affichant les prérequis de connexion, intégration spécialisée, horaire et délégation avant le choix. | Chaînes FR/EN ; recette visuelle et compréhension par utilisateur à faire. |
| Création de Skill | Relecture des entrées/sorties, obligations/options/types ; lien vers un System après création avec mention du raccordement distinct. | Suite skill-authoring passe ; navigateur à faire. |
| Version d’application | Brouillon et Release en service affichés côte à côte avec versions et contenu consultable. Retour de version confirmé avec cible/canal/audience ; CAS conservé ; après conflit, état déployé relu et retour bloqué si la relecture échoue. | Suite studio.spec passe, contrat de confirmation/CAS/relecture conservé. Test navigateur de confirmation et conflit ajouté à 75, non exécuté. |

## Frontière prévue : registre complet et rejeu dans un chantier séparé

Le plan pp. 25–26 distingue la première version du journal, fondée sur les
`TriggerEventClaim` et Runs déjà persistés, du chantier backend séparé ouvert par
une note de conception. La première version est codée ; le chantier complet
reste à réaliser. La note [trigger-delivery-registry.md](../../design/trigger-delivery-registry.md)
définit la proposition de table append-only, rétention, minimisation des données,
autorisation et reçu de rejeu. Elle n’est pas une migration ni un endpoint de
rejeu. Doublons, livraisons ignorées/rejetées, historique par hook et rejeu ne
sont pas disponibles dans cette première version, conformément au découpage du
plan. Cette extension relève du chantier backend séparé ; son absence ne bloque
pas les critères de la première version du journal définis pour ce lot.

## Vérifications réalisées et reprises nécessaires

Commande finale ciblée exécutée depuis `frontend-ng` :

```sh
FLOW_UNIT_FILTER=experience/studio/studio.spec,flow-builder-ui-contract,studio-conflict,flow-persistence.service,flow-triggers-panel,capability-view,skill-authoring,typed-judge-guidance,work-language FLOW_UNIT_REPORTER=tap npm run test:unit
```

Résultat : **9 fichiers de tests passent, 0 échec**, journal
`/tmp/uiux-lot45-regression-final.log`. Le runner compte les fichiers assemblés,
pas le nombre de cas individuels. Les deux régressions de contrat statique
signalées par la suite globale ont été corrigées sans enlever les contrôles de
mutation, de confirmation ou de comparaison de version. Le doublon de clé
`experience.editor.lifecycle.read_error` est corrigé : une traduction FR, une EN.

Le test API `test_systems_event_trigger_api.py` a collecté 13 cas puis bloqué au
premier GET préexistant. Le diagnostic partagé identifie les sockets de réveil
asyncio/TestClient bloquées par le sandbox sans accès réseau. Le processus a été
arrêté ; **aucun résultat backend vert n’est revendiqué**. Le coordinateur peut
relancer avec les permissions réseau appropriées.

La tentative de lancement des specs Playwright 53 et 75 a été interrompue avant
l’exécution de la commande. Aucun journal ni capture de cette tentative n’existe.
Les specs d’édition existantes 16, 30, 32 (forecast), 49, 50 et 53 ont été adaptées
au bouton explicite Modifier ; elles doivent être rejouées, avec les cas de
lecture, conflit et rollback nouvellement ajoutés. Un build de développement a
été annoncé vert par l’agent lot 6 avant les derniers correctifs ; le build final
et les contrôles globaux sont centralisés par le coordinateur. Aucun build
supplémentaire n’a été lancé ici.

Restent donc à vérifier : backend autorisé, navigateur local sur bundle final,
non-régression Luma, clavier/320 px/lecteur d’écran et panel réel prévu au lot 9.

## Correctif P0 complémentaire — promotion du brouillon libre

La création d’un System depuis le Flow utilise désormais `STRICT` et le délai
partagé de 30 secondes. Une erreur réseau, 502/504, un dépassement de délai ou une
réponse vide produit une issue inconnue, jamais un échec confirmé. Le bouton et
la méthode de création refusent tout renvoi tant que cette issue persiste, y
compris après fermeture puis réouverture du dialogue. Nom, objectif et Flow
restent présents. Le lien de vérification ouvre le catalogue dans un nouvel
onglet pour garder la saisie initiale ouverte. Une création confirmée dont le
Flow est incohérent ou dont la révision locale a déjà changé interdit également
une deuxième création. Un refus explicite 400 reste corrigeable.

Vérification complémentaire : `flow-persistence.service` et
`flow-builder-ui-contract` passent (2 fichiers, 0 échec), journal
`/tmp/uiux-promotion-final.log`. Les cas couvrent réseau, 502, 504, délai, réponse
vide, conservation de saisie, réouverture, refus confirmé et création déjà
confirmée. Aucune nouvelle vérification navigateur n’est revendiquée.

Audit d’import : aucun composant UI n’appelle actuellement `importSystem` du
service canonique. L’import du Flow est `importJson`, une modification locale ;
il ne crée pas de System côté serveur.
