# Hyusai — roadmap Skills Probabl, skrub, TabICL et skops

Date de cadrage : **11 octobre 2026**. État inspecté :
`a026ff1c7e763f68ab2fef92ea5d543913b6962c`, branche
`feat/skore-integration-lots-2-6`, cible d'intégration `demo/agentic`.

Le plan initial ci-dessous reste la référence des objectifs et critères de sortie.
Son implémentation se trouve dans `feat/probabl-ecosystem` ; le
[rapport de qualification](agentium-probabl-ecosystem-qualification.md) distingue
code réalisé, preuves locales, décision du pilote et activation réelle.
Les budgets et seuils de cette roadmap sont des critères d'expérience, pas des
résultats mesurés. L'intégration Skore précédente est qualifiée localement ; ses
builds et son activation VM restent à terminer selon sa
[roadmap](agentium-skore-integration-roadmap.md).

## 1. Résultat recherché

Permettre à un System Hyusai d'améliorer une prédiction utile, avec une méthode
explicite, des données traçables et un coût maîtrisé. Quatre contributions :

- **Skills Probabl** : améliorer le cadrage et les propositions des agents, en
  utilisant les contrats et les autorisations Hyusai.
- **skrub** : rendre la préparation réellement effectuée compréhensible,
  reproductible et plus utile sur des données métier hétérogènes.
- **TabICLv2** : mesurer l'intérêt d'un modèle de fondation tabulaire local comme
  challenger, sur un périmètre où il justifie son coût complet.
- **skops** : consolider les artefacts et leur compatibilité avant d'élargir les
  familles et les prétraitements proposés.

La valeur attendue est une meilleure décision à ressources comparables, ou un
coût inférieur à qualité comparable. Un score prédictif ne prouve pas à lui seul
un gain financier. Temps opérateur, coût calculatoire et impact métier conservent
des mesures et des niveaux de preuve distincts.

## 2. Invariants d'architecture

1. **MinIO/ObjectStore garde les octets ; MLflow garde le suivi, le registre et
   les références.** PostgreSQL conserve les objets et politiques Hyusai. Aucun
   `skore.Project`, Skore Hub, feature store, base d'expériences ou cache persistant
   partagé supplémentaire. Les caches de travail sont bornés, éphémères et isolés.
   Un état nécessaire au rechargement est un artefact versionné du modèle dans
   l'ObjectStore, avec ses droits et sa rétention.
2. La conversation et l'interface utilisent les mêmes Systems, Flows, services,
   autorisations, Runs et preuves. Aucun agent Probabl autonome parallèle.
3. Les méthodes suggèrent ; les services valident et exécutent. Une instruction
   Markdown ne confère aucun droit et ne rend pas une Skill `bound`.
4. Cadrage et optimisation utilisent les données de développement. Le test final
   est réservé à une évaluation du protocole figé ; il ne nourrit pas les
   propositions répétées de l'agent.
5. La souveraineté exige une preuve d'exécution locale sans sortie des données,
   sans téléchargement implicite ni dépendance à un fournisseur hébergé. Les
   licences ouvertes sont une condition de réutilisation, pas cette preuve.
6. Les poids profonds et TabICL restent dans le runtime optionnel `ml-deep`.
   L'API générale ne charge ni torch ni le modèle. Les pools apprentissage et
   prédiction existants restent distincts.
7. Publication, approbation, promotion et retour arrière suivent les mécanismes
   Hyusai existants. Le score d'un pilote ne déclenche aucune promotion automatique.
8. Absence de télémétrie = information indisponible, jamais coût nul ou gain
   présumé. Une fonctionnalité non qualifiée reste indisponible ou expérimentale.

## 3. Correspondance avec le mental model

Le [mental model](mental-model.md) et le [contrat des Skills](skills-runtime.md)
restent les références. Au cadrage initial, les noms ci-dessous étaient des
décisions de conception à stabiliser dans le lot P0. Les objets désormais
implémentés et leur portée sont décrits dans le rapport de qualification.

