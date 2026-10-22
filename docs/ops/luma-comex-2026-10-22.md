# Luma — conduite de la démonstration COMEX du 22 octobre 2026

> **Dernière recette : 22 octobre, 08:29 UTC, révision `d03ce83a`.**
> Cinq nouvelles exécutions alimentent Work, Flow, Impact et les jobs. La file
> et la prévision sont consultables ; deux enquêtes attendent une revue humaine
> avec Judge non évalué. Une collision de version dataset a été reproduite et
> corrigée dans la livraison suivante. L’application équipe est publiée en R2.
> Voir [les preuves et limites actuelles](luma-impact-activity-2026-10-22.md) et
> [le parcours Work → Builder → Impact et son nouveau polish](impact-polish-2026-10-22.md).
> Les répétitions ci-dessous conservent leur état historique ; leurs réserves
> de déploiement ne constituent pas le statut actuel de ces composants.

## Mise à jour de recette — 22 octobre

La révision `550807bf` est confirmée en service. La file a été recalculée depuis
l’application **Pilotage SAV — équipe**, désormais publiée en **pilote R2** :
`https://agentium.papai.ai/work/pilotage-sav-equipe/home`. Son Run
`19263298-c5fa-4698-b174-f9afcb7db692` est terminé avec **23 dossiers scorés,
0 exclu, champion v5**. Le bouton, la publication et l’exécution ont été utilisés
dans l’UI. La sélection fine des résultats de l’étape `sav.score` a été
configurée par API avec le contrat générique de data binding ; cette étape
n’est pas une preuve d’autonomie d’un auteur non technique. Le générateur et
le Flow doivent exposer des sorties métier lisibles pour simplifier ce geste.

L’enquête RC-1044 du 22 octobre, Run `47b52fd5-ea6b-404a-b640-f837ed6d6e33`,
a consulté le remboursement antérieur et propose de clore sans second paiement.
Elle attend la revue humaine ; Judge a refusé une citation avec des positions
invalides. Ce défaut est corrigé dans la nouvelle livraison produit par des
citations exactes résolues côté serveur, mais reste à qualifier avec le
fournisseur après déploiement. Le Run RC-1043 interrompu lors du déploiement
n’a pas été réexécuté ni déclaré terminé artificiellement.

Les sections de répétition du 21 octobre ci-dessous restent l’historique de
leurs preuves. Pour l’état de la nouvelle livraison, ses contrôles agentiques,
le protocole de citation et la reprise opérateur, consulter
[la qualification agentique du 22 octobre](luma-agentic-qualification-2026-10-22.md).

## Ce que l'on veut faire comprendre

**« Nous vendons des applications métier qui exécutent un traitement de bout en bout : elles réunissent les informations utiles, préparent le travail, demandent une décision quand elle est nécessaire et rendent le résultat vérifiable. »**

Luma est un commerçant fictif. Son responsable SAV doit traiter plus de réclamations sans multiplier les recherches dans les outils ni perdre la maîtrise des remboursements. La démonstration suit un dossier depuis l'application de travail ; les données, les modèles et le Flow expliquent comment le service est rendu. Ils ne constituent pas des démonstrations séparées.

Deux preuves priment sur le catalogue de fonctions :

1. Un collaborateur traite un dossier dans une application, avec les faits et les documents utiles sous les yeux.
2. Un auteur métier assemble une petite application à partir d'automatisations déjà publiées, sans écrire de SQL ni de code.

**État après répétition du 21 octobre : le parcours complet n'est pas encore prêt à être annoncé comme qualifié.** Le recalcul de la file et la prévision ont été exécutés avec succès en service ; une nouvelle application métier a été créée sans code et enregistrée en brouillon. En revanche, le Judge a refusé une citation invalide, la simulation d'action après approbation est bloquée et la publication de la nouvelle application n'a pas été effectuée. Des correctifs sont préparés dans le dépôt ; leur déploiement et leur recette restent nécessaires. Le détail des preuves figure en fin de document.

## Dire clairement ce qui est réel

Les données et documents Luma sont fictifs. Cela n'empêche pas les lectures PostgreSQL, recherches documentaires, préparations, appels de modèle et exécutions de Flow d'être réels. Le remboursement Luma produit un **reçu simulé** : il ne verse pas d'argent. Les chiffres financiers sont une **projection sous hypothèses**, pas des économies réalisées.

