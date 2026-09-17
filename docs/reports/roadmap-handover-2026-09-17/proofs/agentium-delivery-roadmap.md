# Roadmap Agentium — du BRD au système utile, observable et industrialisé

## 1. Priorités et point de départ

**Ordre de livraison retenu : BRD → System, puis voix → connaissance réutilisable, puis Hyperviseur → action suivie.** Les approfondissements DataOps, MLOps et la généralisation complètent ensuite ces parcours.

La roadmap couvre les **21 effets du diagnostic**, auxquels s’ajoute **W22 — transformer un BRD en System fonctionnel**. Elle réutilise les contrats, moteurs et contrôles existants.

Référence applicative examinée : `demo/agentic`, SHA `30db8c07cc10`. Les corrections récentes du LLM Portal sont acquises : édition des paramètres, modèle effectivement exécuté, provenance et repli du chemin `workspace`. Leur qualification entre dans la roadmap ; leur réimplémentation n’y entre pas.

Les releases sont définies par leurs résultats et critères de sortie. Aucune date calendaire n’est engagée sans capacité d’équipe connue.

## 2. Développements et releases

### R0 — Un Showcase fiable et une lecture cohérente

**Résultat : les parcours de référence sont disponibles, compréhensibles et reproductibles.**

- Versionner les diagnostics et user stories de travail utiles, en actualisant leurs constats avec le code livré.
- Corriger les deux échecs connus des canaries Experience : application utilisable dans Work et contrastes du Studio. Qualifier les exemples et bindings nécessaires, dont la cible Workbench.
- Uniformiser la présentation des résultats : livrable principal, état réel, prochaine action, accès aux sources et au Run. Conserver les détails techniques accessibles.
- Corriger les liens restants, les états bloquants et les contradictions de vocabulaire. Retirer les affirmations économiques dépassant les preuves conservées.
- Fixer les jeux synthétiques, les configurations et les résultats attendus. Conserver un seul dataset NorthForge dans les démonstrations.
- Vérifier les gates locaux, le build VM et les canaries carakai sur le SHA candidat selon `agentium-release-process.md`. Le dépôt est hébergé sur Bitbucket ; aucune CI distante n’est actuellement active (confirmation du responsable, 16 septembre 2026).

**Sortie :** canaries requis réussis, parcours disponibles dans Showcase, configurations consignées et captures actualisées. Les premières sessions métier/développeur établissent la baseline d’adoption.

### R1 — Un BRD devient un System complet en draft

**Effets : W22, W10, W11, W12, W14.**

**Résultat : « Voici mon besoin ; voici le système proposé, son résultat et la preuve du traitement de mes exigences. »**

Le parcours comprend cinq étapes :

1. Importer le BRD structuré.
2. Relire les exigences, interdictions et informations manquantes.
3. Examiner le System proposé.
4. Exécuter ses cas de test et inspecter les résultats.
5. Publier explicitement une application pour un collègue autorisé.

La proposition comprend contrats d’entrée/sortie, Skills, Flow, mappings, ressources autorisées, configuration de modèle, contrôles et cas de test. Plusieurs exigences peuvent partager une même Skill. Une exigence non couverte reste visible.

La génération réutilise les drafts, validations et services de création existants. Elle conserve le BRD et relie **exigence → opération ou contrôle → test → Run**. Une nouvelle génération produit une proposition révisable ; elle ne remplace pas silencieusement un System publié.

**Deux BRD de référence :**

- **PIH SPARK-089 :** produire une synthèse documentaire avec titres et grades actuels/proposés, date, informations manquantes et citations. Le System traite l’extraction et la sélection des passages avant la synthèse, puis une revue du livrable. Il n’approuve pas la transaction.
- **NorthForge — préparation d’intervention :** investiguer une demande avec deux outils de lecture autorisés, notices et historique synthétique d’interventions. L’AgentLoop choisit les appels utiles ; les contrôles obligatoires restent dans le Flow.

Le premier périmètre de génération couvre ces familles documentaires et les exécuteurs déjà supportés. Une connexion absente, une exigence incompatible ou une permission manquante devient un point à résoudre dans le draft.

**Sortie :**

- Les deux BRD produisent des drafts exécutables sans assemblage manuel du Flow.
- Une exigence peut être suivie jusqu’à son résultat de test et son Run.
- Deux demandes NorthForge conduisent à des choix d’outils pertinents différents ; une demande hors mandat est refusée.
- La revue humaine, le refus et la reprise fonctionnent.
- Un second utilisateur consomme l’application publiée ; l’ancien résultat conserve sa version.

### R2 — La voix produit un livrable et enrichit les connaissances

**Effets : W01 à W03, W05 à W08.**

**Résultat : « Je transmets mon expertise ; un collègue peut ensuite la retrouver avec sa source. »**

Livrer en deux incréments :

