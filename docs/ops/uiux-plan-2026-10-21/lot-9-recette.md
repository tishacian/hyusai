# Lot 9 — protocole et état de recette

**État initial avant déploiement : non exécuté.** Les passages automatisés désormais réalisés sont documentés dans la [recette après déploiement](../uiux-recette-2026-10-21.md). Aucun participant humain, temps de tâche ou taux de réussite n'est déduit des tests automatisés. Le plan demande une pile de recette, un second corpus, des comptes et des personnes ; ces observations restent à recueillir.

## Révision et environnement

Avant la séance, consigner le SHA du candidat réellement servi, le SHA frontend/backend et les migrations appliquées. Le checkout local de cette session contient des changements non commités ; son HEAD seul ne décrit pas le candidat. Le bilan d'intégration est dans `README.md` et l'empreinte des fichiers dans `files.sha256`.

La référence avant changement est `7e5652d5`. Garder les mêmes tâches et instruments de mesure pour les deux passages. La matrice des 58 stories et les sept indicateurs détaillés du rapport source n'étaient pas accessibles dans cette session ; les joindre avant de certifier leur couverture complète.

## Contrôles automatisés à exécuter

Depuis `frontend-ng`, après installation des dépendances et du navigateur Playwright :

```sh
npm run check:i18n
npm run check:nav-links
npm run check:ui-chrome
npm run check:fallbacks
npm run test:unit
npm run build:prod
npm run test:e2e:mocked
```

Le mode `npm run build:prod:offline` conserve l'optimisation JavaScript/CSS et les budgets de production, mais ne télécharge pas les polices pour les incorporer. Il sert à la validation du code dans un environnement sans réseau ; il ne remplace pas le build standard dans la chaîne de livraison.

Le job mocked utilise uniquement une origine HTTP locale. Exécuter également les tests de Luma et le test 71 sur la pile de recette autorisée selon leurs prérequis. Ne jamais pointer le test 71 vers la production : il crée puis supprime son workspace de test.

## Trois scénarios à rejouer sur un second corpus

| Scénario | Parcours | Seuil / preuves |
| --- | --- | --- |
| 1 — départ vierge | Un créateur novice construit et publie depuis un workspace neuf ; un collaborateur utilise l'application ; un troisième compte hors audience est refusé. Question connue puis hors corpus. Changer noms et corpus sans modifier le code. | Réponse renvoyant au passage autorisé, abstention hors corpus, reçu de publication, droits effectifs. Aucune intervention extérieure, sauf dépendance affichée au moment du blocage. |
| 2 — décision | Auteur, reviewer avec `run.approve` et collaborateur sans ce droit. Accepter un dossier, refuser l'autre, couper le réseau pendant une décision. Faire modifier un rôle par deux administrateurs. | Aucun doublon ; issue inconnue vérifiable après coupure ; tiers empêché de décider ; conflit de rôle relu. Trois personnes sur trois reformulent l'autorisation et ce que le contrôle n'a pas établi. |
| 3 — données | Import CSV indépendant avec cas normal, dépassement et valeur manquante ; préparation, publication, lecture des anomalies puis second import. | Comptes et sommes exacts ; manque distinct de zéro ; chaque anomalie rejoint sa ligne, sa version et son Run. |

## Accessibilité et premier regard

- Exécuter axe sur les écrans des lots 1 à 8c : zéro violation sérieuse ou critique. Conserver version d'axe, URL, langue, thème et résultat.
- Revoir un dossier entièrement au clavier : ordre visuel respecté, focus visible, absence de piège, alternative au glisser-déposer. Les erreurs et changements d'état doivent être annoncés et reliés à l'action ou au champ.
- Refaire à 320 px, en clair et sombre, en FR et EN : contexte, faits et réserves avant la décision ; reçu retrouvable après ; aucun contenu essentiel perdu.
- Sur Work, fiche modèle et Impact, demander les cinq réponses avant explication : où suis-je ; quel objet/version ; quel état ; quelle action utile ; quel fait la limite. Au moins quatre testeurs sur cinq doivent répondre aux cinq questions.

## Panel

Six personnes : deux collaborateurs métier, deux créateurs, un administrateur, un responsable d'exploitation. Quatre tâches : trouver l'entrée, comprendre une réserve, vérifier une preuve, retrouver un résultat. Au moins cinq sur six réussissent chaque tâche sans aide ; aucune personne ne doit lire une réserve comme une approbation.

Enregistrer pour chaque tâche le profil pseudonymisé, le résultat, l'aide éventuelle, le temps observé et les confusions. Tant qu'une séance n'a pas eu lieu, écrire « non mesuré ». Rattacher chaque défaut à son lot propriétaire, corriger puis rejouer le cas.

Enfin, chaque story de la matrice doit être marquée séparément « implémentée » et « recettée », ou porter une exclusion précise. Un scénario écrit mais non exécuté ne satisfait pas cette condition.
