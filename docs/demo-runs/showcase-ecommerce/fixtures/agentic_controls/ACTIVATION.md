# Luma — contexte agentique, résultat de la file et mandat

**Plan hors ligne, non appliqué.** `reviewed_plan.json` est une configuration de la démo utilisant les fonctions produit génériques. Les scripts ne possèdent aucune commande d’application, ne lisent aucun jeton et ne contactent aucun service. La qualification locale ne prouve ni le déploiement ni une exécution réelle.

## Ce qui est proposé

Le candidat part exclusivement de la **version publiée v10**, `b8eb64d3-e417-41bf-898a-7b1ad232d64a`, empreinte `77d4d521a3526fce8a25ee125ddf010976d637f2f2335d8afee98f1a4dbd09f0`.

- `loop.investigate` utilise explicitement `openai:gpt-5` et reçoit seulement `claim_id`, `sla_prediction`, `sla_model`, `sav_facts`, `data_quality`, déjà raccordés. Taille maximale : 16 384 octets. Objectif, cinq outils autorisés, seuil de confiance, autonomie de recommandation et sortie de budget restent ceux de v10. Budget : 12 tours, 120 secondes vérifiées entre appels. Aucun plafond financier n’est ajouté.
- `sink.queue` expose `case_count` depuis `sav.score.scored_rows`, le dataset et le nom/version du modèle effectivement servi. `excluded_count` utilise `excluded_rows` **seulement si cette mesure existe** : une absence ne devient jamais zéro. Le schéma décrit ces données métier. Le mode historique overlay reste en place ; les champs de routage peuvent encore accompagner le résultat.
- Un mandat **shadow** observe les 14 Skills du contrat publié complet, y compris les outils internes de la boucle, et les cinq collections réellement raccordées. Les modèles LLM autorisés sont `gpt-5` et `openai:gpt-5`. L’identifiant et la version des modèles SLA/prévision restent dans les pins ML ; ce ne sont pas des modèles de texte à ajouter au mandat.
- Aucun droit d’action ou de délégation n’est créé. Les valves de coût, tokens et latence restent non renseignées. Le Judge conserve son propre budget existant ; aucune mesure humaine ou économie financière n’est fabriquée.

Empreinte du candidat Flow : `8446493fc823bad5697c8ff3e85a37a5c3531d14c4d9bd7eb8c965169183f94d`. Une modification du mandat change aussi le contrat d’exécution : **l’empreinte du Flow seule n’atteste pas la politique publiée**.

La nouvelle application d’équipe est désormais le **pilote R2**, release `28f1857d-5e8e-453d-a5a4-fefe57436739`, brouillon **r7**. Ses KPI consomment déjà `sav.score` via `dataBinding.nodeId` ; conserver ces pages et cette audience lors de la bascule, sans réintroduire le header ou le résultat technique retirés.

## Préserver le travail utilisateur

Le brouillon capturé est **r38**, empreinte `3038f5301b0675a19d93f223f14f3e60d33de508530022fb215e6e28607156e2`. Sa préparation inachevée `flow.mv95zi21.1`, sa disposition, ses ports normalisés et ses liens ne figurent pas dans le candidat à publier.

`backup.flow_definition` conserve exactement ce brouillon. `preserved_draft_candidate` part de l’intégralité du brouillon et n’y ajoute que les deux modifications revues. Une divergence utilisateur sur un des champs touchés fait échouer le constructeur avec `USER_DRAFT_CONFLICT`. La restauration produit une **nouvelle révision**, jamais une réécriture de r38. Le brouillon conservé peut rester invalide à cause de son étape inachevée : il ne doit pas être publié implicitement.

## Refaire le plan à partir de lectures fraîches

Captures attendues, chacune sous enveloppe `{ "status": 200, "data": ... }` :

- `before-1.json` : `GET /systems/{id}/flow-state` ;
- `mandate-draft.json` : `GET /systems/{id}/mandate/draft` ;
- `team-app-published.json` : détail Studio de `pilotage-sav-equipe`, avec brouillon et déploiements.

```bash
python docs/demo-runs/showcase-ecommerce/fixtures/agentic_controls/build_plan.py \
  --snapshot-dir /chemin/vers/les/captures \
  --out /chemin/vers/plan-a-relire.json
python -m unittest discover \
  -s docs/demo-runs/showcase-ecommerce/fixtures/agentic_controls -p 'test_*.py' -v
PYTHONPATH=backend python docs/demo-runs/showcase-ecommerce/fixtures/agentic_controls/qualify_plan.py \
  /chemin/vers/plan-a-relire.json --out /chemin/vers/qualification.json
```

La dernière commande requiert l’environnement Python du backend. Elle appelle les validateurs et règles de gouvernance purs du produit, avec des données de test. Le fichier de qualification livré garde `live_qualified: false` et énumère les vérifications encore nécessaires en service.

## Ordre d’application après déploiement et revue