Employer ces quatre formulations pendant la séance :

| Formulation | Signification |
| --- | --- |
| **Exécution réelle, données fictives** | Le service a effectivement exécuté le traitement montré ; sa trace, sa date et sa version sont consultables. |
| **Action simulée** | Le scénario représente une action métier sans l'effectuer chez un prestataire externe, notamment le remboursement. |
| **Projection** | Le résultat dépend des hypothèses affichées ; il ne vaut pas mesure humaine ni facture. |
| **À qualifier** | Le parcours n'a pas encore de preuve suffisante sur la révision présentée. Montrer son état réel, sans annoncer un succès. |

Un bouton présent ou un modèle marqué « champion » ne suffit pas à affirmer qu'une fonction est opérationnelle. Une exécution terminée techniquement ne suffit pas non plus à affirmer que Judge a validé la qualité.

## Parcours principal — douze minutes

Conserver l'application Work comme point de départ et de retour. Préouvrir les écrans de preuve ; éviter de parcourir tous les menus devant le COMEX.

Ce tableau décrit le **parcours cible**. Tant que les réserves de recette ci-dessous ne sont pas levées, montrer la proposition et le contrôle humain sans promettre un nouveau reçu, et montrer l'application créée en brouillon sans annoncer sa publication.

| Temps | Écran et geste | Phrase comprise par un responsable SAV | Ce qu'il faut effectivement montrer |
| --- | --- | --- | --- |
| 0:00–0:40 | **Work → Réclamations**, file et dossier sélectionné | **« Votre équipe trouve les dossiers à traiter et ceux qui risquent de dépasser votre délai de service. »** | La file, le nom du dossier et sa priorité ; distinguer priorité calculée et règle de remboursement. |
| 0:40–2:20 | Dossier, faits de commande, document source et politique | **« Le conseiller retrouve les faits et les justificatifs du client au même endroit, au lieu de les chercher dans plusieurs outils. »** | Un fait PostgreSQL et le passage exact d'un document ; revenir au dossier sans perdre sa sélection. |
| 2:20–3:50 | **Enquêter** ou reprise d'une enquête identifiée ; progression | **« L'application rassemble les preuves et prépare une proposition de traitement avec ses raisons. »** | Une exécution réelle identifiée, ses étapes et sa proposition ; une recherche en cours reste une recherche en cours. |
| 3:50–5:00 | Contrôle qualité, réserve éventuelle, décision humaine et reçu | **« Le responsable voit ce qui est vérifié, ce qui reste incertain et ce qu'il autorise avant l'action. »** | Résultat métier de Judge, droits effectifs et proposition. Le nouveau reçu ne peut être montré comme fonctionnel qu'après correction et qualification du blocage de simulation ; un reçu ancien reste explicitement daté. Dire « remboursement simulé » au moment où le reçu apparaît. |
| 5:00–6:00 | Flow **publié**, puis une source ou une étape de préparation | **« Le même traitement combine vos données, vos règles et l'IA, avec une trace de chaque étape. »** | Source PostgreSQL, préparation, priorité ML, enquête documentaire, contrôle qualité et validation. Le brouillon utilisateur reste séparé. |
| 6:00–7:00 | **Charge et capacité** | **« Le manager anticipe la charge du SAV pour ajuster son organisation. »** | Observations et prévisions distinctes, intervalle et date de calcul ; données synthétiques et horizon explicites. |
| 7:00–8:30 | **Impact**, activité puis scénario financier | **« Vous reliez le volume réellement traité à une estimation transparente de la capacité que votre équipe pourrait récupérer. »** | Sélectionner le jour de recette, ouvrir ses exécutions, puis faire varier une hypothèse financière. Ne pas présenter les durées techniques comme du temps humain économisé. |
| 8:30–11:30 | **Créer → Applications → Nouvelle application** | **« Un responsable métier peut assembler une application adaptée à son équipe à partir de traitements déjà disponibles, puis choisir qui peut l'utiliser. »** | Nom, modèle de page, action publiée et audience : création réelle vérifiée. Aperçu, résultat et publication seulement après déploiement des corrections et qualification de ce parcours. |
| 11:30–12:00 | Retour à l'application | **« Pour un client, nous pouvons commencer par un traitement utile, le mettre dans les mains des équipes, puis étendre les automatismes avec les mêmes contrôles. »** | L'application utilisée, son résultat et l'action suivante ; ne pas terminer sur du JSON ou un formulaire de paramétrage. |

