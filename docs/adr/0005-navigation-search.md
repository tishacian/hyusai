# Recherche de navigation filtrée par droits

Le lot 3 du plan UI/UX du 20 octobre ajoute les documents, collections et connexions à la palette. Le catalogue Work reste fourni par `/work`, qui applique déjà les droits de consommation.

`GET /api/v1/navigation/search?q=…&limit=…` cherche uniquement les noms dans les registres SQL du workspace courant. Il exige un compte actif, un workspace actif et une appartenance à cet espace. Les collections et leurs sources passent par `can_read_collection`, comme leur consultation. Les connexions suivent la même visibilité que leur registre : membres de l’espace, connexion active et fonctionnalité activée. Ni contenu documentaire, ni paramètres de connexion, ni secrets ne sont renvoyés.

Les droits sont appliqués avant la limite et avant `has_more`. Un objet invisible ne produit donc ni résultat ni compteur. Les `%` et `_` saisis sont des caractères littéraux. La réponse contient le type, le libellé, le workspace et une destination interne encodée ; la destination vérifie de nouveau les droits lors de son ouverture.

La palette attend 250 ms après une saisie d’au moins deux caractères, annule l’ancienne recherche et épingle le workspace de la requête. Une réponse d’une époque précédente est ignorée. Une panne reste visible avec Réessayer, y compris lorsque le catalogue local contient encore des résultats.

Ce premier endpoint cherche les noms du registre, sans index de contenu ni service externe. Les tests doivent prouver l’exclusion d’une collection privée et de ses documents, l’isolation des espaces, l’absence de secrets et la distinction entre vide et panne. Aucune migration ni modification des documents n’est nécessaire.
