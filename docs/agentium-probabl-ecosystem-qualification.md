# Écosystème Probabl dans Hyusai — implémentation et qualification

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
| P0 | Protocoles versionnés `config/ml/probabl-pilot.v1.json` et `probabl-pilot.v2.json` : six tâches, données/licences/empreintes, trois partitions de développement, réserve finale indépendante, budgets et critères définis avant les mesures. La révision 2 exclut le profil de régression sans cache après échec de sa qualification technique, avant toute ouverture finale. |
| P1 | Contrat producteur complet, quotas, empreintes, versions exactes et profils de types côté lecteur avant toute désérialisation. skops 0.16.0 dans les contraintes applicatives. |
| P2 | Skills `ml_problem_frame_v1` et `ml_experiment_plan_v1`, revue de développement enrichie, proposition de Flow, contenu de méthode et empreinte du module d'implémentation figés à publication. |
| P3 | skrub 0.11.0 ; constantes sélectionnées sur le train et chaque fold ; seed explicite pour auto/string ; transformations ajustées décrites dans le modèle et en FR/EN. |
| P4 | Agrégats historiques dans le nœud SQL existant, aperçu contrôlé, versions/empreintes des deux tables et lignée du résultat. |
| P5 | Famille `tabular_foundation` expérimentale : TabICL 2.2.0 CPU, conversion contrôlée, import signé, grants existants, rechargement autonome et révocation sur cache chaud. |
| P6 | Comparaison terminée : 97 cas de développement évalués, deux échecs et neuf exclusions ; 12 cas finaux évalués sur quatre tâches. Aucun seuil combiné qualité/coût ou de frugalité atteint ; deux réserves finales restées fermées. |
| P7 | Surfaces Studio/Flow et connecteur FR/EN, contrôles de non-régression, configuration désactivée pour TabICL et procédure de retour arrière. Images VM et canari restent une étape de livraison distincte. |

## Méthodes et mental model

Les deux nouvelles Skills sont des fonctions locales typées et déterministes.
Elles adaptent des pratiques sélectionnées de Probabl Skills, avec
[provenance et notice BSD-3-Clause](../backend/app/resources/ml_methodology/README.md).
Elles n'exécutent ni le CLI amont ni du Python généré, et n'appellent aucun LLM
ou service externe. Elles sont utilisables par les mêmes exécuteurs et API que
les autres Skills Hyusai :

- `POST /ml-models/methodology/problem-frame` cadre l'objectif et les inconnues ;
- `POST /ml-models/methodology/experiment-plan` propose des nœuds existants
  d'entraînement et de revue, sans les publier ni les exécuter.

Le `flow_draft` proposé peut être repris dans une révision via l'authoring
existant, puis suit la publication `SystemVersion`, le Run, les SkillInvocations
et les autorisations habituelles. La Skill ne sauvegarde ni ne publie le Flow.
La publication fige contenu, version, provenance et digest du runtime de la
méthode : cette empreinte couvre son module Python, pas l'image complète et
toutes ses dépendances. Un module modifié est refusé ; rejouer l'ancienne version
nécessite de conserver son environnement producteur.
Le nombre effectif de candidats est vérifié à publication et soumission ; le
plafond temporel à planification et soumission. Mémoire et latence restent des
critères d'acceptation, sans nouveau plafond technique appliqué par ces Skills.
Les boucles/reprises non couvertes par un budget partagé sont refusées.
Les paramètres d'entraînement viennent du graphe ; un alias `registry_call`
ne peut pas rendre une mutation ML/données exécutable en mode conseil.