Si une enquête prend plus de temps que la narration, la laisser s'exécuter et montrer le Flow ou le dossier de preuve dans un autre onglet. Revenir à son **même** Run. Ne pas relancer plusieurs fois pour remplir le silence.

## Choisir un cas qui porte l'histoire

Les trois cas de présentation ont des objectifs différents. Les montants ci-dessous décrivent les fixtures d'origine ; l'état affiché et les reçus actuels priment après les recettes successives.

| Cas | Histoire | Usage en séance |
| --- | --- | --- |
| **RC-1042 / LM-1042** | Commande de 420 € déclarée livrée ; le bordereau indique 75012 alors que l'adresse de commande est 75011, et un destinataire inconnu. | Bon cas principal pour montrer l'intérêt du croisement base + document. Conclure à une contradiction à instruire, pas à une fraude ou à une réception certaine. |
| **RC-1043 / LM-1043** | Colis perdu, 49,90 €, perte confirmée par le document CA-1043. | Cas simple pour expliquer la proposition de remboursement et l'accord humain. Vérifier les reçus préexistants avant toute nouvelle action. |
| **RC-1044 / LM-1044** | Remboursement de 89 € déjà enregistré sous RF-1044. | Contre-exemple de trente secondes : ne pas payer deux fois. Un blocage de doublon est une réussite du contrôle, pas une erreur à masquer. |

Ne pas réinitialiser les dossiers pour donner l'impression d'une première exécution. Un reçu historique doit être présenté avec sa date. Pour démontrer une nouvelle action de bout en bout, utiliser un dossier de recette identifié dont l'état permet réellement cette action ; conserver son historique et son statut de donnée fictive.

## Montrer l'autonomie d'un auteur métier sans exagérer la promesse

### Petite application à construire

**« Pilotage SAV — équipe »** a été créée via l'interface le 21 octobre, dans une application indépendante de `reclamations` : ID `20e33fa4-1653-46e5-b92e-ace7c10fe96d`, adresse `pilotage-sav-equipe`, brouillon r3. Elle utilise uniquement le binding existant `showcase.claims.refresh_queue`, avec une audience contributeur, reviewer et administrateur. Aucun code n'a été écrit pour cette configuration. **Elle n'est pas publiée.**

La répétition a révélé un libellé de bouton manquant et un comportement implicite de l'aperçu. Les corrections produit sont préparées dans le dépôt ; l'aperçu et la publication restent à vérifier après déploiement. Pour présenter le travail déjà réalisé, ouvrir `/create/apps/20e33fa4-1653-46e5-b92e-ace7c10fe96d` plutôt que créer des copies inutiles.

Pour montrer la construction pas à pas après cette qualification :

1. Ouvrir `/create/apps/new` et nommer l'application.
2. Choisir un modèle de page compatible avec le besoin. Pour le premier essai, préférer une action avec son résultat à un tableau nécessitant plusieurs associations de colonnes.
3. Choisir le System Luma déjà publié et une entrée disponible, par exemple le recalcul de la file. Vérifier son libellé réel dans le catalogue avant la séance. La création de l'interface ne doit pas créer un autre moteur métier pour la même démonstration.
4. Choisir explicitement les personnes ou rôles autorisés. Sauvegarder et revenir au même brouillon pour montrer que la configuration est conservée.
5. Dans Studio, donner à l'action un libellé métier clair et vérifier où son résultat s'affiche. Tester sur l'entrée de recette prévue et montrer le Run utilisé par l'aperçu.
6. Si la recette réelle l'a validé, publier sur le canal et l'audience choisis, lire le reçu de publication et ouvrir l'application dans Work. Sinon s'arrêter au dernier état réellement vérifié — actuellement le brouillon enregistré — et dire précisément ce qui reste à qualifier.

**Ce que l'auteur fait seul :** choisir un modèle, nommer l'application, sélectionner des traitements autorisés, disposer les composants disponibles, définir l'audience et publier dans les limites de ses droits.

Dans la répétition du 21 octobre, la création, la sélection du traitement, l'audience et la sauvegarde ont été faites réellement ; cette preuve ne comprend pas encore la publication ni une qualification avec un compte métier aux droits restreints.

