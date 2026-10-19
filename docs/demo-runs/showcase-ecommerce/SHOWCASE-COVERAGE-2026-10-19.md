# Luma : nouveautés produit et parcours de démonstration

État au **19 octobre 2026**, après lecture du dépôt et contrôles API en service.
Cette passe est une analyse : elle ne publie pas de Flow, ne déclenche pas
d'entraînement et n'approuve aucune décision.

## Conclusion

Conserver **un System métier et une Business App Luma**. Le récit est celui
d'une responsable SAV qui priorise une réclamation, retrouve ses preuves,
contrôle la proposition de l'agent, décide, puis améliore son dispositif.
La préparation de la file, l'enquête et la prévision sont des branches du même
Flow. Le System technique de surveillance ML est un service de fond, pas une
seconde application métier.

Le socle PostgreSQL → DataOps → scoring → enquête documentaire → validation
humaine est démontrable. Les principaux compléments à réaliser sont :

1. raccorder le **Judge** et les **déclencheurs** produit au Flow actuel ;
2. montrer la **préparation visuelle** sur une transformation utile à Luma ;
3. rétablir la **prévision de charge**, dont l'artefact actuel est incompatible ;
4. préparer un **challenger compatible** pour le shadow et, avec un modèle
   adapté, TreeSHAP.

Ces travaux relèvent principalement de la configuration et de la qualification.
Le manque produit identifié pour l'équité en production est distinct : conserver
des métadonnées d'audit par échantillon sans les ajouter aux variables prédictives.

## Base vérifiée

| Élément | État |
| --- | --- |
| Dépôt `demo/agentic` | `eccaa253dc6f4a14b1b1d21e405469abadc618f5`, aligné sur sa branche distante lors de la lecture |
| API en service | `718c99bf7e9e07fb689ff0bcd4a1ffd90fca2ece`, révision vérifiée |
| Dernier écart local/service | `eccaa253` corrige le rappel de test périmé du connecteur et documente la recette ; aucune nouvelle fonctionnalité majeure après ce commit |
| System métier | `f3ea83de-df89-45ec-8a85-c00d676b2713` |
| Flow publié | v5, `f3fc70cd-0a51-4719-bbf3-ce30d787f4d4`, 24 nœuds / 25 liens |
| Brouillon distinct | révision 25, 25 nœuds / 26 liens ; le nœud Prepare utilisateur doit être préservé |
| Work | release 4, pages Dossier, Charge et capacité, Amélioration |
| Modèle SLA servi | v5, `2e71ce6f-800f-4d02-b59e-498e40fe48eb`, appelable |
| Observabilité | journal, séries et Flow exécuté ouverts |
| ML Operations | ouvert ; alertes fermées |
| Gouvernance ML | conservation des inputs autorisée ; traitement de rétention désactivé |
| DataOps / contrats de services | fonctionnalités workspace ouvertes |
| Registre Connections | disponible, mais aucune connexion enregistrée ; Luma lit la configuration PostgreSQL historique |

Les grandes nouveautés du 16–18 octobre sont l'assemblage M4.2/M4.3/M5 et
l'observabilité des exécutions. Les correctifs du 19 rendent la chaîne Luma
exploitable. Impact configurable et la prévision existaient déjà ; ils ne sont
pas présentés comme des nouveautés de ce dernier lot.

## Couverture et intérêt métier

« Qualifié » renvoie aux preuves de recette citées en bas de page. « À raccorder »
signifie que le produit existe mais n'est pas utilisé par le Flow Luma publié.

