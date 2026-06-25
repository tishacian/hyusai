# Chat recherche Andritz — Spike de mesure du gain agentic (Phase 0)

_Date : 2026-06-25 · Workspace : `andritz` · Mesure offline, **zéro changement** sur le chat en prod._

## 1. Contexte et question

Le chat recherche Andritz est aujourd'hui un **pipeline déterministe** : profil de réponse
(`precise_fact` / `project_summary` / `transversal_inventory`), scoping, garde-fous de grounding,
plancher de rappel, index full-text inventaire, et trois profils de latence `fast` / `balanced` / `deep`.

Question posée : **quel gain réel** y aurait-il à déléguer le routage et l'organisation de
l'orchestration à un **process agentic** (think, choisir d'escalader en deep selon la première
réponse, auto-évaluer le résultat, demander des inputs de clarification), quitte à payer de la latence ?

Ce spike **mesure** ce gain potentiel **sans rien câbler en prod** : il rejoue le pipeline *fidèle*
du chat sur un corpus borné, auto-évalue chaque première réponse, **simule** une passe d'escalade deep,
et chiffre l'opportunité d'escalade / de clarification.

## 2. Méthode

Script : `backend/scripts/agentic_chat_spike.py` (exécuté in-container, Qdrant + LLM joignables).

| Brique | Ce qu'elle fait | Réutilise |
| --- | --- | --- |
| Corpus | 54 requêtes labellisées (demo 22/06 PASS/FAIL, régression inventaire, 8 facettes golden) | docs demo + `retrieval_golden/*.json` |
| `faithful_chat` | rejoue **exactement** la requête que construit l'endpoint chat (defaults workspace → `orchestrator.process_request` → `apply_answer_policy_to_text`), baseline = `balanced`, escalade = `deep` | endpoints `chat.py` |
| Verdict | juge LLM (`JudgeService`) + signaux déterministes (no_context, fallback, hedge, fuite jargon, contrat de langue, garde-fou exact-match) + `infer_failed_components` → `bon` / `faible` | `evaluation/judge.py`, `rag_components.py` |
| Escalade | re-run `deep` des cas faibles + re-juge → lift composite + surcoût latence | — |
| Sufficiency | heuristique d'ambiguïté (anaphore sans ancre, pièce générique sans projet, cross-projet non scopé, identifiant nu) → opportunité de clarification | — |
| Calibration | courbe précision/rappel du détecteur vs vérité terrain + baseline déterministe-seul | — |

Reproductible :

```bash
cat backend/scripts/agentic_chat_spike.py | \
  ssh omnirag-demo "docker exec -i -e SPIKE_JSONL=/tmp/spike_full.jsonl \
  -w /app/backend agentium-backend python -"
```

## 3. Résultats (54/54 notés, 0 erreur)

### Objectif 1 — Taux de premières réponses faibles
- **14 / 54 faibles = 25,9 %** (40 « bon »).
- Par source : demo 4/10, golden:dense 2/11, hard_intents 3/11, diversity 2/6, multilingual 2/4, multiturn 1/3.
- **0 faible** sur fallbacks, sparse_only, scope_filters, régression inventaire (URACA).

### Objectif 2 — Escalade deep (le levier agentic « classique »)
- 14 cas faibles escaladés → **3 récupérés (21,4 %)**.
- **Lift composite moyen ≈ −0,4** (nul/négatif) · **surcoût latence ≈ +5,9 s**.
- Les 3 récupérés sont **retrieval-shaped** (`dci110_strip_carrier`, `sinamics_s120_s150`, `kd724_partial_ref`).
  → la profondeur aide **uniquement** quand le défaut est de récupération ; **aucun gain** sur langue / jargon / extraction de table.

### Objectif 3 — Opportunité de clarification
- **10 / 54 ambigus = 18,5 %** … mais **0 chevauchement avec les faibles**.
  → les requêtes sous-spécifiées (anaphore, pièce générique, cross-projet) répondent quand même « bon »
  grâce au scoping/fallback déterministe. La clarification est un confort UX, **pas** un levier de qualité ici.