**Ce qui a été préparé auparavant :** connexion et accès aux sources, contrat des entrées et sorties du Flow, règles métier, qualité des données, entraînement et qualification des modèles. Selon le cas client, cette préparation relève d'un administrateur, d'un intégrateur ou d'un spécialiste data.

**Limite à dire si l'on demande « avez-vous construit tout Luma ainsi ? » :** l'application Réclamations possède une interface spécialisée déjà développée. Le wizard assemble les composants génériques et les actions publiées ; il ne démontre pas qu'un utilisateur recrée seul toute cette interface spécialisée, les connecteurs et les modèles en trois minutes.

La démonstration d'autonomie doit être faite avec les permissions réellement nécessaires à la création. Le fait qu'un compte s'appelle « métier » ou « restricted » ne prouve pas qu'il dispose de droits limités.

## Expliquer les chiffres financiers sans ambiguïté

Les conventions retenues pour Luma sont : **40 €/h**, **8 minutes** de travail manuel, **2 minutes** de validation humaine assistée et **0,50 €** de budget d'automatisation par dossier. Ce budget représente les appels, l'infrastructure, la licence et l'intégration amortie ; les deux minutes humaines sont calculées séparément.

| Calcul | Résultat |
| --- | ---: |
| Temps humain libérable : 8 − 2 | 6 min / dossier |
| Capacité valorisée : 6 / 60 × 40 € | 4,00 € / dossier |
| Gain net projeté : 4,00 − 0,50 € | **3,50 € / dossier** |
| Ratio affiché : 3,50 / 0,50 × 100 | **700 %**, rapporté au budget d'automatisation retenu |
| Exemple de volume : 1 000 dossiers × 3,50 € | **3 500 € / mois**, si ce volume et ces hypothèses sont retenus |

Phrase à dire : **« Avec ces hypothèses, chaque dossier libère six minutes de capacité, valorisées quatre euros ; après le budget d'automatisation retenu, il reste trois euros cinquante de valeur projetée. »**

Les 700 % ne constituent pas un rendement financier observé. Les coûts partiels d'appels ne couvrent pas une facture complète. Un cas relancé plusieurs fois ne devient pas plusieurs dossiers traités. La vitesse d'un appel de modèle n'est pas une mesure du temps de travail humain. Les trois cas de présentation ne constituent pas un échantillon permettant de prouver un gain généralisable.

## Préparer les onglets et la séance

Utiliser le même workspace **Agentium Showcase**, la même langue française et le même compte que pendant la répétition. Garder les identifiants techniques hors du propos principal, mais accessibles dans les preuves.

| Onglet | Point d'entrée |
| --- | --- |
| Travail principal | `/work/reclamations/studio?record=RC-1042` ; vérifier qu'il est bien le dossier sélectionné |
| Charge | `/work/reclamations/charge` |
| Flow publié | `/systems/f3ea83de-df89-45ec-8a85-c00d676b2713/flow` ; vérifier l'état lecture du publié, pas le brouillon |
| Impact | Ouvrir Impact depuis la navigation du workspace et sélectionner la période contenant la recette |
| Création | `/create/apps/20e33fa4-1653-46e5-b92e-ace7c10fe96d` pour reprendre « Pilotage SAV — équipe » ; `/create/apps/new` seulement pour une construction nouvelle intentionnelle. Ne pas modifier le brouillon de l'application Luma existante. |
| Secours | Run et document vérifiés pendant la répétition, ouverts dans le produit avec leur date visible |

Avant la séance, vérifier la lisibilité sur l'écran réellement projeté et avec le zoom prévu : nom du dossier, proposition, réserve, décision et retour doivent être trouvables sans explication. Fermer les outils développeur et les panneaux techniques. Recharger une fois Charge et capacité pour vérifier la reprise du résultat, et revenir sur le dossier principal pour vérifier le maintien de la sélection.

Le webhook et le planning permanents étaient en pause à la dernière recette événementielle. Leur présence dans le Flow ne signifie pas qu'ils fonctionnent en continu. Montrer un Run planifié daté si c'est la preuve disponible ; ne pas annoncer une réception automatique en direct sans avoir qualifié et activé cette source.

## Plans de repli honnêtes