| Objet | Application dans cette roadmap |
| --- | --- |
| Capability | Réutiliser `tabular_models` et les capacités de données existantes ; relier le System à une fonction métier, sans Capability portant le nom d'un fournisseur. |
| System | Objectif, utilisateur de la prédiction, coût des erreurs et contraintes d'exploitation explicites. |
| Context | Références de datasets/version, profil autorisé, cible, date de disponibilité des variables, protocole et limites. Les prompts reçoivent des résumés bornés. |
| Skill | Primitive exécutable typée, versionnée et vérifiée, avec coût, durée et statut runtime. Un guide amont peut alimenter son template. |
| Flow | Composition publiée des étapes déjà exécutables, incluant les nœuds ML et les gates nécessaires. Une proposition devient une révision avant publication. |
| Run / SkillInvocation | Une exécution et ses appels réels : mêmes identités, snapshots, erreurs, durées et consommation. Aucun ledger d'expériences parallèle. |
| Decision | Proposition et autorisation restent distinctes. Réentraînement et promotion passent par leurs services/gates actuels ; pas par l'ancien Apply générique du Hypervisor. |
| Outcome / Impact | Qualité statistique, respect du budget et résultats opérationnels observés, avec références aux preuves et niveau de validation. |

```mermaid
flowchart LR
    O[Objectif du System] --> C[Cadrage et plan proposés]
    C --> V[Validation et publication du Flow]
    V --> P[Préparation et apprentissage bornés]
    P --> E[Évaluation et revue des preuves]
    E --> D[Choix du modèle et promotion existante]
    X[Context et politiques du workspace] --> C
    X --> P
    P --> R[Run et SkillInvocations]
    E --> R
```

Exemple de parcours : « anticiper un retard de livraison à partir des informations
connues à la commande ». Le cadrage définit l'erreur coûteuse et la date de
prédiction ; la préparation exclut les événements ultérieurs ; le Flow compare
les candidats sous budget ; le choix final explique qualité et coût observés.
Cet exemple illustre le contrat, sans présumer la disponibilité d'un dataset client.

## 4. État réel et versions candidates

| Brique | Présent dans le dépôt inspecté | Cible à qualifier |
| --- | --- | --- |
| Skore | 0.27.0 ; provenance, diagnostics de développement, revue `ml_evaluation_review_v1` et interface FR/EN. | Réutiliser ces contrats ; terminer la qualification de livraison existante. |
| Skills Probabl | Aucun pack méthodologique adapté. Skills Hyusai et exécuteurs vérifiés déjà présents. | Sélection du commit `9e1b9870113a0955de3c53f47820af0756dbe84d`, puis adaptations versionnées. |
| skrub | 0.10.1 ; `tabular_pipeline`, sélection selon estimateur, imputation, encodages auto/string/minhash ; `TextEncoder` local optionnel. | **0.11.0**, publiée le 1 octobre 2026 : qualifier séparément la compatibilité et les changements de préparation. |
| TabICL | Absent. `tabular_deep` signifie embeddings texte + estimateur sklearn classique. | Package **2.2.0**, publié le 2 septembre 2026 ; checkpoints officiels de classification et régression v2, révision et SHA-256 à figer en P5. |
| skops | 0.14.0 ; sérialisation classique, types contrôlés et tests réels de rechargement. | **0.16.0**, publiée le 24 septembre 2026, après qualification des artefacts existants. |

Versions candidates vérifiées dans les métadonnées PyPI le 11 octobre 2026.
`main` et la documentation `stable` ne constituent pas des versions de production.
Toute montée de version reste additive aux contraintes des images ; un échec de
qualification conserve la version actuelle, avec la limitation documentée.

Écarts observés qui motivent les lots :

- Le prétraitement présenté dans l'interface est générique ; les transformateurs
  effectivement ajustés ne sont pas décrits colonne par colonne.
- Le retrait des colonnes constantes précède actuellement le split dans le
  harness. Ce choix doit être appris sur le train, puis dans chaque fold concerné.
- SQL, Polars et dbt préparent déjà les tables dans les Flows. Une nouvelle
  orchestration de données skrub ferait doublon.
- Le manifeste complet est vérifié avant chargement pour `tabular_deep` et le
  clustering ; ce même contrôle n'est pas encore commun au tabulaire classique.
- La confiance skops est filtrée par préfixes de modules au dump. La liste portée
  par l'artefact doit aussi être confrontée à une politique côté lecteur.
- Les versions du runtime sont enregistrées ; leur enregistrement n'établit pas
  une compatibilité de rechargement entre versions.
- Les checkpoints TabICL `.ckpt` ne passent pas le contrat actuel de l'importeur
  de modèles locaux. Son `save/load` d'estimateur utilise pickle : aucune
  compatibilité skops ou conversion en safetensors ne doit être présumée.

