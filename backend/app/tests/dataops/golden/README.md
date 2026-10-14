# Corpus de référence DataPrep

Les attendus sont écrits indépendamment du compilateur. Chaque étape possède
`ordinary`, `null` et `empty`, avec une spécification, une entrée JSON et son
schéma physique, puis les lignes attendues. L'entrée vide garde le même schéma.
`functions.json` couvre séparément les 74 fonctions publiées.

Le test `test_dataops_typed_contracts.py` exécute ce corpus sur DuckDB et compare
les lignes, les colonnes et les types réellement produits. Ses tests spécialisés
couvrent aussi les bornes int64, les décimaux, les remplacements de colonnes,
les quotas d'échantillonnage et les expressions refusées. Les trois cas génériques
ne remplacent pas la couverture de toutes les limites propres à chaque étape.
La parité Spark appartient au lot différé D5 ; aucun résultat Spark n'est affirmé.
