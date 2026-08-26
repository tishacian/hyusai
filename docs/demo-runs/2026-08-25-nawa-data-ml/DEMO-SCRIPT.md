# Démo NAWA — Data / ML : de l'export sale au modèle servi (7 temps)

Répétée en local le 25/08/2026 (UTC) sur base Postgres vierge + object store local,
seed rejoué de zéro : `backend/scripts/seed_nawa_data_demo.py`. **Déployée et rejouée sur
la VM `omnirag-demo` le 26/08/2026** — les identifiants ci-dessous sont ceux de la VM
(voir [§ Déploiement](#déploiement--ce-qui-a-été-fait)).

Le fil : une base d'abonnés télécom arrive comme les exports arrivent vraiment — doublons,
lignes suspendues, régions écrites de quatre façons, une colonne revenu trouée et un `-1`
qui veut dire « inconnu ». En sept temps elle devient un modèle de churn servi derrière une
clé API, et un deuxième pipeline dbt sort une watchlist radio. **Aucun LLM dans le chemin de
données** : SQL, Polars, scikit-learn, dbt.

Ce runbook est le script présentateur. Les chiffres qu'il cite ne sont pas illustratifs :
ils viennent du seed rejoué le 25/08 et sont reproductibles par graine
(`--seed 20260825`, la valeur par défaut).

## Identifiants (VM `omnirag-demo`, état du 26/08 03 h UTC)

Les UUID changent à chaque seed — c'est le seul contenu de ce runbook qui ne soit
pas reproductible par graine. Ceux-ci sont **ceux de la VM** ; rejouer le seed
ailleurs produit d'autres identifiants et les **mêmes** chiffres.

| Objet | Valeur |
|---|---|
| URL | `https://agentium.papai.ai` — révision servie `8fd380555e5b` |
| Workspace | `nawa` — id `b337fdbf-2689-436e-a287-2fe903ca47cf` |
| System 1 | `Churn Radar` — id `5e0937e3-652c-4eaf-addc-b25ec68e7ba6`, actif |
| System 2 | `Radio Watch` — id `00548e30-e8ea-4bab-a138-31b308af487e`, actif |
| Modèle servi | `Churn Radar` **v1** (`linear`) — id `1b570e6a-0214-4d19-8120-29caa88ebd0e` |
| Challenger | **v2** (`gradient_boosting`) — id `2565e774-1a31-4b2f-85ea-5df3facad2be` ; v3 `8bc2c26c-870c-4d73-913f-52c94ba6b42c` |
| Skill publiée | `ws.b337fdbf-2689-436e-a287-2fe903ca47cf.predict_churn_radar` |
| Clé API | préfixe `agpk_ZsTP-0r` (le secret complet ne s'affiche qu'à la création) |
| Run churn | `4a80aad6-4095-4587-b11b-6c1c8ed99142` — completed, 7 nœuds |
| Run radio | `82503a1e-0c5d-46cc-9017-9e7d54220a89` — completed, 3 nœuds. Le run antérieur `207a77b7…` garde l'échec dbt d'avant le correctif d'arènes glibc (voir le journal) : c'est de l'historique, pas l'état courant |
| Registre MLflow | database `mlflow`, modèle enregistré `b337fdbf.churn-radar`, alias `champion` → v1, `challenger` → v2 |

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

- **8 412 → 6 903.** Exact, pas échantillonné, et dans cet ordre : 412 doublons
  d'abord (reste 8 000), puis sur ce qui reste 640 lignes suspendues + 297 ARPU vides
  + 160 ARPU à `-1`, trois blocs disjoints. 8 000 − 1 097 = 6 903.
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
4. `/systems/5e0937e3-652c-4eaf-addc-b25ec68e7ba6/flow` (Churn Radar) et
   `/systems/00548e30-e8ea-4bab-a138-31b308af487e/flow` (Radio Watch) s'ouvrent avec les
   badges déjà posés sur les nœuds (un run derrière chacun).
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
   - `line_status` : 677 lignes `suspended` — des abonnés qui ne peuvent pas résilier
     et qui n'ont donc rien à apprendre à un modèle de churn volontaire.
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
4. **Le badge du nœud : `8 412 → 6 903 lignes`.** Faire l'addition en direct, et
   c'est là que l'ordre des opérations devient un argument : le brut contient 677
   lignes suspendues, 310 ARPU vides et 170 sentinelles, mais le dédoublonnage passe
   **d'abord** et emporte 412 lignes périmées — dont une partie était justement
   suspendue ou trouée. Sur les 8 000 qui restent : 640 + 297 + 160 = 1 097, et
   8 000 − 1 097 = **6 903**. Exact, pas arrondi. Filtrer avant de dédoublonner
   donnerait un autre nombre, et le mauvais.

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
   demande et mis en cache par empreinte de dépendances — celui-ci, `polars==1.44.0`,
   a coûté 5,2 s et 231 Mo une seule fois, et rien aux runs suivants. Ce n'est pas
   `exec()` dans le worker.

## Temps 4 — L'entraînement et la model card (~6 min)

**Click-path** : même Flow, nœud `3 · Entraîner` → puis Build → Models.

1. **Le nœud d'entraînement** : `ml_train_sklearn_v1`. Cible `churn`, 29 colonnes,
   estimateur et découpe déclarés dans la configuration du graphe. Le badge du run
   du 25/08 lit `6 903 lignes · roc_auc 0.855853` en 15,7 s.
2. **La page Models, trois versions de la même lignée.** Ouvrir **v2** — la model card
   est faite pour être projetée : métriques, matrice de confusion, courbes ROC et
   précision/rappel, importances, signature d'entrée, lignée vers le dataset exact.
3. **Où vivent les artefacts** : format MLflow sur l'object store (MinIO en VM), et un
   **vrai Model Registry MLflow** dans une database `mlflow` du Postgres existant — pas
   de serveur MLflow à opérer, le client écrit directement dans le store SQL. Un modèle
   est un objet gouverné, pas un `.pkl` dans un bucket.
4. **Et la phrase « pas de lock-in » est vérifiable en séance**, avec un client MLflow
   standard qui ne sait rien d'Agentium — c'est le moment pour les sceptiques de la salle :

   ```python
   from mlflow.tracking import MlflowClient
   c = MlflowClient(tracking_uri="postgresql://…/mlflow", registry_uri="postgresql://…/mlflow")
   v = c.get_model_version_by_alias("1f949967.churn-radar", "champion")   # → v1
   import mlflow.pyfunc; mlflow.pyfunc.load_model(v.source).predict(rows)  # les octets sur MinIO
   ```

   Mesuré le 25/08 : `champion` → v1, signature à 20 colonnes, `roc_auc` du run
   **0,835206** — le chiffre de la carte, lu depuis le registre.
5. **L'évaluation elle-même est conservée**, pas seulement son résumé : la carte affiche
   « Évaluation conservée — 173 ko, rapport skore 0.25.0, rechargeable ». Le run porte son
   emplacement (tag `agentium.skore_report_state`), et `EstimatorReport.from_dict` la
   rouvre avec ses **1 726 lignes de test** et ses prédictions en cache. Conséquence
   concrète : une métrique que personne n'avait demandée au moment du fit se calcule
   après coup **sur les lignes dont la carte parle** (`precision` = 0,7049 sur v1), au
   lieu de se rejouer sur une découpe qui ne serait plus la même.
6. **Le détail qui fait tiquer les data scientists dans la salle** : `nps` a 1 144 trous
   dans la base nettoyée. Les arbres boostés les routent dans une branche et **lisent**
   l'absence de réponse ; la régression logistique ne sait pas faire — le harness lui
   ajoute donc un `SimpleImputer(strategy="median")`, décidé par estimateur d'après le
   tag `allow_nan` de scikit-learn. Le trou est comblé pour le modèle linéaire et exploité
   par le modèle à arbres. C'est exactement là que passe l'écart du temps 5.

## Temps 5 — La promotion, avec un delta réel (~5 min)

**Click-path** : Build → Models → comparer v1 / v2 / v3 → **Promouvoir** v2.

1. **Le classement, tel que chaque carte l'a enregistré** — même base de 6 903 lignes,
   même graine, et pour v1/v2 la même découpe (v3 s'entraîne sur les features dérivées) :

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
4. **« Comparer sur les mêmes lignes » → Réévaluer les deux versions**, dans l'onglet
   Comparaison, et c'est le point qui distingue une plateforme d'un tableau de bord.
   Les tuiles à delta soustraient
   deux résultats *enregistrés* ; là, les deux pipelines sont rescorés sur **une seule**
   découpe et la table jointe vient de `skore.ComparisonReport`. Mesuré le 25/08, v1
   contre v2 sur les mêmes 1 726 lignes :

   | Métrique | v1 `linear` | v2 `gradient_boosting` |
   |---|---|---|
   | ROC AUC | 0,835206 | **0,859632** |
   | Exactitude | 0,836037 | **0,851101** |
   | Précision | 0,704918 | **0,758197** |
   | Rappel | 0,449086 | **0,483029** |
   | Log loss | 0,391460 | **0,371024** |
   | Brier | 0,122305 | **0,110612** |

   Les deux colonnes retombent **exactement** sur ce que chaque carte annonce, ce qui est
   la preuve que la découpe a bien été reconstruite. Et v2 gagne sur les six, y compris
   les deux métriques de calibration — le score n'est pas seulement mieux classé, il est
   mieux *croyable*, ce qui est ce qui compte quand il s'affiche en jauge au temps 6.
5. **Comparer v2 et v3 affiche un avertissement**, et il faut le lire à voix haute : v3 a
   été entraîné sur `base-clients-features`, pas sur `base-clients-nettoyee`. La
   comparaison se fait donc sur le dataset du plus récent des deux et signale que l'autre
   a été ajusté ailleurs (`0,859632` contre `0,855853` sur les mêmes lignes). Refuser
   aurait rendu impossible la seule comparaison intéressante ; répondre sans le dire
   aurait été pire.
6. **Le registre nomme aussi la prétendante**, et c'est ce qui rend l'histoire
   champion/challenger lisible de l'extérieur. La puce jaune « Prétendante » sur la carte
   est le même fait que l'alias `challenger` : **la meilleure version qui ne sert pas**,
   pas la plus récente. Avant la promotion, `champion` → v1 et `challenger` → v2 — donc
   v2, pas v3, même si v3 est le dernier entraînement. Le dire à voix haute : un registre
   qui nommerait « le dernier » nommerait souvent le pire, et c'est précisément pour ça
   que la promotion reste un geste humain.

   ```python
   c.get_model_version_by_alias("1f949967.churn-radar", "champion")    # → v1, roc_auc 0,835206
   c.get_model_version_by_alias("1f949967.churn-radar", "challenger")  # → v2, roc_auc 0,859632
   ```

   Un A/B entre le sortant et son concurrent ne demande donc **rien** de nos tables : deux
   alias suffisent.
7. **Promouvoir v2**, et rester sur la page : la puce « sert » se déplace, l'alias
   `champion` du registre MLflow suit (vérifié : `1` → `2`), **et les deux alias
   s'échangent** — `challenger` retombe sur v1, la version qui vient d'être déposée, au
   lieu de rester sur la gagnante. La provenance de la skill publiée suit toute seule
   (temps 6).

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
   | Prépayé, 4 mois, 3 tickets, 7 appels coupés, questionnaire sans réponse | **0,989584** |
   | Postpayé 2 ans, 74 mois, fibre, 4 lignes, 0 ticket, NPS 9 | **0,000729** |

   Et les contributions de la première ligne se lisent dans l'ordre où on les
   raconterait : `tenure_months` 4 contre 49 typiques (+0,0856), `support_tickets` 3
   contre 1 (+0,0233), la promo en cours (+0,0094).

4. **Publier comme Skill** : le modèle devient appelable par un agent. Aller sur la page
   Skills montrer la **puce de provenance** — elle dit « répond depuis Churn Radar v1 »,
   et elle est *dérivée*, pas figée à la publication : après la promotion du temps 5 elle
   lit v2 sans que personne y touche.
5. **La clé API, et le cURL** :

   ```bash
   curl -X POST "$AGENTIUM/api/v1/ml-models/d55698ce-0c29-4813-8b7f-0f60a207686b/predict" \
     -H "X-API-Key: agpk_xdT-Y8q…" -H 'Content-Type: application/json' \
     -d '{"inputs":[{"region":"casablanca-settat","plan":"prepaid","contract":"monthly",
          "tenure_months":4,"arpu_mad":38.5,"support_tickets":3,"dropped_calls":7,
          "nps":null, …}]}'
   ```

   Les 20 colonnes de la signature sont **obligatoires et closes** : en oublier une, ou en
   inventer une, renvoie `ML_PREDICT_FIELD_UNKNOWN` avec la liste des champs fautifs. Un
   contrat qui accepterait n'importe quoi ne serait pas un contrat.

   La convention de charge utile est celle de `mlflow models serve` (`{"inputs": […]}`) :
   un client MLflow existant marche sans adaptateur.

6. **Trois choses à faire remarquer dans la réponse** :
   - un bloc `served` — quelle version a répondu, quel estimateur, quelle métrique. Une
     prédiction sans son émetteur n'est pas auditable ;
   - `cached: false, load_ms: 5206.7` au premier appel du processus,
     `cached: true, load_ms: 0.0` au second, **même prédiction**. `load_ms` est ce que
     *cet* appel a payé pour avoir le pipeline en mémoire — le cache est une
     optimisation, pas un second chemin de code ;
   - après la promotion du temps 5, **la même clé et la même URL répondent depuis v2**
     (mesuré : `served.version` 2, `gradient_boosting`, score 0,999282,
     `cached: false, load_ms: 326.9` — l'empreinte a changé, l'ancien pipeline est
     évincé). Promouvoir, c'est déplacer ce que la production sert.
7. **Clé absente ou fausse → 401.** L'usage est compté par clé (`use_count`,
   `last_used_at`) : une clé qui traîne se voit.

## Temps 7 — L'autre pipeline : dbt, et ses tests qui bloquent (~6 min)

**Click-path** : Build → Systems → `Radio Watch` → Flow → nœud `Watchlist dbt`.

1. **24 192 lignes en entrée** (72 cellules × 14 jours × 24 h), **72 en sortie**. Un
   projet dbt-duckdb réel : `stg_cell_hourly` (staging) puis `mart_cell_risk` (mart).
2. **Le mart dit ce qu'il fait** : heure de pointe seulement (19h–23h — une cellule
   saturée à 3 h du matin n'est pas un problème client), et les 7 derniers jours contre
   les 7 précédents, parce qu'un niveau sans tendance ne dit pas à un ingénieur où aller.
3. **La bande `critique` en entier** — 9 cellules sur 72 (plus 8 `surveillé`, 55 `sain`) :

   | Cellule | PRB % | Δ 7 j | Coupure % | Δ coupure |
   |---|---|---|---|---|
   | `CAS-773-L54` | 92,84 | +0,05 | 2,487 | −0,039 |
   | `AGA-132-N66` | 92,68 | 0,00 | 2,470 | +0,036 |
   | `TNG-818-L59` | 92,67 | 0,00 | 2,451 | +0,004 |
   | `AGA-528-L36` | 91,42 | −0,33 | 2,292 | 0,000 |
   | `FEZ-613-L48` | 91,26 | +0,34 | 2,249 | +0,039 |
   | `OUJ-917-N09` | 90,91 | −0,02 | 2,240 | −0,008 |
   | **`RBA-932-L41`** | 88,42 | **+21,32** | 1,893 | **+1,469** |
   | **`AGA-270-L69`** | 86,65 | **+27,80** | 1,689 | **+1,380** |
   | **`RBA-440-L31`** | 86,14 | **+27,56** | 1,636 | **+1,263** |

4. **Le geste star, c'est la colonne delta.** Les six premières lignes sont saturées
   depuis des mois — deltas entre −0,33 et +0,34, c'est-à-dire immobiles : l'ingénieur
   radio les connaît, elles sont déjà à son planning et elles n'apprennent rien à
   personne. Les trois en gras étaient **saines il y a quinze jours** (67, 59 et 59 %
   de PRB) et sont passées critiques dans la dernière semaine, avec un taux de coupure
   d'appel qui monte de plus d'un point. Ce sont les trois seules lignes de toute la
   table qui bougent vraiment : le quatrième plus gros mouvement du fichier est à
   **+2,42**. Un seuil sur le niveau les aurait noyées dans les six autres ; la
   tendance les isole.
5. **Et ça se lit dans les deux sens** : `CAS-831-N65` à **−20,64** (50,86 % de PRB) et
   `RBA-142-L70` à **−17,43** (45,09 %) — deux cellules qu'une montée en capacité a
   soulagées, et le troisième mouvement négatif n'est qu'à −1,34. Une colonne de
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
4. **Premier run dbt lent** : il construit un venv `dbt-duckdb`, mesuré à 13,2 s pour
   329 Mo, mis en cache ensuite par empreinte de dépendances. Faire tourner Radio Watch
   une fois avant la démo.
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
| Fit v1 / v2 / v3 | roc_auc 0,835206 / 0,859632 / 0,855853 — **identiques à la répétition précédente**, autre base, autres UUID |
| Champion après seed | v1, non réattribué |
| Run Churn Radar `436987e3…` | completed, 7 nœuds (clean 69 ms · features 6,8 s · train 15,7 s · score 3,7 s · brief 1 ms) |
| Run Radio Watch `57b61f49…` | completed, 3 nœuds, dbt 72 lignes en 17,7 s |
| Venvs construits une fois | polars 5,2 s / 243 Mo · dbt-duckdb 13,2 s / 345 Mo, mis en cache par empreinte |
| Registre MLflow | database `mlflow` créée à la volée, 3 versions de `1f949967.churn-radar`, `source` → l'object store, alias `champion` → v1, `challenger` → v2 |
| Client MLflow **étranger** | `get_model_version_by_alias(…, "champion")` → v1, `pyfunc.load_model(v.source)` charge, signature 20 colonnes, `roc_auc` du run 0,835206 |
| Alias `challenger`, même client | → v2 (`roc_auc` 0,859632), `source` distincte de celle du champion — **la meilleure perdante, pas la plus récente** (v3 est le dernier fit) |
| Évaluation conservée | 3 états skore (173 / 522 / 566 ko) ; `from_dict` rouvre v1 avec ses 1 726 lignes de test et retrouve 0,835206 |
| Comparaison sur les mêmes lignes | v2 > v1 sur les 6 métriques ; les deux colonnes retombent sur les chiffres des cartes |
| Comparaison v2/v3 (datasets différents) | répond et signale `TRAINED_ON_ANOTHER_DATASET` sur v2 |
| Skill publiée + clé mintée | `predict_churn_radar`, préfixe `agpk_xdT-Y8q` |
| `POST /predict` avec la clé (HTTP réel, uvicorn) | 200, `served` v1, 0,989584 sur la ligne à risque et 0,000729 sur la ligne fidèle |
| Cache pyfunc | appel 1 `cached:false load_ms:5206.7` · appel 2 `cached:true load_ms:0.0`, prédiction identique |
| Colonne inventée dans la charge utile | 422 `ML_PREDICT_FIELD_UNKNOWN` avec la liste des champs fautifs |
| Promotion v2 → même clé, même URL | répond depuis v2 (0,999282), `cached:false load_ms:326.9` ; alias registre `1` → `2` |
| Clé fausse / absente | 401 / 401 ; `use_count` = 4 après les appels valides |
| Watchlist radio | 9 critique / 8 surveillé / 55 sain |
| Aucune cellule-heure au plafond | 0 / 24 192 à 100,0 % de PRB |

## Déploiement — ce qui a été fait

La tranche est sur `omnirag-demo` depuis le 26/08. Le détail (SHA, dump, migrations,
observables, canaris) est dans le journal :
[`agentium-safe-vm-deployment.md`](../../ops/agentium-safe-vm-deployment.md), itération
du 26/08. Ce qui compte pour un présentateur :

- révision servie **`8fd380555e5b`**, `revision_verified: true` ;
- `096_tabular_data_plane` puis `097_ml_training_plane` appliquées, `alembic current`
  = `097_ml_training_plane` ;
- database `mlflow` en place sur `agentium-pg`, propriétaire `agentium`. Aucun serveur
  MLflow n'est opéré : le client écrit dedans directement, aucun port, aucun conteneur.
  MLflow crée son propre schéma à la première connexion — ce n'est pas une révision
  Alembic, et `MLFLOW_TRACKING_URI` ne doit **pas** être posé dans l'environnement
  compose, le client étant configuré en code ;
- les venvs managés (`polars`, `dbt-duckdb`) sont construits et en cache sous
  `/srv/agentium-data/recipe_envs` : le premier run de la démo ne paie pas de build ;
- pour restaurer ou rejouer ailleurs : `scripts/agentium-data-plane-dump.sh <sha12>`
  prend les trois parties (database `agentium`, database `mlflow`, préfixes d'objets)
  et vérifie que chaque artefact que le registre nomme est dans la fenêtre. Depuis la
  révision 096 un `pg_dump` seul n'est plus restaurable : les lignes de datasets et de
  modèles désignent des objets MinIO qui ne sont pas dans le dump. Les autres prérequis
  sont dans
  [`agentium-data-plane-provisioning.md`](../../ops/agentium-data-plane-provisioning.md).

### Deux défauts que seule la VM a montrés

Ils sont ici parce qu'ils disent où regarder si la démo se comporte autrement qu'écrit.

1. **Le nœud dbt s'arrêtait sur la VM et nulle part ailleurs.** `RLIMIT_AS` compte
   l'espace d'adressage *réservé*, et glibc réserve une arène malloc de 64 Mio par thread
   jusqu'à huit par cœur : sur les 16 cœurs de la VM les arènes seules consomment le
   budget de 3 Gio, et le premier thread que dbt démarre meurt dans l'allocateur
   (`cannot allocate memory for thread-local data: ABORT`) avant que le SQL du projet ne
   tourne. `MALLOC_ARENA_MAX` est désormais épinglé pour tout enfant supervisé.
2. **Le client MLflow « étranger » ne chargeait pas depuis MinIO.** La `source` d'une
   version y est une URI `s3://`, et le dépôt d'artefacts S3 de mlflow importe `boto3`
   par son nom — `botocore`, que `s3fs` apporte déjà pour nos propres lectures, ne suffit
   pas. En local l'object store donne des `file://` : l'étape censée prouver la
   portabilité était la seule jamais exercée là où elle compte.