## 5. Lots, dépendances et responsabilités

Tailles relatives : S = modification ciblée ; M = plusieurs contrats ; L =
intégration runtime/artefacts. Elles ne constituent pas des dates de livraison.
Chaque lot se termine par une revue de ses preuves, avec un résultat explicite.

| Lot | Livrable principal | Dépendances | Pilote de réalisation | Taille |
| --- | --- | --- | --- | --- |
| P0 — Contrat expérimental | Versions, périmètre, métriques, données candidates, budgets et critères de décision figés. | Socle Skore du dépôt | Produit + ML | S |
| P1 — Artefacts et skops | Vérification commune avant chargement, confiance contrôlée, matrice de compatibilité. | P0 | Backend ML + plateforme | M |
| P2 — Méthodes et Skills | Cadrage/plan typés, revue existante enrichie, passage à un Flow publié. | P0 ; P1 avant exécution de nouveaux modèles | Runtime agents + produit | M |
| P3 — Préparation skrub | Prétraitement observable, absence de fuite, choix sobres, qualification 0.11.0. | P0 ; P1 pour les exports | ML + interface | M |
| P4 — Enrichissement multitables | Un cas utile avec lignée et contraintes de jointure ; transformation apprenante seulement si nécessaire. | P3 ; P2 pour assistance au plan | Données + ML | M |
| P5 — Faisabilité TabICL hors ligne | Nouvelle famille expérimentale, chargement contrôlé, export/reload autonome et profil mémoire. | P0 + P1 | ML runtime + plateforme | L |
| P6 — Preuve de valeur TabICL | Benchmark borné, décision documentée CPU/batch/interactif ou arrêt. | P3 + P5 ; P2 pour l'évaluation du parcours agent | ML + produit | M |
| P7 — Consolidation et activation | Parcours FR/EN, preuves de livraison, canari et rollback. | Lots retenus qualifiés ; P6 positif pour exposer TabICL | Produit + plateforme | M |

P1, P2 et l'observation de P3 peuvent avancer en parallèle après P0. P4 ne bloque
pas le pilote tabulaire mono-table. P5 peut s'arrêter sans interrompre les gains
Skills/skrub/skops. P6 peut produire un résultat valable de non-adoption.

### P0 — Figer le contrat avant les expériences

- Identifier un cas métier mono-table et un cas multitables ; à défaut de données
  métier autorisées, utiliser des jeux ouverts licenciés et garder la preuve de
  valeur métier au statut non évalué.
- Fixer cible, unité de décision, métrique principale et sens, erreur acceptable,
  contraintes de confidentialité, taille des requêtes et objectif de latence.
- Geler datasets/version, exclusions, protocole de partitions et budget. Choisir
  les critères de gain avant le test final et conserver les décisions dans les
  artefacts et snapshots existants.
- Qualifier les dépendances candidates indépendamment. Inventorier les licences,
  révisions, empreintes et notices à redistribuer. Ne pas mettre à jour les
  contraintes du runtime général simplement pour satisfaire TabICL.

**Sortie :** un contrat lisible par le métier et validable par le backend, une
baseline reproductible et une liste explicite de données/manques. Un protocole
temporel ou par groupe non pris en charge doit être implémenté et testé avant
utilisation ; aucun remplacement silencieux par un split aléatoire.

### P1 — Consolider skops et le cycle des artefacts

Étendre le mécanisme d'intégrité existant, sans créer un registre supplémentaire :

1. Décrire famille, format, versions, politique de confiance, inventaire exact,
   tailles et SHA-256. Vérifier ces éléments **avant** le chargement MLflow et
   toute désérialisation. L'ancre de confiance vient des métadonnées autorisées
   du modèle et du producteur, pas du seul fichier téléchargé avec ses empreintes.
2. Borner la matérialisation : chemins relatifs, absence de traversée/symlink
   sortant, nombre de fichiers, volume total et volume décompressé du `.skops`.
   Le plafond actuel par fichier ne remplace pas un plafond par bundle.
3. Définir des profils de types réellement qualifiés pour les combinaisons
   supportées ; le lecteur refuse une liste `trusted` élargie par l'artefact.
   Aucun repli automatique de skops vers pickle pour faire passer un modèle.
4. Transformer les versions enregistrées en contrat de lecture. Qualifier
   0.14.0 → 0.16.0 avec les versions sklearn/skrub associées ; conserver le
   runtime producteur pour les artefacts anciens non compatibles. Pas de
   réécriture massive ni de réentraînement implicite.
