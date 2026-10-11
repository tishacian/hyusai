# Écosystème Probabl dans Omnirag — implémentation et qualification

Qualification locale du **11 octobre 2026**, branche `feat/probabl-ecosystem`,
sur le socle Skore `a026ff1c7e763f68ab2fef92ea5d543913b6962c`.
La [roadmap P0–P7](agentium-probabl-ecosystem-roadmap.md) fixe le périmètre.
Les preuves concernent le code candidat ; elles ne prouvent pas un déploiement VM.

## Architecture livrée

Les octets restent dans **ObjectStore/MinIO**, le suivi et le registre dans
**MLflow**, les objets et autorisations dans PostgreSQL. Aucun Skore Project,
service hébergé, feature store ou stockage d'expériences concurrent n'est ajouté.
Les JSON de qualification versionnés dans `docs/evidence/` sont des preuves de
livraison sur des données publiques ou synthétiques, pas un magasin opérationnel.

| Lot | Implémentation |
| --- | --- |
| P0 | Protocole versionné `config/ml/probabl-pilot.v1.json` : six tâches, données/licences/empreintes, trois partitions de développement, réserve finale indépendante, budgets et critères définis avant les mesures. |
| P1 | Contrat producteur complet, quotas, empreintes, versions exactes et profils de types côté lecteur avant toute désérialisation. skops 0.16.0 dans les contraintes applicatives. |
| P2 | Skills `ml_problem_frame_v1` et `ml_experiment_plan_v1`, revue de développement enrichie, proposition de Flow, méthode et runtime figés à publication. |
| P3 | skrub 0.11.0 ; constantes sélectionnées sur le train et chaque fold ; seed explicite pour auto/string ; transformations ajustées décrites dans le modèle et en FR/EN. |
| P4 | Agrégats historiques dans le nœud SQL existant, aperçu contrôlé, versions/empreintes des deux tables et lignée du résultat. |
| P5 | Famille `tabular_foundation` expérimentale : TabICL 2.2.0 CPU, conversion contrôlée, import signé, grants existants, rechargement autonome et révocation sur cache chaud. |
| P6 | Runner de comparaison borné, réseau interdit par seccomp, appariement et sélection sur développement, test final accessible seulement après gel. Résultat conservé séparément des possibilités techniques du pilote. |
| P7 | Surfaces Studio/Flow et connecteur FR/EN, contrôles de non-régression, configuration désactivée pour TabICL et procédure de retour arrière. Images VM et canari restent une étape de livraison distincte. |

## Méthodes et mental model

Les deux nouvelles Skills sont des fonctions locales typées et déterministes.
Elles adaptent des pratiques sélectionnées de Probabl Skills, avec
[provenance et notice BSD-3-Clause](../backend/app/resources/ml_methodology/README.md).
Elles n'exécutent ni le CLI amont ni du Python généré, et n'appellent aucun LLM
ou service externe. Elles sont utilisables par les mêmes exécuteurs et API que
les autres Skills Omnirag :

- `POST /ml-models/methodology/problem-frame` cadre l'objectif et les inconnues ;
- `POST /ml-models/methodology/experiment-plan` propose des nœuds existants
  d'entraînement et de revue, sans les publier ni les exécuter.

Un plan accepté devient une révision de Flow et suit la publication
`SystemVersion`, le Run, les SkillInvocations et les autorisations existantes.
La publication fige contenu, version, provenance et digest du runtime de la
méthode. Un runtime modifié est refusé plutôt que substitué silencieusement.
Le nombre effectif de candidats et le budget sont vérifiés à publication et à
soumission. Les boucles/reprises non couvertes par un budget partagé sont refusées.
Les paramètres d'entraînement viennent du graphe ; un alias `registry_call`
ne peut pas rendre une mutation ML/données exécutable en mode conseil.

Les schémas imbriqués restent éditables via le mode JSON sans perte du composant
Skills existant. Il n'y a pas encore de formulaire métier visuel spécialisé.
Les protocoles temporels, groupés ou prédéfinis restent bloqués dans ces plans
d'entraînement, avec une raison explicite. La préparation temporelle P4 ne rend
pas à elle seule un split aléatoire approprié à un problème temporel.
Le corpus de douze missions et ses cas adverses vérifient les contrats ; aucune
économie de temps opérateur n'est déduite de ces seuls tests.

## Préparation et enrichissement

Le résumé `metrics.preprocessing` décrit les colonnes reçues, retenues et
exclues, les opérations effectivement ajustées, la largeur de sortie et les
versions. Il reste borné à 64 colonnes/64 Kio, sans valeurs de cellules ni
catégories. L'interface ne reconstruit pas de preuve pour les anciens modèles.
Les colonnes constantes restent dans la signature d'entrée ; leur exclusion
est apprise par le pipeline sur chaque train, pas sur la table avant le split.
La sélection `auto` utilise maintenant le seed du Run pour rendre StringEncoder
reproductible, y compris sans tuning.

La recette [ml_qualify_preprocessing.py](../scripts/ml_qualify_preprocessing.py)
rejoue les six combinaisons classification/régression × auto/string/minhash.
Les preuves [ancien runtime](evidence/probabl-preprocessing-base.json) et
[runtime candidat](evidence/probabl-preprocessing-candidate.json) montrent des
scores et empreintes de prédictions identiques, avec rechargement MLflow/skops.
Les temps observés sur cette machine partagée ne constituent pas un benchmark
comparatif de vitesse.

