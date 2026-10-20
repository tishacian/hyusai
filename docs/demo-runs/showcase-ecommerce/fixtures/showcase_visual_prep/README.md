# Luma : préparation visuelle du dataset SAV

Cette configuration remplace le SQL de `sav.prepare` par une préparation native
`data_prep_v1`, modifiable dans l'atelier DataOps existant, et adapte ses ports
et le binding du scoring consommateur. Elle ne crée ni System, ni Skill
spécifique, ni dataset supplémentaire au moment de la publication.

Les quatre étapes sont : sélectionner l'identifiant et les six entrées du
modèle, calculer `evidence_gap`, calculer `duplicate_refund_check`, puis trier
par identifiant. Les formules conservent les NULL ; aucun fait manquant n'est
inventé. Les deux indicateurs ne sont ni une décision de remboursement ni de
nouvelles variables prédictives.

## Appliquer avec la publication composée

Charger `configuration.py` et appeler `build_flow(flow)` sur la publication
fraîche. Appliquer la même fonction séparément au brouillon : elle conserve
notamment le nœud utilisateur `nodePrepare`. La fonction refuse un SQL ou une
source modifiés et ne remplace pas arbitrairement une préparation déjà éditée.
Une configuration déjà identique peut être relue sans modification, après
revérification de la source, des arêtes, des ports et du Skill de scoring.
Une préparation native portant encore l'ancien nom de sortie est refusée,
et nécessite un diff ciblé relu ; elle n'est pas migrée silencieusement.

Le composeur `showcase_quality_events/compose_four_lots.py` compare également
tous les paramètres du nœud de prévision entre publication et brouillon avant
de les modifier. Une version, un horizon ou un intervalle édité dans le brouillon
fait arrêter la composition pour préserver le choix de l'utilisateur.

Le résultat change le nœud `sav.prepare`, le port d'entrée de son arête
depuis `sav.features`, le port de sortie vers `sav.score` et le binding du dataset
consommé par ce dernier. Les identifiants, libellés et positions des nœuds sont
conservés. Le dataset produit porte en revanche le nouveau nom
**Luma — Préparation visuelle SAV** : ses versions appartiennent à une nouvelle
lignée native `data_prep_v1`. La lignée historique **Luma — Données SAV préparées**
reste attribuée à `sql_transform_v1`, avec ses versions et ses preuves intactes.
Réutiliser son nom serait refusé par `DATAPREP_OUTPUT_SLUG_TAKEN` : le contrôle
empêche un autre producteur de reprendre une lignée existante. Ce changement de
nom ne rompt pas le scoring ni Work, qui suivent le dataset du Run et le nœud
`sav.prepare`, et non un slug historique figé.

Les paramètres ne figent aucun dataset :
l'arête fournit l'extraction PostgreSQL du Run courant. Le Skill natif publie
`dataset_id` au premier niveau, `source=transform`, `node_id=sav.prepare` et sa
filiation. Le scoring lit l'enveloppe du port `out` via l'arête, avec
`passthrough_inputs=["dataset_id"]` explicite pour le mode strict. Les ports
visuels DataOps représentent les sorties dataset, pas les champs de leur
enveloppe ; `dataset_id` n'est donc pas déclaré comme un second port. Les
paramètres du modèle et les lecteurs Work restent compatibles.

Vérifier avant publication que `data_prep_v1` est dans le catalogue autorisé et
les Skills du System, que la préparation est activée pour le workspace, et que
le worker DataOps de la révision déployée est disponible. Utiliser la publication
et les bindings Work existants ; ne pas rejouer l'installation initiale de Luma.

## Parcours de démonstration

Depuis Work, recalculer la file puis ouvrir son Flow pour voir les objets du
Run. Dans l'éditeur, **Ouvrir l'atelier** du nœud **Préparer le dataset et les
contrôles SAV** montre les quatre étapes et leurs commentaires. Les résultats
d'un Run Work ne sont pas automatiquement chargés comme entrées de cet atelier.

Après déploiement du sélecteur générique d'entrée d'aperçu, sélectionner
`sav.prepare` et ouvrir l'atelier. Dans **Données pour cet aperçu**, choisir
la version **Luma — Faits SAV PostgreSQL** produite par le Run Work terminé :
vérifier le nom, la version et le lien vers le Run, dont le nœud producteur est
`sav.features`. La source du Flow reste **Utiliser la sortie amont** ; le choix
du jeu est limité à cette ouverture de l'atelier. Demander l'aperçu, inspecter
les deux colonnes de contrôle et consulter le SQL compilé. Aucune épingle ni
sauvegarde de brouillon n'est nécessaire ; le nœud utilisateur isolé reste
intact. La conversion en nœud SQL est désactivée tant qu'une entrée temporaire
est choisie, pour ne pas transformer ce choix d'exploration en dépendance du Flow.

Ce parcours ne prétend pas que les étapes éditées ont été exécutées dans le
Run d'origine. Celui-ci prouve la provenance du dataset choisi ; l'aperçu
évalue les étapes courantes sur un échantillon de cette version. Les contrôles
d'accès aux datasets du workspace restent ceux des API DataOps.
Un changement d'entrée ou de préparation efface les résultats périmés ; une
fermeture, un rechargement ou un changement de contexte perd le choix temporaire.

Le raccord **Exploiter → Atelier d'essai → Nœud** reste utilisable pour les Skills
qui acceptent une exécution isolée. Il ne convient pas à `sav.features` : la
recette live du 20 octobre sur `1b36e8a1` a obtenu
`CLAIMS_COMPOSITION_FLOW_REQUIRED`, car la projection isolée ne porte pas le
contrat de composition et le point d'entrée qui déterminent le périmètre SAV.
Ne pas inférer une opération « file » depuis `{}`, supprimer les contrôles,
ni modifier le brouillon utilisateur pour contourner cette condition.

Ouvrir ensuite le dataset publié depuis l'inspecteur, puis le dataset scoré et
le modèle SLA. Revenir à la file Work et poursuivre le même dossier. Ne pas
publier une modification pédagogique des règles sans requalifier les sorties.

## Vérification

`backend/app/tests/services/test_ecommerce_visual_preparation.py` compare le
SQL précédent et le compilateur DataOps réel sur 23 lignes variées, des NULL et
une entrée vide : même schéma, mêmes lignes, mêmes six variables prédictives.
Il vérifie aussi la conservation des autres nœuds et du brouillon utilisateur.
Le test d'intégration conserve une version SQL historique sous l'ancien nom,
publie un Flow et une Work release locaux puis exécute la préparation native et
un modèle réellement entraîné. Il vérifie le nouveau slug, l'ancien producteur
inchangé et la filiation du dataset scoré vers la nouvelle préparation.
Seule la lecture externe
PostgreSQL utilise une fixture ; aucune prédiction ni sortie DataOps n'est
remplacée par un résultat simulé.

Le 19 octobre, le snapshot complet des 23 lignes du dataset d'entrée
`ee16192e-badc-4fa1-ac98-d31fd7b6e757` a aussi été compilé et exécuté localement.
La préparation est exactement équivalente au SQL de la publication v5
`f3fc70cd-0a51-4719-bbf3-ce30d787f4d4`, empreinte
`3a76ce8d45886496cf64bd6c2785a507265a8bac1fc6f68b97189e57c0310921` :
23 lignes, neuf colonnes de mêmes types, zéro `evidence_gap` et cinq
`duplicate_refund_check`. Ce résultat ne qualifie pas une publication ou une
nouvelle exécution live ; la recette Work doit les constater séparément.