Les schémas imbriqués restent éditables via le mode JSON sans perte du composant
Skills existant. Il n'y a pas encore de formulaire métier visuel spécialisé.
Les protocoles temporels, groupés ou prédéfinis restent bloqués dans ces plans
d'entraînement, avec une raison explicite. La préparation temporelle P4 ne rend
pas à elle seule un split aléatoire approprié à un problème temporel.
Le corpus de douze missions et ses cas adverses vérifient les contrats ; aucune
économie de temps opérateur n'est déduite de ces seuls tests.
La comparaison observée du parcours actuel et du parcours assisté prévue en
sortie P2 reste à réaliser avec une baseline opérateur.

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
Le scoring shadow reçoit lui aussi l'ancre du registre et applique ce lecteur,
avec son plafond propre de 256 Mio vérifié avant toute copie. Les intentions
shadow historiques sans cette identité sont annulées explicitement ; aucune
ancre n'est reconstruite à partir des fichiers téléchargés.

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
amont complètes sont épinglées avec leur provenance dans le dépôt puis dans un
`license.json` inventorié et signé. Elles suivent les poids jusqu'à l'export
autonome ; un ancien bundle sans cette notice doit être repackagé et réimporté
avant de produire un nouvel export. Aucune sérialisation pickle d'estimateur
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
Le lecteur borne aussi le nombre de threads du profil enregistré par
`OMP_NUM_THREADS` du worker courant ; un entraînement à deux threads peut ainsi
être rechargé sur un worker limité à un thread sans élargir cette enveloppe.
Le profil d'artefact `tabicl-json-safetensors-v2` distingue ce code embarqué :
les exports pilotes `v1` sont refusés avant chargement et doivent être régénérés,
même si leurs versions de dépendances correspondent. Les smokes historiques
restent des preuves de l'ancien environnement, sans admission rétroactive.
Pas de promotion automatique, de champion de repli, de surveillance planifiée
ou de réentraînement automatique pour cette famille expérimentale.

La **régression TabICL est refusée**, avec ou sans cache, à la soumission et
avant prédiction, y compris pour un modèle déjà résident. Le premier
développement a révélé des écarts du profil sans cache après
éviction/reconstruction : jusqu'à `3,6621e-4` et
59/120 sorties au-delà de `rtol=atol=1e-6` dans une reproduction linéaire.
Entrées, cibles, poids et buffer de sortie n'étaient pas altérés. Le phénomène
peut disparaître dans un processus frais ; sa cause numérique interne n'est
pas isolée. Aucun seuil n'a été assoupli et aucune correction spéculative n'est
revendiquée. Le développement révisé a ensuite constaté un échec de parité du
profil avec cache sur `linear-regression-demo/dev-1`, sans dépassement de budget.
Un second échec de même nature est conservé sur `friedman-mixed-demo/dev-2`.
Le cache ne constitue donc pas une correction qualifiée. L'admission produit
refuse toute régression pour ce pilote ; les résultats expérimentaux des autres
tâches restent conservés sans rétablir cette admission. La classification
conserve ses deux profils candidats, sous les flags et grants du pilote.

Les [preuves diagnostiques P6](evidence/probabl-pilot-2026-10-11/README.md)
conservent les 51 cas terminés du premier développement : 48 évalués, trois
échecs de parité et 57 non évalués après arrêt. Elles sont reproductibles depuis
le commit `0cf5e01c7054059b26c03e3c87c0ed8aa257cf75` et n'autorisent aucune
décision de valeur. Le protocole révisé conserve les partitions, critères et
seuils ; ses neuf exclusions ne sont pas de nouvelles mesures. Le budget de
43 200 secondes de cœur inclut une réserve conservatrice de 8 071,139346 secondes
pour les tentatives interrompues et les diagnostics, distinguée du CPU mesuré.

La comparaison P6 mesure le **cycle du modèle directement** : préparation,
sélection/fit, prédiction, export skops ou JSON/safetensors, éviction et reload.
La projection CPU inclut le démarrage/imports et les processus enfants.
Elle n'inclut pas les transferts ObjectStore, l'enveloppe MLflow, RPC, contrôle
d'accès et HTTP du produit. Le serving de classification peut aussi effectuer
deux inférences (`predict` puis `predict_proba`) alors que la sonde comparative
appelle `predict`. Tous les candidats sont mesurés dans le même venv `ml-deep`,
qui diffère du packaging classique minimal. Une sélection technique positive
ne vaudrait donc ni validation de frugalité en production ni activation métier.
Le premier appel et le reload concernent l'objet modèle dans un processus
jetable : le cache de pages du système n'est pas purgé. L'hôte est partagé ;
ces mesures ne représentent ni un démarrage disque froid ni un p95 d'API.
Les tailles comparées sont celles des exports directs mesurés ; elles excluent
aussi la nouvelle notice signée transmise par le packaging produit.
Énergie, prix et ROI restent indisponibles.

## Décision comparative P6

