# Carte de présentation — démo Data/ML Nawa

Fiche à garder ouverte pendant la démo. Le raisonnement complet, beat par beat, est dans
[`DEMO-SCRIPT.md`](DEMO-SCRIPT.md) ; ceci en est le déroulé opérationnel : où cliquer, quel
chiffre dire, quelle phrase porte l'argument.

Tout ce qui s'affiche à l'écran est **en anglais** — le workspace déclare
`presentation.locale = en`, donc le chrome s'ouvre en anglais sans toucher au sélecteur. Les
libellés cités ici le sont verbatim.

**État vérifié le 27/08 à 05:32 UTC** sur `omnirag-demo`, révision servie `29aa898159b5` :
les 13 conteneurs sont up, le vérificateur de plan ne relève aucune dérive, et les sept
surfaces de la démo ont de quoi s'afficher. Preuves :
`demo-plane-verifier.log`, `demo-surface-readiness.log`.

---

## Pré-vol — 5 minutes, dans cet ordre

1. **Minter une clé API.** Celle du seed (`agpk_Se_tOeb`) a `use_count = 0` et son secret
   n'est montré **qu'une fois**, à la création : il n'est plus récupérable. Sans clé
   fraîche, le beat 6 n'a pas de `curl`. Models → `Churn Radar` → onglet Playground →
   *Mint an API key*, copier le secret immédiatement.
2. **Rejouer le `curl` une fois**, hors scène. Le premier appel paie le chargement du
   modèle MLflow (~5 s) : `cached: false`. Le second répond en dizaines de ms. On peut
   aussi l'assumer et lire le `load_ms` à voix haute — c'est le point 6 du beat 6 — mais
   c'est un choix, pas une surprise.
