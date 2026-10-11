# Reprise — programme « Skills lisibles et définissables », 8 août 2026

Branche `codex/flow-builder-p0-integration`. Plan de référence :
`~/.cursor/plans/skills_lisibles_et_definissables_10a1238a.plan.md` (ne pas éditer).

> **Mise à jour du 9 août, 9h30.** Les trois chiffres de la section suivante ont été faux
> pendant vingt-quatre heures et ont produit une fausse prémisse deux nuits de suite : la base
> n'est plus en `080`, les candidates ne sont plus en `522632e0`, et « 89 inertes » ne décrit
> plus l'estate. Ce qui suit est à jour au 9 août 9h30. Les sections *Décision de déploiement*
> et *Ce que voient les utilisateurs* datent du 8 et sont **dépassées** ; lire d'abord
> *Les deux fenêtres du 8 août au soir*.

## Où en est la production

> **Mise à jour du 10 août, 07h15 UTC — c'est déployé.** Tout ce qui suit dans cette
> section décrivait l'état d'avant la bascule et n'est plus vrai. La fenêtre a été jouée
> d'un trait, sans trafic, et chaque point de contrôle a rendu le chiffre attendu.
>
> | | Valeur |
> |---|---|
> | Images servies | `f8c0758bf938`, `revision_verified: true` |
> | Base | `084_decision_condition_repair`, tête unique |
> | `demo/agentic` | `5ca80901`, local, remote et VM alignés |
> | Publication | `published 84`, `already_pinned 1`, `failed 4` (les quatre défauts d'auteur) |
> | Dispatch | 77 Systems, `manual 59 / chat 16 / event 1` |
> | Canaris | 6/6 |
> | Rollback | images `5c1f8838ac66` conservées, dump du 10/08 vérifié |
>
> Les observables complets, les deux pièges rencontrés et ce que la fenêtre **ne**
> prouve pas sont dans [`agentium-safe-vm-deployment.md`](./agentium-safe-vm-deployment.md),
> section *Fenêtre exécutée le 10/08*.

La VM sert toujours `5c1f8838ac665706dfeecd79cc35ff63f55bb51a` sur les trois images
(backend, frontend, worker), conteneurs debout, `demo-agentic` non déplacé — vérifié le 9 août
au matin : sur chaque image, `demo-agentic` et `:5c1f8838ac66` sont le même identifiant d'image,
ce qui prouve que le tag n'a pas bougé.

**La base, elle, a bougé : elle est en `083_workspace_skill_executor`, tête unique.** La migration
a été appliquée en live le 8 au soir et ne coûte rien tant que les images ne basculent pas,
puisque l'image servie lit le drapeau par son absence et recompile à la volée. Le retour arrière
reste « images seulement » ; il n'y a rien à défaire côté base.

**Rien du code de ce programme n'est déployé.** HEAD local est à `f8c0758b`, non poussé.

> **Mise à jour du 9 août, après-midi — la mesure combinée existe.** La séquence
> complète (`084` puis backfill) a été jouée en une passe sur une copie fraîche du
> dump. Résultat : **85 publications sur 89**, et **77 Systems dispatchables** dont
> `manual 59, chat 16, event 1`. Le retour arrière « images seulement » est
> **prouvé** avec `084` appliquée. En revanche le downgrade de `084` après le
> backfill est destructeur. La procédure exécutable et tous les chiffres sont dans
> [`agentium-safe-vm-deployment.md`](./agentium-safe-vm-deployment.md), section
> *Bascule `flow_publication_v1` — procédure exécutable, mesurée en combiné le 09/08*.
> Ce fichier reste le récit ; la procédure ne se lit plus ici.

Artefacts laissés par la fenêtre du 8 au soir :

- dump pré-migration vérifié : `/srv/agentium-data/flow-publication-deployments/2026-08-08-108bbfcea7b5/postgres-pre-migration.dump` (448 576 596 octets, sha256 `9f8a56bc…9a8811`, restauré avec succès) ;
- rapports sous `…/2026-08-08-108bbfcea7b5/reports/` : dry run live, apply du témoin, deux répétitions, sonde de disponibilité pré-témoin ;
- exports d'évidence sous `/srv/agentium-data/candidate-out/evidence/` : estate avant correctif, sortie du backfill après correctif, mesure de disponibilité, sonde de compilation ;
- images candidates taguées `108bbfcea7b5`, **sans** déplacement du tag mutable ;
- base de répétition `agentium_reh_108bbfce` (~4,7 Go) encore présente sur l'instance PG.

## Ce qui a atterri aujourd'hui

| Commit | Contenu |
| --- | --- |
| `78da2679` | Tranche E — kind de Trigger, schéma d'ingress, bindings nommés Decision, schémas de sortie par nœud |
| `a1a2f959` | Tranche B — colonne `category` réelle (9 catégories), heuristique frontend supprimée, 6 wrappers orphelins semés, raison de visibilité par ligne, `resource_kind` IAM `skill` |
| `2443bbd0` | Tranche D — `/catalog/curation`, couverture décomposée en leviers |
| `714bac2c` | Tranche A — `flow_publication_v1` en défaut de code, migration 081, effondrement vertical du Flow Builder corrigé |
| `073d9005` | Six classes d'exception dégelées (`frozen` masquait l'erreur réelle ; `slots` innocent) |
| `a13bea8c` | Runbook — ordre obligatoire de la bascule de publication |
| `522632e0` | Classifieur du backfill corrigé : l'identité d'une version est le hash canonique de sa charge utile, pas la colonne `flow_sha256` nullable |
| `e6c610a4` | Tranche F — CRUD Skill scopé au workspace, slugs `ws.<id>.<nom>`, exécuteurs vérifiés, binding eager fail-closed |
| `828210e6` | Tranche C — palette sur Capabilities, 46px → 24px, surface par défaut sans défilement |
| `083a9ada` | Gel de l'exécuteur à la publication (voir ci-dessous, le risque n'était pas celui annoncé) ; attente périmée corrigée sur `validate_flow` |
| `276b8624` | `no_visible_capability` éclaté en quatre leviers nommés ; l'échappatoire nomme l'industrie qui bloque |
| `8a4589dd` | Identifiant de révision 081 ramené à `081_flow_publication_baseline` (29 car.) + garde qui lit la limite sur la table de version d'Alembic |
| `108bbfce` | Sonde `GET /api/v1/systems/dispatch-readiness` — rendre visible quels Systems refusent de dispatcher |
| `6604d957` | Compilateur : rôle structurel résolu par un helper partagé (`flow_node_kind.py`), chat clé sur le rôle `type=input` et non sur l'id `source.request` |
| `61eab738` | Tests épinglant l'accord entre le compilateur et le marcheur de DAG sur le rôle d'un nœud |
| `69b42432` | Migration `084_decision_condition_repair` — les 7 conditions Decision endommagées réécrites dans les graphes stockés, ledger de retour arrière, 17 tests sur graphes réels |
| `1808196f` | Backfill : classement par recompilation et comparaison de `contract_sha256`, republication des contrats périmés, `apply_risk` qui prédit les refus de compilation ; harnais `rehearse_published_ingress_run.py` |
| `f8c0758b` | Runbook — pourquoi 40 Systems refusaient encore de publier, et correction de la règle du marcheur |
| `dcc36f97` | Répétition combinée sur copie fraîche + runbook exécutable de la fenêtre ; retour arrière prouvé, vrai point de non-retour identifié |