| Incident | Réaction à l'écran et phrase utile |
| --- | --- |
| Source temporairement indisponible | Montrer le message d'erreur et ouvrir une exécution conservée : « Voici le traitement exécuté à cette date ; la source n'est pas disponible maintenant. » |
| Judge indisponible ou réponse invalide | Montrer « Non évalué » et la réserve avant décision : « Le contrôle n'a pas abouti ; le responsable voit cette limite avant d'autoriser le traitement. » Ne pas présenter cela comme un jugement favorable. |
| Réponse d'approbation perdue | Utiliser la vérification du reçu du dossier concerné, sans répéter la décision à l'aveugle. |
| Simulation bloquée après approbation | Ne pas confondre « décision enregistrée » et « action effectuée ». Montrer l'état réel et, au besoin, un reçu historique distinct. Tant que la qualification après correctif n'est pas faite, ne pas réapprouver RC-1043 pour essayer de débloquer son Run. |
| Action déjà enregistrée | Ouvrir son reçu daté : « L'application évite une seconde action identique. » Ne pas réinitialiser le dossier. |
| Prévision lente | Ouvrir le dernier résultat conservé et donner sa date et son horizon. Ne pas changer le libellé pour le présenter comme recalculé en direct. |
| Création d'application interrompue | Reprendre le brouillon par son adresse. Si le test ou la publication échoue, conserver l'erreur et montrer l'application préalablement qualifiée en la présentant comme telle. |
| Temps de séance raccourci | Conserver dossier → preuves → proposition/décision → résultat et création métier ; mettre le détail ML et le catalogue de connecteurs en annexe. |

## Annexes à ouvrir seulement si le COMEX le demande

- **D'où viennent les données ?** Dataset versionné → table PostgreSQL exacte → retour au dataset ; document original et passage cité.
- **Comment les dossiers sont-ils préparés ?** Étapes visuelles utiles : variables, pièces manquantes, contrôle de doublon, tri. L'aperçu et le SQL sont des preuves, pas une obligation pour le responsable SAV.
- **Pourquoi ce dossier est-il prioritaire ?** Fiche du modèle servi, variables et explication disponibles. Un score de risque oriente la file ; il ne justifie pas à lui seul un refus ou un remboursement.
- **Comment améliore-t-on le modèle sans perturber les utilisateurs ?** Champion et challenger, shadow et explications. Les comparaisons sans résultats connus ne prouvent pas que le challenger est meilleur ; la promotion reste une décision distincte.
- **Peut-on automatiser le déclenchement ?** Planning ou événement reçu, identité d'exécution et Run associé. Un événement accepté n'est pas une preuve d'action métier terminée.

## Preuves de répétition du 21 octobre et blocages ouverts

La révision en service pendant ces essais est **`5e93f2af`**, confirmée par le frontend et l'API. Les identifiants ci-dessous proviennent des contrôles réels du 21 octobre. Les corrections préparées ensuite dans le dépôt ne sont pas présentées comme déployées.

| Élément | Preuve réelle et état constaté le 21 octobre | Limite ou suite nécessaire |
| --- | --- | --- |
| Flow protégé | Brouillon r38 et publication v10 constatés avant les essais et relus identiques en fin de recette ; aucune republication du grand workflow effectuée | Ne pas restaurer un ancien brouillon |
| Recalcul de file | Run **`78e6aded-c599-4fea-9d6d-5cb0f7effec6` terminé** ; horodatage relevé 21:43. Dataset scoré `7538f8fb-513b-4d50-9db9-570b60400c0a` : **23 scores**, dont les trois dossiers de présentation | Exécution réelle sur données fictives ; ce score ne prouve ni qualité prédictive sur des clients réels ni gain humain |
| Charge et capacité | Run **`c768b307-7157-4573-bf6b-f0ba7e2485c9` terminé** ; sortie v2 produite à l'horodatage relevé 21:47:36, **70 lignes : 42 observations et 28 prévisions**. Retour et restauration du résultat vérifiés | Données synthétiques ; afficher les dates et l'horizon du résultat, pas une mesure de demande client réelle |
| Enquête et Judge | Run RC-1043 **`64a9aac5-2ecd-4f37-821a-e171dfb9386c`**. Le Judge a refusé une preuve : `evidence_quote`, question 0, citation 0. 948 tokens de sortie, coût d'appel enregistré **0,020395 USD**. Le contrôle humain est resté nécessaire | Aucun avis positif de qualité obtenu. La consigne de citation exacte a été corrigée dans le dépôt sans assouplir la validation ; une nouvelle qualification fournisseur est nécessaire après déploiement |
| Décision et action simulée | Une approbation a été donnée via l'interface après revue des faits ; **la simulation s'est bloquée**, avec blocage PostgreSQL observé depuis l'horodatage 21:57:52 | Pas de nouveau reçu réussi à annoncer. Déployer le correctif de verrouillage, recréer le worker CPU puis qualifier la reprise ou la nouvelle exécution de façon contrôlée |
| Auteur métier | Application **`20e33fa4-1653-46e5-b92e-ace7c10fe96d`**, `pilotage-sav-equipe`, créée via l'interface sans code, brouillon r3. Réutilisation de `showcase.claims.refresh_queue`, audience contributeur/reviewer/administrateur | **Publication non effectuée**. Libellé du bouton et aperçu corrigés dans le dépôt ; vérifier l'aperçu, le résultat et la publication après déploiement |
| Webhook | La qualification historique couvre signature et déduplication ; cette répétition ne fournit pas de nouvelle preuve de bout en bout | Ne pas promettre un nouveau dossier déclenché en direct par webhook tant qu'une enquête isolée et son identité ne sont pas vérifiées |
| Impact | De nouvelles exécutions réelles existent maintenant pour la file, la prévision et l'enquête ; les hypothèses financières restent celles affichées ci-dessus | Vérifier leur présence dans le bon jour et le bon périmètre ; distinguer dossiers, exécutions, échecs et simulations ; aucun ROI humain observé n'est revendiqué |

