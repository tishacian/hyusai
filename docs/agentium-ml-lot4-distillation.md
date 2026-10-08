# Lot 4 — Étiquetage, revue humaine et distillation

Le parcours tabulaire est complet : le modèle du workspace étiquette les textes,
une personne confirme ou corrige les classes, puis un modèle sklearn apprend sur
les données revues. Sa carte compare ses réponses aux classes LLM d’origine et
aux classes confirmées par la personne. Aucun appel LLM supplémentaire n’est
nécessaire pour entraîner ou comparer le modèle.

Le 4a est décrit dans [le contrat d’étiquetage](agentium-ml-lot4a-labeling.md).
Le 4b ajoute la revue et la distillation sur ce socle. La classification de texte
du lot 2 fournit déjà les encodeurs. Le NER spaCy reste une capacité conditionnée
à un cas client dans la roadmap ; les embeddings profonds relèvent du lot 6.

## Composer le Flow

1. Relier un dataset à **Label Dataset with LLM** et renseigner les colonnes de
   texte, les classes, la consigne et les tarifs estimatifs. Les limites et la
   reprise sont celles du 4a.
2. Ajouter la porte humaine existante, choisir **Revoir les étiquettes d’un dataset**
   (`prompt_kind="review_dataset_labels"`) et la relier à la sortie d’étiquetage.
3. Relier la porte à **Train a Model**, avec la tâche `classification`, la cible
   créée par l’étiquetage (`label` par défaut) et les colonnes de texte comme
   variables. La référence du dataset vient de la porte ; aucune épingle vers
   le dataset antérieur n’est nécessaire.
4. Lancer le Flow. Le terminal et la boîte de validations de l’espace opérateur
   proposent la même revue et utilisent la même décision.
5. Parcourir les lignes, corriger les classes si nécessaire, puis confirmer
   explicitement l’ensemble du dataset avant d’utiliser le bouton d’acceptation
   existant. Le refus arrête ce parcours sans lancer d’entraînement.
6. Ouvrir les résultats du modèle pour consulter la carte **Distillation**.

En mode strict, choisir `label.dataset_id` comme entrée `dataset_id` de la porte,
puis `review.dataset_id` comme entrée `dataset_id` de l’entraînement. L’éditeur
et le serveur dérivent ces ports du mode de revue, y compris au chargement d’un
Flow déjà sauvegardé. Un nœud de validation ordinaire n’expose pas ce dataset en sortie.
Ses entrées déclarées restent inchangées, notamment les contextes de type texte.
Le mode revue conserve aussi les entrées de contexte et ajoute l’entrée typée
`dataset_id` ; seules les sorties de la porte sont imposées par le runtime.

Le formulaire d’entraînement propose un coût d’inférence estimatif du modèle
pour 1 000 lignes, facultatif, en USD. Il est réservé à la cible d’un dataset
revu. Une valeur zéro est explicite ; un champ vide reste indisponible.
Ce paramètre est commun au studio et à l’atelier Flow.

## Revue et intégrité

La porte fige l’identifiant, la version et l’empreinte SHA-256 du dataset LLM.
Les lignes sont paginées, avec un identifiant stable égal à leur position dans
le fichier immuable. Seules les colonnes de texte utilisées pour l’étiquetage
sont affichées dans la revue. Les corrections sont conservées entre les pages ;
un changement de workspace, de décision ou d’empreinte invalide la saisie.

L’API de lecture est
`GET /runs/{run_id}/label-review?expected_decision_id=…&offset=0&limit=50`
(100 lignes au maximum). L’acceptation reste `POST /runs/{run_id}/hitl` ; son
champ `label_review` porte l’identifiant et l’empreinte observés, une confirmation
explicite et les corrections `{row_id, label}`. Les classes inconnues, les lignes
dupliquées ou hors limites et les décisions périmées sont refusées.

Les règles d’autorisation HITL existantes s’appliquent avant toute écriture.
La décision est verrouillée, puis le dataset source. L’acceptation, la nouvelle
sortie et la demande de reprise partagent la même transaction. Un nouvel appel
sur une décision déjà acceptée réutilise sa publication. Une expiration rejette
la porte ; une acceptation automatique ou générique sans revue humaine ne peut
pas livrer un dataset confirmé à l’entraînement.

La sortie est un nouveau dataset `source="generated"`,
`produced_by="llm_label_review_v1"`, dont le parent est le dataset LLM. Elle garde
les mêmes lignes et colonnes ; seule la cible peut être corrigée. La lignée
publique `label_review` contient la décision, la personne, la date, le parent,
son empreinte, les classes et les nombres de lignes confirmées et corrigées.
La source LLM demeure inchangée.

## Entraînement et comparaison

L’entraînement de la cible LLM brute est refusé par `ML_LABEL_REVIEW_REQUIRED`.
La distillation est reconnue automatiquement sur la cible du dataset revu.
Sa provenance est vérifiée à la soumission, puis de nouveau par le worker avant
le fit. Les données retirées, modifiées ou dépourvues d’approbation humaine
valide sont refusées.