- **R2.1 — Documents vérifiables :** réponse concise et passage accessible ; PDF natif, scan OCR et Excel avec page ou cellule d’origine ; chaîne dépôt, promotion, extraction et recherche lisible ; erreur distincte d’absence de données.
- **R2.2 — Capture réutilisable :** conversation et fiche visibles ensemble, interruption et correction conservées, revue explicite, publication, puis ouverture d’une nouvelle conversation sur la collection autorisée.

Réutiliser les exports et l’inspecteur de provenance existants. La publication Capture conserve son mécanisme d’ingestion actuel ; Deep Search conserve son `WorkspaceJob`. Chaque surface ouvre les preuves réellement produites.

Montrer le mode de recherche effectivement utilisé, son apport et son délai : recherche initiale, HAH/C-HAH ou approfondissement. Les sommes exhaustives passent par un dataset contrôlé et SQL/Polars.

**Sortie :** une référence synthétique est absente avant Capture, corrigée oralement, relue, publiée, puis citée exactement dans une nouvelle conversation. Le même parcours reste réalisable en texte. Les cas OCR/Excel et l’échec d’ingestion sont expliqués et récupérables.

### R3 — L’Hyperviseur permet de comprendre, décider et suivre

**Effets : W15, W16, W17 ; prolongement vocal de W01.**

**Résultat : « Cet objectif dérive ; je comprends les preuves, j’engage une action et j’en retrouve les suites. »**

- Implémenter **US-AHYP-603** : « Expliquer cet écart » transmet Systems, période, fuseau, métrique, objectif et références. Le retour retrouve la sélection d’origine.
- Étendre les lectures à la période demandée et rendre visibles couverture, exclusions et incompatibilités de comparaison.
- Présenter les sujets nécessitant une action : attente humaine, écart comparable, objectif absent, changement sans mesure.
- Raccorder la boucle de valeur à la V2 : scénario, simulation, décision, application et observation. La première action reste le patch de garde-fous déjà supporté.
- Permettre de demander un indicateur en langage naturel à partir des métriques supportées, avec proposition relue avant enregistrement.
- Ajouter tendances et export PDF/tableur du même périmètre, avec qualification des valeurs.
- Après qualification du parcours texte, transmettre le même contexte et les mêmes identifiants de requête par LiveKit. Une approbation reste une action explicite d’interface.

**Sortie :** un écart est expliqué sur la bonne période ; les Runs soutiennent l’analyse ; un changement synthétique suit la simulation approuvée et produit son reçu. Une observation absente reste absente. Le canari de boucle de valeur existant est exécuté sur une cible dédiée.

### R4 — Calculer, agir et améliorer avec des preuves

**Effets : W09, W13, W19, W21 ; approfondissements W10 et W12.**

**Résultat : « Le système accomplit plusieurs opérations ; je peux vérifier son calcul et mesurer les conséquences d’une modification. »**

- Finaliser Operational Analysis comme application : données → Python/Polars → synthèse → contrôle → revue.
- Ajouter les parcours SQL/Polars, branches parallèles avec Join et appel de sous-System, avec filiation des datasets et Runs.
- Comparer deux versions ou modèles sur les mêmes références : réponse, qualité, durée, coût qualifié et modèle effectif. Détecter une régression volontaire.
- Étendre les BRD supportés aux analyses tabulaires et actions outillées qualifiées.
- Livrer un premier effet externe sur un outil synthétique à état consultable : approbation, reçu, déduplication et traitement d’une réponse réseau incertaine.
- Pour les KPI personnalisés issus des anciens scénarios, calculer dans un Flow SQL/Polars évalué et publié ; l’Hyperviseur consomme une sortie métrique typée avec unité, période et provenance.

**Sortie :** NorthForge produit **120 minutes prévues, 155 réalisées, +35, trois dépassements, maximum NF-04 à +25**. Une régression est détectée. Une répétition ne duplique pas l’effet externe. Le choix de modèle et ses conséquences sont explicables.

### R5 — Faire évoluer un service prédictif

**Effet : W18.**

**Résultat : « Les corrections améliorent un candidat ; sa promotion reste contrôlée et son histoire reste lisible. »**

- Appliquer les autorisations canoniques aux mutations ML : entraînement, promotion et publication.
- Vérifier l’impact d’un changement de contrat avant promotion.
- Relier feedback relu, dataset versionné, entraînement, comparaison, promotion et prédiction via Skill.
- Conserver la version effectivement servie dans les preuves, y compris avec un champion dynamique.

**Sortie :** deux modèles sont comparés sur une population identique ; une promotion non autorisée échoue ; les nouveaux appels utilisent la version attendue et les anciens Runs gardent leur attribution.

### R6 — Généraliser les acquis clients et ouvrir la marque blanche

**Effets : W04, W20 ; généralisation de W02.**

**Résultat : « Cette application fonctionne dans un autre domaine avec ses données, ses accès et sa marque. »**

