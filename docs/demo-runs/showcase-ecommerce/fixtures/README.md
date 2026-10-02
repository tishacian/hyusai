# Premier pack de sources Luma Maison

**Statut : assets préparés, pas encore chargés ni ingérés.** Aucun accès PostgreSQL, appel Agentium ou déploiement n’est exécuté par le générateur. Ce pack contient des données de démonstration et aucune mesure de ROI.

## Corpus documentaire

Les originaux de [documents](documents/) sont les fichiers à ingérer dans Document Center : **9 PDF, 1 DOCX et 1 Markdown d’archive**. Les fichiers de [source-texts](source-texts/) permettent de relire/éditer leurs textes ; ne pas les indexer en plus des originaux.

- Politique de remboursement v2, procédure d’enquête, contrat transporteur et guide de validation.
- Politique v1 archivée, explicitement remplacée par v2.
- Trois réclamations, un bordereau de livraison contradictoire, une confirmation de perte et un reçu de remboursement antérieur.

Le [manifest](manifest.json) conserve identifiants métier, versions, dates, rattachement à la commande et SHA-256 des originaux. À l’ingestion, compléter le mapping vers les véritables identifiants sources/collections/passages Agentium ; ils ne sont pas préinventés. Vérifier indexation, extraits, pages et ouverture des originaux.

## Source tabulaire PostgreSQL

[postgres/seed.sql](postgres/seed.sql) crée le schéma dédié `showcase_ecommerce` et sept tables : clients, commandes, lignes, expéditions, remboursements, réclamations et références documentaires. Le pack prépare trois dossiers de scène, un remboursement antérieur et les liens vers les onze documents. Les insertions ignorent les IDs déjà présents et ne réinitialisent pas les états. En cas de changement de fixtures, contrôler les versions et choisir explicitement la stratégie de mise à jour ; ce script n’est pas une migration de schéma.

Les [requêtes de lecture](postgres/read-queries.sql) sont des contrats de requêtes paramétrées pour le futur outil backend. Le fichier de seed n’a pas été exécuté contre le PostgreSQL fourni. Il faut le charger dans la base choisie avec un compte opérateur, puis donner au lecteur de la démo l’accès `USAGE` au schéma et `SELECT` aux seules tables nécessaires. Aucun secret ou création de rôle n’est inclus.

Les `knowledge_source_id` restent `NULL` jusqu’à ingestion effective. Le compte de lecture et ce schéma de sources ne réalisent pas les actions de remboursement ; celles-ci appartiennent au service d’action simulé et à ses reçus.

## Résultats de référence

| Dossier | Fait PostgreSQL | Fait documentaire | Résultat de contrôle |
| --- | --- | --- | --- |
| RC-1042 / LM-1042 | 420 EUR payés, adresse 75011, statut livré, aucun remboursement | Bordereau 75012, destinataire inconnu | Contradiction à instruire, sans conclure à une réception certaine. |
| RC-1043 / LM-1043 | 49,90 EUR payés, statut perdu, aucun remboursement | Perte confirmée CA-1043 | Proposition de remboursement sous validation humaine. |
| RC-1044 / LM-1044 | 89 EUR déjà remboursés, référence RF-1044 | Reçu RF-1044 du même montant | Seconde action identique bloquée, sans conclusion de fraude. |

## Reproduction

Le backend possède déjà les dépendances PyMuPDF et python-docx. Depuis le dossier `backend` du checkout :

```bash
.venv/bin/python ../docs/demo-runs/showcase-ecommerce/fixtures/build.py
```

La spécification éditable est [fixture_spec.json](fixture_spec.json). Le générateur contrôle les clés de rapprochement, les totaux de commande et le remboursement antérieur ; produit les originaux et leurs textes, le manifest et le seed ; et vérifie que chaque PDF tient sur sa page. Les métadonnées et dates des fichiers sont fixes pour que leurs hashes soient reproductibles.

La cohorte du benchmark manuel/assisté sera un autre jeu, versionné séparément. Ne pas utiliser ces trois dossiers connus du présentateur comme mesure unique du ROI.

## Vérifications réalisées à la préparation

Originaux contrôlés par extraction PDF/DOCX et lecture visuelle d’un bordereau ; références de commande, code postal contradictoire, marqueur synthétique et SHA-256 vérifiés. Une seconde génération produit les mêmes fichiers et hashes.

Le seed et les cinq contrats de requêtes ont fait l’objet d’un contrôle de compatibilité dans DuckDB en mémoire, sans les commentaires de métadonnées PostgreSQL. Les trois dossiers, références documentaires et remboursements attendus sont retrouvés ; une seconde charge n’ajoute pas de doublon et conserve un état modifié. Ce contrôle ne qualifie pas PostgreSQL : le chargement et les lectures sur l’instance cible restent à effectuer.