### Objectif 4 — Calibration du détecteur (vérité terrain = 10 cas)
| Détecteur | Précision | Rappel | Note |
| --- | --- | --- | --- |
| Juge + seuil composite | 0,75 | 0,50 | **plat de 50 à 90** : les composites se massent à 85-97, le seuil ne discrimine pas ; le faible est porté par les **signaux durs + taux d'hallucination**, pas par le composite |
| **Déterministe seul** | **1,00** | 0,50 | 3 TP / 0 FP / 4 TN / 3 FN — **parfaitement précis**, attrape la moitié, **coût quasi nul (pas de LLM)** |

Latence : baseline moyenne **19,3 s**, escalade moyenne **23,1 s**.

## 4. Lecture des 14 cas faibles

| Typologie | Cas | Levier qui aiderait |
| --- | --- | --- |
| **Contrat de langue DE (7 cas, 50 %)** | `akk200_de`, `german_generic`, `qms12_de`, `div_qms12_de`, `german_simotics_akk200`, `ml_akk200_de`, `ml_injector_de` | **re-génération dans la langue de la requête** (déterministe) |
| Retrieval-shaped (3) | `dci110_strip_carrier`, `sinamics_s120_s150`, `kd724_partial_ref` | escalade deep ciblée (les 3 récupérés) |
| Extraction de table / fait dur (1) | `geotex_label_b` (composite 47,1) | canal exact-match / table |
| Synthèse comparative (1) | `compare_continental_pollrich` | prompt comparatif |
| Anaphore multiturn (1) | `mt_followup_etachrom_maint` | résolution d'ancre conversationnelle |
| **Faux positif du juge (1)** | `injector_cartridge_cleaning` (vérité = bon) | variance LLM (à ignorer) |

**50 % des faibles = le contrat de langue allemand** : un seul correctif déterministe couvre la moitié du déficit.

## 5. Caveats méthodologiques (à lire avant d'interpréter)

1. **Run offline CPU-partagé** : le cross-encoder time out sur 45/54 (`xenc:timeout`). En prod (reranker préchargé,
   CPU dédié) il aboutit souvent → le rerank est **sous-représenté** ici, et l'attribution « retriever » est gonflée
   (à escompter dans l'objectif 1).
2. **Variance du juge LLM** sur les cas limites (composites massés haut ; 1 flip bon↔faible observé). Les **signaux durs**
   sont l'axe fiable ; le juge est un filet secondaire moins précis.
3. **Vérité terrain limitée (10) et partiellement périmée** : `d60_greasing`, `cu250s2_role`, `etachrom_spares`
   — étiquetés « faible » au 22/06 — ressortent **« bon »** car corrigés depuis (plancher de rappel + dé-collage HTML).
   La calibration est **indicative**, pas définitive ; un jeu labellisé plus large la solidifierait.
4. Multiturn désormais couvert (fix `context` via `request_dict`, cf. `faithful_chat`).

## 6. Conclusion et recommandation

- **La qualité de première réponse est déjà élevée** (≈ 74 % « bon » ; plus en réalité, une part des faibles
  étant du bruit de juge ou le bug de langue déterministe). L'orchestration déterministe (scope, fallback,
  plancher de rappel, full-text inventaire) tient bien : ambigu / non-scopé / inventaire répondent « bon ».
- **Le levier agentic « classique » (escalade deep autonome sur insatisfaction) n'est PAS le gain** :
  lift ≈ −0,4, +5,9 s, 21 % de récupération. Les défauts dominants (langue, jargon, table) ne sont **pas**
  des problèmes de profondeur — chercher « plus » ne les corrige pas.