3. **Vérifier que v1 sert.** Models → `Churn Radar` : le chip *serves* doit être sur **v1**.
   S'il est sur v2, la promotion du beat 5 n'a plus rien à montrer, et le seed ne remet
   jamais le champion en place (il ne défait pas la promotion d'un opérateur) : il faut
   repromouvoir v1 à la main.
4. **Ouvrir les deux Flows en onglets**, badges déjà posés (un run derrière chacun) :
   Churn Radar et Radio Watch. Zoom navigateur à 100 %.

Si un doute subsiste sur l'état du plan, la commande qui répond en 30 s, sur la VM :

```bash
sudo docker exec agentium-backend sh -lc "cd /app && python -m scripts.verify_nawa_data_ml_plane"
```

Elle re-mesure chaque chiffre de cette fiche et dit `ok` ou `DRIFT`, ligne par ligne.

## Identifiants — état du 27/08

| Objet | Valeur |
|---|---|
| URL | `https://agentium.papai.ai` — révision `29aa898159b5` |
| Workspace | `nawa` — `b337fdbf-2689-436e-a287-2fe903ca47cf` |
| Flow Churn Radar | `/systems/5e0937e3-652c-4eaf-addc-b25ec68e7ba6/flow` — 7 nœuds |
| Flow Radio Watch | `/systems/00548e30-e8ea-4bab-a138-31b308af487e/flow` — 3 nœuds |
| Business page | `/work/retention-board` — publiée, déployée `live` |
| Modèle v1 `linear` | `ebf81740-cb36-4c7e-a890-c0e52951afd5` — **champion**, roc_auc 0.836617 |
| Modèle v2 `gradient_boosting` | `aa2a51db-24c5-4de0-8013-b07dc33a0db7` — roc_auc 0.864133 |
| Modèle v3 `gradient_boosting` | `ebf6238c-fa5b-4e7c-a50a-4d8bc61beb11` — roc_auc 0.853761 |
| Skill publié | `ws.b337fdbf-2689-436e-a287-2fe903ca47cf.predict_churn_radar` |
| Registre MLflow | base `mlflow`, modèle `b337fdbf.churn-radar`, `champion` → v1, `challenger` → v2 |

Les sept tables visibles sur la page Data, versions actuelles :

| Table | Version | Lignes | Colonnes |
|---|---|---|---|
| `Subscriber base — raw export` | v4 | 8 412 | 24 |
| `Radio cell KPIs` | v4 | 24 192 | 12 |
| `Subscriber base — cleaned` | v6 **et** v7 | 6 903 | 22 |
| `Subscriber base — features` | v3 | 6 903 | 31 |
| `Subscriber base — scored` | v3 | 6 903 | 34 |
| `Cells at risk — 7 days` | v4 | 72 | 13 |

Le numéro de version compte les réécritures du slug, il ne fait pas partie de l'histoire.
`cleaned` apparaît deux fois parce que le seed la construit une fois et que le Flow la
reconstruit devant la salle — à présenter comme tel, jamais comme un doublon accidentel.

## Les six chiffres à savoir par cœur

- **8 412 → 6 903**, exact et dans cet ordre : 412 doublons d'abord (8 000 restent), puis
  sur ce qui reste 640 lignes suspendues + 297 ARPU vides + 160 ARPU à `-1`. 8 000 − 1 097.
- **0.836617 / 0.864133 / 0.853761** — v1 `linear`, v2 `gradient_boosting`, v3 sur les 29
  colonnes dérivées. Promouvoir v1 → v2 vaut **+0.027516** de ROC AUC.
- **v3 ne gagne pas**, et on le laisse comme ça. Un registre sert justement à dire qu'un
  challenger a perdu.
- **Churn de la base nettoyée : 22.16 %.** Le modèle en signale 1 000 sur 6 903 ; le
  décile le plus risqué churne à **77.4 %**, soit **×3.5** le taux de base.
- **Watchlist radio : 9 `critical`, 8 `watch`, 55 `healthy`** sur 72 cellules.
- **Trois cellules bougent vraiment** (+21.32, +27.80, +27.56 points de PRB) ; le quatrième
  mouvement du fichier est à **+2.42**. C'est tout l'argument de la colonne de tendance.

---

## Le déroulé — 7 beats, ~37 min

### Beat 1 — L'export arrive sale (4 min)

Build → Data → `Subscriber base — raw export`.

Le profil de colonnes s'affiche sans requête. Montrer la saleté colonne par colonne :
`region` **28 orthographes pour 7 régions**, `plan` 6 pour 3 offres, `arpu_mad` **310 vides
et 170 à `-1`**, `line_status` 677 suspendus, `msisdn` **412 numéros en double**, `nps`
1 383 vides.

> « Le `-1` est le piège : un "inconnu" que l'export écrit comme un nombre. Un modèle
> entraîné dessus apprend que −1 MAD prédit le churn. »

Et le point qui prépare le beat 5 : **`nps` ne sera pas nettoyé.** Un abonné qui a cessé de
répondre au sondage est un signal, pas un défaut.

### Beat 2 — Le SQL qui nettoie, et son badge (5 min)

Flow Churn Radar → nœud `SQL cleanup`.

L'inspecteur est un atelier SQL duckdb avec autocomplétion sur le schéma amont (taper `arp`
propose `arpu_mad`). Lire la requête : dédoublonnage par `ROW_NUMBER() … ORDER BY
snapshot_date DESC`, `lower(trim(…))` sur région et plan, `line_status = 'active'`,
`arpu_mad IS NOT NULL AND >= 0`.

Le `ORDER BY msisdn` final a l'air décoratif et ne l'est pas : duckdb est parallèle, sans
lui l'ordre des lignes change d'un run à l'autre, le split train/test est positionnel, et
les métriques annoncées cessent d'être celles de la répétition.

**Faire l'arithmétique en direct** sur le badge `8 412 → 6 903 rows`. Si on demande si
l'ordre des filtres compte : **ici non**, un ré-export périmé porte les mêmes défauts que
la ligne qu'il copie. Le dire plutôt que bluffer.

> « Une transformation gouvernée et versionnée, avec son lignage. Pas un notebook sur le
> portable de quelqu'un. »

### Beat 3 — Les features, en Polars (4 min)

Même Flow → nœud `Polars features`. **22 → 31 colonnes**, neuf dérivées.

> « Ce qui prédit un départ n'est pas le revenu ni le nombre de tickets, mais le revenu
> **par mois d'ancienneté** et la friction **par dirham facturé**. Un arbre approxime mal
> un ratio avec des splits orthogonaux. »