## Les deux blocages de la fenêtre

**1. La migration 081 ne pouvait pas être estampillée.** Son identifiant faisait 36 caractères, `alembic_version.version_num` est un `varchar(32)`. Jamais exposé en quatre-vingts migrations parce que toutes les autres tenaient — les deux plus longues survivantes font exactement 32, il n'y avait aucune marge. **Corrigé en `8a4589dd`.** Élargir la colonne n'était pas une option : le 32 est codé dans `DefaultImpl.version_table_impl` d'Alembic, qu'aucune option d'`env.py` n'atteint, et un élargissement par migration bute sur le fait que sa propre estampille est celle qui déborde. La garde ajoutée lit la limite sur la table qu'Alembic créerait réellement, plutôt que de la coder en dur.

**2. Ma mesure était fausse d'un facteur cinq.** J'avais annoncé 16 Systems inertes. Le dry run en rapporte **89**. Cause : `execution_contract` contient le scalaire JSON `null` sur 88 des 104 versions publiées, et un `null` JSON n'est pas un NULL SQL — un `IS NULL` ne les voit pas. Requête correcte : ajouter `jsonb_typeof(...) = 'null'`. `already_pinned` vaut 0, donc **aucun System en production ne démontre aujourd'hui qu'une publication sous ce code produit un contrat accepté**. L'écart entre 104 et 89 vient de deux workspaces en suppression douce (`acme`, `personal-253f4c1c`), que le script saute correctement.