- **La clarification est à faible ROI immédiat** ici (orthogonale à la faiblesse).
- **Le gain agentic à plus fort ROI = auto-évaluation bornée + remédiation CIBLÉE**, pas l'exploration libre :
  - un **garde déterministe (P = 1,0, R = 0,5)** flague gratuitement la moitié des échecs **sans faux positif** ;
    le juge LLM en second filet (moins précis) ;
  - à chaque défaut nommé, la remédiation est chirurgicale : **violation de langue → re-générer dans la langue** (couvre
    50 % des faibles), **fuite jargon « vectoriel » → re-générer filtré**, **miss retrieval-shaped → escalade deep ciblée**
    (les seuls cas où la profondeur paie).

**Reco** : ne pas transformer tout le chat en agent libre. **Conserver l'orchestration déterministe** et lui ajouter
une **boucle d'auto-correction bornée** (1 passe de re-génération optionnelle, déclenchée par le type de défaut détecté).
On capture l'essentiel du gain de qualité à **latence prévisible**. Réserver l'autonomie LLM plus large
(profondeur adaptative, questions de clarification) à une **phase ultérieure**, seulement si un jeu labellisé plus
grand le justifie — les données actuelles disent que le gain marginal est faible et le coût de latence réel.

## 7. Annexe — substrat de build (si Phase 1)

Le futur câblage viserait le **run_engine v3** (schéma de flow typé, variable pool, sous-flows, validateurs DAG,
`MembraneSpec`) : le garde déterministe et la remédiation ciblée s'expriment naturellement comme nœuds typés
avec conditions, sans casser les specs d'orchestration existantes.

---

### Tableau par cas (composite, route, lift escalade)

| id | source | vérité | verdict | composite | route | lift | récup. |
| --- | --- | --- | --- | --- | --- | --- | --- |
| demo_fail_akk200_de | demo | faible | faible | 92.1 | faible | -19.2 | non |
| demo_fail_cu250s2_role | demo | faible | bon | 95.4 | bon | — | — |
| demo_fail_d60_greasing | demo | faible | bon | 97.5 | bon | — | — |
| demo_fail_etachrom_spares | demo | faible | bon | 96.7 | bon | — | — |
| demo_fail_german_generic | demo | faible | faible | 95.4 | faible | -4.2 | non |
| demo_fail_qms12_de | demo | faible | faible | 90.0 | faible | 3.8 | non |
| demo_pass_acj200_carde | demo | bon | bon | 95.4 | bon | — | — |
| demo_pass_akk200_width_speed | demo | bon | bon | 96.2 | bon | — | — |
| demo_pass_injector_cartridge_cleaning | demo | bon | faible | 96.2 | faible | -5.0 | non |
| demo_pass_qms12_function_en | demo | bon | bon | 95.8 | bon | — | — |
| g_dense_dci110_strip_carrier | golden:dense | — | faible | 91.2 | faible | -4.1 | **oui** |
| g_dense_geotex_label_b | golden:dense | — | faible | 47.1 | faible | 1.7 | non |
| g_div_qms12_de_betriebsanleitungen | golden:diversity | — | faible | 85.4 | faible | 11.7 | non |
| g_div_sinamics_s120_s150 | golden:diversity | — | faible | 91.7 | faible | 4.1 | **oui** |
| g_hi_compare_continental_pollrich | golden:hard_intents | — | faible | 86.7 | faible | -1.3 | non |
| g_hi_german_simotics_akk200 | golden:hard_intents | — | faible | 91.7 | faible | 0.4 | non |
| g_hi_kd724_partial_ref | golden:hard_intents | — | faible | 93.3 | faible | 2.1 | **oui** |
| g_ml_akk200_de | golden:multilingual | — | faible | 91.2 | faible | 2.1 | non |
| g_ml_injector_de | golden:multilingual | — | faible | 48.8 | faible | 0.8 | non |
| g_mt_followup_etachrom_maint | golden:multiturn | — | faible | 91.2 | faible | 0.9 | non |

_(40 cas « bon » omis du tableau ; composites 85-97.)_