| Capacité produit | Ce que Luma doit en montrer | État et action |
| --- | --- | --- |
| PostgreSQL : diagnostic, catalogue, aperçu, transport explicite | Retrouver la commande qui justifie la décision, explorer sa table depuis la source | **Qualifié** : connexion, sept tables, aperçu frais ; choix administrateur Sans chiffrement appliqué à cette seule connexion |
| Document Center / OmniRAG | Ouvrir le passage du bordereau et la règle de traitement ; constater la contradiction d'adresse | **Qualifié** : six documents accessibles sur RC-1042 ; l'enquête consulte les preuves et les règles |
| DataOps et datasets versionnés | Voir comment les données de la file deviennent les six variables du modèle ; inspecter source, préparation et résultat | **Qualifié en SQL** : 23 lignes préparées puis scorées, datasets distincts et traçables |
| Atelier DataOps visuel | Corriger les types, traiter les manquants, créer `evidence_gap`, prévisualiser chaque étape | **À raccorder** : Luma utilise `sql_transform_v1`, pas encore `data_prep_v1` ; préserver le contrat ML lors de la transformation |
| Jointure, union, agrégation et profilage | Enrichir les dossiers ou produire la charge quotidienne quand cela sert le parcours | **Produit livré**, pas de preuve d'utilisation de toutes ces opérations dans Luma ; ne pas ajouter des étapes artificielles pour cocher une liste |
| ML tabulaire + agentique + humain | Prioriser, enquêter avec les bons outils, proposer une enquête transporteur puis attendre la décision | **Qualifié jusqu'au HITL** : recalcul de file réussi ; enquête avec 12 appels réussis ; aucune nouvelle approbation ni action finale lors de cette recette |
| Judge `evaluate_v2` | Contrôler preuves, politique, montant/doublon, contradictions et incertitude avant décision humaine | **À raccorder** : absent des 24 nœuds publiés ; restitution générique dans Work, pas de carte codée pour Luma |
| Webhook et planification métier | Faire entrer une nouvelle réclamation et actualiser la file automatiquement | **À raccorder** : aucun hook ni planning du System métier ; événements en `dry_run` ; le planning ML de fond est distinct |
| Flow exécuté, Opérations, Activités | Expliquer où un dossier attend, ouvrir l'appel et la preuve, retrouver erreurs et durées sur la bonne période | **Ouvert et qualifié en partie** : Flow du Run et séries accessibles ; nouvelle recette complète multi-rôles/SSE direct non acquise |
| M4.2 : référence et compatibilité runtime | Expliquer pourquoi la v5 peut être servie et comment contrôler un changement d'environnement | **Référence enregistrée** de 256 lignes ; une requalification après changement d'environnement reste à démontrer séparément |
| M5 : Play et contrefactuel | Explorer la sensibilité du risque à la présence de pièces | **Qualifié** sur `case_documents` ; sensibilité du modèle, pas causalité ni instruction de modifier les faits |
| M5 : diagnostic en production | Relier des réponses réellement servies aux résultats connus, inspecter erreurs et exclusions | **Qualifié sur corpus synthétique** : 64 retours, 48 corrects ; pas 64 enquêtes métier ni une performance réelle du SAV |
| Surveillance et réentraînement gouverné | Relier les retours à un dataset figé, une proposition, une approbation, puis un futur challenger | **Proposition en attente** : 4 627 lignes, holdout préservé ; aucun challenger créé ou promu par cette proposition |
| Shadow et TreeSHAP | Comparer un challenger sans remplacer le champion, expliquer une prédiction d'arbre | **À préparer** : challenger actuel legacy ; v5 calibrée incompatible TreeSHAP. Entraîner et qualifier un arbre non calibré avec les mêmes six inputs |
| Prévision et capacité | Anticiper les dossiers des 28 prochains jours et préparer les ressources SAV | **Branche existante mais bloquée** : Chronos v1 `ready` mais non appelable, `ML_ARTIFACT_LEGACY_UNSUPPORTED` |
| M4.3 : import externe / M4.1 : export gouverné | Montrer la collaboration avec une équipe data science et la portabilité contrôlée | **Annexe facultative** : import fermé selon la dernière activation opérateur ; formats admis et validation requis. L'import n'offre pas toutes les boucles MLOps natives |
| Impact configurable | Mettre l'activité Luma et les hypothèses de valeur dans une vue choisie par l'utilisateur | **Configuré et relu** : vue SAV filtrée, blocs génériques, ouverture par défaut ; aucune mesure de gain humain réalisée |

