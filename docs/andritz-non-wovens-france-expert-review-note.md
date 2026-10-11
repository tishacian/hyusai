# ANDRITZ NON-WOVENS France - Note externe de revue expert

Statut : support de discussion pour reunion expert

Cette note ne doit pas etre injectee telle quelle comme Knowledge Guide. Elle contient des questions ouvertes, des hypotheses et des decisions de gouvernance documentaire a trancher avec un expert humain.

## Ce qui doit rester hors Knowledge Guide

- Les questions ouvertes aux experts.
- Les noms de clients, projets ou fichiers particuliers cites comme exemples de QA.
- Les tables completes de valeurs extraites d'un classeur.
- Les hypotheses non validees qui pourraient biaiser le retrieval.
- Les decisions d'organisation : split par client, par process, par type d'essai, exclusion de doublons, traitement des feuilles cachees.
- Les notes de demo ou de test.

## Ce qui peut aller dans le Knowledge Guide

- Nomenclature transverse : MD/CD, grammage, emport, dewatering, rouissage.
- Regles de prudence : ne pas inventer d'unite, citer la source, ne pas generaliser une table locale.
- Termes d'expansion pour le retrieval.
- Conseils de distinction entre parametres machine, mesures laboratoire et resultats.
- Definitions prudentes quand elles sont valables dans l'industrie ou confirmees par l'expert.

## Questions pour l'expert humain

### Labels et diametres

- Dans les feuilles de type `Def strips`, que representent exactement les labels `A`, `B`, `C`, etc. ?
- Ces labels correspondent-ils a des diametres, des ouvertures de filet, des dimensions de strip, des buses, des jets, des fentes ou autre chose ?
- Quelle est l'unite attendue pour ces valeurs ?
- Cette unite est-elle toujours la meme ou depend-elle du classeur / de l'essai ?
- Une table label -> valeur est-elle specifique a un classeur, specifique a un essai, ou transverse a plusieurs essais ?
- Comment faut-il traiter les labels absents ou vides ?
- Comment faut-il traiter les labels composes ou atypiques ?

### Rouissage

- Le terme `non roui` signifie-t-il bien fibre non rouie dans ces essais ?
- Le statut `roui` / `non roui` est-il une information matiere, une condition de preparation, ou un critere de qualite ?
- Quels impacts metier attendez-vous entre une fibre rouie et non rouie : ouverture, cardage, liaison, dewatering, traction, toucher ?
- Peut-on comparer directement des resultats entre fibres rouies et non rouies si le protocole n'est pas strictement identique ?

### Tests et resultats

- Confirmez-vous que MD correspond au sens machine et CD au sens travers ?
- Confirmez-vous que `sens production` correspond a MD et `sens travers` a CD ?
- Quelles feuilles sont les plus fiables : protocole d'essai, resultats laboratoire, synthese client, retour terrain ?
- Quand une feuille contient moyenne, min, max, ecart-type ou CV, quelle valeur doit etre citee par defaut ?
- Les valeurs d'emport sont-elles comparables entre classeurs ou la formule change-t-elle ?
- Quelle est la definition metier d'`exprimage` dans ces essais ?

### Rouleaux et process

- Quelle difference faites-vous entre `roll`, `rouleau`, `bobine`, `winder` et `baseweb roll` ?
- Quand un fichier mentionne des rolls envoyes ou produits, s'agit-il de lots de production, d'echantillons ou de supports d'essai ?
- Que signifie exactement `avancee rouleau` dans les mesures ?

### Organisation Knowledge

- Faut-il organiser les connaissances par client/projet, par type d'essai, par famille matiere ou par ligne/process ?
- Les feuilles cachees doivent-elles etre indexees et citees par defaut ?
- Les fichiers `sent`, doublons ou brouillons doivent-ils etre exclus du scope canonique ?
- Quelles informations doivent devenir des faits reutilisables, et lesquelles doivent rester attachees a un essai specifique ?

### Questions utiles pour Knowledge Capture

- Quand vous voyez une table de correspondance label -> valeur, comment savez-vous si elle est locale ou transverse ?
- Quels champs faut-il lire en premier pour comprendre un essai non-tisse ?
- Quelles erreurs d'interpretation un nouvel ingenieur ferait-il avec ces Excel ?
- Quels parametres machine expliquent le plus souvent une difference de resultat ?
- Quels termes doivent rester en anglais dans les reponses, et lesquels doivent etre traduits en francais ?

## Decisions a prendre avant publication comme guide stable

- Confirmer si `roui` / `non roui` doit etre defini dans le guide transverse ou dans un guide specifique fibres naturelles.
- Confirmer si les feuilles cachees doivent etre considerees comme sources citables.
- Confirmer si les tables de labels doivent etre indexees seulement comme documents bruts ou aussi transformees en faits valides.
- Confirmer le niveau de granularite des Knowledge scopes : par famille de process, par client/projet ou par type d'essai.
- Confirmer les unites standards a afficher lorsque la source est implicite mais connue des experts.

## Proposition de workflow

1. Utiliser le Knowledge Guide transverse pour ameliorer le retrieval sans biaiser les valeurs.
2. Mener la session expert avec les questions ci-dessus.
3. Transformer les reponses validees en une version publiee du Knowledge Guide.
4. Garder les exemples clients/fichiers dans des notes de QA ou dans les citations documentaires, pas dans le guide transverse.
5. Si certaines tables deviennent officielles, les promouvoir comme faits ou mini-referentiels separes, versionnes et cites.