5. Documenter les exceptions actuelles : embeddings en cloudpickle, prévisions
   classiques en joblib, fondation temporelle en JSON/safetensors. Une empreinte
   prouve l'intégrité attendue, pas l'innocuité d'un format exécutable.

**Sortie :** vrais roundtrips MLflow classification/régression, auto/string/minhash,
calibration/seuil et clustering ; parité des prédictions avant/après rechargement ;
refus avant load des altérations, types interdits, versions non qualifiées et
volumes excessifs. Les artefacts historiques sans manifeste restent explicitement
legacy : chemin compatible isolé qualifié, ou indisponibilité expliquée, jamais
marqués vérifiés sur la base d'un manifeste fabriqué après coup.

### P2 — Adapter les méthodes Probabl au runtime Hyusai

Importer une sélection documentée de pratiques, avec licence et provenance,
sous forme de templates contrôlés du dépôt. Garder les méthodes de cadrage,
planification, évaluation et audit ; traduire leur vocabulaire vers Hyusai.
L'amont sert de référence maintenable, sans récupération mutable à chaque Run.

| Besoin | Intégration proposée |
| --- | --- |
| Cadrer le problème | Skill proposée `ml_problem_frame_v1`, schéma métier validé côté serveur. |
| Préparer une expérience | Skill proposée `ml_experiment_plan_v1`, sélection parmi les opérations/familles autorisées. |
| Expliquer les résultats | Enrichir `ml_evaluation_review_v1` ; conserver ses preuves de développement et son statut propositionnel. |
| Construire/exécuter | Traduire le plan en révision de Flow ; utiliser les nœuds et wrappers existants. |
| Organiser workspace/Git/packages/publications/synchronisation | Garder les responsabilités Hyusai actuelles ; ces fonctions du pack amont ne sont pas importées dans le runtime. |

Le contrat de plan contient : objectif, dataset/version, cible, variables
disponibles au moment de prédire, hypothèses, baseline, métrique, partition,
budget, critères d'arrêt et preuves attendues. Les inconnues sont explicites.
Un protocole non supporté reste une proposition bloquée, pas un plan exécutable.

Les nouvelles Skills réutilisent les exécuteurs vérifiés `prompt_template` ou un
wrapper contrôlé selon le besoin. Le JSON d'un LLM passe une validation réelle.
Les templates sélectionnent des nœuds existants, sans exécution de Python généré,
installation de dépendances ou appel direct privilégié aux API internes.

Utiliser un modèle local autorisé pour le parcours souverain ; une indisponibilité
ne provoque pas de fallback cloud silencieux. Ne charger que les instructions
nécessaires, avec budgets de tokens/tours/temps et cache de template non sensible.
Les résumés peuvent contenir des informations sensibles : appliquer la politique
de données du workspace même si aucune table brute n'est envoyée.

Le plan accepté suit la publication et le snapshot `SystemVersion` existants.
Le contrat publié doit figer révision/digest de la méthode et contenu du template
si nécessaire ; un wrapper seedé doit aussi être lié à son runtime qualifié.
Un fichier chargé à la volée n'est pas figé par le seul snapshot du Flow.
La même publication doit exécuter la même méthode après une évolution de l'amont.
Les étapes ML mutantes restent initialement des nœuds explicites. Avant de les
exposer à AgentLoop, compléter la classification des effets dans `WRITE_SKILLS`
et tester les refus en mode `recommend` ; les slugs inconnus y sont aujourd'hui
classés en lecture. Le training impose déjà `_train` du graphe et le retraining
son approbation : préserver ces gardes plutôt que déduire un droit du prompt.

**Sortie :** sorties typées, mêmes droits UI/chat, refus inter-workspace et
d'escalade, aucune mutation par les Skills de conseil, publication stable,
abstention sur preuve insuffisante, absence du test final dans les entrées de
planification. Sur un corpus figé d'au moins 12 missions avec cas adverses,
comparer le parcours actuel/assisté : plans exécutables, erreurs méthodologiques,
temps actif opérateur, Runs inutiles, tokens et durée. L'objectif de gain est
fixé après mesure de la baseline, avant évaluation du parcours assisté.

### P3 — Mieux exploiter skrub et rendre la préparation vérifiable