### Conditions avant d'annoncer le parcours complet comme prêt

1. **Révision déployée confirmée** pour l'API, le frontend et le worker CPU concerné. Le correctif de simulation remplace un verrou `FOR UPDATE` sur le workspace par `NO KEY UPDATE` : l'ancien verrou empêchait l'écriture d'audit effectuée dans une autre session. Les tests du correctif ne débloquent pas le worker actuellement en service ; sa recréation puis la vérification de l'état de l'ancien Run restent nécessaires.
2. **Une action simulée terminée et son reçu relu**, rattachés à la décision et au dossier montrés. L'approbation seule ne satisfait pas ce critère. Aucun paiement externe ne fait partie de cette qualification.
3. **Une nouvelle enquête et son vrai verdict Judge**, avec citations acceptées ou réserve correctement affichée. Les 109 tests locaux du correctif de consigne ne démontrent pas à eux seuls un avis favorable du fournisseur en service.
4. **L'application métier testée puis publiée**, avec aperçu explicite, libellé de bouton lisible, résultat, audience et reçu de publication. Jusqu'à cette preuve, le résultat obtenu est une application configurée en brouillon.
5. **Une dernière lecture continue du parcours**, sur la révision finale, puis vérification de la conservation du brouillon Luma et des épingles publiées. Les résultats des tests locaux ci-dessous ne remplacent pas cette recette en service.

Si un de ces points reste ouvert, adapter le discours et le parcours à la preuve disponible. Ne pas transformer une correction dans le dépôt en promesse de fonctionnement en production.

Consigner les résultats de la répétition avec date, révision, Run ou objet, résultat observé et limite. Une capture de l'écran de succès ne remplace pas le reçu ni la preuve d'exécution.

## Déploiement et reprise de la qualification

### Livraison à mettre en service

La révision à déployer est **le commit porteur de cette version du document**, communiqué avec la livraison. Employer cette même révision pour **l'API, le frontend et le worker CPU** qui poursuit l'exécution après décision humaine. Cette livraison ne demande **aucune migration supplémentaire ni nouveau drapeau**.

La recréation du worker CPU est nécessaire pour interrompre la transaction actuellement bloquée et libérer ses verrous ; mettre à jour uniquement l'API et le frontend ne suffit pas. Vérifier ensuite que le worker a effectivement démarré avec la nouvelle image. Ne pas purger la file de tâches pour effectuer cette opération.

Ne pas rejouer l'installation Luma, republier son Flow ou restaurer un ancien brouillon. Préserver :

- Brouillon Flow **r38** ; publication **v10**, `b8eb64d3-e417-41bf-898a-7b1ad232d64a`.
- Champion SLA **v5**, `2e71ce6f-800f-4d02-b59e-498e40fe48eb`.
- Shadow à **10 %**, sans promotion du challenger ni changement de politique.
- L'application `reclamations` et ses bindings publiés ; l'application indépendante `pilotage-sav-equipe` reste un brouillon jusqu'à sa qualification.