Les snapshots immuables, la lecture multipart, CSV/Parquet et le stockage Delta
appartiennent au socle DataOps. Le corpus de 23 dossiers ne démontre pas une
capacité à traiter des millions de lignes. Le registre Connections constitue
un parcours différent de la fiche historique : le remplir seul ne migre pas
les lecteurs Luma. Ces extensions méritent une recette séparée si elles entrent
dans l'objectif commercial ; elles ne sont pas requises pour raconter ce cas.

## Parcours principal, environ 15 minutes

1. **Le problème métier — Work, 2 min.** Ouvrir la file, expliquer le risque de
   résolution au-delà de 72 h, sélectionner RC-1042. Distinguer les trois dossiers
   présentés des 23 dossiers du corpus de préparation.
2. **La décision se fonde sur des faits — dossier, 3 min.** Ouvrir la commande
   PostgreSQL et le passage transporteur. Montrer la divergence 75012/75011 et
   la règle applicable. Le spectateur doit pouvoir vérifier la preuve sans
   ouvrir un journal technique.
3. **Le système travaille — Work puis Flow exécuté, 3 min.** Montrer préparation,
   scoring, choix des outils et proposition d'enquête transporteur. Le Judge
   s'insérera ici après son raccordement ; aujourd'hui, le présenter comme une
   prochaine étape. La validation humaine reste une décision explicite.
4. **Le système apprend sous contrôle — Model Center, 4 min.** Ouvrir la version
   effectivement servie, Play/contrefactuel, les retours synthétiques et le
   diagnostic. Terminer sur la proposition de réentraînement en attente,
   avec populations et test préservé. Approbation d'entraînement et promotion
   en service sont deux étapes distinctes.
5. **On observe et on chiffre — Activités puis Impact, 3 min.** Filtrer Luma sur
   7 jours, retrouver le même Run et ses appels. Ouvrir la vue SAV par défaut :
   activité constatée, coûts couverts ou inconnus, puis scénario financier.

Après raccordement et qualification, commencer la même histoire par une entrée
webhook ; le rejeu du même événement doit renvoyer la même exécution. Ajouter
« Charge et capacité » en fin de parcours uniquement après remise en service
de son modèle. Le Builder sert à expliquer l'architecture après l'expérience
métier, pas à remplacer celle-ci.

## Lots d'application recommandés

### 1. Qualité et événements dans le même Flow

Reconstruire le candidat à partir du **Flow v5, brouillon r25, SLA v5 et Work
release 4**. Le plan du 17 octobre porte `applied=false` et contient des épingles
historiques : il ne doit pas être rejoué tel quel. Préserver le brouillon
utilisateur et réaligner publication, trois bindings, contrat de triage et
release Work après revue du diff.

Configurer le Judge avant HITL avec un snapshot immuable des preuves du même
Run et cinq questions. Vérifier route fournisseur, tarif et budget actuels,
citations, abstention et erreur technique. Le Judge n'autorise pas l'action à
la place de la personne. Le rendu Work existe déjà.

Créer les entrées webhook/planifiée en pause, vérifier signature et périmètre,
puis faire une recette bornée : une livraison et son rejeu donnent un Run ; un
tick de planification donne une actualisation. L'idempotence dépend du corps
canonique complet, pas seulement de `event_id`. Le cron est indépendant du
`dry_run` événementiel. Contrôler la cadence finale après recette.

**Preuve attendue :** un dossier, un Run, un Judge consultable près du HITL,
un état d'événement identifiable et aucune action dupliquée.

### 2. Préparation visuelle utile et lisible

Partir de la préparation existante : types cohérents, sélection des six inputs,
indicateur de pièces manquantes et contrôle de remboursement antérieur. Utiliser
l'atelier générique avec aperçu et profilage intermédiaires. La configuration
ne doit pas changer silencieusement le sens d'une variable ML.

