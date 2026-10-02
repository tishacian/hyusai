# Les preuves, les agents et l’application métier

Ce document précise le scénario demandé ; ses intégrations restent à implémenter. Les documents et fixtures tabulaires préparés sont répertoriés dans [fixtures](fixtures/README.md).

## Deux types de sources qui se complètent

| Source | Contenu | Ce que l’enquête doit établir |
| --- | --- | --- |
| Document Center → OmniRAG | Politique de remboursement, procédure SAV, contrat transporteur, règles de validation | Quelle règle est applicable à la date de la commande, quelles pièces sont nécessaires et quelle action est autorisée. |
| Documents du dossier | Réclamation du client, bordereau de livraison, confirmation de perte ou reçu antérieur | Ce qu’affirme chaque pièce, avec passage cité, version, page et lien vers le document original. |
| PostgreSQL | Clients fictifs, commandes, lignes, expéditions, réclamations et remboursements | Adresse de commande, montant payé, statut transporteur, remboursement antérieur et correspondance des identifiants. |

Pour LM-1042, la commande indique **75011** dans PostgreSQL et le bordereau indique **75012**. OmniRAG doit retrouver le passage du bordereau et la règle commerciale applicable. L’application met les deux éléments en regard. Une simple réponse générée sans documents et requêtes associés ne satisfait pas le scénario.

Le Document Center permet aussi de montrer le cycle complet : déposer les PDF et le DOCX, suivre l’extraction/indexation, prévisualiser l’original, poser une question et ouvrir les sources. Les textes Markdown du pack servent à éditer/reproduire les originaux, pas à créer des doublons dans l’index.

Les documents archivés sont distingués des règles en vigueur. Les pièces de dossier sont filtrées par leurs liens avec la réclamation/commande et par le workspace, avant récupération. Une citation doit correspondre à un document réellement ingéré et à un passage réellement retrouvé. Les clés de fixtures ne remplacent pas les identifiants Document Center après ingestion.

### Accès PostgreSQL attendu

Le backend utilise le connecteur du workspace, avec les secrets conservés côté serveur. La lecture métier doit être bornée au schéma `showcase_ecommerce`, aux tables/vues du pack et à des requêtes paramétrées. Le compte utilisé par l’agent est en lecture seule, avec timeout, plafond de lignes et annulation. Les secrets et les requêtes internes ne sont pas exposés dans Work.

Chaque lecture conserve sa provenance : connecteur, requête identifiée et hash, paramètres métier, horodatage, ensemble de tables et résultat/version de snapshot. Le snapshot est réutilisé pour une enquête afin d’éviter qu’une recommandation assemble des états incompatibles. Un snapshot DataOps doit rester identifié comme snapshot ; il ne prend pas le statut de lecture live.

La fixture SQL est un jeu métier stockable dans une vraie instance PostgreSQL. Elle n’est pas une réponse API simulée. Son chargement reste une étape opérateur distincte ; le compte de lecture ne crée pas les tables et ne réalise pas le remboursement.

## L’agentic doit se voir dans les décisions

La mission est : **résoudre ce dossier selon les règles et les preuves disponibles**. L’orchestration choisit ses prochains outils à partir de l’état de l’enquête.

| Responsabilité | Outils et preuves | Résultat attendu |
| --- | --- | --- |
| Coordinateur d’enquête | État du dossier, informations présentes/manquantes, politique d’action | Plan court, choix de la prochaine recherche, arrêt ou demande d’information. |
| Enquêteur données | Lectures PostgreSQL paramétrées | Faits structurés, montant, adresse, statut et éventuel remboursement antérieur. |
| Documentaliste | Recherche OmniRAG et ouverture des passages | Règles en vigueur et preuves du dossier, avec citations contrôlables. |
| Responsable de résolution | Faits rapprochés, règles citées, options de traitement | Proposition motivée ; aucune action financière autonome. |
| Contrôle puis exécution | Vérifications déterministes, décision humaine, outil d’action simulé | Autorisation effective, absence de doublon, action unique et reçu. |

Ces responsabilités peuvent partager des capacités ; multiplier les personnages ne constitue pas, seul, de l’orchestration agentique. Une preuve attendue est un **choix d’outil observable** :