La [campagne révisée complète](evidence/probabl-pilot-2026-10-11/revision-2/README.md)
conserve les 108 lignes de développement : **97 évaluées, deux échecs de parité
avec cache et neuf exclusions prévues**. La sélection exige les trois partitions
réussies ; les réserves finales des tâches linéaire et Friedman restent donc
fermées. Les quatre autres tâches sélectionnent le profil TabICL avec cache.
Leurs **12 cas finaux passent** (dummy, référence classique et TabICL par tâche).

**Aucun cas ne justifie une promotion selon les critères définis.** Les quatre
comparaisons échouent aux seuils combinés qualité/coût et à ceux de frugalité.
Le stockage augmente dans les quatre cas ; la tâche de retards échoue aussi à
la garde de rappel des classes. Le pilote reste désactivé par défaut et sa
régression refusée, y compris lorsqu'une autre tâche de régression a réussi
son test technique final. Aucune activation métier ne découle de ces mesures.

| Tâche finale | Référence classique | TabICL avec cache | Gain et IC 95 % apparié | Rapport CPU projeté |
| --- | --- | --- | --- | ---: |
| Breast Cancer | Linéaire, F1 macro 0,97158 | 0,98115 | +0,96 point [0 ; 2,94] | 3,56× |
| Iris | Linéaire, F1 macro 0,96658 | 0,96658 | 0 point [0 ; 0] | 3,02× |
| Retards synthétiques | HistGradientBoosting, F1 macro 0,54978 | 0,48320 | −6,66 points [−19,13 ; 0,40] | 2,52× |
| Régression linéaire | Réserve fermée | Non évalué | Échec de parité au développement | — |
| Friedman | Réserve fermée | Non évalué | Échec de parité au développement | — |
| Coûts synthétiques | Linéaire, MAE 1,89031 | 1,84152 | Réduction de MAE +2,58 % [−1,52 ; 6,42] | 6,65× |

Un F1 plus élevé ou une MAE plus basse est préférable. Les intervalles sont
calculés par tâche sur 2 000 bootstrap appariés, stratifiés pour la classification,
sans garantie simultanée sur les six tâches. Le rapport CPU projette le cycle
direct du modèle et **100 requêtes de 100 lignes** ; sa portée et les éléments
exclus sont précisés ci-dessus. Aucun score agrégé entre F1 et MAE n'est calculé.
Les rapports de coût sont des estimations ponctuelles sur un hôte partagé ;
deux répétitions de latence ne donnent pas un intervalle de confiance sur ces coûts.

Le développement et le final v2 mesurent **2 552,41 secondes de cœur**. Avec les
réserves antérieures distinctes de **8 071,14 secondes**, l'imputation atteint
**10 623,55 / 43 200 secondes**. Cette réserve conservatrice n'est pas une mesure
de consommation du modèle. Le code numérique gelé est celui du commit
`054d2596`, empreinte `8637ffcbced79aba7a5f8f44c61efb72fbef5503627e8ddbf7f59618efde0c4f`.
Les corrections ultérieures d'admission, de shadow et de transport de notice
ne modifient aucun des six fichiers gelés du protocole.

## Vérifications locales

Les suites ci-dessous se recouvrent : leurs nombres ne doivent pas être
additionnés comme des tests distincts. Les qualifications P1/P3 comparent le
runtime de base (skrub 0.10.1 / skops 0.14.0) au candidat (0.11.0 / 0.16.0).
Les premiers tests de services P2/P4 utilisent le runtime de base ; la régression
transverse et les qualifications P2/P4 finales utilisent le candidat. Les essais
TabICL utilisent le runtime optionnel CPU décrit dans la preuve hors réseau.