**Preuve attendue :** données avant/après, 23 dossiers conservés, schéma attendu,
modèle v5 appelé sans dérive de contrat, lineage jusqu'à PostgreSQL. Montrer
le SQL compilé seulement en approfondissement technique.

### 3. Réparer la branche Charge et capacité

La lecture fraîche du modèle `ec5436b1-8233-4e06-9912-5bc9956c96f3` confirme
`serving.callable=false`, malgré `status=ready`. Recréer un artefact compatible
et tester une inférence avant de modifier l'épingle de la branche.

Le complément le plus cohérent serait une prévision classique sur les 420 jours
de volume : comparaison au naïf saisonnier, backtests temporels, horizon 28 jours
et intervalles. Elle permet aussi une boucle de surveillance/réentraînement.
Chronos reste une option de prévision, sans réentraînement planifié pris en
charge. Les observations futures ne doivent jamais être inventées pour fournir
une mesure de prévision : la prévision doit avoir été émise strictement avant
la date cible observée, pas seulement avant l'ingestion de cette observation.

**Preuve attendue :** page Charge alimentée par un Run réussi du même System,
modèle/version visibles, historique distingué du futur, erreur de prévision
mesurée uniquement lorsqu'une observation admissible existe.

### 4. Challenger, shadow et explications

Créer un challenger compatible avec le contrat d'entrée existant. Pour montrer
TreeSHAP, choisir un algorithme d'arbre pris en charge dans la famille tabulaire,
par exemple RandomForest non calibré. Qualifier
l'artefact et Play ; activer un échantillonnage shadow borné puis produire de
nouveaux appels. Le shadow ne reconstitue pas rétroactivement la comparaison.

Conserver le champion v5 pendant la comparaison. La proposition actuelle de
réentraînement conserve son algorithme prévu : elle ne devient pas un arbre
automatiquement. Sa décision du 19 octobre expire le 21 octobre à 13 h 57,
heure de Paris, avec rejet par défaut ; relire l'état au moment de la recette.

**Preuve attendue :** mêmes entrées, réponses champion/challenger identifiables,
couverture et désaccords visibles, explication applicable, aucune promotion
implicite.

## Impact : configuration constatée et lecture correcte

La vue **SAV — activité et scénario** est enregistrée comme vue workspace par
défaut, filtrée sur le System Luma et sur **7 jours**. Elle contient notamment
les blocs génériques **Activité des exécutions** et **Scénario financier**.
Le parcours utilisateur est **Impact → Personnaliser → créer/choisir une vue →
choisir System et période → ajouter/régler/réordonner les blocs → définir la vue
par défaut → enregistrer**. Aucune carte n'est injectée selon le nom Luma.

À la lecture du 19 octobre, 14 h 31 UTC, l'API du bloc d'activité renvoie :

- **3 tentatives**, dont 1 terminée, 1 échouée et 1 en attente ;
- **16 appels**, dont 12 tarifés et 4 sans coût documenté ;
- une tentative le 16 octobre, deux le 19 ; pas de sous-total tronqué ;
- coûts partiels séparés : 0 EUR documenté et 0,012 USD.

Cette fenêtre ne contient plus les essais du début octobre. Elle ne doit pas
être comparée directement aux captures historiques montrant 23 exécutions.
Un HITL en attente n'est pas un résultat métier accompli. Les séries Opérations
et les anciens graphiques de résultats Impact ont des contrats distincts ; le
bloc d'activité est celui qui montre aussi échecs et attentes.

Les paramètres enregistrés sont 8 min manuelles, 2 min humaines assistées,
40 €/h et 0,50 €/dossier de budget complet. Ils donnent **3,50 €/dossier nets
projetés**, et **700 %** rapportés au budget incrémental de 0,50 €. Le volume
mensuel enregistré est **non renseigné** : aucune projection mensuelle ne doit
être présentée comme configurée. Ces conventions valorisent une capacité ;
ni les latences techniques ni les feedbacks synthétiques ne prouvent un gain
de travail humain ou une économie encaissée.

