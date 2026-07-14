# Plan de réconciliation — branche `demo/agentic` (chat agentic) ↔ `origin/demo/agentic`

> Statut : **investigation seulement**. Aucun push, aucun rebase, aucun déploiement n'a été
> exécuté. Ce document est le plan à valider avant toute action sur la branche/VM/DB de démo
> partagées.

## 1. Contexte

- **Merge-base** : `080ccbf0` (« fix(capture): restore scrolling in report review surface »).
  C'était le HEAD avant la session de travail chat-agentic. **Aucune migration agentic**
  n'existe au fork.
- **Local (HEAD)** : 4 commits non poussés portant toute l'implémentation agentic
  (code + migrations `048→049→050→051`).
  - `a343e81b` base (skills, flow, migrations 048/049/050)
  - `5eaf4e87` roadmap P1–P4
  - `c1cdc19c` gate flag + fallback Ollama juge
  - `cd80bd0a` flow JSON oublié dans 5eaf4e87 (corrigé)
- **Upstream (`origin/demo/agentic`)** : 5 commits **client360** (dont réconciliation alembic),
  et **aucun code agentic** (flow artifact absent, 0 skill agentic, 0 route agentic).

## 2. Topologie alembic après le fork

Base commune identique jusqu'à `047_andritz_membrane`. Ensuite :

### Local (mes vraies migrations)
```
047_andritz_membrane
 └─ 048_andritz_chat_agentic            (rev 048_andritz_chat_agentic,  down 047)
     └─ 049_andritz_chat_grounding      (rev 049_andritz_chat_grounding, down 048_andritz_chat_agentic)
         └─ 050_andritz_chat_agentic_parity  (rev 050_andritz_chat_parity, down 049)   ← REAL
             └─ 051_..._latency_multihop      (rev 051_andritz_chat_latency_mh, down 050_andritz_chat_parity)
HEAD local = 051_andritz_chat_latency_mh
```

### Upstream (client360 + stub de compat)
```
047_andritz_membrane
 ├─ 048_client360_pdr_pre_mvp   (rev 048_client360_pdr,       down 047)
 └─ 050_andritz_chat_parity     (rev 050_andritz_chat_parity, down 047)   ← STUB no-op (upgrade/downgrade = pass)
        └─ 051_client360_pdr_merge  (rev 051_client360_pdr_merge, down = (048_client360_pdr, 050_andritz_chat_parity))
HEAD upstream = 051_client360_pdr_merge
```

## 3. Les deux (seuls) points de conflit

1. **Collision d'ID de révision** : `050_andritz_chat_parity` existe des **deux** côtés,
   dans des fichiers différents, avec des `down_revision` différents (mien : `049` ; upstream :
   `047`, no-op). → `alembic upgrade head` refuserait (« Multiple revisions with id… »).
2. **Conflit de code** : **un seul fichier** touché des deux côtés →
   `backend/app/core/config.py` (moi : `judge_model` + `enable_agentic_chat` ; client360 :
   ses propres settings). Conflit trivial (deux ajouts de champs). Tout le reste est disjoint
   (fichiers client360 vs fichiers agentic).

> Le stub upstream `050_andritz_chat_parity` correspond exactement au stamp que **ma vraie
> migration** a laissé sur la DB VM lorsqu'elle a été appliquée impérativement. C'est le même
> point logique — il faut donc dé-dupliquer l'ID, pas dupliquer le travail.

## 4. Plan de réconciliation recommandé (minimal, VM-safe, un seul head)

### 4.1 Intégration git
- Rebase les 4 commits locaux sur `origin/demo/agentic`.
- Résoudre `config.py` : **garder les deux** blocs de settings (client360 + `judge_model`
  + `enable_agentic_chat`).
- Tout le reste rebase proprement (fichiers disjoints).

