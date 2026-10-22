# Recette réelle Luma et corrections — 22 octobre 2026

Les captures proviennent de `agentium.papai.ai`, révision `55415938`, avec le
workspace Showcase, navigateur Chromium, 1440 × 1000, langue française. Elles
ne sont pas des réponses API simulées. Les dossiers sont fictifs.

- [Usage workspace](usage-live-fr.png) : 11 appels conservés, couverture 11/11,
  tokens et sous-total USD visibles ; graphique alimenté par le nouveau pilote.
- [Qualité du pilote](quality-live-fr.png) : le contrôle échoué reste non évalué,
  sans verdict métier inventé.
- [Usage du Run](run-usage-live-fr.png) : mêmes totaux, liens vers les appels et
  pagination. Le petit coût positif des embeddings arrondi visuellement à zéro
  a motivé le correctif de présentation inclus dans cette livraison.
- [Mesures conservées et état](live-pilot-summary.json) : agrégats du fournisseur,
  résultat du Judge, préservation du Flow et budget préparé mais désactivé.

Le contrôle Axe de la vue Usage du workspace à vide puis de l'Usage du Run
alimenté n'a relevé aucune violation. Les pages Work, Usage et Qualité examinées
ne présentent ni erreur navigateur ni débordement horizontal à cette largeur.
Cela ne constitue pas une certification d'accessibilité de toute la plateforme.

Le Run a atteint la validation humaine ; aucune décision ni action financière
n'a été effectuée. Le Flow, v10 et le binding ont des lectures avant/après
identiques. Le champion reste v5 ; le pilote métier ajoute une prédiction et une
version de dataset scoré. Ce n'est pas une campagne QA isolée.

Les correctifs de campagne, Judge, admission AgentLoop et provenance tarifaire
sont validés localement ; ils demandent encore une recette après déploiement.
Les 48 essais ne sont pas présentés comme exécutés. Voir le
[runbook de reprise](../../ops/luma-usage-qualification-2026-10-22.md) et les
[critères proposés](../../demo-runs/showcase-ecommerce/qa-2026-10-22/criteria-review.proposal.md).
L'utilisateur a ensuite validé ces critères ; la suite de 12 dossiers a été
enregistrée à 14 h 28, heure de Paris, sous l'identifiant
`7ff7e53f-f9fc-4df1-827b-c31ff84714da`. Aucun Run de campagne n'a été lancé.

## Vérifications locales

- Suite frontend complète : **2 761 tests réussis**, zéro échec ou test ignoré.
  Elle a aussi révélé puis permis de corriger deux tokens CSS absents du thème
  et la destination Usage manquante du catalogue de navigation.
- Compilation production offline, i18n, chrome et liens de navigation : réussis.
- Navigateur sur réponses contrôlées : les trois parcours Usage/Budgets
  existants et deux nouveaux parcours Tarifs FR/EN passent. Ces cinq parcours
  sont distincts des captures de production ci-dessus.
- Lot backend ciblant usage, tarifs, budgets, campagnes, projection, parcours
  hybride et contextes d'images : **148 tests réussis**. Quatre entraînements ML
  ont d'abord rencontré le répertoire personnel non inscriptible du runner ;
  leur relance avec `SKB_DATA_DIRECTORY=/tmp/luma-skrub-data` a réussi.
- Judge et calibration : **132 tests réussis** ; comparaison/qualification
  agent : **17** ; admission/transports : **18**. Ces lots se recouvrent avec
  d'autres recettes ciblées ; ils ne sont pas additionnés à un total global.
- Hooks du commit : réussis ; seule la mise à jour automatique des versions de
  hooks est omise. Le détecteur de secrets conserve une exception de fingerprint
  pour l'identifiant documentaire synthétique `refund-policy-v2`, avec son champ
  métier conservé dans le manifeste ; aucun fichier entier n'est exempté.

Les images Docker n'ont pas été reconstruites dans cette recette. La taille du
runner et le résultat du nouveau Judge avec un fournisseur réel restent des
contrôles de déploiement.
