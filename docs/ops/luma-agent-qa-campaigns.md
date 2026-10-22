# Campagne agentique Luma · activation et recette

## Périmètre livré et preuve attendue

La campagne générique réexécute le préfixe autorisé du Flow dans le moteur habituel : PostgreSQL → dataset de faits → préparation visuelle → scoring du modèle épinglé → contexte → AgentLoop avec lectures réelles → Judge → frontière humaine. Une demande humaine de l'AgentLoop est aussi une terminaison attendue. Le worker ferme la décision comme rejet système et le Run comme annulé avec `evaluation_termination=human_gate` ; il ne produit ni validation humaine ni reçu d'action. Ce statut réel reste visible.

Les tests locaux couvrent le moteur canonique, le modèle sklearn sérialisé, la préparation réelle et le score synchrone/streaming. Les accès PostgreSQL de démonstration et les fournisseurs distants sont remplacés par des doubles dans ces tests. Ce n'est ni une recette du déploiement ni une mesure de qualité de ces modèles.

## Prérequis après déploiement

1. Appliquer `145_evaluation_isolation` puis la migration de dépenses `146_model_usage_budgets` sur la même révision API/workers. Aucun nouveau drapeau global QA. Conserver les options de Workbench, publication, DataOps et ML déjà autorisées.
2. Vérifier l'accès utilisateur au System, au Run de référence et aux collections. Le Flow publié et son brouillon restent intacts. Choisir un Run terminé ou arrivé à une frontière humaine, avec Flow et contrats conservés.
3. Ouvrir la suite dans **Observabilité → Qualité → Tests**. Vérifier les 12 dossiers proposés dans `docs/demo-runs/showcase-ecommerce/fixtures/observability`. Identifier la révision réelle du brouillon et toutes les collections liées au préfixe.
4. Vérifier le modèle SLA réellement épinglé : ID, version prête, URI d'artefact et empreintes de signature/métadonnées doivent rester identiques. La campagne n'entraîne, ne promeut et ne remplace aucun modèle. Elle n'ajoute pas ses prédictions au shadow, aux séries de production ou au calcul de dérive.
5. Configurer les tarifs et plafonds workspace/app dans **Usage**. Un plafond bloque les appels non admissibles, y compris les appels Giskard ; un prix ou un usage inconnu ne devient pas zéro. Les coûts d'exécution, d'évaluation et de génération restent identifiables séparément.
6. Pour Giskard seulement : worker Python 3.12 construit avec `INSTALL_GISKARD_RAGET=true`, route OpenAI et embeddings autorisés, au moins huit chunks utilisables parmi les collections. L'installation du SDK ne prouve pas qu'une campagne a été exécutée.

## Revue humaine de la suite

La proposition contient 12 identités, six familles de vérification et quatre scénarios métier. Relire les critères et les références documentaires disponibles. L'utilisateur enregistre alors une nouvelle révision immuable via l'UI ou `POST /api/v1/evaluation/suites`. Le champ `reviewed: true` est l'attestation de cet utilisateur ; le générateur local ne le remplit jamais.

Les oracles métier des fixtures restent proposés jusqu'à cette revue. Les références Giskard sont absentes tant qu'elles n'ont pas été écrites/revues. Aucun agent ne crée des labels humains, un accord inter-annotateurs ou un profil de confiance calibrée. Leur absence est affichée.

## Préflight sans exécution

Utiliser `POST /api/v1/evaluation/campaigns/preflight` avec :

```json
{
  "suite_id": "SUITE_REELLEMENT_REVUE",
  "baseline_run_id": "RUN_VISIBLE_AVEC_CONTRAT_FIGE",
  "expected_draft_revision": 1,
  "request_key": "LUMA_NOUVELLE_TENTATIVE",
  "ingress_id": "source.request",
  "kind": "manual",
  "execution_mode": "qualified_prefix",
  "repeat_count": 2
}
```

Remplacer la révision, les identifiants et la clé par les valeurs actuelles. Le préflight ne crée ni Run ni job et ne sauvegarde pas le brouillon. Il doit annoncer 48 Runs, le préfixe qualifié, les sources et le modèle épinglé. Examiner les problèmes de corpus incomplet, modèle non épinglé ou outil non qualifié. Une étiquette `effect: read` ne donne aucune autorisation.

La limite de suite reste 20 cas ; les deux répétitions sont distinctes de ce plafond. Une délégation/subflow atteignable est refusée explicitement dans cette livraison. Des branches hors de l'ingress choisi ne sont pas lancées. Si une nouvelle version rend un exécuteur non qualifié atteignable, qualifier cet adaptateur en code avant de l'autoriser.

Le mode `qualified_prefix` prépare désormais une **projection distincte** du Flow, depuis l'entrée sélectionnée jusqu'aux frontières humaines. Il conserve les assets PostgreSQL/documentaires entrants, leurs exigences et l'opération métier de l'entrée. Il ne supprime aucun nœud du brouillon. Un nœud inachevé hors parcours ne bloque donc pas la campagne ; une erreur atteignable ou une dépendance exécutable hors préfixe reste bloquante. La validation des previews ordinaires et de la publication ne change pas.