- Corriger d'abord la sélection des constantes : apprentissage sur train et
  folds, application inchangée au test/serving. Préserver provenance et ordre
  des colonnes ; ne pas multiplier les fits pour produire un rapport.
- Produire depuis la pipeline ajustée un résumé borné : types retenus,
  transformations effectives, encodeurs, exclusions et raisons, dimensions,
  versions et temps. Le montrer dans Evidence FR/EN et l'exposer à la revue.
- Qualifier 0.11.0 séparément. Évaluer notamment la description publique des
  transformations ; vérifier les API de la release au lieu de présumer les noms
  `LLMEncoder`/`TextEncoder` de documentations de versions différentes.
- Conserver `auto` comme défaut sobre. Ajouter des choix déclaratifs par colonne
  seulement s'ils répondent à un diagnostic. Comparer les encodeurs déjà présents
  sous budget ; un nouveau codage supervisé doit avoir une qualification de
  cross-fitting avant exposition.
- Laisser le cache persistant DataOps désactivé. Un éventuel graphe DataOps est
  un détail interne borné de la préparation ; le Flow reste le graphe utilisateur.

**Sortie :** jeux couvrant nombres, dates, catégories, texte, valeurs manquantes
et colonnes constantes ; résumé identique après reload ; changement du test
réservé sans changement des choix appris ; cohérence train/CV/tuning/serving ;
tableau qualité/temps/mémoire/taille d'artefact. Si la montée de version change
les résultats, l'expliquer et conserver l'ancien runtime pour ses modèles.

### P4 — Un enrichissement multitables utile et borné

Choisir un cas réel : enrichir des commandes par des agrégats historiques
disponibles au moment de la décision, par exemple. Réutiliser les datasets,
versions et nœuds SQL/Polars/dbt ; ne pas reconstruire leurs jointures avec skrub.
Ajouter une transformation skrub seulement pour un besoin non couvert, tel qu'un
rapprochement de libellés, après qualification sur la release retenue.

Le contrat fixe tables, clés, cardinalité, agrégations, date de disponibilité,
taux de non-correspondance admissible et borne de lignes après jointure.
Les tables de référence et leur version sont enregistrées ; au serving, une
nouvelle référence ne peut pas remplacer silencieusement celle qualifiée.
Les agrégats temporels excluent les événements futurs ; les transformations
apprenantes et l'utilisation de la cible respectent train et folds. Le lignage
relie les lignes produites aux sources : sans cette preuve, ne pas déclarer
indépendantes des comparaisons entre datasets transformés différents.

**Sortie :** absence d'explosion de jointure, refus d'accès inter-workspace,
contrôle des événements futurs et des clés ambiguës, reproduction au serving,
comparaison avant/après sous même protocole et budget. Sans gain utile, conserver
le chemin de préparation existant et documenter le résultat.

### P5 — Construire la faisabilité TabICL avant son exposition

Périmètre initial : classification et régression mono-table, variables numériques
et catégorielles, poids figés. Nouvelle famille proposée `tabular_foundation`,
avec harness et pyfunc dédiés. Ne pas assimiler cette famille à `tabular_deep`
ni contourner la restriction actuelle des estimateurs classiques à `sklearn.*`.
Pas de fine-tuning, préentraînement, forecasting, SHAP coûteux, tuning libre ou
réentraînement automatique dans le pilote initial.

**Premier point d'arrêt : format et reproductibilité.**

- Figer package, révision des poids et empreintes. Le provisionnement est une
  opération séparée ; aucun identifiant distant ou chemin libre dans le payload.
- Les `.ckpt` officiels utilisent un chargement torch restreint `weights_only` ;
  le `save/load` de l'estimateur est un autre mécanisme, fondé sur pickle. Ne pas
  confondre les deux ni désactiver la règle générale de l'importeur Hyusai.
- Qualifier un adaptateur explicite : conversion vers tenseurs safetensors et
  configuration validée si réalisable, ou contrat de checkpoint tensoriel
  strictement borné dans le worker isolé. Comparer aux prédictions de référence.
  Si aucun chemin contrôlé et reproductible n'est établi, arrêter ce lot.
- Exporter état déclaratif, prétraitement, classes, paramètres, versions et
  contexte d'apprentissage avec un format non exécutable. Reconstruire les
  objets au chargement avec le code de confiance de l'image. Aucun pickle
  d'estimateur TabICL accepté par défaut, aucun type torch ajouté au profil skops.