L'[enrichissement historique](agentium-historical-enrichment.md) réutilise
DuckDB et le nœud `sql_transform_v1`. Chaque événement doit être disponible
**strictement avant** la décision ; une égalité de date est exclue. La table de
base conserve sa cardinalité. Clés, colonnes autorisées, dates, taille, durée,
taux de non-appariement, versions et empreintes sont contrôlés. L'aperçu retourne
un contrat qualifié que l'atelier permet d'épingler avant publication.
La démonstration de gain sur signal synthétique planté est une vérification
technique de la jointure ; elle ne prouve pas un gain métier.

## Artefacts et migration

Le [contrat lecteur](agentium-artifact-reader-contract.md) impose inventaire
complet, SHA-256, tailles, plafond de 512 Mio/2 048 fichiers, format, profil de
confiance et versions exactes. Les archives skops sont aussi bornées après
décompression. La liste de types déclarée par l'artefact n'élargit jamais la
politique du lecteur. Les exceptions cloudpickle/joblib existantes restent
explicites et protégées par l'intégrité et la provenance du producteur.

La [qualification croisée](evidence/probabl-skops-compatibility.json) ne permet
**pas** une migration générale 0.14.0 → 0.16.0 : deux exports sur huit passent
avec parité, six exports HistGradientBoosting sont refusés par skops.
Les nouveaux exports 0.16.0 portent le type qualifié requis ; cela ne certifie
pas rétroactivement les artefacts historiques.

Conséquence opérationnelle : conserver l'image productrice pour les modèles
existants. Un ancien artefact sans contrat, ou produit avec d'autres versions,
est explicitement indisponible dans le nouveau lecteur. Il n'y a ni réécriture
de manifeste historique, ni réentraînement implicite, ni migration en masse.
Ne pas remplacer un service portant un ancien champion avant d'avoir organisé
sa continuité sur le runtime producteur ou qualifié un réentraînement explicite.

## TabICL : capacité et limites de la preuve

Le [guide du pilote](agentium-tabicl-pilot.md) décrit les deux checkpoints
officiels, leurs SHA-256, la conversion `weights_only=True`, les safetensors,
le bundle dérivé signé et son import par les contrôles existants. Les notices
BSD-3-Clause restent dans le bundle. Aucune sérialisation pickle d'estimateur
TabICL ni aucun téléchargement implicite n'est utilisé.

La [preuve hors réseau](evidence/probabl-tabicl-offline.json) compare l'amont,
la conversion et le rechargement autonome pour classification et régression,
avec tolérance `1e-6`, après suppression de la copie source. Seccomp refuse les
connexions/envois avec `EPERM`. Les pics de 634 et 701 Mio sont ceux de petits
smokes techniques ; ils ne définissent pas un SLA ni la mémoire à 10 000 lignes.

Le pilote conserve son contexte d'apprentissage sensible dans le même bundle
versionné que les poids. Le cache d'inférence est éphémère et reconstruit au
rechargement. Chaque requête revalide les grants, y compris sur cache chaud.
Les limites sont 10 000 lignes, 100 variables, quatre threads et 600 secondes
au maximum ; le superviseur conserve les plafonds du workspace s'ils sont
plus stricts. La mémoire du conteneur reste la borne ultime des allocations.
Pas de promotion automatique, de champion de repli, de surveillance planifiée
ou de réentraînement automatique pour cette famille expérimentale.

La comparaison P6 mesure le **cycle du modèle directement** : préparation,
sélection/fit, prédiction, export skops ou JSON/safetensors, éviction et reload.
La projection CPU inclut le démarrage/imports et les processus enfants.
Elle n'inclut pas les transferts ObjectStore, l'enveloppe MLflow, RPC, contrôle
d'accès et HTTP du produit. Le serving de classification peut aussi effectuer
deux inférences (`predict` puis `predict_proba`) alors que la sonde comparative
appelle `predict`. Tous les candidats sont mesurés dans le même venv `ml-deep`,
qui diffère du packaging classique minimal. Une sélection technique positive
ne vaudrait donc ni validation de frugalité en production ni activation métier.
Énergie, prix et ROI restent indisponibles.

## Activation, sauvegarde et retour arrière

TabICL est livré avec `ML_TABICL_ENABLED=false` et `ML_TABICL_WORKSPACES=[]`.
Avant une activation canari : qualifier les images immuables et leur enveloppe
mémoire, importer et activer les checkpoints autorisés, sauvegarder PostgreSQL,
MLflow et les objets par les procédures existantes, puis tester la restauration
du bundle et des autorisations sur la cible. L'API, le worker d'apprentissage et
le worker de prédiction doivent partager flags et liste des workspaces autorisés.
Un grant et un modèle local ne suffisent pas à activer la famille.

Pour retirer le pilote, remettre le flag à `false` et recréer ces processus via
le [processus de livraison](agentium-release-process.md). La route refuse aussi
les modèles déjà résidents ; le champion classique conservé reste le chemin
de retour. Les artefacts et preuves sont conservés selon les politiques de
rétention existantes. Les méthodes peuvent être retirées indépendamment avec
`ML_METHODOLOGY_ENABLED=false`. Un rollback skrub/skops exige l'image productrice
correspondante : ne pas tenter de lire les nouveaux artefacts dans un ancien
runtime sans qualification.

Les images de release, la restauration complète PostgreSQL/MinIO/MLflow et le
canari doivent être réalisés sur la VM désignée par le dépôt. Cette session
ne possède pas la clé SSH ni le réseau configuré pour cette VM : aucune
activation réelle ou restauration de la plateforme n'est revendiquée.
