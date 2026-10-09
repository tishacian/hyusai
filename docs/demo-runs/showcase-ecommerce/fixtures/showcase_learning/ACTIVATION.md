# Activer le parcours Luma composé avec la charge et l'amélioration

Plan préparé le **9 octobre 2026**, à partir de lectures authentifiées du
workspace `agentium-showcase`. **Ce document n'est pas un reçu d'activation.**
Le [plan](live_learning_plan.json) contient la configuration complète ; la
[revue locale](live_learning_plan.review.json) conserve les IDs, versions,
empreintes et contrôles hors ligne. Aucun secret n'est inclus.

## Changement attendu

Un seul System métier, `f3ea83de-df89-45ec-8a85-c00d676b2713`, portera **24 nodes,
25 edges et trois entrées** :

- `source.request` : PostgreSQL → dataset → préparation SQL → score SLA →
  contexte du dossier → enquête/documentation → validation humaine → reçu simulé ;
- `source.queue` : lecture/préparation/scoring de la file, sans enquête ni reçu ;
- `source.forecast` : prévision native à 28 jours → SQL historique/prévision →
  dataset de courbe Work, sans toucher aux dossiers ni aux décisions financières.

La release Work contiendra **Dossier · Charge et capacité · Amélioration**.
Le studio métier reste le lancement par défaut ; sa navigation lit les pages
de la release et ouvre `/work/reclamations/charge` et
`/work/reclamations/amelioration`. Ne pas modifier `theme.live_href` pour afficher
ces pages. Le dossier générique conserve l'enquête et le recalcul et ajoute une
carte de prédiction tirée de la sortie intermédiaire `sav.context.model_advice`.

| Épingle | Valeur |
| --- | --- |
| Modèle SLA servi | `17331ddf-7811-42e1-8e0f-c8dc75dd3541`, v1 |
| Modèle de prévision | `ec5436b1-8233-4e06-9912-5bc9956c96f3`, Chronos v1 |
| Historique de volumes | `1268f620-0608-4a56-b095-0143e6e213e4`, 420 jours synthétiques |
| Ancien modèle d'apprentissage conservé | `67ee9f56-0a79-4ad6-b550-a932fa0d6e78`, v1 |
| Ancien System d'apprentissage à retirer du portefeuille actif | `04aaadef-e8d7-4614-aea0-454d08652e15` |
| Ancien System de scoring à retirer du portefeuille actif | `7477fafa-574b-479f-aea3-b8a5ac1fb540` |

La nouvelle lignée SLA a été entraînée via Model Center et son `system_id` est
vide. `training_history_model_id` identifie explicitement le **modèle précédent**
qui justifie l'archivage du System d'apprentissage. Ce raccordement ne réattribue
pas le nouveau fit à cet ancien System. Les deux Systems deviennent `retired` ;
leurs Runs, versions, datasets et modèles restent conservés.

Les sept modèles prêts sont consultables dans « Amélioration » : SLA calibré et
challenger réglé, durée avec intervalles, profils KMeans, naïf saisonnier,
prévision classique et Chronos. Aucun modèle de texte revu n'est annoncé ; la
cohorte de 480 messages demeure à étiqueter puis à revoir humainement.

## État de départ contrôlé

La publication métier reste v3, ID `af9c97e6-3060-4f6f-ad1a-c062f781d867`,
empreinte `2cc25fce82a3ba58b51944580ea35d977d9b70519681f3e6c8c9cf481d961554`.
La release Work attendue est `3e4f2bb8-6c49-4dd4-a307-16f240212563`.
Le draft observé est la révision 12, empreinte
`dd91c17260e93406ff5a56a79aad837b420caf109987078c2bbf813400a56111`.
Les publications/drafts des deux anciens Systems ont également été relus et
leurs empreintes figurent dans le plan et sa revue.

Le constructeur applique `reviewed_source_base()` : il retire uniquement les
quatre valeurs de normalisation inactives ajoutées par le Builder lorsque ces
clés n'existent pas dans la publication (`collections=[]`, `rag_mode=OmniRAG`,
`canonical_rag_mode=chah`, `context_reused=false`). Toute autre différence
fonctionnelle non publiée est refusée. Les numéros de révision dans la revue
locale décrivent le snapshot ; la CLI opérateur refait ses contrôles sur l'état
courant et utilise les CAS du produit pendant la publication.