- Si un remboursement est déjà enregistré, l’enquête bloque la nouvelle demande et présente le reçu ; elle ne poursuit pas inutilement une enquête de livraison.
- Si le bordereau manque, elle demande cette pièce et se met en attente, puis reprend avec les nouveaux éléments.
- Si les adresses divergent, elle confronte les deux sources et prépare une enquête transporteur ; elle ne transforme pas « livré » en preuve de réception.
- Une pièce ou un statut modifié invalide la recommandation à valider et demande une nouvelle vérification.

Les contrôles monétaires, les doublons, les transitions d’état et les droits sont appliqués par le backend. Ils ne reposent pas sur la seule consigne du modèle. La trace conserve le plan, les outils appelés, les sources retenues, les révisions de preuves, les contrôles et la décision humaine.

## Une belle application, utilisable par le SAV

Le titre métier est **Réclamations**. L’écran de travail utilise les tokens UI existants, une typographie lisible et une action principale contextualisée.

- La file présente les dossiers à traiter, leur montant, ancienneté, priorité expliquée et prochain geste utile.
- À 1440 px, la fiche juxtapose **commande et historique**, **preuves et analyse**, **décision** ; à 1024 px, les panneaux se réorganisent sans masquer les justificatifs ni faire déborder la page.
- Les faits confirmés, contradictions et informations manquantes ont des états visuels et des libellés distincts. Les montants et adresses restent comparables sans ouvrir une console.
- L’analyse affiche une progression compréhensible : « Vérification de la commande », « Recherche des justificatifs », « Une contradiction à examiner », « Décision attendue ».
- Le passage cité ouvre le bon document/page et le retour conserve la sélection du dossier et la progression. Les références SQL apparaissent comme une provenance métier lisible.
- La validation montre l’action, le montant et ses conséquences avant confirmation ; un double clic ne produit qu’une action. Les états d’échec et de reprise conservent le travail déjà fait.
- Après exécution, le reçu et l’historique permettent de retrouver les preuves. La vue Impact utilise le même système et la même période que l’expérimentation.

Les détails de DAG, modèle, tokens et SQL sont accessibles au créateur/présentateur depuis la trace. L’utilisateur SAV dispose des informations nécessaires à sa décision dans la fiche métier.

## La trame de démonstration

1. **Work** : une réclamation de 420 €, contradictoire et prioritaire, à résoudre.
2. **Document Center/OmniRAG** : ouvrir la politique et la preuve de livraison ; montrer ingestion, recherche et citations.
3. **PostgreSQL/Data** : retrouver la commande et les remboursements ; montrer le lien vers les sources et, si utilisé, le snapshot et sa lineage.
4. **Agents** : lancer l’enquête et expliquer le choix des outils, la contradiction et les informations manquantes.
5. **Application métier** : examiner les options, décider et retrouver l’action simulée et son reçu.
6. **Trace et audit** : vérifier que les sources, décisions et événements appartiennent à cette exécution.
7. **Impact** : présenter le benchmark effectué, le temps réellement mesuré, sa convention de valorisation, les coûts et le ROI de la démonstration ; ouvrir ses preuves.

## Écarts constatés dans le code actuel

| Capacité | Constat | Travail à réaliser |
| --- | --- | --- |
| Documents | Les endpoints Document Center, extraction PDF/DOCX et retrieval existent. Le nouveau corpus n’est pas ingéré. | Créer les collections Showcase et leurs métadonnées, ingérer les originaux et vérifier les passages/citations. |
| PostgreSQL | Le connecteur générique teste la connexion par `SELECT 1`. Le chemin métier de lecture tabulaire reste à construire. | Lecture bornée et provenance, puis bridge de snapshot pour DataOps si nécessaire. |
| Business app | La plateforme Experience existe ; Réclamations n’est pas publiée. | Construire/publier l’application et ses bindings au système métier. |
| ROI | Impact distingue les bases déclarées et les mesures. Le moteur de valeur actuel peut dériver une valeur d’une convention ; cela ne mesure pas un gain de temps. | Instrumenter un benchmark manuel/assisté et exposer ses preuves dans Impact. |
| Boucle de valeur | `baseline_run_exclusion_reason` refuse les runs synthétiques ; la baseline de Lot 8 exige une preuve runtime indépendante. | Un benchmark de démonstration identifié comme tel, séparé de la baseline de production. Aucun changement des marqueurs synthétiques pour franchir le gate. |

Les essais cloud précédents n’ont pas atteint le PostgreSQL fourni avant authentification. La connectivité doit être vérifiée depuis le backend/worker qui exécutera réellement le scénario. Ce constat ne prouve pas un défaut de la base.