## Qualité UI/UX à traiter dans le produit

La démonstration doit rester compréhensible sans exposer ses mécanismes internes
à chaque écran. Les corrections suivantes ont une utilité générique :

- **Décision en cours et reçu historique :** séparer clairement leur date,
  statut et Run d'origine. RC-1042 a un reçu simulé du 2 octobre à côté d'une
  nouvelle proposition ; ne pas laisser croire que celle-ci est exécutée.
- **Flow exécuté :** réserver l'information principale à l'état, à la durée et
  à la preuve. Réduire les mentions répétées « Indisponible » et corriger les
  clés de traduction d'activité/invocation exposées.
- **Sources et datasets :** garder des actions compactes et stables pour ouvrir
  aperçu, transformation, provenance et modèle ; ne pas demander au métier de
  reconstruire ces liens depuis une liste d'identifiants.
- **Approbation de réentraînement :** afficher d'abord raison, populations,
  résultats attendus et effet de la décision ; laisser les hashes et contrats
  techniques dans un détail dépliable.
- **Événements :** la recette technique dispose de hooks/Run et d'idempotence,
  mais pas encore d'un registre utilisateur complet de livraison/rejeu. Ne pas
  faire passer une commande API pour un parcours end user abouti.

Le correctif du rappel PostgreSQL après test réussi est dans `eccaa253`, pas
dans la révision live relue. Les derniers essais UI à 1 440 et 390 px sont
documentés ; cette analyse API ne constitue pas une nouvelle recette visuelle.

## Approfondissements et limites

- **Équité :** `language` est conservée dans les données figées de réentraînement,
  mais absente des inputs de production. Il manque des métadonnées d'audit
  par échantillon, séparées des variables prédictives, avec consentement,
  provenance, droits et couverture. Ne pas ajouter la langue comme prédicteur
  uniquement pour débloquer un graphique. Les 64 retours ne permettent pas de
  revendiquer une mesure d'équité par langue.
- **Import externe :** activation opérateur, droits et limites de taille proxy
  requis ; archive MLflow sklearn/skops sûre avec validation. Les formats
  pickle/joblib et custom pyfunc ne sont pas pris en charge. Une lignée importée
  ne bénéficie ni du shadow, ni de la comparaison, ni du réentraînement planifié,
  ni des explications M5.
- **Alertes :** garder cette activation indépendante du récit principal. La boîte
  interne peut être ouverte sans canal externe ; une notification externe exige
  une destination essayée. Vérifier les envois en attente avant d'ouvrir le
  drapeau global. Aucun canal ni envoi externe n'a été créé dans cette analyse.
- **Rétention :** le traitement est désactivé, alors que les inputs sont conservés
  selon la politique workspace. Ce sont deux réglages distincts ; une démo de
  nettoyage exige une politique et un périmètre de recette dédiés.
- **Preuves :** 75 % de bonnes réponses sur le corpus synthétique n'est pas une
  performance métier. L'AUC de test comporte une réserve sur trois
  contenus communs train/test. Une couverture honnête distingue fonction livrée,
  activation, passage réussi et validité métier, sans pourcentage global ambigu.

## Références

- [Qualification Luma et preuves du 19 octobre](../../ops/luma-model-qualification-2026-10-19.md)
- [Recette UI/UX du parcours](../../ops/luma-ux-qualification-2026-10-19.md)
- [Assemblage MLOps M4.2, M4.3 et M5](../../agentium-mlops-delivery.md)
- [Observabilité : Opérations, Activités, Flow exécuté](../../agentium-operations-activities-flow-implementation.md)
- [Guide DataOps](../../agentium-dataops-guide.md)
- [Stockage et versions DataOps](../../agentium-dataops-storage.md)
- [Blocs configurables Impact](../../impact-configurable-blocks.md)
- [Candidat qualité/événements historique, non appliqué](fixtures/showcase_quality_events/ACTIVATION.md)
- [Déclencheurs de Flow](../../agentium-flow-trigger-operations.md)