### 4.2 Migrations (2 éditions seulement — ne PAS toucher aux fichiers upstream)
- **Renommer l'ID** de ma migration parité pour tuer la collision :
  dans `050_andritz_chat_agentic_parity.py` : `revision = "050_andritz_chat_parity"`
  → `revision = "050_andritz_chat_agentic_parity"` (le `down_revision = "049_andritz_chat_grounding"`
  reste). On **laisse** le stub upstream posséder l'ID `050_andritz_chat_parity`.
- **Faire de ma migration latence/multihop le nœud de merge** (unifie les deux heads) :
  dans `051_andritz_chat_agentic_latency_multihop.py` :
  `down_revision = "050_andritz_chat_parity"`
  → `down_revision = ("051_client360_pdr_merge", "050_andritz_chat_agentic_parity")`.

### 4.3 Graphe cible (un seul head)
```
047_andritz_membrane
 ├─ 048_client360_pdr ───────────────────────────┐
 ├─ 050_andritz_chat_parity (stub no-op) ─────────┤
 │                                                 ├─ 051_client360_pdr_merge ─┐
 ├─ (via stub)                                     │                            │
 └─ 048_andritz_chat_agentic                       │                            │
     └─ 049_andritz_chat_grounding                 │                            │
         └─ 050_andritz_chat_agentic_parity ───────────────────────────────────┤
                                                                                 └─ 051_andritz_chat_latency_mh (MERGE + reseed latence/multihop)
HEAD unique = 051_andritz_chat_latency_mh
```

### 4.4 Ce qui s'exécutera réellement au `alembic upgrade head` sur la VM
La DB VM est déjà stampée sur la branche du stub (`050_andritz_chat_parity`, voire
`051_client360_pdr_merge` si upstream a déjà été déployé). Alembic appliquera donc :
- ma branche andritz réelle `048_andritz_chat_agentic → 049 → 050_andritz_chat_agentic_parity`
  (branche parallèle non encore « appliquée » côté VM),
- puis le merge `051_andritz_chat_latency_mh`.

**Toutes ces migrations sont idempotentes** (upsert par slug, garde-fous snapshot, marqueurs
scoping) → sur la VM où le System agentic existe déjà, ce sont des no-op/upserts sûrs ; sur une
**DB fraîche**, elles reseedent tout de façon reproductible (ce que le stub upstream, no-op, ne
fait PAS — d'où l'intérêt de rendre mes migrations canoniques).

## 5. Checklist de validation (avant push)
- [ ] `alembic heads` → **un seul** head (`051_andritz_chat_latency_mh`).
- [ ] `alembic history` linéarisable, pas d'ID dupliqué.
- [ ] Re-confirmer l'**idempotence** de 048 (seed System) sur DB déjà seedée (dry-run / relecture).
- [ ] `dag_validator` sur `andritz_chat_agentic_v3.json` → 0/0.
- [ ] Suite de tests agentic verte (skills, dataflow, judge, routing, profils).
- [ ] `config.py` : les settings client360 ET agentic présents.

## 6. Déploiement (étape séparée, après validation + accord explicite)
1. `git push origin demo/agentic` (branche partagée).
2. Sur `omnirag-demo` : `cd /home/ubuntu/omnirag && bash scripts/deploy-vm.sh`
   (fetch+reset → build → up ; le service `agentium-migrate` lance `alembic upgrade head` ;
   health + audit de dérive).
3. Sweep A/B v3 : si quota OpenAI épuisé, basculer le juge/génération sur Ollola
   (`ollama_default_model`) — déjà câblé.

## 7. À NE PAS faire
- Ne pas supprimer le stub upstream `050_andritz_chat_parity` (référencé par le merge client360
  et correspond au stamp DB VM).
- Ne pas garder mon ID `050_andritz_chat_parity` (collision).
- Ne pas appliquer de hotfix in-container (cause racine des dérives ; cf. `deploy-vm.sh`).
- Ne pas `--force` push sur `demo/agentic`.