## Les deux fenêtres du 8 août au soir

**La fenêtre a été rejouée et s'est arrêtée au témoin.** Le correctif d'identifiant de révision
est prouvé sur PostgreSQL : sur une copie restaurée, Alembic a marché `081 → 082 → 083` en
inscrivant `081_flow_publication_baseline` dans `alembic_version` puis en le dépassant deux fois.
C'est exactement ce qui échouait. Considérer le point comme réglé. La base live a ensuite été
migrée ; le dry run a confirmé les 89 publications attendues, rien de sauté, rien à risque.

**Le témoin est un faux positif, et c'était le vrai enseignement.** La publication a réussi,
`PUBLISHED_EXECUTION_CONTRACT_MISSING` est réellement corrigé, `assert_dispatchable` accepte le
System. Mais le contrat compilé était vide — `{"nodes": {}, "outputs": [], "ingresses": []}` — et
sans ingress publié, les cinq adaptateurs sont refusés à la barrière suivante avec
`FLOW_INGRESS_KIND_UNAVAILABLE`. **Une colonne `execution_contract` non nulle est satisfaite par
un contrat qui ne nomme rien** : c'est la troisième fois que ce fichier enregistre une mesure
fausse construite sur la présence d'une valeur plutôt que sur son contenu.

Répétition de l'`--apply` complet sur copie restaurée, avant correctif : 49 Systems publient,
40 échouent, et **43 des 49 publiés compilent zéro ingress**. Six Systems sur 89 auraient accepté
un Run. Basculer les images là-dessus faisait passer l'estate de « le chemin legacy fonctionne
partout » à « rien ne dispatche sauf six ».

**Deux causes, pas une.** L'orthographe legacy était réelle — 104 des 109 graphes stockés écrivent
l'entrée `type: "source"` sans champ `kind`, que le compilateur ignorait. Mais le chat était cassé
indépendamment : le compilateur le reconnaissait sur un identifiant de nœud codé en dur,
`source.request`, alors que tous les Systems de chat seedés nomment ce port `chat.request`. Ne
corriger que l'orthographe aurait classé chaque System de chat en source d'événement — pire que
vide, puisque aucun adaptateur d'événement ne l'aurait routé.

Après `6604d957`, remesuré de la même manière sur les mêmes lignes : **45 des 49 portent un
`ingresses` non vide, contre 6.** Avec un astérisque qui compte : `manual 44, chat 1, event 1`.
Le dispatch manuel est réel mais ce n'est pas l'automatique que vise le programme. En
contrefactuel, hors validation de publication, 84 Systems sur 89 compilent au moins un ingress et
le chat monterait à 20 — l'écart est entièrement dû au blocage des conditions Decision.

### Ce qui reste avant toute bascule

1. ~~**Le backfill n'accomplit pas le travail qu'on lui prête.**~~ **Fermé par `1808196f`.** Le
   classement recompile désormais la définition épinglée et compare `contract_sha256` au contrat
   stocké : un contrat que le compilateur d'aujourd'hui ne produirait plus est vu comme périmé et
   republié. L'idempotence vient gratuitement, sans mécanisme séparé — après une passe la
   recompilation concorde. Mesuré : `already_pinned 49 / publish 40` avec l'ancien script contre
   `already_pinned 10 / publish 79` (dont **39 republications**) avec le nouveau, et une seconde
   passe consécutive revient à `publish_republication: 0`. Le dry run signale en outre les contrats
   qui ne compileront pas comme `apply_risk` : il a prédit les trois refus au moment de l'apply,
   avec les bons codes, là où l'ancien annonçait `at_risk: 0`.