1. Vérifier les révisions effectivement exécutées par API et workers, puis reprendre les trois captures. Comparer version publiée, empreintes, r38, empreinte de mandat et état des applications. En cas de changement, reconstruire et relire le plan ; ne pas remplacer une précondition par la dernière valeur pour forcer une écriture. Réserver une fenêtre sans autre éditeur. Garder webhook et planning en pause.
2. Sauvegarder les données originales hors du dépôt. Lire aussi les trois bindings `showcase.claims.investigate`, `showcase.claims.refresh_queue`, `showcase.claims.forecast`, les réglages de triage, et les releases/déploiements de **toutes** les applications qui les consomment, au minimum `reclamations` et `pilotage-sav-equipe`. Un ancien binding immuable dans une release continue de viser l’ancienne version après modification de son binding courant.
3. Enregistrer `publication_candidate` par `PUT /systems/{id}/flow-draft` avec `expected_revision: 38`. Relire le mandat et ses options : `openai:gpt-5`, désormais explicitement référencé par le Flow, doit faire partie des modèles configurés autorisés. Vérifier aussi le catalogue fournisseur. Une option manquante bloque cette étape ; aucun droit ni modèle n’est ajouté par contournement.
4. Enregistrer `shadow_mandate_candidate` par `PUT /systems/{id}/mandate/draft`, avec **la révision retournée à l’étape précédente** et l’empreinte de mandat attendue. Valider le mandat et le Flow, relire le diff de publication complet et son empreinte de contrat. Qualifier les appels locaux disponibles avant publication. La version du registre ML, le shadow ML à 10 %, la surveillance et les triggers ne changent pas.
5. Publier par le mécanisme générique avec CAS sur révision du brouillon, version publiée attendue et empreinte du contrat relu. Le plan contient les noms de champs exacts et des références `$response...` volontairement non exécutables. Restaurer ensuite `preserved_draft_candidate` avec la nouvelle révision retournée par la publication. Relire et comparer l’orphelin, ses propriétés, les positions et les liens ; le mandat shadow publié reste associé au nouveau brouillon.
6. Effectuer une qualification réelle **shadow** sur les entrées enquête, file et prévision, puis dossier sans preuve et remboursement antérieur. Relever Run, version, empreinte du contrat, contexte réellement transmis, modèle demandé/retourné, appels autorisés et événements `would_block`. Vérifier sortie métier de la file, dataset accessible, modèle servi et absence de faux zéro d’exclusion. Ne pas annoncer « gouvernance bloquante » à ce stade.
7. Durant la même fenêtre de bascule Work, retargeter **les trois bindings** sur la version publiée, puis modifier uniquement `scoring_version_id` / `scoring_flow_sha256` du triage. Conserver ses pins ML et son contrat de prédiction. Les endpoints de binding et de triage n’offrent pas un CAS équivalent à la publication : comparer leurs lectures juste avant et juste après chaque écriture et arrêter si un autre éditeur intervient. Il n’existe pas de transaction atomique couvrant Flow, bindings, triage et releases.
8. Pour chaque application consommatrice, garder ses pages, textes, audience et thème relus. Exécuter le ready-check avec les nouveaux bindings, créer une release immuable avec CAS sur révision/contenu du brouillon, date de l’application et `expected_bindings_sha256`. Déployer par CAS sur release actuelle/date du canal. Conserver `pilot` pour l’application d’équipe si elle est en pilote ; ne pas l’ouvrir à une autre audience. Restaurer séparément tout brouillon utilisateur d’application qui aurait dû être temporairement remplacé.
9. Depuis les URLs Work réellement utilisées, vérifier que les trois actions et les deux applications utilisent la nouvelle version/empreinte, que la file affiche des données métier, que la prévision revient, que le Judge accompagne l’enquête et que la validation humaine demeure nécessaire. Ne reprendre les usages que lorsque l’ensemble des pins concorde. Laisser les événements en pause sauf qualification séparée explicitement prévue.

## Cohérence des règles SAV et de la revue qualité

La question 5 du Judge et le prompt de validation humaine mentionnent actuellement **300 EUR**. Le seuil SAV est maintenant paramétrable : une variation de cette règle doit entraîner une revue conjointe et une nouvelle version de la rubrique, ou une condition dérivée des règles effectivement fournies. Ce plan ne change pas cette rubrique sans preuves. Garder un contrôle explicite de cohérence avant toute démonstration d’un autre seuil, et montrer la version de politique utilisée.

## Passer éventuellement en enforce

`enforce_mandate_candidate_not_activated` est un **candidat distinct**, jamais une preuve d’activation. La version précédente du moteur appliquait `allowed_models` même aux outils sans LLM ; elle pouvait donc bloquer DataOps/ML avec `model_not_allowed:missing`. Le correctif générique doit être en service : seul le moteur peut exempter une opération qu’il classe de manière certaine comme non LLM. Un fournisseur/modèle inconnu pour une opération LLM reste refusé. Aucun drapeau auteur ne permet cette exemption.

Après shadow, qualifier les frontières via le dispatcher déployé : un Skill hors liste doit être refusé ; une collection étrangère doit être refusée ; un autre modèle et une identité LLM absente doivent être refusés. DataOps, ML tabulaire et prévision doivent continuer avec leurs identités natives, sans faux modèle de texte injecté. Les tests purs livrés vérifient ce contrat localement ; ils ne remplacent pas ces Run de qualification.

Les scopes peuvent être imposés sans inventer de budgets numériques : les valves non configurées ne réclament aucune couverture fictive. En revanche, une valve coût/tokens/latence activée exige les mesures correspondantes complètes. Ne pas activer un plafond financier tant que les monnaies et la couverture ne sont pas comparables.

Un passage shadow → enforce est une nouvelle publication avec un nouveau mandat gelé et un nouveau contrat, puis **la même bascule coordonnée** bindings/triage/releases et restauration du brouillon. Il ne faut pas simplement retourner un drapeau global.

## Repli

Avant publication, restaurer le brouillon et le mandat d’origine sans toucher à la version en service : le mécanisme générique de restauration du brouillon depuis v10 rétablit son snapshot de politique, puis le brouillon sauvegardé est remis avec le CAS retourné. Ne le faire que si les dernières écritures correspondent encore à cette intervention.

Après publication, conserver les preuves et utiliser le rollback produit relu ; vérifier aussi bindings, triage et releases, car revenir au seul Flow ne rétablit pas ces pins. Ne jamais écraser une modification concurrente pour « revenir à r38 ». Aucun installateur Luma, replay d’activation ou promotion de modèle n’est nécessaire à cette livraison.
