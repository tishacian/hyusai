# Un ROI démontré, avec ses preuves dans Impact

Le ROI sera un résultat de l’expérimentation, pas une constante du seed. Les données commerciales sont synthétiques ; le travail humain, les exécutions, les temps et les coûts observés doivent être réels. L’affichage attendu est **« ROI opérationnel observé sur le benchmark de démonstration »**, avec accès au protocole et aux preuves.

La [campagne automatisée du 7 octobre](ACTIVITY-ROI-2026-10-07.md) fournit
20 Runs natifs sur 10 dossiers et un scénario financier séparé, approuvé par
l’utilisateur : 8 min manuelles, 2 min assistées et 0,50 €/dossier à 40 €/h,
soit 3,50 € nets et 700 % de ROI **projetés**. Le benchmark ci-dessous reste
à 0/10 et ses résultats observés restent inconnus. Les essais automatiques
n’alimentent pas les temps humains, la revue indépendante ou les gains.

## Ce que nous cherchons à mesurer

L’effet principal est le changement de **temps de travail humain nécessaire pour résoudre un dossier, à qualité comparable**. Un remboursement déjà bloqué par la procédure manuelle n’apporte aucun gain financier supplémentaire. Le montant de 420 € est une exposition du dossier, pas une valeur créée par l’agent.

| Élément | Preuve | Nature |
| --- | --- | --- |
| Temps de traitement manuel et assisté | Sessions chronométrées, événements serveur et décision de fin | Observation sur le benchmark. |
| Résolution correcte | Grille d’évaluation indépendante, règles attendues et citations | Contrôle de qualité. |
| Coût horaire chargé du SAV | Convention approuvée, montant, devise, version et période | Hypothèse de valorisation, même si issue d’une donnée RH réelle. |
| Coût des appels Agentium | Usage enregistré et prix applicable, couverture des appels, devise et période | Coût observé ou calculé, avec sa provenance. |
| Infrastructure/licence/intégration | Factures ou convention d’allocation explicite | Dépense constatée ou coût alloué ; les deux restent distingués. |
| Projection mensuelle | Volume supposé × résultat du benchmark | Projection, séparée du résultat observé. |

Le demandeur a retenu **40 EUR/h comme hypothèse de démonstration** pour le coût horaire chargé du SAV. Cette convention explicite valorise le temps ; elle ne constitue pas une mesure de dépense effectivement réduite. Le [contrat de benchmark](fixtures/benchmark_config.json) conserve ce choix, avec les temps, coûts et résultats non renseignés. L’approbation du contrat dans l’application sera une étape distincte. Aucun temps manuel, coût nul, pourcentage de gain ou montant de ROI n’est prérempli.

## Comparaison manuelle et assistée

1. Préparer une cohorte de dossiers synthétiques distincte des trois dossiers de scène, en paires de difficulté comparable : perte simple, preuve contradictoire, information manquante, doublon. Figer la version des documents et le snapshot tabulaire.
2. Viser au moins dix paires pour une première lecture exploratoire. Alterner l’ordre manuel/assisté et répartir les variantes ; éviter de faire résoudre systématiquement le même dossier manuel puis assisté à la même personne, ce qui introduit un effet d’apprentissage.
3. En condition manuelle, l’opérateur dispose des mêmes documents, commandes, remboursements et règles, avec un moyen normal de recherche. Il traite le dossier et prend une décision sans recommandation Agentium. Ne pas ralentir artificiellement cette condition.
4. En condition assistée, mesurer depuis le début de la prise en charge jusqu’à la décision, avec recherche, lecture des résultats et correction humaines. Ne pas comparer le temps manuel au seul temps d’exécution du modèle.
5. Séparer temps de travail humain, délai écoulé jusqu’à la décision et durée technique du run. Les pauses sont journalisées ; si l’activité humaine n’est pas instrumentée de manière exploitable, présenter seulement le délai observé, sans le convertir en gain de main-d’œuvre.
6. Vérifier la décision, la règle en vigueur, les preuves citées, l’absence de doublon et la bonne action avec une grille préparée avant l’essai. Un résultat incorrect ne devient pas un succès rapide. Inclure le temps de correction et les échecs, ou rendre leur exclusion explicite.
7. Conserver toutes les sessions prévues, leurs abandons et leur ordre. Afficher effectif, médiane, distribution et différence moyenne appariée ; avec peu de cas, qualifier le résultat d’exploratoire. Plusieurs opérateurs améliorent la portée du résultat.