2. ~~**36 conditions Decision invalides** bloquent 36 publications.~~ **Fermé par `69b42432`**
   (migration `084_decision_condition_repair`) : mesuré sur export pré-migration, les publications
   passent de **49 à 85 sur 89**, et les Systems portant un ingress `chat` de **1 à 20** — le
   plafond contrefactuel exactement. Voir *La réparation des conditions* plus bas.

   **Le « 20 » a été confirmé et ne veut pas dire ce qu'on lui fait dire.** Sur la
   mesure combinée du 9 août, 20 contrats publiés *contiennent* bien un ingress
   `chat`, mais **16 seulement accepteraient un Run** : les 4 autres appartiennent à
   des Systems `retired`, refusés en `FLOW_INGRESS_SYSTEM_INACTIVE`. Compter des
   ingress compilés est précisément l'erreur de mesure que ce fichier documente par
   ailleurs. Le chiffre à présenter est **16**.
3. ~~**Aucun Run bout-en-bout n'a été prouvé.**~~ **Fermé.** Quatre Runs terminés en `completed`
   depuis l'image candidate sur la copie de répétition : News Lab (`smoke-dfbfc7`), Evidence Graph
   (`sentinel-ci`), Password Reset (`nawa`, DAG overlay) et Andritz Chat Agentic — l'ingress chat.
   Le dialecte ne mord pas une seconde fois.

   **La règle du marcheur était mal comprise, et la correction renforce la position.** L'overlay DAG
   exige `schema_version >= 2` **et** un nœud portant un `kind` de contrôle ; un `type: "source"`
   sans `kind` ne qualifie pas. Rejoué sur les 99 graphes non vides : 56 DAG, 43 séquentiels, aucun
   dans les deux ensembles. Les 42 graphes à `type: "sink"` legacy, les 42 à `type: "source"` legacy
   et les 20 à `skill_slug` à plat sont **tous** séquentiels. Les orthographes legacy ne sont jamais
   lues par un marcheur DAG — c'est pourquoi la tolérance étroite peut le rester, et pourquoi
   l'élargir aux sinks changerait les contrats figés de 42 Systems sans bénéficier à aucun lecteur.

   Les trois échecs restants ne sont pas des problèmes de dialecte : `Contract Risk Copilot` ne
   déclare réellement aucun sink, et `Shared mailbox creation` déclare bien `config.skill_slug` —
   le compilateur le lit correctement, le refus vient de ce que `system.skill_ids` est vide, donc le
   System ne possède pas le Skill.

### L'ordre de la bascule, et ce que la publication achète réellement

**`084` doit précéder le backfill, pas le suivre.** Les deux fronts ont travaillé en parallèle et
chacun a mesuré sa moitié : sans la migration, 36 Systems restent impubliables quoi que fasse le
backfill. Séquence : migrer (`084`) → backfill `--apply` → reprendre le trafic. ~~Personne n'a encore
mesuré l'état **combiné** sur une seule copie~~ — **fait le 9 août** : 85 publications sur 89, 77
Systems dispatchables, `chat 16`. L'ordre est confirmé, et il y a maintenant une raison de plus de
le respecter : une fois le backfill passé, `084` ne peut plus être downgradée sans casser 30
Systems en `PUBLISHED_FLOW_MIRROR_DRIFT`.

**Ce que la publication apporte à ces Systems est plus modeste que le programme ne le laisse
croire.** Pour les graphes séquentiels, le contrat compile `nodes: {}` et `outputs: []`, et les
validateurs de sortie renvoient `None` quand un nœud est absent du contrat. Au-delà de la
vérification de la charge utile d'ingress, un Run publié y est **identique** au chemin legacy. La
valeur est la barrière d'ingress, pas le contrat. À garder en tête avant de présenter la bascule
comme un gain d'exécution.

Dans le même registre : les 44 ingress manuels gagnés sont majoritairement du contenu de
démonstration, pas du trafic. News Lab et Evidence Graph n'ont aucun Run historique.