`nps_answered` : la non-réponse devient une colonne. Et le harnais — le Python de l'auteur
tourne dans un venv isolé, construit à la demande et mis en cache par empreinte de
dépendances : `polars==1.44.0`, 5.2 s et 231 MB une fois, rien ensuite. **Ce n'est pas un
`exec()` dans le worker.**

### Beat 4 — L'entraînement et la fiche modèle (6 min)

Même Flow → nœud `Churn training`, puis Build → Models → ouvrir **v2**.

La fiche est faite pour être projetée : métriques, matrice de confusion, courbes ROC et
précision/rappel, importances, signature d'entrée, lignage jusqu'au dataset exact.

Où vivent les artefacts : format MLflow sur l'object store, et un **vrai Model Registry
MLflow** dans une base `mlflow` du Postgres existant. **Aucun serveur MLflow à exploiter**,
le client écrit directement dans le store SQL.

C'est le moment des sceptiques — la phrase « pas de lock-in » est vérifiable dans la salle
avec un client MLflow standard qui ne connaît rien à Agentium :

```python
from mlflow.tracking import MlflowClient
c = MlflowClient(tracking_uri="postgresql://…/mlflow", registry_uri="postgresql://…/mlflow")
v = c.get_model_version_by_alias("b337fdbf.churn-radar", "champion")   # → v1
import mlflow.pyfunc; mlflow.pyfunc.load_model(v.source).predict(rows)  # les octets sur MinIO
```

Mesuré ce matin : `champion` → v1, sept artefacts tirés de MinIO, signature à 20 colonnes,
`roc_auc` **0.836617** — le chiffre de la fiche, lu depuis le registre.

Le détail qui fait redresser la tête aux data scientists : `nps` a 1 144 trous dans la base
nettoyée. Les arbres boostés les routent dans une branche et **lisent** la non-réponse ; la
régression logistique ne peut pas, donc le harnais lui ajoute un
`SimpleImputer(strategy="median")`, décidé par estimateur d'après le tag `allow_nan` de
scikit-learn. Le trou est bouché pour le modèle linéaire et exploité par l'arbre. **C'est
exactement de là que vient l'écart du beat 5.**

### Beat 5 — La promotion, avec un delta réel (5 min)

Build → Models → comparer v1 / v2 / v3 → **Promote v2**.

| Version | Estimateur | Colonnes | ROC AUC |
|---|---|---|---|
| v1 | `linear` | 20 | **0.836617** ← sert avant la démo |
| v2 | `gradient_boosting` | 20 | **0.864133** |
| v3 | `gradient_boosting` | 29 (+ dérivées) | 0.853761 |

> « Un ticket la première année est une lettre de démission ; le même ticket sur une ligne
> de huit ans est un appel au support. Une régression logistique ne peut pas représenter un
> produit de deux variables. La baseline n'a pas été handicapée — le monde n'est pas
> additif. »

Puis **« comparer sur les mêmes lignes »** : onglet Comparison → *Re-evaluate*. C'est le
point qui sépare une plateforme d'un tableau de bord — les deux pipelines sont re-scorés sur
**un** split et la table jointe vient de `skore.ComparisonReport`. v2 gagne sur les six
métriques, calibration incluse, et les deux colonnes retombent **exactement** sur ce
qu'annoncent les fiches : c'est la preuve que le split a bien été reconstruit.

Comparer v2 et v3 lève un avertissement `TRAINED_ON_ANOTHER_DATASET` — le lire à voix
haute. Refuser aurait rendu impossible la seule comparaison intéressante ; répondre sans le
dire aurait été pire.

Le chip jaune *Contender* est le même fait que l'alias `challenger` : **la meilleure version
qui ne sert pas**, pas la plus récente. Avant promotion, `champion` → v1 et `challenger` →
v2 — donc v2, et pas v3 qui est le dernier fit.

> « Un registre qui nommerait "le dernier" nommerait souvent le pire. C'est précisément
> pour ça que la promotion reste un acte humain. »

**Promouvoir v2** et rester sur la page : le chip *serves* se déplace, l'alias `champion`
suit dans MLflow, et les deux alias s'échangent — `challenger` retombe sur v1, la version
qu'on vient de rétrograder.

### Beat 6 — Le service : Playground, skill, clé API (7 min)

Models → `Churn Radar` → onglet Playground.