**Contexte et stockage.** TabICL utilise les exemples d'apprentissage à la
prédiction ou une représentation mise en cache. Le contexte dérivé est donc
un artefact sensible du modèle ; le cache n'est pas présumé anonymisé. Conserver
droits, rétention, suppression et isolation du workspace pour ces éléments.
Le bundle autonome et ses poids/contexte vont dans l'ObjectStore existant, avec
référence MLflow ; une éventuelle déduplication utilise ce même socle. Le volume
local de provisionnement et les copies de travail restent des miroirs contrôlés
ou temporaires, pas des sources d'expériences indépendantes.
Réutiliser les grants et leases existants des artefacts locaux. Pour le premier
pilote, recalculer le cache à partir du contexte au chargement ; sa persistance
éventuelle devra devenir un format d'artefact explicitement qualifié.

**Runtime.** Étendre explicitement familles, catalogue, heartbeat, modèle local,
routage `ml_deep`/`ml_deep_rpc` et validation de serving. Réutiliser le superviseur
interruptible, les quotas et le cache borné. Fixer le device ; forcer
`allow_auto_download=False`, modes offline et absence de code distant. Le catalogue
reste indisponible si poids/runtime manquent ou divergent. La simple compatibilité
sklearn ne prouve ni clonage sûr, ni support des checks Skore : publier uniquement
les métriques évaluées et signaler les diagnostics non pris en charge.
Vérifier les grants à chaque exécution et prédiction, même sur cache chaud ; une
révocation bloque l'accès et déclenche l'éviction des données correspondantes.

**Sortie :** export réel classification et régression, suppression du répertoire
de provisioning initial, reload autonome puis prédiction identique sous tolérance
fixée. Réseau sortant effectivement bloqué pendant le test, vérification des
artefacts, timeout/annulation sans processus orphelin, isolation des contextes,
révocation après chargement, suppression/éviction, API sans import profond et pic
mémoire sous plafond.

### P6 — Démontrer ou réfuter la valeur de TabICL

#### Protocole comparatif

1. Constituer au moins six tâches prédéfinies : trois classifications, dont une
   déséquilibrée et une multiclasse, et trois régressions ; petites/moyennes tables
   numériques et mixtes. Ajouter un cas métier autorisé pour décider de son usage
   métier. Consigner licences, exclusions et limites des jeux synthétiques/publics.
2. Réserver le test final de chaque tâche. Comparer sur trois partitions de
   développement fixées à l'avance, identiques pour tous les candidats. Groupes
   et dates priment sur la stratification lorsqu'ils définissent le vrai usage.
3. Comparer : référence triviale, meilleur parcours sklearn/skrub actuel sans
   tuning, même parcours avec recherche bornée existante, et TabICL figé. Tous
   reçoivent les mêmes lignes, variables admissibles et budgets maximums ; leurs
   prétraitements respectifs sont inclus dans les mesures.
4. Borner les variantes TabICL avant campagne : un profil sans cache et un profil
   de cache mémoire, si supporté par la release. Choisir sur développement ;
   ne pas ajouter des essais après lecture du test final. Toute sous-sélection du
   contexte est déterministe, sans cible de test, déclarée et mesurée séparément.
5. Mesurer le cycle entier : préparation, fit, première prédiction, prédictions
   répétées, export, reload et éviction. Une partie du coût TabICL est dans
   `predict` ; comparer le seul temps de `fit` serait trompeur.
6. Évaluer une fois le protocole figé sur test final. Documenter les résultats
   appariés et leur incertitude, par tâche, sans moyenner des métriques de natures
   différentes. Un résultat insuffisant est conservé, pas remplacé par un jeu
   sélectionné après coup.

Répartir le budget avant campagne et ordonnancer les candidats de façon équilibrée.
Conclure uniquement sur les comparaisons appariées complètes ; un candidat non
exécuté après arrêt global est « non évalué », pas en échec. Une modification
après lecture du test final exige une nouvelle réserve indépendante.

#### Enveloppe initiale proposée

À confirmer sur le matériel cible en P0/P5 avant la campagne. Ces plafonds ne
constituent aucune promesse de vitesse ni une modification de Compose.