**Une réserve sur la preuve chat.** Le Run d'Andritz Chat Agentic a échoué deux fois sur
`membrane_valve_breach:max_latency_ms` avant d'aboutir (vanne à 45 s, `semantic_search_v1` à
27–35 s). Ce n'est pas une régression de publication — l'historique du même System sur la copie
est de 253 `completed` contre 90 `failed`, tous sur ce même code. Environ un Run de chat sur quatre
franchit déjà cette vanne aujourd'hui. C'est un problème réel, mais antérieur et distinct.

### La réparation des conditions

**Sept chaînes endommagées distinctes, pas trois.** Six vivent dans le seul template
`Agentium Workspace Chat` (nœuds `router.fast_exit` et `runtime.deep_router`, 19 Systems, rejetées
en `condition_syntax_error`), la septième dans `Expert Knowledge Capture` (`decision.answer_route`,
17 Systems, `condition_unsupported`). Chaque occurrence est identique à l'octet près, donc la
réécriture est un appariement exact sans ambiguïté. Travailler à partir des trois exemples connus
aurait laissé 19 Systems en échec.

**Aucune sémantique n'a été inventée** : `aab6b5a6` avait déjà réparé les sept conditions dans les
templates, la migration applique la réponse de l'auteur verbatim. Un test vérifie que chaque
remplacement apparaît encore dans un graphe seedé, pour que migration et templates ne dérivent pas
en silence. La décision produit que j'avais réservée n'avait donc pas lieu d'être.

**La classe 2 n'était pas un défaut du validateur.** La grammaire n'admet un chemin pointé que pour
`ctx.<clé>`/`context.<clé>` et les quatre espaces réservés `workspace`, `system`, `run`, `node`.
Il n'existe **aucune forme atteignant un champ imbriqué d'une valeur de ctx** : `evaluation.verdict`
n'est pas mal orthographié, il est inexprimable. Rien ne bougeait dans `run_engine/condition.py`.

**Comportement après migration, mesuré et non déduit** : les prédécesseurs ne lient ni `route`, ni
`deep_search_requested`, ni `verdict`, donc chaque Decision réparée sélectionne exactement la
branche qu'elle déclare déjà en `default_branch`. C'est le repli sûr envisagé, atteint sans rien
inventer, et la branche redevient sélectionnable dès qu'une charge utile fournit le nom. Épinglé
par un test.

Nuance relevée à l'exécution réelle : la réparation écrit `True` sur la branche de repli, donc le
moteur la voit **matcher** et journalise `decision_resolution: matched`, non un repli par défaut.
Le résultat est bien celui décrit ci-dessus, mais un opérateur qui cherche `default` dans les
checkpoints ne trouvera rien.

**La casse touche 41 Systems, pas 36.** Les cinq de plus sont dans des workspaces où
`flow_publication_v1` est éteint, donc invisibles à la répétition. La migration les répare aussi
(130 lignes au total) : ils publieront proprement quand leur drapeau basculera.

**Précision sur « jamais publiable sous aucun code ».** L'affirmation tenait, mais pas pour la
raison avancée : `decision_condition_invalid`, la barrière `validate_condition` du validateur de
DAG et `decision_condition_error` du moteur sont **tous arrivés dans `aab6b5a6`**, le commit même
qui répare les seeds. Ce qui le précède, c'est `condition.py`, qui n'a jamais accepté `ast.Call` ni
su lire `&&`. Ces conditions n'ont donc jamais pu s'**évaluer** ; `aab6b5a6` a déplacé l'échec du
temps d'exécution vers le temps de publication.

### Les quatre restants — aucun n'est mécanique