Le formulaire s'ouvre **pré-rempli** avec la ligne typique du jeu d'entraînement (médiane
des numériques, modalité la plus fréquente des catégorielles). Personne ne démontre un
modèle en tapant quarante champs.

Changer une chose et regarder : `support_tickets` de 0 à 3, vider `nps`. Le score monte, le
cadran suit, et les **contributions par ligne** disent quelles colonnes ont poussé.

Deux abonnés pour le contraste : prépayé 4 mois / 3 tickets / 7 appels coupés / sondage sans
réponse → score **haut** ; postpayé 2 ans / 74 mois / fibre / 4 lignes / 0 ticket / NPS 9 →
**quasi nul**.

Si la salle demande « puis-je essayer le challenger avant de le promouvoir ? » : ouvrir **v3**
depuis l'onglet Versions et cliquer Predict. Le formulaire est le contrat de v3 —
**vingt-neuf colonnes contre vingt** — et la ligne sous le bouton indique `answered by v3`.
La fiche nomme sa propre version. Vérifié ce matin sur les trois versions.

Puis **Publish as Skill** → page Skills → le **chip de provenance** dit « answers from Churn
Radar v2 » : il est *dérivé*, pas figé à la publication, donc il a suivi la promotion du
beat 5 sans que personne y touche.

Enfin la clé et le `curl` (payload à la convention `mlflow models serve`, donc un client
MLflow existant marche sans adaptateur) :

```bash
curl -X POST "https://agentium.papai.ai/api/v1/ml-models/aa2a51db-24c5-4de0-8013-b07dc33a0db7/predict" \
  -H "X-API-Key: agpk_…" -H 'Content-Type: application/json' \
  -d '{"inputs":[{"region":"casablanca-settat","plan":"prepaid","contract":"monthly",
       "tenure_months":4,"arpu_mad":38.5,"support_tickets":3,"dropped_calls":7,
       "nps":null, …}]}'
```

*(l'id ci-dessus est celui de v2 ; si la promotion n'a pas eu lieu, prendre v1
`ebf81740-cb36-4c7e-a890-c0e52951afd5`.)*