| Périmètre | Résultat et portée |
| --- | --- |
| Artefacts | 27 tests dans chacun des deux runtimes, puis 11 contrôles complémentaires dans le candidat ; refus avant désérialisation, quotas, chemins, types, versions et cache. |
| Shadow et profils embarqués | 31 tests de service/API et six tests shadow réels passent après raccordement au lecteur commun ; quatre gardes ciblées artefact/cache vérifient notamment le refus des exports TabICL v1 avant chargement. |
| Serving existant | 132 succès initiaux ; fixture d'absence d'objet corrigée après durcissement du namespace, puis ses deux cas de refus/absence passent. |
| Méthodes | 196/196 tests finaux dans le runtime candidat : méthodes/API/rollback, publication, alias, dispatch, droits, revue et retraining ; aucun skip. Les premiers passages 124/54/9 utilisaient le runtime de base. Corpus de 12 missions, sans mesure de productivité. |
| Préparation | Neuf tests dans chacun des deux runtimes, six roundtrips réels par runtime ; les six tests combinés calibration/seuil/CV/tuning passent. |
| Enrichissement | 29/29 tests de service dans le runtime candidat, contrôles API de replay et de droits, 59 tests frontend ciblés ; les parcours navigateur FR et EN passent. |
| TabICL | Premiers contrôles : 19 tests du pilote et 13 tests du runtime existant, deux vrais roundtrips MLflow et deux smokes hors réseau avec retrait de la copie source ; vrais rechargements cache avec passage de deux à un thread. Après retrait de toute régression : 23 tests serveur ciblés et deux tests HTTP vérifient le refus avant job, chargement, promotion ou publication. Ces smokes historiques ne rétablissent pas l'admission de la régression. |
| Notice et import TabICL | 38 tests passent sur pilote complet, notice, activation et import offline ; six cas ONNX optionnels sautés. Le transport signé → ObjectStore → cache → export autonome conserve la notice après retrait des sources, sans entraînement de poids factices. |
| Protocole comparatif | 13 tests passent : empreintes/partitions, exclusions irrévocables, sélection finale, budgets des processus descendants, vrai refus réseau seccomp et projection du coût complet. Les preuves des 108 cas de développement et 12 cas finaux sont conservées. |
| Régression transverse | 239 succès, six skips ONNX optionnels et cinq anciens contrats de tests à actualiser au premier passage ; après correction, les suites catalogue/familles (60 tests) et contraintes d'images (neuf tests) passent. |
| Admission HTTP | Le vrai schéma FastAPI accepte `tabular_foundation` pour ML et refuse les activations RAG/dataset ; test ciblé réussi. |
| Navigateur | 25/25 scénarios modèles/Skore passent sur le build final (2,9 minutes), dont dix cas TabICL FR/EN Studio/Flow/Play et les refus avec ou sans cache ; aucun timeout au dernier passage. Les deux parcours d'enrichissement ont été qualifiés précédemment. Un timeout initial sous compilation concurrente n'est pas reproduit, sans changer les délais ni les assertions. |
| Build | Compilation Angular de production réussie avec deux workers ; avertissements existants sur les dépendances CommonJS et les templates, aucune erreur de compilation. |
| Tests unitaires frontend | 2 113/2 113 tests passent dans la campagne complète, sans skip ; 123 tests ciblés après la première garde de profil, puis 127 tests des options, contrats de modèle et connecteur après retrait de toute régression et traduction des refus de notice. |
| Qualité statique | Contrôles i18n, navigation et chrome ; Ruff, format, conformité produit, secrets et contrôles de fichiers pre-commit réussis. |

L'isolation Giskard est conservée : son venv garde skrub 0.10.1 et skops 0.14.0,
séparément qualifiés. Le test de contraintes vérifie explicitement ces exceptions
sans modifier ses dépendances. Les tests ONNX sautés ne constituent pas une
qualification d'ONNX dans cette session.
La dernière suite de transport de notice utilise le runtime candidat, avec le
site-packages du pilote ajouté en dernier pour les métadonnées optionnelles
TabICL/torch requises par l'export d'état. Aucun environnement n'a été modifié ;
ce test ne constitue pas un nouveau fit ni une qualification d'image complète.

Le hook `pre-commit-update`, qui met à jour les outils de développement depuis
l'amont, est exclu du dernier passage ; sa modification automatique de Ruff a
été annulée. Tous les hooks de contrôle applicables ont été exécutés avec les
versions déjà épinglées par le dépôt. Le runtime du benchmark reste figé.

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
rétention existantes. Les méthodes peuvent être désactivées indépendamment avec
`ML_METHODOLOGY_ENABLED=false` sur l'API et les workers, puis leur redémarrage.
Catalogue et historique restent consultables. Un rollback skrub/skops exige l'image productrice
correspondante : ne pas tenter de lire les nouveaux artefacts dans un ancien
runtime sans qualification.

Les images de release, la restauration complète PostgreSQL/MinIO/MLflow et le
canari doivent être réalisés sur la VM désignée par le dépôt. Cette session
ne possède pas la clé SSH ni le réseau configuré pour cette VM : aucune
activation réelle ou restauration de la plateforme n'est revendiquée.
