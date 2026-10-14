# Contrat du scoring quotidien — Showcase

Le Showcase est l’environnement de recette. Aucun client pilote n’est exigé pour construire ou tester ce parcours. Les données de benchmark sont explicitement synthétiques ; elles ne prouvent pas une demande commerciale.

| Question de parcours | Réponse vérifiable |
|---|---|
| Pour qui et quel travail ? | Le responsable du System prépare chaque jour une base de scores exploitable par les membres autorisés de Showcase. |
| Quelle unité et quelle répétition ? | Une fenêtre quotidienne, 2 millions de lignes nominales, 3 millions en recette haute. Une ligne conserve son identifiant métier. |
| Quel résultat justifie l’acceptation ? | Un dataset immuable avec version du modèle, cardinalité complète, colonnes de prédiction documentées et qualification humaine liée au résultat exact. |
| Où et comment est-il reçu ? | Work, destination `work:showcase-scoring`. Un DeliveryReceipt atomique lie résultat, qualification, décision et fenêtre. Le téléchargement du reçu fournit les octets vérifiés. |

## Entrées et traitement

Le System publié utilise le Flow source → `data_prep_v1` → `ml_batch_score_v1` → sortie. Le graphe détient les paramètres et les ports ; un payload ne peut pas remplacer sa configuration. Le modèle servi et son lecteur sont figés à la soumission. Les familles tabular et clustering sont qualifiées pour ce worker ; les autres familles refusent ce placement.

Les entrées gouvernées peuvent être sélectionnées par `ServiceDefinition.inputs` : clé logique, type, fraîcheur maximale et qualification requise. La représentation `native_id` alimente `dataset_id` sans épingle statique dans le nœud de préparation. La fenêtre conserve `input_snapshot_json` pour ses reprises et revérifie les qualifications gelées avant constitution du candidat, approbation et publication. Une version manquante, périmée ou non qualifiée crée un incident pour son responsable.

Le worker lit des batches Arrow bornés (65 536 lignes par défaut), conserve toutes les colonnes sources et ajoute ses colonnes de prédiction sans collision. Son journal contient au plus 64 exemples ; les totaux portent sur toutes les lignes. Le modèle n’est chargé qu’une fois par exécution. Les sorties DataOps peuvent être une table Delta indépendante par version, sans append dans une table précédente.

## Sortie et recette

- `input_rows = scored_rows + excluded_rows` et `excluded_rows = 0` dans la première version : une erreur de ligne fait échouer le lot, sans livraison partielle silencieuse.
- Les prédictions des premières lignes reproduisent l’API native du même modèle ; la version servie et le digest des entrées ne changent pas pendant la reprise.
- Pas de valeur non finie, de prédiction manquante ou de cardinalité différente du manifeste.
- Le scénario haut contient 3 millions de lignes et des colonnes variées pour exercer l’I/O, les parts Delta, les profils et le spill. Le rapport indique durée, RSS, portée de la mesure, taille et nombre de parts.
- Une annulation, un worker perdu, un Run absent, une entrée périmée et une échéance dépassée doivent produire l’état attendu et un incident attribué. Les leases/fences empêchent une ancienne tentative de livrer après sa relève.
- Aucun résultat en attente de revue n’apparaît comme livré. L’approbation est liée aux trois empreintes affichées dans Work ; une qualification modifiée invalide cette revue.
- Le téléchargement et la restauration vérifient le journal Delta et tous les fichiers annoncés. Les versions retenues par un actif gouverné ne sont pas supprimées par le nettoyage des datasets.

## Ressources et exploitation

Worker permanent `dataops`, concurrence 1, cible 2 CPU/4 GiB. Timeout local 900 secondes configurable, DuckDB 1 GiB, spill 4 GiB. Le watchdog extérieur au scheduler rend visible une absence de fenêtre ou un lease expiré. Les réglages sont déclarés et les dépassements échouent avec un code ; ils ne déclenchent pas une infrastructure éphémère.

Les garanties de production exigent une recette sur les distributions réelles, la restauration et l’installation du watchdog. Le benchmark local doit distinguer un cap RSS supervisé d’une limite cgroup réellement appliquée. Kubernetes éphémère, Spark et les autres connecteurs restent conditionnels à un besoin mesuré.