Le résultat vaut pour ce protocole et cet échantillon. Un transfert à une vraie entreprise exige une mesure sur ses dossiers et son organisation. La démo ne doit pas le présenter comme un gain de production déjà acquis.

## Calculs et périmètres

Pour une cohorte comparable de dossiers terminés :

```text
Delta de temps humain = total temps manuel - total temps assisté
Valeur de capacité = Delta de temps humain / 3600 × coût horaire chargé
Coût incrémental = coût Agentium + coûts supplémentaires affectés à la cohorte
Bénéfice net = Valeur de capacité - Coût incrémental
ROI opérationnel = Bénéfice net / Coût incrémental
```

Le coût Agentium couvre les appels LLM et outils de l’ensemble du travail assisté, y compris retries et échecs. Les coûts supplémentaires comprennent infrastructure et licence selon une convention d’allocation affichée, puis intégration/formation si le périmètre annoncé les inclut. Les coûts présents des deux côtés s’annulent dans cette comparaison ; les coûts spécifiques d’une méthode restent affectés à cette méthode.

Afficher les temps négatifs ou un ROI négatif quand ils sont observés. Si le taux manque, le gain reste en secondes/minutes. Si la couverture des coûts manque, la devise n’est pas comparable ou le dénominateur est nul, afficher **ROI indéterminé**. Ne pas afficher un rendement infini ni remplacer une donnée absente par zéro. Toute conversion de devises cite le taux et sa date.

La valeur de capacité exprime du temps rendu disponible. Pour annoncer une économie financière réalisée, ajouter une preuve de dépense effectivement réduite, par exemple une facture de sous-traitance, et une attribution évaluée. Un remboursement simulé ou un doublon évité dans une fixture n’est pas cette preuve.

## Ce qu’Impact doit montrer

Le bloc du système Réclamations et de sa cohorte affiche :

- période, effectif, protocole et état de qualité ;
- temps humain manuel et assisté, minutes de différence et distribution ;
- coût horaire utilisé, clairement nommé « convention de valorisation » ;
- valeur de capacité, coût incrémental, couverture des coûts et bénéfice net ;
- ROI du benchmark, son périmètre et ses données manquantes éventuelles ;
- projection mensuelle dans un bloc distinct, avec volume supposé ;
- liens vers sessions, dossiers, snapshots, versions documentaires, runs, invocations, décisions et justificatifs de coût.

Les anciens runs du workspace Showcase ne sont pas agrégés à cette cohorte. Une carte « économies » ne remplace pas ce périmètre et ces preuves. Le lien depuis Work conserve le contexte du système, de la cohorte et de la période.

## Contrat de preuve à implémenter

L’enregistrement du benchmark doit lier `benchmark_id`, `protocol_version`, `workspace_id`, `system_id`, cohorte, variante, opérateur autorisé et condition manuelle/assistée. Chaque essai conserve les identités de dossier, le snapshot SQL, les hashes/versions des documents, les événements de début/pause/reprise/fin, la décision et la grille de qualité. L’essai assisté référence ses `run_id` et coûts, même si l’analyse a été relancée.

Les événements sont écrits par une route backend autorisée, horodatés au serveur et audités. Un navigateur ne transmet pas une durée déclarée qui deviendrait automatiquement une mesure. Les règles de mesure, unités, exclusions et agrégations sont versionnées. Un amendement ultérieur laisse une trace et le résultat se recalcule depuis les preuves.

Le calcul de benchmark et son rendu Impact nécessitent une extension produit. Ils ne sont pas obtenus en remplissant `Capability.value_per_outcome` avec une somme choisie. Les runs synthétiques restent marqués comme tels et exclus de la baseline indépendante de Lot 8. Une provenance d’exécution valide ne suffit pas à établir la causalité d’un gain métier.

## Conditions de qualification

Le bloc ne peut annoncer « démontré » qu’après : sessions réelles dans les deux conditions, cohorte comparable, qualité contrôlée, temps interprétables, convention affichée, coûts complets dans le périmètre et résultats reproductibles depuis les preuves. En attendant, il expose **expérimentation à effectuer**, **mesure partielle** ou **ROI indéterminé**, selon l’information réellement disponible.