- Exposer dans l’UI les options existantes de Capture/FSE : contrat, sections du rapport, vocabulaire et ressources.
- Généraliser Client360 : mapping des données, règles d’éligibilité, explication des exclusions et brouillon contextualisé.
- Conserver l’envoi Client360 au stade brouillon jusqu’au raccordement de son effet aux garanties qualifiées en R4.
- Ajouter une permission de marque déléguable et révocable, limitée à ce périmètre.
- Transporter `platform_brand` via le mécanisme de Blueprint et son plan de validation existants.
- Installer les applications dans un second workspace synthétique avec remappage explicite des connexions.

**Sortie :** rapport et dossier commercial fonctionnent dans deux domaines ; la marque est configurable sans privilège d’administration générale ; brouillon et identité publiée restent distincts. **NAWA natif demeure inchangé**, avec recette visuelle et fonctionnelle dédiée.

## 3. Contrats communs à compléter

- **Construction depuis BRD :** conserver la route d’import actuelle ; ajouter une proposition validée côté serveur et son application idempotente aux objets canoniques. Stocker fichier, empreinte et correspondances d’exigences ; figer leur référence avec la version publiée.
- **Conversation :** étendre le contrat de tour avec le contexte Hyperviseur ; le réutiliser pour la voix. Vérifier chaque ressource et permission côté serveur. Navigation et changement de portée restent explicites.
- **Résultats et preuves :** présenter les références existantes de document, passage, Run, invocation, décision et effet externe sous forme de liens utilisables, sans journal concurrent.
- **Indicateurs calculés :** référencer une sortie typée d’un Flow publié et son Run de calcul. Aucune formule libre n’est exécutée par le panneau Hyperviseur.
- **Marque et ML :** compléter IAM et les contrats existants de Blueprint/promotion. Réaliser uniquement des migrations additives nécessaires.

## 4. Recette obligatoire

Chaque release comprend un succès, une absence légitime et un refus ou échec maîtrisé.

| Parcours | Vérifications décisives |
|---|---|
| BRD → System | Document vide/invalide, exigences non couvertes, provenance conservée, absence de duplication, ressource hors workspace refusée |
| AgentLoop et HITL | Choix d’outils observés, mandat et budget, instruction malveillante dans une source, refus humain, décision périmée, double envoi |
| Voix → connaissance | Interruption, correction exacte, reconnexion, échec puis reprise d’ingestion, nouvelle conversation et citation exacte |
| Runs et publications | Version exécutée, modèle effectif, parent/enfant, retour après navigation, application accessible au collègue autorisé |
| Hyperviseur | Même période et unités, couverture partielle, zéro distinct d’absence, simulation exacte approuvée, export réconcilié |
| DataOps/MLOps/marque | Calculs exacts, régression détectée, droits de promotion, historique conservé, deuxième workspace et protection NAWA |

Pour chaque parcours central : **cinq réussites consécutives**, avec nouvelle session et second utilisateur lorsque pertinent. Conserver les délais individuels, les preuves et les éventuels coûts ; ces essais constituent une recette interne.

Les sessions formatives restent nécessaires : cinq utilisateurs métier et cinq développeurs extérieurs à la conception. Cibles initiales : **4/5 trouvent un résultat et sa preuve en moins de dix minutes ; 4/5 développeurs adaptent et expliquent l’exemple en moins de trente minutes.**

## 5. Organisation des releases

**Ordre de sortie : R0 → R1 → R2 → R3 → R4 → R5 → R6.** Les préparations indépendantes peuvent avancer en parallèle : DataOps après le socle R1, généralisation après les contrats R2. Une seule version candidate est qualifiée à la fois sur la VM partagée.

Pour chaque livraison :

1. Développer sur une branche `codex/…` issue de `demo/agentic`, avec périmètre fermé et tests associés.
2. Passer `check:i18n`, `check:nav-links`, `check:ui-chrome`, tests unitaires, build production, tests backend concernés, puis les gates VM et canaries carakai du processus de release.
3. Intégrer et publier le commit sur `demo/agentic`.
4. Construire les trois images sur `omnirag-demo`, avec tags immuables par SHA.
5. Exécuter les canaries depuis **carakai**, vérifier le SHA servi et effectuer la recette manuelle.
6. Joindre résultats, captures réelles, courte vidéo du parcours et mise à jour des user stories FR/EN.

Activation progressive : **Showcase → interne → client pilote → généralisation**. Réutiliser les flags existants ; ne pas créer un drapeau permanent par effet.

Pour `adoption_experience_v1`, viser la **bascule par défaut en R2** après validation du pilote R1, puis le **retrait en R3** après un cycle stable. Tout report doit identifier le blocage et la release de remplacement.

Le rollback revient à une version compatible ou désactive l’expérience ; il ne restaure pas une ancienne base par-dessus des écritures récentes. **Tu décides des bascules et des releases**, sur les preuves techniques et utilisateur réunies.