### Contrôles immédiatement après déploiement

1. Lire `/api/v1/build-info` et `/build-info.json` : la révision doit correspondre au commit livré, avec révision vérifiée. Contrôler la révision de l'image du worker CPU séparément ; les endpoints web ne prouvent pas sa mise à jour.
2. Vérifier `/api/v1/health/ready`, puis l'ouverture de Work dans Showcase. Relever la fin du blocage PostgreSQL après recréation du worker.
3. **Avant toute nouvelle validation**, ouvrir le Run **`64a9aac5-2ecd-4f37-821a-e171dfb9386c`** et retrouver sa décision **`80a3ede7-9d77-4faf-8c8c-45e68fac67ae`**, déjà acceptée pendant la recette. Relire le dossier **RC-1043** et ses reçus. Lectures de contrôle disponibles : `GET /api/v1/runs/64a9aac5-2ecd-4f37-821a-e171dfb9386c` et `GET /api/v1/ecommerce-claims/RC-1043`, dans Showcase et avec le compte autorisé.
4. Consigner séparément **statut de la décision, statut du Run, statut de l'invocation de simulation et reçu métier**. Une décision acceptée n'est pas à soumettre à nouveau. Si un reçu correspondant existe, le relire et ne pas refaire l'action. Si le Run reste interrompu ou incomplet, qualifier sa récupération avant de lancer un nouveau traitement du même dossier ; la recréation du worker ne garantit pas, à elle seule, cette récupération.
5. Vérifier l'absence de double action et les versions protégées ci-dessus. Puis reprendre la qualification de Judge et de la nouvelle application métier, sans modifier le Flow Luma pour contourner un échec.

Le contrôle de reprise doit conserver les preuves du blocage et de l'approbation initiale. Ne pas supprimer un reçu, réinitialiser la décision, modifier manuellement le statut du Run ou approuver à nouveau pour rendre la présentation plus simple.

### Recette à terminer sur la nouvelle révision

| Parcours | Critère de réussite |
| --- | --- |
| Simulation d'action | Une seule décision pertinente, une simulation terminée et un reçu correspondant relu ; aucun doublon après relecture ou reprise |
| Enquête et Judge | Appel réel sous le nouveau prompt ; citations exactes contrôlées ; verdict réel et éventuelle réserve affichés avant décision |
| Auteur métier | Reprise de `20e33fa4-1653-46e5-b92e-ace7c10fe96d` ; libellé lisible, choix de Run explicite dans l'aperçu, résultat vérifié, publication puis ouverture dans Work pour l'audience choisie |
| Continuité Work | Retour au dossier, changement de dossier, réserve rattachée au bon Run, prévision conservée au rechargement |
| Impact | Exécutions de recette visibles au bon jour ; passage du graphe à leurs preuves ; hypothèses financières toujours identifiées comme telles |

### Validation locale de la livraison

Au dernier relevé : **2 628 tests unitaires frontend réussis** ; compilation de production, i18n, chrome et navigation réussis ; **109 tests Judge** et **38 tests e-commerce**, dont **deux tests PostgreSQL réels**, réussis.

Les **61 scénarios de la dernière campagne navigateur disposent d'un passage réussi** : 58 lors du passage initial, puis les trois restants après correction de sélecteurs stricts dans les tests. Le motif recherché apparaît désormais également dans un titre ; les sélecteurs ont été précisés, sans nouvelle modification produit. Cette campagne comprend Réclamations en sombre, clair et mobile, la prévision, Studio ainsi que les contrôles de géométrie et d'accessibilité à 320 px.

Une campagne précédente avait réussi **71 scénarios sur 71**, sur un périmètre plus large comprenant notamment Impact, le wizard et les preuves de données. Les deux campagnes se recouvrent : **ne pas additionner 71 et 61 pour annoncer un nombre de tests distincts**. Les tests locaux, y compris PostgreSQL, ne constituent pas une preuve de déploiement ni de fonctionnement des fournisseurs en service.

Sources : [recette UI/UX du 21 octobre](uiux-recette-2026-10-21.md), [recette Luma du 20 octobre](luma-postdeploy-be3c7439-2026-10-20.md), [cas fictifs et documents](../demo-runs/showcase-ecommerce/fixtures/README.md), [qualification du challenger](../demo-runs/showcase-ecommerce/CHALLENGER-QUALIFICATION-2026-10-19.md).
