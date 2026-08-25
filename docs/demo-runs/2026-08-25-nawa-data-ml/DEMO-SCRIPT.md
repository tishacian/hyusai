# Démo NAWA — Data / ML : de l'export sale au modèle servi (7 temps)

Répétée en local le 25/08/2026 (UTC) sur base Postgres vierge + object store local,
seed rejoué de zéro : `backend/scripts/seed_nawa_data_demo.py`. Non encore déployée sur
la VM `omnirag-demo` (voir [§ Déploiement](#déploiement--ce-quil-reste-à-faire)).

Le fil : une base d'abonnés télécom arrive comme les exports arrivent vraiment — doublons,
lignes suspendues, régions écrites de quatre façons, une colonne revenu trouée et un `-1`
qui veut dire « inconnu ». En sept temps elle devient un modèle de churn servi derrière une
clé API, et un deuxième pipeline dbt sort une watchlist radio. **Aucun LLM dans le chemin de
données** : SQL, Polars, scikit-learn, dbt.

Ce runbook est le script présentateur. Les chiffres qu'il cite ne sont pas illustratifs :
ils viennent du seed rejoué le 25/08 et sont reproductibles par graine
(`--seed 20260825`, la valeur par défaut).

## Identifiants (état du seed rejoué le 25/08)

| Objet | Valeur |
|---|---|
| Workspace | `nawa` — id `f6e94159-1e81-4430-9a3f-5f3829e1e0d4` |
| System 1 | `Churn Radar` — id `14b9c0dc-3aa8-4be9-9595-73fd68ec93d0`, actif |
| System 2 | `Radio Watch` — id `3e176090-7080-46ec-ad4e-dfead5d8fbc2`, actif |
| Modèle servi | `Churn Radar` **v1** (`linear`) — id `6445be44-c21a-4e2c-8c10-99db4b2952d0` |
| Skill publiée | `ws.f6e94159-….predict_churn_radar` |
| Clé API | préfixe `agpk_cdukue9` (le secret complet ne s'affiche qu'à la création) |
| Run churn | `84d79dd1-f09b-4a22-af06-767f8d2b0a6d` — completed, 7 nœuds |
| Run radio | `d587a9f6-e792-4036-81ce-fc7add4fa39e` — completed, 3 nœuds |

Sept datasets, et la lignée se lit dans l'ordre :

| Dataset | Version | Lignes | Colonnes | Produit par |
|---|---|---|---|---|
| `base-clients-export-brut` | v1 | 8 412 | 24 | l'upload |
| `kpi-cellules-radio` | v1 | 24 192 | 12 | l'upload |
| `base-clients-nettoyee` | v1 | 6 903 | 22 | le seed (SQL duckdb) |
| `base-clients-nettoyee` | v2 | 6 903 | 22 | le nœud `1 · Nettoyer` du Flow |
| `base-clients-features` | v1 | 6 903 | 31 | le nœud `2 · Features` (Polars) |
| `base-clients-scoree` | v1 | 6 903 | 34 | le nœud `4 · Scorer` |
| `cellules-a-risque-7-jours` | v1 | 72 | 13 | le nœud dbt de Radio Watch |

## Les chiffres à connaître par cœur

- **8 412 → 6 903.** Exact, pas échantillonné : 412 doublons + 640 lignes suspendues
  + 297 ARPU vides + 160 ARPU à `-1`, blocs disjoints par construction.
- **Trois versions, un classement mesuré** : v1 `linear` **0,835206** · v2
  `gradient_boosting` **0,859632** · v3 `gradient_boosting` sur les 29 colonnes
  **0,855853**. La promotion v1 → v2 vaut **+0,024426** ROC AUC.
- **v3 ne gagne pas**, et c'est laissé tel quel. Un registre sert justement à dire
  qu'un challenger a perdu.
- **Taux de churn de la base nettoyée : 22,16 %.** Le modèle en signale 999 sur 6 903 ;
  le décile le plus risqué churne à **77,2 %**, soit **×3,5** la base.
- **Watchlist radio : 9 `critique`, 8 `surveillé`, 55 `sain`** sur 72 cellules. Trois des
  neuf critiques étaient saines il y a quinze jours (delta +21 à +28 points de PRB).

## Check-list pré-démo (15 min avant)

1. Page **Data** : les 7 datasets, tous `ready`. Le brut à 8 412 et la watchlist à 72
   sont les deux extrémités du récit.
2. Page **Models** : 3 versions de `Churn Radar`, **v1 marquée servante**. Si v2 sert
   déjà, la promotion du temps 5 n'a plus rien à montrer — remettre v1.
3. Page **Skills** : `predict_churn_radar` visible avec sa puce de provenance
   (« répond depuis Churn Radar v1 »).
4. `/systems/14b9c0dc-…/flow` et `/systems/3e176090-…/flow` s'ouvrent avec les badges
   déjà posés sur les nœuds (un run derrière chacun).
5. Clé API dans le presse-papier du terminal de démo, `curl` répété **une fois** avant
   de monter sur scène : le premier appel paie le chargement du modèle (~5 s), les
   suivants non, et c'est un point du discours, pas un incident.
6. Zoom navigateur 100 %, thème au choix du public.

---

## Temps 1 — L'export arrive sale (~4 min)

**Click-path** : Build → Data → `base-clients-export-brut`.

1. **8 412 lignes, 24 colonnes.** Le profil de colonnes se lit sans requête : distributions,
   taux de remplissage, cardinalités.
2. **Montrer la saleté, colonne par colonne** — c'est ce qui rend le temps 2 nécessaire :
   - `region` : **28 valeurs distinctes pour 7 régions**. Quatre systèmes sources, quatre
     conventions : `Casablanca-Settat`, `CASABLANCA-SETTAT`, `casablanca-settat`,
     `« Casablanca-Settat »` avec espaces.
   - `plan` : 6 orthographes pour 3 offres (`PREPAID` / `prepaid`…).
   - `arpu_mad` : **310 vides** et **170 à `-1`**. Le `-1` est le piège : c'est un
     « inconnu » que l'export écrit comme un nombre. Un modèle entraîné dessus apprend
     que *−1 MAD prédit le churn*.
   - `line_status` : 677 lignes `suspended` — des abonnés qui ne peuvent pas résilier.
   - `msisdn` : **412 numéros apparaissent deux fois**, avec un `snapshot_date` plus
     ancien et des compteurs plus vieux. Un dédoublonnage naïf garderait la mauvaise ligne.
   - `nps` : 1 383 vides. **Celle-là ne se nettoie pas** — un abonné qui ne répond plus
     au questionnaire, c'est un signal, pas un défaut. On y revient au temps 5.

**Argumentaire** : rien de tout cela n'est décoratif. Chaque défaut correspond à une ligne
du SQL du temps 2, et le total des lignes retirées est vérifiable à l'unité.

## Temps 2 — Le SQL qui nettoie, et son badge (~5 min)

**Click-path** : Build → Systems → `Churn Radar` → Flow → nœud `1 · Nettoyer la base`.

1. **L'atelier SQL** dans l'inspecteur : duckdb, autocomplétion sur le schéma du dataset
   amont (taper `arp` propose `arpu_mad`). Ce n'est pas un champ texte.
2. **Lire la requête à voix haute** — elle fait quatre choses et rien d'autre :
   - `ROW_NUMBER() OVER (PARTITION BY msisdn ORDER BY snapshot_date DESC)` puis
     `snapshot_rank = 1` : on garde le **dernier** instantané de chaque abonné.
   - `lower(trim(region))` et `lower(trim(plan))` : une orthographe par région.
   - `line_status = 'active'` : les lignes suspendues sortent.
   - `arpu_mad IS NOT NULL AND arpu_mad >= 0` : les trous **et** le sentinelle `-1`.
3. **`ORDER BY msisdn` en fin de requête** — la ligne qui a l'air décorative et qui ne
   l'est pas. duckdb est parallèle : sans elle, l'ordre des lignes change d'un run à
   l'autre, la découpe train/test est positionnelle, et les métriques citées sur scène
   cessent d'être celles de la répétition.
4. **Le badge du nœud : `8 412 → 6 903 lignes`.** Faire l'addition en direct :
   412 + 640 + 297 + 160 = 1 509. C'est exact, pas arrondi.

**Argumentaire** : le nettoyage est une transformation gouvernée, versionnée, avec sa
lignée — `base-clients-nettoyee` v2 pointe sur `base-clients-export-brut` v1. Pas un
notebook sur le poste de quelqu'un.

## Temps 3 — Les features, en Polars (~4 min)

**Click-path** : même Flow, nœud `2 · Dériver les features`.

1. **22 → 31 colonnes**, neuf dérivées : `arpu_per_month`, `gb_per_mad`, `friction_score`,
   `friction_per_mad`, `usage_index`, `mobility_index`, `tenure_band`, `on_promo`,
   `nps_answered`.
2. **Pourquoi des ratios** : ce qui prédit un départ, ce n'est pas le revenu ni le nombre
   de tickets, c'est le revenu **par mois d'ancienneté** et la friction **par dirham
   facturé**. Un arbre approxime mal un ratio avec des coupures orthogonales, donc les
   lui donner explicitement déplace la métrique pour une vraie raison.
3. **`nps_answered`** : la non-réponse devient une colonne. On rend explicite le signal
   que le trou portait déjà.
4. **Le harness** : le Python de l'auteur tourne dans un venv isolé, construit à la
   demande et mis en cache par empreinte de dépendances (le premier build de ce nœud a
   coûté 5,2 s ; les suivants, rien). Ce n'est pas `exec()` dans le worker.

## Temps 4 — L'entraînement et la model card (~6 min)

**Click-path** : même Flow, nœud `3 · Entraîner` → puis Build → Models.

1. **Le nœud d'entraînement** : `ml_train_sklearn_v1`. Cible `churn`, 29 colonnes,
   estimateur et découpe déclarés dans la configuration du graphe. Le badge du run
   du 25/08 lit `6 903 lignes · roc_auc 0.855853` en 15,6 s.
2. **La page Models, trois versions de la même lignée.** Ouvrir **v2** — la model card
   est faite pour être projetée : métriques, matrice de confusion, courbes ROC et
   précision/rappel, importances, signature d'entrée, lignée vers le dataset exact.
3. **Où vivent les artefacts** : format MLflow sur l'object store (MinIO en VM), registre
   sur Postgres. Un modèle est un objet gouverné, pas un `.pkl` dans un bucket.
4. **Le détail qui fait tiquer les data scientists dans la salle** : `nps` a 1 144 trous
   dans la base nettoyée. Les arbres boostés les routent dans une branche et **lisent**
   l'absence de réponse ; la régression logistique ne sait pas faire — le harness lui
   ajoute donc un `SimpleImputer(strategy="median")`, décidé par estimateur d'après le
   tag `allow_nan` de scikit-learn. Le trou est comblé pour le modèle linéaire et exploité
   par le modèle à arbres. C'est exactement là que passe l'écart du temps 5.

## Temps 5 — La promotion, avec un delta réel (~5 min)

**Click-path** : Build → Models → comparer v1 / v2 / v3 → **Promouvoir** v2.

1. **Le classement, mesuré sur les mêmes 6 903 lignes, la même découpe, la même graine** :

   | Version | Estimateur | Colonnes | ROC AUC |
   |---|---|---|---|
   | v1 | `linear` | 20 | **0,835206** ← sert avant la démo |
   | v2 | `gradient_boosting` | 20 | **0,859632** |
   | v3 | `gradient_boosting` | 29 (+ dérivées) | 0,855853 |

2. **v2 > v1 de +0,024426.** Dire *pourquoi* : le churn de cette base n'est pas additif.
   Un ticket la première année est une lettre de démission ; le même ticket sur une ligne
   de huit ans est un appel au support. Une régression logistique ne peut pas représenter
   un produit de deux variables. Ce n'est pas la baseline qu'on a bridée, c'est le monde
   qui est non additif.
3. **v3 ne gagne pas** (0,855853 < 0,859632) et on le montre. Un registre qui ne saurait
   pas dire « ce réentraînement a perdu » ne servirait à rien. Personne ne promeut v3.
4. **Promouvoir v2**, et rester sur la page : la puce « sert » se déplace, la provenance
   de la skill publiée suit toute seule (temps 6).

## Temps 6 — Servir : Playground, skill, clé API (~7 min)

**Click-path** : Models → `Churn Radar` → onglet Playground.

1. **Le Playground s'ouvre pré-rempli** — la ligne typique du jeu d'entraînement (médiane
   des numériques, modalité la plus fréquente des catégorielles). Personne ne démontre un
   modèle en tapant quarante champs.
2. **Changer une chose et regarder** : passer `support_tickets` de 0 à 3 et `nps` à vide.
   Le score monte, et les **contributions par ligne** disent lesquelles des colonnes ont
   poussé. Une prédiction sans explication ne se défend pas devant un métier.
3. **Deux abonnés, pour le contraste** (chiffres du 25/08, v1 servante) :

   | Profil | Score churn |
   |---|---|
   | Prépayé, 4 mois, 3 tickets, 7 appels coupés, questionnaire sans réponse | **0,980** |
   | Postpayé 2 ans, 74 mois, fibre, 4 lignes, 0 ticket, NPS 9 | **0,002** |

4. **Publier comme Skill** : le modèle devient appelable par un agent. Aller sur la page
   Skills montrer la **puce de provenance** — elle dit « répond depuis Churn Radar v1 »,
   et elle est *dérivée*, pas figée à la publication : après la promotion du temps 5 elle
   lit v2 sans que personne y touche.
5. **La clé API, et le cURL** :

   ```bash
   curl -X POST "$AGENTIUM/api/v1/ml-models/6445be44-c21a-4e2c-8c10-99db4b2952d0/predict" \
     -H "X-API-Key: agpk_cdukue9…" -H 'Content-Type: application/json' \
     -d '{"inputs":[{"region":"casablanca-settat","plan":"prepaid","contract":"monthly",
          "tenure_months":4,"arpu_mad":38.5,"support_tickets":3,"dropped_calls":7,
          "nps":null, …}]}'
   ```

   La convention de charge utile est celle de `mlflow models serve` (`{"inputs": […]}`) :
   un client MLflow existant marche sans adaptateur.

6. **Trois choses à faire remarquer dans la réponse** :
   - un bloc `served` — quelle version a répondu, quel estimateur, quelle métrique. Une
     prédiction sans son émetteur n'est pas auditable ;
   - `cached: false, load_ms: 5268.4` au premier appel, `cached: true, load_ms: 0.0` au
     second, **même prédiction**. Le cache est une optimisation, pas un chemin de code ;
   - après la promotion du temps 5, **la même clé et la même URL répondent depuis v2**
     (`cached: false` : l'empreinte a changé, l'ancien pipeline est évincé). Promouvoir,
     c'est déplacer ce que la production sert.
7. **Clé absente ou fausse → 401.** L'usage est compté par clé (`use_count`,
   `last_used_at`) : une clé qui traîne se voit.

## Temps 7 — L'autre pipeline : dbt, et ses tests qui bloquent (~6 min)

**Click-path** : Build → Systems → `Radio Watch` → Flow → nœud `Watchlist dbt`.

1. **24 192 lignes en entrée** (72 cellules × 14 jours × 24 h), **72 en sortie**. Un
   projet dbt-duckdb réel : `stg_cell_hourly` (staging) puis `mart_cell_risk` (mart).
2. **Le mart dit ce qu'il fait** : heure de pointe seulement (19h–23h — une cellule
   saturée à 3 h du matin n'est pas un problème client), et les 7 derniers jours contre
   les 7 précédents, parce qu'un niveau sans tendance ne dit pas à un ingénieur où aller.
3. **La watchlist telle qu'elle sort** — 9 `critique`, 8 `surveillé`, 55 `sain` :

   | Cellule | PRB % | Δ 7 j | Δ taux de coupure | Bande |
   |---|---|---|---|---|
   | `CAS-773-L54` | 92,84 | +0,05 | −0,039 | critique |
   | `AGA-132-N66` | 92,68 | 0,00 | +0,036 | critique |
   | `TNG-818-L59` | 92,67 | 0,00 | +0,004 | critique |
   | `OUJ-917-N09` | 90,91 | −0,02 | −0,008 | critique |
   | **`RBA-932-L41`** | 88,42 | **+21,32** | **+1,469** | critique |
   | **`AGA-270-L69`** | 86,65 | **+27,80** | **+1,380** | critique |
   | **`RBA-440-L31`** | 86,14 | **+27,56** | **+1,263** | critique |

4. **Le geste star, c'est la colonne delta.** Les six premières cellules sont saturées
   depuis des mois : l'ingénieur radio les connaît, elles sont déjà à son planning. Les
   trois en gras étaient **saines il y a quinze jours** (67, 59 et 59 % de PRB) et sont
   passées critiques dans la dernière semaine, avec un taux de coupure d'appel qui monte
   de plus d'un point. Ce sont les trois seules lignes de la table qui bougent : le
   quatrième plus gros mouvement est à +2,42. Un seuil sur le niveau les aurait mélangées
   aux six autres ; la tendance les isole.
5. **Et ça se lit dans les deux sens** : `CAS-831-N65` à **−20,64** et `RBA-142-L70` à
   **−17,43** — deux cellules qu'une montée en capacité a soulagées. Une colonne de
   tendance qui ne descendrait jamais ne serait pas crue.
6. **Les tests dbt, et pourquoi ils sont le sujet** : `unique` et `not_null` sur `cell_id`,
   `accepted_values` sur `risk_band`. Une cellule qui apparaîtrait deux fois dans une
   watchlist, ou une utilisation à 140 %, veut dire que le pipeline est faux — et le nœud
   **refuse de publier** plutôt que de passer ça à l'aval. C'est la différence entre un
   pipeline et un script.

---

## Pièges connus

1. **v2 déjà promue** : si une répétition précédente a promu v2, le temps 5 n'a plus de
   geste. Le seed **ne réattribue pas** le champion (c'est volontaire : il ne défait pas
   une promotion d'opérateur), donc il faut remettre v1 à la main avant la démo.
2. **Le premier `curl` paie le chargement** (~5 s pour désérialiser le modèle MLflow).
   Le répéter une fois avant de monter sur scène ; ou l'assumer et lire le `cached: false`
   à voix haute — c'est le temps 6 point 6.
3. **Deux réglages obligatoires** pour que les nœuds Polars et dbt s'exécutent :
   `RECIPE_EXECUTION_ENABLED=true` et, sans worker Celery, `WORKER_EAGER_MODE=true`.
   Sans eux le run se termine quand même, mais ces deux nœuds rapportent leur refus.
4. **Premier run dbt lent** : il construit un venv `dbt-duckdb` (13 s la première fois,
   345 Mo). Faire tourner Radio Watch une fois avant la démo.
5. **Deux versions de `base-clients-nettoyee`** dans la page Data (v1 du seed, v2 du Flow).
   C'est correct et c'est explicable : le seed prépare l'état, le Flow refait le travail
   pour de vrai. Ne pas la présenter comme un doublon accidentel.
6. **Régénérer les données change les chiffres** : tous ceux de ce runbook sont liés à
   `--seed 20260825`. Une autre graine donne un autre monde, cohérent mais différent.

## Preuves de répétition (25/08, local, base vierge)

| Vérification | Résultat |
|---|---|
| Seed rejoué sur base vide + object store vide | 7 datasets `ready`, 3 modèles, 2 systems actifs |
| `base-clients-nettoyee` | 6 903 lignes depuis 8 412, exact |
| Fit v1 / v2 / v3 | roc_auc 0,835206 / 0,859632 / 0,855853 |
| Champion après seed | v1, non réattribué |
| Run Churn Radar `84d79dd1…` | completed, 7 nœuds (clean 60 ms · features 6,8 s · train 15,6 s · score 4,4 s) |
| Run Radio Watch `d587a9f6…` | completed, 3 nœuds, dbt 72 lignes en 17,7 s |
| Skill publiée + clé mintée | `predict_churn_radar`, préfixe `agpk_cdukue9` |
| `POST /predict` avec la clé | 200, `served` v1, score 0,980159 |
| Cache pyfunc | appel 1 `cached:false load_ms:5268.4` · appel 2 `cached:true load_ms:0.0`, même prédiction |
| Promotion v2 → même clé, même URL | répond depuis v2, `cached:false` (empreinte invalidée) |
| Clé fausse / absente | 401 / 401 ; `use_count` incrémenté sur les appels valides |
| Watchlist radio | 9 critique / 8 surveillé / 55 sain ; 3 movers à +21…+28, 2 à −17…−21 |
| Aucune cellule-heure au plafond | 0 / 24 192 à 100,0 % de PRB |

## Déploiement — ce qu'il reste à faire

Rien de tout ceci n'est encore sur `omnirag-demo`. Le chemin est celui de
[`agentium-release-process.md`](../../agentium-release-process.md), et il **part de
`origin/demo/agentic`** : il n'y a pas de déploiement latéral d'une branche `cursor/…`.
Dans l'ordre, après la fusion de la PR :

1. **dump des deux moitiés** — `scripts/agentium-data-plane-dump.sh <sha12>` : à partir
   de la révision 096, un `pg_dump` seul n'est plus restaurable (les lignes de datasets
   et de modèles désignent des objets MinIO qui ne sont pas dans le dump). Le script
   prend les deux et vérifie que chaque artefact que le registre nomme est bien là ;
2. `migrate` — la tranche apporte `096_tabular_data_plane` puis `097_ml_training_plane`,
   qui s'enchaînent sur le `095_python_recipes` de la VM ;
3. **il n'y a pas de base `mlflow` à créer** — MLflow est ici un *format* d'artefact, pas
   un service : le registre est la table `ml_models`. Les prérequis réels (les deux
   réglages `RECIPE_EXECUTION_ENABLED` / `WORKER_EAGER_MODE`, la place disque des venvs,
   la restauration) sont dans
   [`agentium-data-plane-provisioning.md`](../../ops/agentium-data-plane-provisioning.md) ;
4. `storage-check` puis `up` au tag `<sha12>` ;
5. canaris carakai + e2e, puis rejouer ce runbook sur la VM et remplacer la section
   « preuves de répétition » par les identifiants de la VM ;
6. journal de déploiement dans `docs/ops/agentium-safe-vm-deployment.md`.
