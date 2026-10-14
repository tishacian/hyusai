# Préparer des données dans un Flow

Le catalogue DataOps propose sept opérations : Préparer, Joindre, Union,
Agréger, Dépivoter, Découper et Échantillonner. Leur disponibilité dépend du
drapeau `dataops_enabled` effectif du workspace. Sans activation, les routes
DataOps répondent 404 et la palette reste masquée.

## Construire et inspecter

Ajouter une opération depuis la palette, puis choisir ses sources : une version
de dataset épinglée, ou une arête issue d'un autre nœud. Un même port ne peut pas
avoir les deux sources. Joindre utilise `left` et `right`, Union de deux à seize
ports nommés `in_1` à `in_16`. Les autres opérations utilisent `in`.

Dans Préparer, ajouter les étapes depuis les familles colonnes, types, valeurs
manquantes, lignes, texte, nombres, dates, calcul et confidentialité. Chaque étape
garde son identifiant lorsqu'elle est déplacée, désactivée ou commentée. Annuler
et rétablir conservent les 50 derniers états du brouillon. La limite est de
200 étapes, éventuellement abaissée par la configuration du serveur.

Les sélecteurs acceptent une liste, un motif, des types de colonnes ou toutes
les colonnes, avec exclusions. Le schéma affiché après une étape vient des types
physiques des entrées et du SQL compilé. Une conversion impossible d'une valeur
constante est refusée même sur une entrée vide. Une colonne de sortie existante
ne peut être remplacée que lorsque l'étape le demande explicitement.

L'aperçu d'une étape utilise uniquement son préfixe : une erreur dans une étape
ultérieure n'empêche pas de l'inspecter. Il peut parcourir jusqu'à dix niveaux
amont DataOps et 32 nœuds au total ; chaque source est autorisée séparément dans
le workspace. Une requête amont ne peut pas dépasser 1 Mio.

## Lire les résultats de l'aperçu

L'aperçu utilise les échantillons persistés, au plus 10 000 lignes par source,
avec un budget mémoire et une échéance. Il ne lit pas toute la table et ne crée
pas de version de dataset. La table affiche au plus 200 lignes, mais les profils
et les compteurs portent sur toutes les lignes produites par les échantillons.
Le calcul et le décodage des échantillons utilisent un processus séparé, sans
variables d'environnement de l'application. Le budget DuckDB vaut 512 Mio par
défaut ; la limite système d'espace virtuel ajoute 512 Mio pour les bibliothèques
natives, soit 1 Gio au total. Cette limite virtuelle n'est pas une mesure de RSS.
Elle est installée avant les imports natifs ; si le système ne peut pas
l'appliquer, l'aperçu est refusé. L'échéance arrête le groupe de processus et
vérifie sa terminaison. Le résultat transmis à l'API est plafonné à 32 Mio.
Pour une ancienne version sans échantillon, le worker DataOps le construit à la
première demande. L'atelier indique « échantillon en préparation » ; relancer
l'aperçu une fois la construction terminée. Le dataset reste disponible pour ses
autres lecteurs. Le travail est durable et peut reprendre après une interruption,
sans remplacer un fichier d'échantillon existant par des octets différents.
Les aperçus réussis sont gardés 60 secondes, pour au plus 64 entrées et 32 Mio
de contenu sérialisé. La clé distingue le préfixe, les versions d'échantillon,
le workspace, le port sélectionné et les limites de la requête.
Les statistiques portent la mention `stats_scope: sample` ; elles ne constituent
pas le profil de la population complète. Les échecs de `cast`, `parse_date` et
`parse_number` sont comptés par étape et colonne, sans compter les NULL entrants.

Les comptes d'une jointure ou d'une agrégation sur cet échantillon ne prédisent
pas nécessairement leur taille complète. Une jointure sans égalité affiche un
avertissement. Découper permet de choisir le port à prévisualiser. Nommer chaque
sortie et câbler explicitement son port évite de confondre les branches.

## Formules et sorties

L'éditeur de formules complète les colonnes et les fonctions du catalogue,
valide l'expression et affiche son type. Les sous-requêtes, accès à des tables,
fonctions hors catalogue et fenêtres libres sont refusés. `col_mean(a)` et les
autres `col_*` calculent un agrégat de colonne réutilisable sans modifier le
nombre de lignes. Les dates sont traitées en UTC. Les conversions numériques et
les fonctions gardent les conventions définies dans le plan de référence.

« Voir le SQL » rend la compilation visible. « Convertir en nœud SQL » conserve
les sources et les liens compatibles ; cette conversion est désactivée quand
elle exposerait un besoin de sel lié ou perdrait des branches. Un sel de workspace
est fourni au runner par paramètre lié, jamais intégré au SQL ni à l'aperçu.

Une exécution crée de nouvelles versions immuables, avec schéma, profil et
filiation `prep` : opération, spécification, empreinte, placement, entrées et
port de sortie. Les placements disponibles sont `auto` et `local`, tous deux
exécutés sur le worker permanent DataOps. Kubernetes éphémère et Spark restent
différés ; le catalogue ne les propose pas.

## Diagnostiquer et déployer

| Code | Action |
|---|---|
| `DATAPREP_DISABLED` | Faire activer le service pour ce workspace. |
| `DATAPREP_COLUMN_UNKNOWN`, `DATAPREP_COLUMNS_INVALID` | Actualiser le schéma et corriger le sélecteur ou la formule. |
| `DATAPREP_TYPE_MISMATCH`, `DATAPREP_LITERAL_TYPE` | Corriger la conversion ou sa constante, à l'étape indiquée. |
| `DATAPREP_PREVIEW_BUSY` | Attendre la fin de l'aperçu en cours. |
| `DATAPREP_PREVIEW_TIMEOUT` | Réduire le préfixe ou la complexité de la jointure sur échantillon. |
| `DATAPREP_PREVIEW_MEMORY_LIMIT`, `DATAPREP_PREVIEW_OUTPUT_LIMIT` | Réduire l'expansion des formules ou la taille du résultat d'aperçu. |
| `DATAPREP_PREVIEW_ISOLATION_UNAVAILABLE`, `DATAPREP_PREVIEW_CLEANUP_FAILED` | Faire vérifier les limites système et la supervision du processus avant de réessayer. |
| `DATAPREP_SAMPLE_REQUIRED`, `DATAPREP_SAMPLE_CHANGED` | Faire vérifier ou reconstruire l'échantillon ; ne pas substituer silencieusement les données complètes. |
| `DATAPREP_PLACEMENT_UNAVAILABLE` | Choisir un placement effectivement proposé par le serveur. |

Avant activation, suivre le [processus de release](agentium-release-process.md)
et le [runbook Showcase](ops/dataops-showcase.md). La réconciliation du catalogue
VM et son contrôle ne sont pas remplacés par un simple redémarrage du worker.
Les lecteurs Delta doivent être déployés avant l'activation des écrivains ;
consulter [stockage, téléchargement et purge](agentium-dataops-storage.md).
Le [suivi de qualification](codex-review-dataops-typed-judge-followup.md) distingue
les tests locaux des vérifications restant à faire avant une release.
