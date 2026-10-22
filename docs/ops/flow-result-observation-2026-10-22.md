# Consulter les résultats depuis le Flow

## Livraison

Capacité produit générique, accessible sur un Flow rattaché à un système.
Déployer cette livraison sur l’API et le frontend. Aucune migration, aucun
nouveau drapeau, aucun changement de worker ou de publication de Flow.
Les autorisations existantes de lecture des Runs, invocations et datasets
restent applicables. Les champs de provenance sont issus du Run enregistré,
jamais de la publication courante.

## Parcours builder

1. Ouvrir le Flow d’un système, puis **Résultats**. Le sélecteur propose les
   exécutions récentes avec date, état, entrée et version lorsqu’ils sont conservés.
   La sélection initiale privilégie une exécution métier terminée.
2. Double-cliquer une étape, ou utiliser son bouton de consultation. Le clic
   simple reste dédié au paramétrage. La vue Liste propose la même consultation.
3. Consulter la sortie ou l’entrée enregistrée. Choisir une tentative lorsque
   l’étape a plusieurs passages. Les prévisions compatibles affichent une courbe
   et ses intervalles ; les tables, métriques, documents et décisions disposent
   de présentations dédiées. Les autres structures restent consultables.
4. Une sortie qui référence un dataset exact charge automatiquement un aperçu
   de 50 lignes au maximum. **Actualiser les données** relit cette même version. Une référence absente ou devenue inaccessible ne provoque jamais
   une substitution par la version actuelle des données.
5. Épingler le résultat à côté de son producteur, déplacer la carte par son
   en-tête et l’agrandir pour présenter le résultat. Le menu des vues épinglées
   donne aussi accès aux cartes hors cadre et sur petit écran.

Les cartes sont des vues consultatives en mémoire, limitées à quatre. Elles ne
font pas partie du graphe exécutable et disparaissent à la fermeture de la
consultation, au changement de contexte ou au rechargement de la page. Elles
conservent leur propre Run et tentative lorsqu’on change l’exécution sélectionnée.
La version et la provenance restent consultables ; un avertissement signale une
version différente ou non vérifiable. Le titre métier reprend le libellé du
graphe affiché, tandis que l’identifiant d’étape reste dans la provenance.

La consultation, l’épinglage et le déplacement d’une carte ne lancent aucun
traitement et ne sauvegardent ni ne publient le Flow. Les contrôles d’exécution
habituels restent des actions distinctes. Un résultat absent ne prouve pas que
l’étape n’a pas tourné : il peut ne pas avoir été conservé ou être inaccessible.
Une recherche explicite examine au maximum dix exécutions terminées récentes.

## Démonstration Luma après déploiement

Conserver le brouillon utilisateur r38, la publication v10 et ses bindings.
Ne pas réinstaller Luma pour activer cette lecture ; ne changer ni champion v5,
ni shadow à 10 %, ni événements en pause.

Depuis **Charge et capacité**, ouvrir le Flow puis sélectionner l’exécution
métier de prévision. Consulter l’étape TS, afficher les valeurs et agrandir la
courbe. Phrase métier : « Le responsable SAV voit la charge prévue et peut
vérifier sur quelles données repose sa décision de capacité. »

Poursuivre avec une étape de préparation et son aperçu de données, puis avec
une enquête terminée et ses décisions d’agent. Changer explicitement le Run
si les entrées ne font pas partie de la même exécution : ne pas présenter des
résultats de Runs différents comme une unique exécution de bout en bout.
Les appels réels restent distingués des dossiers de démonstration et des
transactions financières simulées.

## Recette

La recette locale utilise des réponses API contrôlées et des tests unitaires ;
elle ne constitue pas une recette en service de cette nouvelle interface.
Vérifier après déploiement les Runs Luma accessibles et la disponibilité des
sorties TS/datasets conservées avant la présentation. Aucune activité métier
ne doit être lancée simplement en consultant une carte.

Contrôles de livraison : 554 tests frontend ciblés du Flow, 31 tests backend
sur les projections de Run et les vues d’exécution, build de production,
contrôles i18n, chrome UI et navigation. Le parcours navigateur couvre le
français sombre sur desktop et l’anglais clair sur mobile : courbe, valeurs,
tentatives, cartes épinglées, déplacement, agrandissement, dataset exact,
provenance, résultats retenus, refus d’accès, réponse tardive et décisions
attribuées au bon nœud. Les assertions surveillent l’absence de sauvegarde,
publication, dispatch et appel de modèle ; les journaux de navigation et la
validation de brouillon déjà présents dans le shell restent autorisés.
