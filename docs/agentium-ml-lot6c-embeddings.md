# Lot 6c — Variables issues d’un encodeur multilingue figé

Le formulaire commun au Studio et au Flow propose un encodage multilingue lorsque
le runtime optionnel et ses poids locaux sont disponibles. L’utilisateur choisit
explicitement une colonne de texte et la dimension de réduction
(2 à 128, 30 par défaut). Les autres variables conservent le prétraitement
ordinaire. Classification et régression utilisent les estimateurs déjà proposés.

La tâche reste `classification` ou `regression`. `spec.text_encoder=embedding`
sélectionne la famille `tabular_deep`, la file `ml_deep` et le service de prédiction
`ml_deep_rpc`. Sans cette option, le parcours tabulaire reste celui du worker
courant. La famille et ses options viennent du catalogue ; l’absence du runtime
ou des poids produit un refus explicite avant la création du modèle.

## Modèle et validation

La roadmap nommait `LLMEncoder` ; skrub 0.10.1 fournit son successeur `TextEncoder`.
Le premier encodeur proposé est
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, sous licence
Apache-2.0, provisionné sous l’alias `multilingual-minilm`. La révision qualifiée
est `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`. Le lot 6a décrit son installation.

Les poids préentraînés restent figés. Le split train/test précède le fit de la
pipeline : la réduction PCA et l’estimateur ne voient que le train. La réduction
suit le comportement natif de skrub lorsque le train est trop petit pour la
dimension demandée (troncature des dimensions). La colonne explicite est
encodée même lorsqu’elle a moins de 40 valeurs distinctes.

Cette première version utilise un seul split. Optuna, validation croisée,
calibration, optimisation du seuil, intervalles conformes et pack d’explicabilité
sont refusés explicitement avec l’encodeur profond, afin de borner les fits et
copies de poids. Les options ordinaires restent disponibles sans cet encodeur.
La surveillance avec réentraînement et le scoring fantôme ne sont pas proposés
pour cette nouvelle famille. Ses métriques ordinaires et ses appels restent
journalisés et consultables.

## Provenance et export

La demande fige la révision et l’empreinte du modèle préentraîné annoncées par le
heartbeat. Le worker revérifie chaque fichier, copie ces octets dans son espace
isolé et vérifie encore les empreintes de la copie. Aucun chargement distant ni
téléchargement de poids n’est déclenché par un entraînement ou une prédiction.

La pipeline MLflow sklearn embarque les poids du `TextEncoder`
(`store_weights_in_pickle=True`). Cette famille utilise `cloudpickle`, car skops
ne sérialise pas la pile transformer. Tous les fichiers du bundle, y compris
`MLmodel` et `model.pkl`, sont empreintés par le harness. Le service vérifie les
fichiers et leur ensemble exact avant toute désérialisation. Celle-ci est réservée
au runtime profond. Les exports tabulaires ordinaires conservent skops.

Un export autonome reste chargeable après disparition de l’emplacement source.
Ses dépendances figent les versions CPU. `metrics.embedding` publie l’identité,
la révision et l’empreinte de l’encodeur, les colonnes et la dimension demandée.
Les poids ne sont pas inclus dans l’image. Le rapport skore sérialisé n’est pas
publié pour cette famille, afin de ne pas charger torch dans l’API à sa lecture.

## Prédiction et livraison

`/predict`, les clés API et le nœud de scoring Flow gardent leur contrat de lignes.
L’API sélectionne la version servie et valide les entrées ; le worker profond
calcule les réponses ; l’API journalise une seule fois. Le scoring de dataset
utilise des lots bornés sur le même service distant puis écrit le dataset avec sa
lignée habituelle. L’API ne charge jamais les poids.

Le lot 6c suit 6a puis 6b. Aucune migration ni nouvelle dépendance au-delà du socle
6a. Reconstruire backend, worker, frontend et l’image optionnelle `ml-deep`.
L’activation du profil et le provisionnement des poids sont explicites ; le
chemin de livraison reste Bitbucket puis la VM habituelle.