| Dimension | Limite initiale du pilote |
| --- | --- |
| Ressources | CPU en premier, 4 threads maximum, 1 job ; worker existant 8 Gio, serving 4 Gio ; garder de la marge sous les limites des processus. |
| Taille | Smoke à 1 000 lignes ; campagne jusqu'à 10 000 lignes et 100 variables ; toute extension forme une expérience distincte. |
| Temps par candidat | 10 minutes maximum par tâche/partition pour préparation + sélection éventuelle + fit + première prédiction ; dépassement comptabilisé comme échec sous budget. |
| Campagne | 12 heures de cœur CPU consommées au total, mesure des enfants comprise ; arrêt à la limite avec résultat partiel. Pas de prolongation silencieuse. |
| Artefacts | Plafond total proposé de 1 Gio par modèle, sous les plafonds par fichier existants ; stockage des poids, du contexte et éventuels caches comptabilisé. |
| Serving | Mesurer requêtes de 1, 100 et 1 000 lignes, froid/chaud séparés ; répétitions bornées, cache de modèles limité à 1 entrée. |
| GPU | Option ultérieure si matériel déjà disponible et question économique précise ; image CUDA qualifiée séparément, temps GPU, mémoire et coût déclarés. Aucune dépendance GPU imposée au parcours CPU. |

La mesure « frugale » comprend coût de préparation du modèle, coût de service sur
un volume de requêtes annoncé et stockage. Les prix doivent provenir d'un tarif
ou coût interne explicite ; sans cette donnée, publier CPU-secondes, durée et
mémoire, pas des euros inventés. Sans mesure énergétique, ne pas annoncer de
gain énergétique ou carbone. Une campagne synthétique ne prouve pas un ROI client.

#### Décision avant activation

Les seuils suivants sont proposés pour P0 ; leur version finale est gelée avant
la lecture du test final. Tous exigent souveraineté, intégrité et reproductibilité.

| Issue | Critère proposé et conséquence |
| --- | --- |
| Gain de qualité utile | Sur un segment métier prédéfini : au moins +0,02 sur un score de classification borné à maximiser, ou −5 % sur une perte choisie (régression ou classification) ; intervalle apparié excluant l'absence de gain ; coût complet au plus 2× la meilleure baseline qualifiée et SLA métier tenu. Exposition limitée à ce segment. |
| Gain de frugalité | Qualité non inférieure dans une marge fixée (0,01 absolu sur un score borné ou 2 % sur une perte), borne de l'intervalle apparié comprise dans cette marge, et coût complet inférieur d'au moins 25 % au volume de requêtes déclaré. Un gain de calcul ne doit pas masquer plus de stockage ou de travail opérateur. |
| Intérêt en batch seulement | Gain utile et budget respecté, mais SLA interactif non tenu : proposer seulement le scoring batch explicitement qualifié. |
| Incertitude | Échantillon ou mesures insuffisants : rester expérimental ; ne pas annoncer d'adoption générale. |
| Arrêt | Absence de segment gagnant, format non qualifiable, mémoire/durée hors limite ou sortie réseau nécessaire : conserver les modèles actuels et les résultats du pilote. |

Fixer en P0 la construction des intervalles à 95 %, appariée et respectant les
unités indépendantes (groupes/blocs lorsque nécessaires). Un calcul non fiable
avec les données disponibles conduit à l'issue « Incertitude ». Le gain de
qualité avec surcoût justifie éventuellement un usage, mais pas une affirmation
de frugalité : celle-ci exige la preuve de coût correspondante.

Le seuil métier peut être plus exigeant que ces propositions. Toute métrique
secondaire critique (calibration, classe rare, sous-groupe métier) possède sa
tolérance préenregistrée. Une moyenne favorable ne masque pas une régression
critique. Aucune sélection automatique de TabICL par l'agent avant cette décision.

### P7 — Consolider le produit et livrer progressivement

- Montrer dans les surfaces existantes : méthode/version, préparation effective,
  modèle candidat, périmètre qualifié, qualité, latence froide/chaude, mémoire,
  taille et limitations. FR/EN et même disponibilité dans Studio, Flow et chat.
- Faire produire aux Skills un choix expliqué à partir des preuves, y compris
  « conserver le modèle actuel ». Ne pas ajouter un écran d'orchestration Probabl.
- Qualifier l'ensemble : import/export, entraînement autorisé, prédiction,
  comparaison avec provenance, backup/restore, refus de droits et suppression.
- Distinguer code local, runtime qualifié, images qualifiées et activation réelle.
  Suivre le [processus de livraison](agentium-release-process.md) avec images
  immuables, budgets, sauvegarde et canari sur workspace désigné.