Empreinte cible du Flow calculée localement :
`fad0507f94c836d392a5822c81aed47e482329b5f240398661c72c12b7944556`.
**Ce n'est pas `composition_sha256`.** L'empreinte de composition couvre aussi
les pages, bindings, épingles et archivages ; seule la revue CLI contre la base
déployée fournit la valeur à passer à l'application.

## Livraison et catalogue

1. Déployer la livraison finale de `demo/agentic` synchronisée sur Bitbucket avec
   le [runbook VM sûr](../../../../ops/agentium-safe-vm-deployment.md). Reconstruire
   et livrer backend, workers concernés et frontend. Conserver les runtimes
   `ml-ts`/`ml-deep` et le serving nécessaires aux modèles déjà entraînés ;
   les poids Chronos restent locaux. Vérifier les révisions frontend/backend
   et les images des workers. Ce plan n'installe pas les composants produit.

   La synchronisation intègre également l'implémentation Hugging Face. Respecter
   le [guide d'activation et de migration ML locale](../../../../agentium-huggingface-ml-migration.md)
   de cette livraison. **La migration Alembic 123 doit précéder le basculement
   vers le nouveau code**, car les contrôles de serving consultent le registre
   `HubArtifactUsage`, y compris pour les modèles v1. Cette migration de schéma
   est distincte d'une migration facultative des artefacts ML.
   Les modèles v1 non migrés continuent avec leur manifeste
   et provisionnement historiques. **Conserver ce provisionnement** pour le
   Chronos déjà entraîné ici. Une migration v2 est une opération explicite :
   même dépôt/commit/inventaire SHA-256, artefact activé avec vrai chargement et
   inférence (`loaded_and_inferred`) et heartbeats compatibles, puis
   `migrate-legacy` et contrôle de sa preuve. Après liaison v2, une révocation
   ne provoque pas de fallback implicite vers v1. Ne pas retirer le
   provisionnement v1 tant que ses usages ne sont pas migrés ou retirés. Luma
   n'exige pas une nouvelle acquisition publique pour publier ce parcours ;
   la disponibilité du nouveau connecteur ne vaut pas migration automatique.
2. Réconcilier le catalogue après examen du rapport complet :

   ```bash
   agentium-vm-deploy.sh catalog-check
   agentium-vm-deploy.sh catalog-apply
   agentium-vm-deploy.sh catalog-check
   ```

   Le premier contrôle peut annoncer `behind` avec le code 3. L'application porte
   sur toutes les différences canoniques affichées ; le dernier contrôle doit
   être `in_sync`. Le déploiement gère déjà le chemin et le tag d'image de ce
   script, comme décrit dans le runbook VM. Vérifier les Skills natifs de SQL,
   scoring, forecast et la Capability
   [Model Operations](../../../../agentium-model-operations-catalog.md).
   Le catalogue n'active aucune politique de surveillance à lui seul.
3. Vérifier les modèles épinglés `ready`, leur serving, l'accès PostgreSQL et
   les collections du dossier. Conserver les credentials configurés. Le plan
   ne réimporte ni les tables PostgreSQL ni les datasets et ne réentraîne rien.

## Revue fraîche puis application

Depuis le checkout propre de la livraison sur la VM, avec un opérateur autorisé
du workspace, commencer **sans `--apply`** :

```bash
LUMA_PLAN=docs/demo-runs/showcase-ecommerce/fixtures/showcase_learning/live_learning_plan.json
docker exec -i agentium-backend python -m scripts.activate_ecommerce_composition \
  --workspace agentium-showcase \
  --actor-user-id 06a2e190-ae2d-4365-b4f3-9952401f531d \
  < "$LUMA_PLAN" > /tmp/luma-learning-review.json
```

Inspecter `/tmp/luma-learning-review.json` : `applied=false`, Flow attendu,
24 nodes/25 edges, trois entrées, modèle SLA et ancien modèle d'historique
distincts, trois pages, deux nouveaux bindings, retrait des seuls deux Systems
nommés. Vérifier le SQL et les deux épingles du forecast, la classe positive `1`
et les bandes de priorité Work 0/0,35/0,60. Elles ne sont pas le seuil Youden du
modèle. Vérifier que le `flow_sha256` correspond à la cible ci-dessus.

Si la source, le draft métier, un binding, une release ou un modèle ont changé,
la commande doit refuser l'opération ou la revue doit être réexaminée. Ne pas
contourner les refus en remplaçant automatiquement les empreintes. Mettre à jour
la configuration à partir de nouveaux snapshots, puis reprendre cette revue.

Après lecture du résultat, copier **son** `composition_sha256` :

```bash
LUMA_REVIEWED_SHA='<composition_sha256 du résultat relu>'
docker exec -i agentium-backend python -m scripts.activate_ecommerce_composition \
  --workspace agentium-showcase \
  --actor-user-id 06a2e190-ae2d-4365-b4f3-9952401f531d \
  --apply --expected-composition-sha256 "$LUMA_REVIEWED_SHA" \
  < "$LUMA_PLAN" > /tmp/luma-learning-activation.json
```

L'activation conserve les versions et releases précédentes, publie le Flow,
épingle les trois bindings sur la même publication, déploie la nouvelle release
Work et archive les anciens Systems dans la transaction. Tous les bindings
requièrent la confirmation utilisateur. Conserver le reçu avec ses IDs et
empreintes. Ne pas rejouer les seeds historiques.

Ce plan n'est pas une commande de mise à jour de pages seules. Il refuse un
Flow inchangé (`CLAIMS_COMPOSITION_FLOW_UNCHANGED`) et le rejeu après activation
rencontre les nouveaux états/bindings : ne pas forcer une seconde application.

## Recette de bout en bout

1. Ouvrir `/work/reclamations/studio`, vérifier les onglets localisés de la release.
   Dossier reste dans le studio ; Charge et Amélioration ouvrent les pages du
   même Work. Vérifier clavier, clair/sombre, petit écran et actions compactes.
2. **Recalculer la file** avec confirmation : Run de `source.queue`, datasets
   préparé/scoré du même Run, modèle SLA épinglé, 23 dossiers attendus et aucun
   reçu financier. Les anciennes lignes scorées ne deviennent pas un résultat
   de cette nouvelle publication.
3. **Enquêter sur un dossier** : traversée du même pipeline puis `sav.context`,
   agent et pièces, validation humaine. La carte générique ouvre la vraie sortie
   intermédiaire du Run ; une prédiction absente reste absente. RC-1042/1043/1044
   conservent leurs preuves et règles historiques. Une action déjà simulée
   n'obtient pas un deuxième reçu.
4. **Charge → Actualiser la prévision** avec confirmation : Run de
   `source.forecast`, deux Skills natifs, dataset de prévision puis dataset SQL
   de 70 lignes (42 passées/28 prévues). Le chart lit `dataset_id` depuis le
   résultat de cette action autorisée et affiche courbe, bande, provenance et
   fraîcheur. Aucun run de prévision ne crée une réclamation ou un reçu.
5. **Amélioration** : ouvrir les sept modèles/véritables versions, leurs datasets
   et métriques ; le modèle SLA réglé reste un challenger, sa promotion est
   distincte. Les labels synthétiques et la revue de texte à effectuer restent
   explicites. Les politiques de monitoring/shadow ne sont pas activées par
   ce plan : elles se configurent séparément dans Model Center.
6. **Impact** : la vue enregistrée conserve le périmètre du même System, ses
   Runs et échecs. Distinguer enquêtes, recalculs et prévisions dans le détail ;
   ne pas compter chaque appel technique comme un dossier résolu ni multiplier
   ces appels par le bénéfice unitaire. Les hypothèses restent 8 min / 2 min /
   40 €/h / 0,50 € par dossier ; aucun ROI humain observé n'est ajouté ici.

Les notes `campaign-plan.md` et `capacity-policy.md` existent dans le pack, mais
leur ingestion n'est **pas incluse** dans ce plan d'activation. Vérifier leur
ingestion effective et le rattachement de leur collection avant d'annoncer que
l'agent les cite. De même, l'historique reste ancré au 9 octobre : une prévision
émise après ses premières dates cibles n'est pas une prévision observée en avance.
Le suivi des observations doit attendre des dates éligibles, sans réécriture
de l'heure d'émission ni régénération silencieuse d'« actuals ».

## Suites après publication initiale

Ces parcours sont préparés mais **n'ont pas été exécutés dans le workspace par
ce plan**. Ils enrichissent la même histoire ; ils ne bloquent pas la première
publication du Flow hybride et des pages Work.

### Surveiller et comparer le modèle SLA

Dans Model Center, ouvrir le nouveau SLA v1, puis **Monitoring**. Vérifier les
références statistiques du nouveau fit et les droits d'administration. Activer
la surveillance à une cadence explicite ; garder d'abord les propositions de
réentraînement désactivées pour observer les premiers contrôles. Vérifier le
scheduler/beat, le Flow géré, ses Runs et ses erreurs avant de présenter une
boucle planifiée comme opérationnelle.

Dans **Systems → Model operations**, retrouver le System technique lié à cette
version. Le filtre **Business** conserve Luma comme System métier. Le lien aux
consommateurs vient des nœuds ML de la publication : après activation, Model
Center doit retrouver Luma et indiquer que `sav.score` épingle v1. Ce lien est
une preuve de configuration, pas une propriété exclusive ni une allocation
automatique des coûts. Voir le
[contrat de portefeuille](../../../../agentium-model-operations-portfolio.md).

Le v2 `0c93ef17-3241-43bd-93dc-cc0d9c5524e1` appartient à la même nouvelle
lignée que v1. Dans la configuration **Shadow** de v1, vérifier que ce v2 est
le challenger compatible retenu, puis choisir explicitement taux et timeout
bornés. Des appels au modèle servi doivent créer les jobs de comparaison sans
modifier la réponse utilisée par le dossier. Montrer les effectifs, erreurs et
résultats disponibles ; **aucune promotion** n'est déclenchée par le shadow.
Les écarts observés sur cette cohorte synthétique ne prouvent pas un gain réel.

Pour le réentraînement proposé, utiliser des labels de **clôture après 72 h**,
pas l'approbation du remboursement. Le parcours requiert un champion en alerte
et au moins `max(40, ML_TRAIN_MIN_ROWS)` appels labellisés dans sa fenêtre ; le
feedback ne concerne que la première ligne par appel. La cohorte feedback du
pack peut qualifier ce contrat technique, en restant nommée synthétique.
Une personne examine une proposition et la porte HITL avant création du nouveau
challenger ; sa promotion reste une décision séparée. Après changement de
champion, revoir les politiques attachées aux versions.

### Qualifier les textes avec une revue réelle

Le dataset importé de messages est `a58c4067-1eea-48d3-bcda-e8340fcef74e`.
Vérifier qu'il est maintenant `ready`, contient les 480 lignes attendues et
aucune colonne de label avant de lancer le parcours décrit dans le
[README](README.md). Choisir le fournisseur du workspace, ses tarifs et budgets,
puis configurer `llm_label_dataset_v1` avec `initial_message` et les trois motifs.

La sortie reste non revue. Brancher la porte canonique
`review_dataset_labels`, faire lire/corriger **toute la cohorte** par une personne,
puis transmettre son dataset à l'entraînement. Comparer MinHash et MiniLM avec
les mêmes lignes/split ; MiniLM garde les options compatibles et ses poids figés.
Le nouveau catalogue Hugging Face peut fournir un artefact ML activé explicite
pour une future expérience ; il ne dispense ni de revue ni de contrôle de la
révision locale. Ne pas importer ou migrer un modèle pour la seule présence
d'un écran de showcase. Conserver les preuves LLM/revue/fit et leurs coûts
estimés, connus ou inconnus. Aucun dataset « revu » ni modèle distillé ne doit
être annoncé avant ces étapes réelles.

### Ajouter les notes métier et vérifier leur retrieval

Importer `generated/campaign-plan.md` et `generated/capacity-policy.md` dans
Document Center avec leur manifeste de référence. Attendre les jobs et vérifier
la lecture/recherche de passages. Rattacher la collection de contexte au même
System par la configuration produit, puis publier le changement avec ses
contrôles habituels. Tester une question sur la campagne et retrouver les deux
sources exactes depuis la réponse de l'agent. Ces notes ne remplacent pas les
politiques de remboursement et ne deviennent pas une covariable Chronos.

Les Runs MLOps restent consultables. Impact au niveau workspace peut les
inclure ; une vue limitée au seul System Luma ne les absorbe pas automatiquement.
Garder ce périmètre explicite et éviter le double comptage avec le budget complet
conventionnel de 0,50 €/dossier.

## Reproduire le plan hors ligne

Les snapshots doivent provenir de lectures récentes et autorisées :
`flow-before.json`, `flow-training-before.json`, `flow-scoring-before.json`,
`work-before.json` et les sept `model-*.json` nommés dans le constructeur.

```bash
DATABASE_URL=sqlite:///:memory: PYTHONPATH=backend backend/.venv/bin/python \
  docs/demo-runs/showcase-ecommerce/fixtures/showcase_learning/build_live_plan.py \
  --snapshots /chemin/vers/les/snapshots
```

Le constructeur valide le Flow et les pages et écrit le plan et sa revue locale.
Il ne contacte aucun service, ne se connecte pas à la base et n'applique rien.
Le [README](README.md) décrit les données, leurs splits et les tests.
