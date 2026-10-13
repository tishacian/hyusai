# Contrat documentaire narration — Showcase (brouillon différé)

> Hors lot actif à la demande de l’utilisateur le 13 octobre 2026. `narration_enabled=false` et le seed conserve ce service en brouillon. Gemini via OpenRouter est la route envisagée pour une reprise future ; aucun raccordement ni qualification du moteur/fournisseur n’est livré dans ce lot. Les sections ci-dessous décrivent la recette future.

La chaîne `narration` conserve son moteur externe. Agentium possède les contrats, les actifs, l’exécution gouvernée, la revue et le reçu. Le Showcase sert de recette, sans client pilote requis.

| Question de parcours | Réponse vérifiable |
|---|---|
| Pour qui et quel travail ? | Le responsable du System livre un lot documentaire contrôlé aux membres autorisés du Showcase. |
| Quelle unité et quelle répétition ? | Un lot par fenêtre quotidienne, recette de 500 unités page ou image. Une page scannée qui est une image compte une seule fois. |
| Quel résultat justifie l’acceptation ? | Toutes les unités annoncées sont traitées, les objets et les versions sont vérifiés, les jugements ont leurs preuves et une revue humaine porte sur ce résultat exact. |
| Où et comment est-il reçu ? | Work, destination `work:showcase-narration`, avec reçu et bundle des octets. |

## Entrées et moteur externe

Un actif `document_set` immuable décrit ses `objects`, ses `units` (id, type page/image, clé, SHA-256, page éventuelle) et ses preuves. Les champs document_family/source/language/task décrivent le contenu réel ; ils ne sont jamais inventés pour rendre un profil applicable. La fraîcheur et les qualifications sont celles du contrat de service.

`narration_run_v1` utilise le protocole gateway v1 décrit dans [narration-gateway.md](ops/narration-gateway.md) : POST idempotent, polling paginé, checkpoints par unité, budgets cumulatifs et annulation distante. L’endpoint HTTPS est configuré côté serveur avec une liste d’hôtes ; les redirections et les URLs de résultats arbitraires sont refusées. Le gateway dispose de ses propres droits de lecture sur l’ObjectStore.

Chaque unité devient un objet vérifié avant son checkpoint. Le moteur doit confirmer la révision et le digest de source. Une couverture incomplète reste un échec technique, même si certaines pages semblent utiles. Un coût ou un usage absent est NULL, accompagné de sa couverture de mesure.

## Juge typé et J2450

Le Flow peut connecter narration → `evaluate_v2`, en `batch_mode: per_unit`, puis produire un nouveau candidat gouverné. Une preuve source et une preuve résultat sont demandées pour chaque unité. Les réponses canoniques sont persistées ; le Run transporte un résumé et une référence, pas toutes les pages en JSON.

Le premier contrat de rubrique est le classement J2450 lorsqu’il s’agit réellement d’une traduction : terminologie, sens, omission, structure, morphologie, orthographe et ponctuation ; plusieurs catégories peuvent être retenues. La gravité, l’abstention et les preuves sont explicites. Un parcours qui n’est pas une traduction doit employer une autre rubrique.

Les images passent réellement dans le transport multimodal gouverné. Une route vision sans qualification de transport est refusée avant appel. Les citations image donnent hash, description et zone normalisée ; une OCR textuelle n’est pas une preuve que l’image a été examinée.

Un profil de confiance exige corpus/version/rubrique/modèle/contextes concordants, annotations humaines indépendantes, familles séparées et rapport verrouillé. La qualité d’un résultat n’est pas sa confiance. Pour un lot de centaines d’unités, `confidence` reste NULL : le minimum des bornes par unité n’est pas une confiance de lot. `min_unit_confidence`, lorsqu’il existe, est descriptif. La livraison du Showcase requiert donc la revue humaine.

## Recette

- 500 unités annoncées, 500 checkpoints vérifiés, sans double compte page/image ; traitement et juge ont chacun leur couverture.
- Reprise après réponse perdue sans nouveau POST ni nouveau coût affirmé ; annulation asyncio → DELETE distant.
- Refus si source/révision changée, octets corrompus, réponse trop grande, budget épuisé, route image non qualifiée ou corpus de test contaminé.
- Abstention si preuves insuffisantes ; aucune valeur de confiance fabriquée depuis un score.
- Pas de publication automatique d’un candidat partiel ou non qualifié ; décision liée à la fenêtre, à la qualification et au digest du candidat.
- Preuve d’unification : les deux parcours partagent A1, les fenêtres, les fences, les budgets, la revue et les reçus ; le parcours documentaire peut réutiliser une préparation tabulaire des référentiels.

Une machine HTTP de test établit le protocole et les reprises. La recette complète avec le vrai moteur, les images réelles et les fournisseurs exige leur endpoint, leur configuration et leurs traces. Le seed conserve le contrat brouillon tant que ces prérequis manquent.