- **`Tender Response Analyst`** : la branche `escalate` n'a pas d'arête sortante et le graphe ne contient aucune cible d'escalade. La câbler sur le sink jetterait silencieusement les escalades ; la supprimer ferait tomber la Decision à une branche et déclencherait `decision_no_branches`. Demande un auteur.
- **`Shared mailbox creation` (Nawa)** : un moignon de trois nœuds où les **deux** branches sont non câblées et où la moitié aval n'existe pas. Le réparer, c'est écrire le reste du flow. À signaler d'autant plus que Nawa est l'organisation cliente la plus exposée.
- **`Contract Risk Copilot`** : un Flow strict de quatre tâches chaînées, sans source ni sink. Le rendre publiable impose de désigner une sortie, ce qui change la forme du contrat publié.
- **`Translation Suite`** : cause racine établie sur les lignes du dump, pas déduite. Le System lie la capacité `a62f579b` (`video_translation_suite`, créée le 1er juillet) tandis que son AdaptivePolicy `3f7d4c0f`, scopée capacité, vise toujours `fa9924d9` (`showcase_translation_suite`, 24 juin). `_resolve_adaptive_policy` exige `target_id == capability_id` sous scope `capability`. Le System a été relié à une capacité plus récente sans que la policy suive. Défaut de données sur deux lignes, ni graphe ni code.

