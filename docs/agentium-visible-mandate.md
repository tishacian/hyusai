# Le mandat dans les écrans Agentium

Un utilisateur peut lire ce que son System est configuré pour utiliser, identifier une demande d’accord et comprendre une action refusée. Les explications d’exécution ouvrent le Run concerné, jusqu’à l’événement sélectionné.

## Parcours livré

| Point d’entrée | Ce que voit l’utilisateur | Preuve accessible |
|---|---|---|
| Conversation liée à un System | Mandat actuel en tête de conversation, puis contrôles sous chaque réponse | Le Run de ce message, jamais le dernier Run du System |
| Résultat d’une application Work | Résumé des contrôles enregistrés, attente ou refus | Inspection dans l’application ; accès au Cockpit selon le profil existant |
| Work → validations | Demande et données soumises avant les boutons de décision | Identifiant de décision attendu, version du Flow, puis suivi du même Run après réponse |
| System → Contexte | Éditeur du mandat du draft : sources, Skills, modèles, délégations existantes, revue et limites | Diff avec la référence publiée, enregistrement relu et validation côté serveur |
| System → Gouvernance | Matrice des événements conservés sur quatre Runs récents visibles | Sélection d’un Run et d’une facette, puis ouverture de l’événement exact |
| Détail d’un Run | Sources → opérations et limites → sortie et revue | Règle, état, date, opération et références autorisées |

La revue d’une demande n’est pas une approbation. Une modification de la demande, des données soumises ou de la version du Flow invalide la revue. Une décision indisponible ne peut pas être envoyée depuis l’interface. La route canonique conserve le contrôle d’autorisation et de concurrence grâce à `expected_decision_id`.

Après un accord, le message indique que la décision est enregistrée. Les événements suivants établissent si le traitement a effectivement repris et quels effets ont eu lieu.

## Lecture des preuves

- Une configuration actuelle n’est jamais attribuée rétroactivement à une ancienne exécution.
- Chaque nouvelle publication fige le contenu complet de la ControlPolicy dans le contrat d’exécution, y compris l’absence explicite de policy. Les Runs conservent ce contrat dès leur création puis enregistrent le mandat appliqué dans leurs checkpoints au démarrage.
- Un Run en file d’attente, en revue humaine ou en pause de débogage reprend avec cette même policy. Les délégations conservent chacune le contrat de leur version publiée. Les droits actuels du membre et des sources restent vérifiés.
- Les versions historiques sans policy figée conservent leurs contrôles historiques ; leur mandat n’est pas reconstruit rétroactivement. Restaurer leur Flow garde le mandat actuellement identifié dans le draft. Une version possédant un snapshot restaure exactement ce snapshot.
- Un mode d’observation signale l’écart sans prétendre qu’il a bloqué l’action.
- Un dépassement n’est présenté comme bloquant que si l’arrêt correspondant est conservé.
- Une approbation humaine exige une confirmation humaine persistée ; un statut automatique ne la remplace pas.
- Une provenance documentaire exige les références concordantes du registre d’invocations et des checkpoints. Un emplacement de stockage configuré n’est pas une preuve.
- L’absence de trace reste une absence de trace. La matrice ne calcule pas un taux de conformité à partir de cellules vides.

Les détails techniques se déplient après l’explication lisible. Les résultats retenus, prompts et adresses internes de stockage ne sont pas copiés dans cette projection.

Les délégations s’appuient sur les liens persistés entre Runs, et non sur la seule présence d’un nœud dans le Flow. Un sous-Run et sa porte humaine ne sont exposés qu’après vérification indépendante de leurs droits. La projection présente jusqu’à vingt sous-Runs directs autorisés.

## Implémentation

Les deux lectures supplémentaires sont `GET /api/v1/systems/{id}/mandate` et `GET /api/v1/runs/{id}/mandate`. Elles réutilisent les contrôles canoniques de visibilité des Systems, Runs, décisions et invocations. Le changement de workspace annule les lectures et les réponses tardives ne repeuplent pas l’écran.