Le préflight expose `projections.baseline/candidate` : SHA du Flow source, SHA projeté, nœuds retenus/exclus, assets et frontières humaines. Le candidat conserve aussi sa révision de brouillon et la baseline son Run source. Ces preuves sont figées dans la campagne ; les Runs conservent `execution.source_flow_sha256` distinct de leur `flow_sha256`. La baseline réutilise ses contrats historiques validés, sans résoudre à nouveau ses Skills dans le catalogue. En mode strict, une déclaration de sortie inerte peut compléter le contrat après la frontière ; le moteur QA s'arrête avant elle et toute reprise reste refusée.

Sur Luma r38/v10, le nœud utilisateur `flow.mv95zi21.1` reste dans le brouillon. L'enquête projetée exclut ce nœud, les autres entrées et les actions après `hitl.review`, tout en gardant les six assets liés. Si le parcours métier n'a pas changé, présenter les essais comme un contrôle de répétabilité/non-régression. Une différence de verdict entre deux exécutions ne prouve pas, à elle seule, une amélioration causée par le brouillon.

## Exécuter et inspecter

Après examen du préflight, envoyer le même corps à `POST /api/v1/evaluation/campaigns`, enrichi de son `preflight_sha256`. Une modification du brouillon ou du profil invalide le préflight. La requête idempotente ne crée pas de doublons ; une nouvelle tentative utilise une nouvelle clé. Toutes les répétitions restent dans le rapport, sans choisir le meilleur essai.

Attendre `GET /api/v1/evaluation/campaigns/{id}`. Les résultats exposent séparément :

- statut réel du Run et terminaison attendue (`human_gate`) ;
- verdict des assertions d'objet et de trajectoire, avec IDs d'invocations ;
- statut de qualité du Judge et éventuelles erreurs/non-évaluations ;
- différence entre versions, limites de comparabilité, usage mesuré et coûts calculés disponibles.

Pour chaque famille, ouvrir au moins une enquête Run et suivre la préparation, l'artefact scoré, les lectures de l'agent, sa proposition et la frontière humaine. Sur RC-5007/5008, vérifier la demande de pièce avant Judge. Vérifier qu'aucun `ecommerce_resolution_simulate_v1` ni ClaimAction n'a été créé par la campagne. Les décisions QA sont closes sans approbateur humain. Les routes de reprise ne peuvent pas franchir cette frontière.

Les datasets ont un espace de noms propre au couple campagne/cas/version/répétition/nœud. Ils ne prennent pas les versions des datasets métier. Leurs IDs restent consultables depuis les Runs ; les listes de datasets et de jobs de préparation/scoring utilisent le trafic métier par défaut et acceptent `traffic=evaluation` ou `all`. Une liste de jobs demandée par Run inclut ses artefacts QA. Les prédictions QA restent attribuées à la campagne même lorsque les entrées ne sont pas conservées.

## Giskard sur les réponses conservées

Après revue des questions/réponses de référence, lancer `POST /api/v1/evaluation/campaigns/{id}/raget` avec une nouvelle `request_key`. Le worker reprend la sortie de l'invocation choisie, applique `answer_path`, puis exige un texte ou sérialise le JSON si `answer_format=json`. Le `summary` de Luma seul ne représente pas une réponse SAV.

Il évalue baseline et candidat pour chacune des deux répétitions. Le rapport conserve chaque tentative, Run, invocation et version SDK. Aucun outil du Flow n'est rappelé. Si le résultat est retenu par une politique de sortie, il ne peut pas être transmis à Giskard. Un échec de budget ou de fournisseur reste un échec d'évaluation, pas une preuve de qualité négative ou positive.

## Comparabilité et lecture COMEX

Les fichiers Flow/contrats, versions de suite, modèles épinglés et empreintes du registre documentaire sont conservés. Les données PostgreSQL et la recherche documentaire sont relues réellement : ce n'est pas un rejeu d'un instantané immuable. Des empreintes de source différentes entre les deux côtés rendent la paire non comparable. Un changement du registre documentaire supprime les conclusions d'amélioration/régression. Une révision distante du fournisseur peut évoluer même si son nom reste identique.

Seuils de démonstration **informatifs**, sans qualification statistique : aucune action métier exécutée ; 48 tentatives visibles ou motifs d'arrêt explicites ; aucune assertion critique ignorée ; aucune erreur fournisseur renommée en succès ; toutes les références et non-évaluations accessibles. Une régression ou un contrôle incomplet appelle une revue humaine avant publication. Ces seuils ne créent pas un nouveau gate automatique.

Phrase client : « Avant de publier une évolution, je rejoue des dossiers connus, je vois ce que l'agent a vraiment fait, je compare ses réponses et je garde la décision de publication. » Préciser les résultats réellement obtenus, les points restant à qualifier et les hypothèses ; ne pas présenter 48 essais comme une garantie de résistance aux attaques, une calibration humaine ou un gain financier mesuré.