Note annexe : une troisième instance de `decision_branch_unwired` existe hors des 89
(`e2e-debug-1777215653923`, workspace d'Alice), dans un workspace où la publication est éteinte.

### Limite de la sonde de disponibilité

`dispatch-readiness` lit **vert-et-vide** pour un workspace dont les Systems ne déclarent aucune
surface. Elle ne montre donc pas, seule, qu'un estate entier est inerte. Le 8 au soir elle n'a
trouvé qu'une seule surface de dispatch dans toute la production, un nœud de trigger chez
`andritz`. Le complément qui dit la vérité est de rejouer la barrière d'ingress contre chaque
System non retiré : avant témoin, **0 accepté sur 83**.

## Ce que voient les utilisateurs si la bascule passe sans backfill

*Section du 8 août, conservée : l'analyse par surface reste valable, la décision qui la suit non.*

Tracé dans le code, par surface.

**Bruyant et propre** : run manuel → 409 sans création de Run ; Flow Runner → bloqué, affiche le message du serveur ; sous-flow → le run parent échoue visiblement.

**Silencieux, et c'est le vrai risque** : un tick de planification ne crée aucun Run et avance quand même son `next_fire_at` — l'exécution s'évapore ; un webhook reçoit **HTTP 200** avec `"status": "rejected"` enfoui dans le corps.

**Le chat survit** : un tour routé vers la voie agentique échoue avant création de Run, l'exception est rattrapée, le moteur classique reprend avec une étape « Repli technique contrôlé ». L'utilisateur reçoit une réponse.

**Piège de diagnostic** : le bouton Exécuter du Flow Builder compile depuis le brouillon et continue de marcher, même quand la production refuse le System.

**Retour arrière : images seulement, pas de restauration de base.** Les anciennes images lisent le drapeau par absence et reprennent le chemin legacy qui recompile à la volée. La base peut rester en 082.

**Ne rien faire n'est pas neutre** : drapeau éteint, chaque sauvegarde de l'éditeur écrit directement dans le graphe exécutable — pas de barrière de publication, un graphe à moitié édité devient exécutable au prochain déclenchement. Et nous venons de rendre le Flow Builder nettement plus engageant.

## Décision de déploiement ~~du 8 août~~ — dépassée

~~**Garder la bascule dans le lot**, avec backfill **témoin d'abord** : publier un workspace de
test, vérifier qu'un run passe de bout en bout pour obtenir le précédent qui manque, puis élargir
par vagues.~~

La stratégie était bonne et c'est elle qui nous a sauvés : le témoin a bien révélé ce qu'un dry
run ne peut pas voir. Mais sa prémisse était fausse — **une publication par System ne rend pas
l'estate exécutable**. Le témoin a été joué, il a échoué à produire le précédent recherché, et les
vagues ont été annulées. Ne pas rejouer de fenêtre avant que les trois points de *Ce qui reste
avant toute bascule* soient fermés, et notamment le troisième : un Run qui aboutit, pas seulement
un Run accepté.

Le prérequis du 8 août — rendre bruyants les deux chemins muets — a été livré en `108bbfce`, avec
la réserve de lecture notée plus haut.

## Le gel des contrats : le risque n'était pas celui annoncé

Nous avions identifié le mauvais danger. Les **schémas** n'ont jamais été l'exposition : la publication les figeait déjà dans `SystemVersion.execution_contract` et `run_contracts` ne relit jamais une ligne Skill, donc une modification d'`input_schema` ne peut pas atteindre un Run.

C'est l'**exécuteur** qui l'était. Il était résolu depuis la ligne à chaque invocation, si bien qu'un PATCH changeait ce que faisait un flow déjà publié — sans nouvelle version, sans signal : une clé de dispatch immuable pointant vers une cible mutable. `083a9ada` fige donc l'exécuteur à côté des schémas. Le gel épingle *quels* paramètres vérifiés tournent, jamais qu'ils le sont encore : `bind_executor` revalide à chaque dispatch, donc un binding retiré depuis échoue fermé plutôt que de devenir exécutable pour avoir été figé.

L'édition reste permise — la refuser rendrait un Skill inéditable tant que quelque chose de publié s'en sert — et PATCH répond désormais avec les versions publiées désormais en retard. DELETE refuse, lui : le contrat figé ferait tourner les runs, mais le System ne pourrait plus être validé ni republié.

## Chantiers

- **En cours au 9 août** : reclassification du backfill pour qu'il republie les contrats vacants, et preuve d'un Run bout-en-bout sur la copie de répétition ; en parallèle, migration des 36 conditions Decision stockées.
- **Fait** : rendre bruyants les deux chemins de dispatch muets (`108bbfce`).
- **En attente** : inventaire des skills du flow avec santé runtime et remplacement sur place, plus l'entrée de navigation de l'écran de curation. L'agent a été coupé sans rien écrire, à relancer de zéro.

### Décisions produit réservées

La décision que j'avais réservée sur les conditions **n'avait pas lieu d'être** : `aab6b5a6`
contenait déjà la réponse de l'auteur pour les sept chaînes. Restent deux arbitrages qui, eux,
demandent un humain :

- **`Translation Suite`** : deux bindings coexistent, la capacité portée par le System et celle visée par sa policy. Repointer le `target_id` de la policy sur la capacité courante est la réparation évidente, mais laquelle des deux fait foi est un choix, pas une déduction.
- **Trois Systems demandent un auteur, pas un correctif** : `Tender Response Analyst`, `Contract Risk Copilot`, et le moignon Nawa `Shared mailbox creation`. Les laisser non publiables est tenable — ils ne dispatchent pas aujourd'hui non plus.

## Dette explicitement acceptée

- Dedup de triggers, rate limiting et disjoncteur ne sont vérifiés que sur le chemin legacy.
- `rollout_system360_canary` et `backfill_flow_v3_variables` refusent de tourner sous publication active ; le rollout canary du Lot 6 est injouable en l'état.
- Le classement par usage de la palette est tout-venant, sans fenêtre, et scopé par appelant : deux collègues voient des ordres différents du même catalogue.
- Tranches G (chat par System) et H (objet UseCase Intake/BR/TOM/QA, golden set, périmètre BR) non commencées.

## Enseignement de méthode

Trois erreurs n'ont été attrapées que par la répétition sur copie restaurée : l'identifiant trop
long, la requête confondant `null` JSON et NULL SQL, et le contrat publié mais vacant. Aucune
relecture de code n'aurait trouvé les deux dernières — elles étaient syntaxiquement correctes et
retournaient un résultat plausible. Ne pas raccourcir cette étape, même quand la fenêtre semble
anodine.

Les trois partagent une seule racine : **avoir conclu de la présence d'une valeur à la réalité
qu'elle est censée représenter.** Une colonne non nulle ne prouve pas un contrat utile, un `IS NULL`
ne voit pas un `null` JSON, une publication réussie ne prouve pas un dispatch possible. La parade
n'est pas la vigilance, c'est de mesurer la propriété qui compte plutôt que son indice le plus
proche — ici, rejouer la barrière d'ingress plutôt que compter des colonnes remplies.

Corollaire opérationnel : **ce document a lui-même induit deux agents en erreur** en restant figé
au 8 août pendant que la production avançait. Un état daté vaut mieux qu'un état faux ; c'est la
raison de l'encadré en tête.