Trois choses à pointer dans la réponse : le bloc `served` (quelle version a répondu — une
prédiction sans son émetteur n'est pas auditable) ; `cached: false` avec un `load_ms` de
plusieurs secondes au premier appel puis `cached: true, load_ms: 0.0` au second, **même
prédiction** ; et le fait que la même clé et la même URL répondent maintenant depuis v2.

Oublier une colonne ou en inventer une → `ML_PREDICT_FIELD_UNKNOWN` avec les noms fautifs.
Clé absente ou fausse → 401, et l'usage est compté par clé.

### Beat 7 — L'autre pipeline : dbt et ses tests bloquants (6 min)

Build → Systems → `Radio Watch` → Flow → nœud `dbt — cells at risk`.

**24 192 lignes en entrée** (72 cellules × 14 jours × 24 h), **72 en sortie**. Un vrai projet
dbt-duckdb : `stg_cell_hourly` puis `mart_cell_risk`. Le mart ne regarde que l'heure de
pointe (19:00–23:00 — une cellule qui sature à 3 h du matin n'est pas un problème client) et
compare les sept derniers jours aux sept précédents.

**Le coup d'éclat est la colonne de delta.** Les six premières `critical` sont saturées
depuis des mois — deltas entre −0.33 et +0.34, immobiles : l'ingénieur radio les connaît,
elles sont déjà à son plan. Les trois en gras étaient **saines il y a quinze jours** (67, 59
et 59 % de PRB) et sont passées critiques cette semaine. Ce sont les seules lignes du
fichier qui bougent : le quatrième mouvement est à +2.42.

Et ça marche dans les deux sens : `CAS-831-N65` à **−20.64** et `RBA-142-L70` à **−17.43**,
deux cellules qu'une montée en capacité a soulagées. Une colonne de tendance qui ne
descendrait jamais ne serait pas crue.

Finir sur les tests dbt — `unique` et `not_null` sur `cell_id`, `accepted_values` sur
`risk_band` :

> « Une cellule qui apparaît deux fois dans une watchlist, ou une utilisation à 140 %,
> signifie que le pipeline est faux — et le nœud **refuse de publier** plutôt que de laisser
> passer ça en aval. C'est la différence entre un pipeline et un script. »

### Clôture possible — la page métier (2 min)

`/work/retention-board`. Presser **Refresh** : la page appelle le System Retention Board et
remplit ses seize blocs — abonnés à risque, revenu en jeu, taux du décile contre taux de
base, la liste à appeler triée par ce qui est en jeu, la note de rétention, et la
provenance (nom du modèle, version, métrique).

> « La même chaîne, restituée pour quelqu'un qui n'ouvrira jamais un canvas. Et rien ici ne
> retrain ni ne réécrit une table : la page lit ce que le pipeline a laissé. »

C'est la bonne dernière image si la salle est composée de métier plutôt que de data.

---

## Ce qu'il ne faut pas faire

- **Ne pas ouvrir le Flow `Churn Desk`** sauf pour parler de l'AgentLoop : c'est le beat
  agentique et il n'est pas dans ce déroulé.
- **Ne pas chercher de formulaire de consultation sur `/work/retention-board`** : la page
  est en lecture avec un bouton Refresh. La consultation par abonné est du travail en cours,
  non déployé.
- **Ne pas re-seeder** pendant ou juste avant la démo. `--reset` retire les datasets et les
  versions de modèle du seed, et jette le champion promu sur scène.
- **Ne pas promettre une durée de run à voix haute.** La métrique est identique à chaque
  fois, l'horloge non : l'entraînement prend 15 s sur une VM au repos et trois fois plus
  quand la boîte construit des images.

## Pièges et réponses de secours

| Symptôme | Cause et sortie |
|---|---|
| Le `curl` renvoie 401 | La clé du seed n'a pas de secret récupérable. Minter une clé depuis la fiche modèle, le secret s'affiche une seule fois. |
| Premier `curl` lent (~5 s) | Chargement du modèle MLflow. C'est `cached: false` — le lire à voix haute ou l'avoir rejoué avant. |
| Le chip *serves* est déjà sur v2 | Une répétition antérieure a promu. Repromouvoir v1 à la main, le seed ne le fait pas. |
| L'onglet Comparison dit « nothing to compare » | Défaut connu et corrigé dans la révision servie ; si ça revient, c'est la route de détail qui sérialise les versions sans leurs scores. |
| Un nœud Polars ou dbt refuse de s'exécuter | `RECIPE_EXECUTION_ENABLED` et `WORKER_EAGER_MODE` ; le run se termine quand même mais ces deux nœuds signalent leur refus. |
| Une page semble vide | Le bloc `runtime_status` de la page dit si le run a réussi ou s'il travaille encore. Sur les Flows, les badges de nœud portent la même information. |

## Les questions qui viennent, et la réponse d'une ligne

**« C'est du lock-in ? »** Un client MLflow standard, à qui on ne donne que l'URI du
registre, résout les alias et charge les octets depuis l'object store. Le faire dans la
salle (beat 4).

**« Vos chiffres sont-ils réels ? »** Tout est reproductible depuis la valeur de graine
`--seed 20260825` ; un script re-mesure chaque chiffre de cette fiche contre la base et dit
`ok` ou `DRIFT` ligne par ligne.

**« Un LLM intervient-il dans les données ? »** Nulle part dans le chemin de données : SQL,
Polars, scikit-learn, dbt. Le seul nœud LLM écrit la note de rétention, en fin de pipeline.

**« Pourquoi le meilleur modèle ne sert-il pas ? »** Parce que la promotion est un acte
humain, et c'est le beat 5. Le registre nomme le challenger ; il ne le déploie pas.

**« Que se passe-t-il si le modèle se dégrade ? »** L'évaluation elle-même est conservée,
pas seulement son résumé : le rapport skore se rouvre avec ses 1 726 lignes de test et ses
prédictions en cache, donc une métrique que personne n'avait demandée au moment du fit se
calcule après coup **sur les lignes dont parle la fiche**.

**« Combien de temps pour un nouveau cas ? »** Ne pas répondre en semaines. Répondre en
composants : un dataset, un nœud de transformation, un nœud d'entraînement, une fiche
modèle, une clé — tous déjà là, et c'est ce que la démo vient de dérouler.