Le résumé du System porte sur les huit Runs récents accessibles ; la matrice en présente quatre. Les sélections sont conservées dans les paramètres `mandateRun`, `mandateFacet` et `mandateEvent` des routes existantes. Les contrôles continuent d’être suivis pendant une attente humaine ou une délégation durable.

Les composants sont partagés entre Chat, Work, System et Run. Ils utilisent les tokens du Cockpit et les dictionnaires FR/EN. Aucun CSS de marque NAWA, moteur de permissions ou moteur d’orchestration supplémentaire n’est introduit.

## État de la livraison

Développement dans `codex/mandate-experience`, à partir de `origin/demo/agentic` (`c432f2dc`). Cette version n’est pas déployée. Les captures de recette montrent les composants compilés avec des données synthétiques locales ; elles ne constituent pas des preuves d’exécution en production.

L’éditeur M4 est disponible dans **System → Contexte**, pour les membres autorisés à administrer le System et lorsque la publication de Flow est activée. Les autres membres conservent le résumé de lecture.

1. Ajuster les collections, Skills et modèles proposés, les délégations déjà autorisées, les conditions de revue et les limites de coût, durée et tokens.
2. Relire le diff avec la version publiée et confirmer sa revue avant **Enregistrer le mandat dans le draft**.
3. **Valider le draft enregistré** vérifie la structure, les références configurées et la compilation. La disponibilité du fournisseur reste distincte et non attestée par cette analyse. Les tests sur des Runs restent explicitement « non vérifiés » tant qu’ils ne sont pas exécutés.
4. **Relire et publier dans le Flow** ouvre la publication existante. Un changement de policy constitue un changement de version, même à graphe identique. Une modification sensible demande l’accusé de revue existant.

Le même numéro de révision protège les écritures du Flow et du mandat. L’empreinte de la policy protège également le premier enregistrement d’un mandat historique. Un conflit impose de recharger et relire ; le navigateur ne remplace pas un draft concurrent. La publication vérifie l’empreinte du contrat relu afin de détecter un changement intervenu après le diff.

L’éditeur ne modifie pas la ligne ControlPolicy partagée. Les actions avancées et contrats de délégation existants sont conservés. Une liste vide de modèles, Skills ou collections ne signifie pas « tout interdire » : les autres contrôles du workspace continuent de s’appliquer. Le mode compatibilité, observation ou application des règles est affiché explicitement.

Les commandes sont `GET/PUT /api/v1/systems/{id}/mandate/draft` et `POST /api/v1/systems/{id}/mandate/draft/validate`. Elles partagent le draft, les autorisations et la publication existants. La migration additive **108** ajoute `system_flow_drafts.control_policy_snapshot` ; aucun nouveau moteur, flag ou stockage de versions n’est créé.

Les budgets des évaluateurs et les limites de fréquence des déclencheurs restent des contrôles opérationnels courants. Un ancien Run de réponse directe Chat, sans contrat de Flow, n’est pas réétiqueté comme ayant exécuté un mandat publié.

L’ancien actuateur de l’Hyperviseur qui modifie directement une policy courante ne s’applique pas à un mandat figé : il demande de passer par le draft et la publication, sans annoncer un effet inexistant sur les Runs. Ses reçus historiques restent idempotents.

Avant activation distante, les API et workers doivent tous comprendre le contrat enrichi. Revenir à un ancien worker qui rejette ce contrat ne constitue pas un rollback compatible des nouvelles versions publiées. Les anciens Runs et écritures doivent être conservés.

La qualification locale et ses captures sont conservées dans [le rapport de recette](reports/mandate-experience/README.md). La qualification sur de vrais Runs et la bascule suivent [le processus de release](agentium-release-process.md), depuis `demo/agentic`.

Référence de conception : [Paper — Autonomie, mandat, décisions et preuves](https://app.paper.design/file/01KZXGRFVFWR9G56P5FVDBD4X1/7-0).