- Désactivation indépendante des guides, options skrub et famille TabICL. Le
  rollback retire les nouveaux choix et conserve les versions/artefacts lisibles
  ainsi que le modèle champion précédent. Aucune conversion destructive.

**Sortie :** preuves attachées au SHA livré, parcours métier démontré, restauration
testée et décision d'activation explicite par périmètre. Un flag activé ou une
PR fusionnée ne vaut pas preuve de déploiement.

## 6. Points d'intégration et vérifications attendues

| Domaine | Points de code existants | Qualification ciblée |
| --- | --- | --- |
| Skills et publication | [registry](../backend/app/services/skills_registry/seed.py), [wrappers](../backend/app/services/skills_registry/wrappers.py), [exécuteurs](../backend/app/services/skills_registry/executors.py), [bindings publiés](../backend/app/services/skills_registry/published_bindings.py) | Schémas, statuts, immutable publication, isolation, coût inconnu distinct du zéro. |
| Agents et droits | [AgentLoop](../backend/app/services/run_engine/agent_loop.py), [pont conversation](../backend/app/services/assistant/tools.py), [réentraînement](../backend/app/services/ml_retraining.py) | Effets read/write, même autorité UI/chat, absence d'entraînement ou promotion par la revue. |
| Préparation et preuves | [harness](../backend/app/resources/ml_train_harness.py), [revue](../backend/app/services/ml_evaluation_review.py), [transformations](../backend/app/services/tabular_transforms.py) | Folds sans fuite, résumé fidèle, provenance multitables et stabilité des prédictions. |
| Artefacts | [intégrité](../backend/app/services/ml/artifacts.py), [matérialisation](../backend/app/services/tabular_ml.py), [lecture tabulaire](../backend/app/services/tabular_predict.py), [runtime](../backend/app/services/ml/runtime.py) | Vérification avant load, confiance, quotas, roundtrips réels et versions legacy. |
| Modèles locaux | [familles](../backend/app/services/ml/families/__init__.py), [adapters](../backend/app/services/huggingface/adapters.py), [serving profond](../backend/app/services/ml/deep_serving.py) | Nouvelle famille explicite, egress bloqué, poids figés, cache isolé, chargement contrôlé. |
| Stockage et registre | [MLflow](../backend/app/services/ml_registry.py), [runtime local](agentium-ml-lot6a-runtime.md) | Références aux mêmes objets, aucune écriture dans un second backend, restauration autonome. |

Les tests portent sur les frontières et les comportements réels, pas sur une
copie des décisions d'implémentation. Prévoir notamment des artefacts corrompus,
un modèle avec types non autorisés, un test final modifié, une jointure future,
un runtime absent, une annulation et une demande inter-workspace. Réutiliser les
suites ML/Skore/deep existantes puis qualifier les parcours FR/EN concernés.

## 7. Sources et maintenance

Sources primaires consultées le 11 octobre 2026 :

- [Probabl Skills, révision étudiée](https://github.com/probabl-ai/skills/tree/9e1b9870113a0955de3c53f47820af0756dbe84d) ; licence BSD-3-Clause.
- [skrub 0.11.0](https://pypi.org/project/skrub/0.11.0/) et [historique des changements](https://github.com/skrub-data/skrub/blob/35effabc9dc2c65fd4a814f34c84aee629bde4e0/CHANGES.rst) ; BSD-3-Clause.
- [skops 0.16.0](https://pypi.org/project/skops/0.16.0/) et [persistance et compatibilité](https://skops.readthedocs.io/en/stable/persistence.html) ; MIT.
- [TabICL 2.2.0](https://pypi.org/project/tabicl/2.2.0/), [sources étudiées](https://github.com/soda-inria/tabicl/tree/c91f00df184a5097e584cb376f7e699e9f3444c4) et [poids officiels](https://huggingface.co/jingang/TabICL) ; code tabulaire et poids BSD-3-Clause. Le module forecast Apache-2.0 est hors périmètre.
- [Skore 0.27.0](https://pypi.org/project/skore/0.27.0/) ; MIT.

Conserver les notices dans les distributions et l'origine des adaptations.
La veille amont produit des changements relus et qualifiés ; aucune mise à jour
automatique de méthodes, dépendances ou poids sur les Systems publiés. Après
chaque lot, compléter ce document par un rapport de vérification et ses limites,
sans convertir une intention en affirmation de livraison.