Les classes LLM d’origine sont relues dans le parent et transmises au harness
comme un vecteur séparé. Elles ne deviennent jamais des variables d’entrée et
ne participent ni au fit, ni à Optuna, ni à la calibration. Les indices physiques
des lignes permettent de les aligner avec le seul jeu de test, y compris lorsque
le fichier source transporte un index dupliqué. L’artefact entraîné et le modèle
servi conservent leur contrat MLflow/skops ordinaire.

`metrics.distillation` contient notamment :

| Champ | Sens |
|---|---|
| `test_rows` | Nombre de lignes réservées au test |
| `agreement` | Accord entre modèle distillé et LLM sur ces lignes |
| `reviewed_accuracy` | Accord du modèle avec les classes confirmées |
| `teacher_accuracy_on_reviewed` | Accord du LLM avec les classes confirmées |
| `rows_reviewed`, `corrected_rows` | Étendue de la revue humaine |
| `llm_estimated_cost_per_1000` | Coût estimé cumulé d’étiquetage, ramené à 1 000 lignes |
| `inference_cost_per_1000` | Estimation déclarée pour le modèle, ou `null` |

Les trois scores utilisent exactement les mêmes lignes de test. Les scores,
coûts disponibles et références de provenance sont également enregistrés dans
MLflow. La carte affiche la base estimative des coûts et les tentatives dont
l’usage fournisseur est inconnu. La durée d’exécution ne devient jamais un coût
en USD. Le coût de revue humaine n’est pas inclus dans ces deux estimations.

## Livraison et recette

Ordre de revue et d’intégration : **4a, puis 4b**. La branche 4b part de la tête
du 4a. Aucune migration, nouvelle dépendance ni image supplémentaire n’est
nécessaire. La livraison reconstruit backend, worker et frontend, puis vérifie
le catalogue comme décrit dans le 4a. Le déploiement reste effectué depuis le
dépôt de référence.

Les tests vérifient la chaîne du moteur Flow avec un transport LLM simulé, les
autorisations et conflits HTTP, les transactions de revue, le refus d’une
approbation automatique, puis un entraînement réel et son chargement MLflow/skops
sur des tickets synthétiques. Un cas contrôlé impose des désaccords LLM uniquement
sur le test afin de détecter toute confusion entre fidélité au LLM et accord avec
la revue humaine. Les parcours navigateur couvrent la correction et la validation
en français et en anglais. Aucun appel fournisseur facturé n’est effectué par
cette recette locale.

Résultats de qualification conservés dans
[la preuve synthétique](reports/ml-lot4-distillation-qualification.json) :

| Tickets | Lignes test | Accord modèle/LLM | Accord modèle/revue | Coût LLM estimé / 1 000 | Coût modèle déclaré / 1 000 |
|---:|---:|---:|---:|---:|---:|
| 48 | 12 | 50 % | 50 % | 0,50 USD | 0 USD, explicitement déclaré |
| 240 | 60 | 100 % | 100 % | 0,50 USD | 0,01 USD |

Le cas de 48 tickets conserve son résultat observé : les 36 textes distincts du
train restent sous le seuil de l’encodeur texte skrub et sont traités comme des
catégories. Le cas de 240 tickets exerce l’encodage de texte. Les deux exports
MLflow produisent les mêmes classes qu’Agentium. Ces jeux simples et leurs tarifs
synthétiques valident les calculs et le contrat ; la recette métier mesurera
la qualité et les coûts sur les données réelles.

Vérification locale : 275 tests backend du parcours et des APIs passent,
ainsi que 121 tests de régression entraînement/registre/API (15 tests lents exclus
de cette commande). Les tests dédiés de distillation et les entraînements réels
complètent ces contrôles. L’infrastructure compte 920 succès et 36 tests ignorés
selon l’environnement ; le frontend compte 2 012 succès et cinq parcours
Playwright, dont les revues FR/EN et la sauvegarde/relecture des liaisons strictes.
Les 80 tests de ports et du validateur DAG passent, ainsi que les quatre parcours
réels du moteur (acceptation, refus, expiration non humaine et entraînement strict).
`ngc`, i18n, UI chrome et liens de navigation passent.
`build:prod` réussit, exécuté une seule fois pour le 4b, avant la correction finale
des ports de la porte en mode strict. Cette correction est ensuite vérifiée par
`ngc`, les tests des validateurs et le parcours réel
étiquetage → revue → entraînement → sortie en mode strict. Angular émet des
avertissements de templates, budgets de bundles et dépendance CommonJS.

Lors de la revue d’intégration, les entrées des portes humaines ordinaires ont été
préservées pour éviter de remplacer leur contexte texte par un objet. La recette
des deux sous-lots fusionnés compte 197 tests ciblés réussis. Après ce correctif,
107 tests backend, 70 tests frontend, les quatre parcours réels du moteur,
`ngc` et le parcours navigateur strict passent. Aucun nouveau build production
n’est exécuté.

L’échec préexistant du contrôle global de catalogue concernant les wrappers
OpenAI/Azure reste documenté dans le 4a. Aucun déploiement ou appel fournisseur
réel ne fait partie de cette qualification locale.
