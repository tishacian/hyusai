# SENTINEL-CI — Backlog post-démo (Vague 4)

> Date cible d'implémentation : à partir de S+1 de la démo VP du **lundi 25 mai 2026**.
> Tous les items sont **spec uniquement** — chaque item fait 1 à 3 jours-homme.
> Sources :
> - QA prod 2026-05-24 : [docs/sentinel-ci-qa-prod-2026-05-24.md](sentinel-ci-qa-prod-2026-05-24.md)
> - QA résolveur AYA 2026-05-24 : [docs/sentinel-ci-aya-resolver-robustness-2026-05-24.md](sentinel-ci-aya-resolver-robustness-2026-05-24.md)

---

## Item 4.1 — `/calendar/events` honorer `date_from` / `date_to`

**Effort** : ~0,25 j (≈ 2 h en comptant tests + revue).
**Bénéfice** : aligner l'API publique sur le vocabulaire UI (filtres « du / au »), réduire la taille des payloads cockpit en dehors de la fenêtre démo, éliminer une source de confusion entre `start`/`end` (semantique RFC 5545) et la fenêtre de listing.
**Fichier(s) cible(s)** :

- `backend/app/api/v1/endpoints/calendar.py:58-68` (route `GET /events`)
- `backend/app/services/workspace_calendar.py:207-222` (`list_events`)
- `backend/app/tests/api/test_calendar_api.py` (tests de la route — créer si absent)

**État actuel** : la route `GET /api/v1/calendar/events` accepte aujourd'hui `start: datetime` et `end: datetime` et les transmet à `list_events(db, workspace, start=..., end=..., status=...)` qui filtre correctement (`end_at >= start`, `start_at <= end`). Côté front et docs métier, le vocabulaire utilisé est `date_from` / `date_to` ; côté cockpit, la consommation passe par `_agenda_items_from_calendar` qui appelle directement `list_calendar_events(...)` en Python sans HTTP. Le polish #1 du rapport QA prod 2026-05-24 (cf. `docs/sentinel-ci-qa-prod-2026-05-24.md` section « Polishs rapides ») relève que les paramètres « semblent ignorés » côté API publique — symptôme du décalage de naming (`date_from`/`date_to` envoyé par les consommateurs externes n'est pas reconnu et FastAPI ignore silencieusement les query params inconnus).

**Plan d'implémentation** :

1. Ajouter les query params `date_from: Optional[date]` et `date_to: Optional[date]` à la signature `calendar_events(...)` dans `backend/app/api/v1/endpoints/calendar.py`, en gardant `start: Optional[datetime]` et `end: Optional[datetime]` pour rétro-compat.
2. Règle de précédence (documentée dans le docstring de la route) : si `start`/`end` sont fournis, ils l'emportent ; sinon, `date_from`/`date_to` sont convertis en bornes journalières (`date_from → datetime.combine(date_from, time.min, tz=UTC)`, `date_to → datetime.combine(date_to, time.max, tz=UTC)`) puis passés à `list_events`.
3. Conserver la signature actuelle de `list_events(db, workspace, *, start, end, status)` (un seul couple de bornes datetime), pour ne pas exploser l'API service. La conversion `date → datetime` est faite côté route.
4. Renvoyer dans le payload un champ optionnel `meta = {"window": {"date_from": ..., "date_to": ..., "start": ..., "end": ...}}` pour faciliter le debug front (auditable, ne casse pas le contrat existant `{"events": [...]}` : ajouter en sus, ne pas modifier).
5. Mettre à jour `app/services/mission_room.py::_agenda_items_from_calendar` pour qu'il puisse, en option, prendre `date_from`/`date_to` (déjà fait via `start`/`end` interne — vérifier qu'aucun appelant n'a besoin d'un changement).

**Critères d'acceptation** :

- `GET /api/v1/calendar/events?date_from=2026-05-25&date_to=2026-05-26` retourne uniquement les 8 events 25-26 mai 2026 (vs 16 events sans filtre aujourd'hui).
- `GET /api/v1/calendar/events?start=2026-05-25T00:00:00Z&end=2026-05-27T00:00:00Z` reste fonctionnel et identique à la prod actuelle.
- `GET /api/v1/calendar/events?date_from=2026-05-25&end=2026-05-26T12:00:00Z` privilégie `end` (précédence datetime > date) ; comportement documenté.
- `date_from` postérieur à `date_to` → 400 avec message « date_from doit être antérieur ou égal à date_to ».
- `date_from` au format invalide (`2026-13-99`) → 422 (validation FastAPI native via `pydantic.date`).

**Tests** (`backend/app/tests/api/test_calendar_api.py`) :

- `test_calendar_events_filters_by_date_from_only` (n events 25 mai et + uniquement).
- `test_calendar_events_filters_by_date_from_and_date_to` (8 events 25-26 mai).
- `test_calendar_events_start_end_takes_precedence_over_date_from_date_to`.
- `test_calendar_events_invalid_window_returns_400` (`date_from > date_to`).
- `test_calendar_events_meta_window_echoes_request`.

**Risques** :

- Casser un consommateur externe qui aurait par hasard nommé son param `date_from` en attendant l'ancien comportement « retourne tout ». Mitigation : changelog côté `/docs/api` + bannière commitlog.
- Confusion de fuseaux (`date` n'a pas de fuseau, `datetime` UTC oui). Mitigation : forcer UTC dans la conversion et l'expliciter dans le docstring de la route.

---

## Item 4.2 — Variantes `voice_demo_script.prompt` matin / midi / soir bilingues

**Effort** : ~0,5 j.
**Bénéfice** : renforcer l'effet « le VP arrive au cockpit » selon l'heure réelle (ou simulée via `SENTINEL_DEMO_TIME`) et offrir un fallback EN pour les démos bilingues investisseurs. Couvre directement le polish #4 du rapport QA prod.
**Fichier(s) cible(s)** :

- `backend/app/services/mission_room.py:706-716` (`VOICE_DEMO_SCRIPT` constant actuel)
- `backend/app/services/mission_room.py:1766, 2677, 3549` (sites de consommation `voice_demo_script`)
- `backend/app/services/demo_time_context.py:44-54` (`resolve_demo_time`)
- `backend/app/tests/services/test_mission_room.py` (tests de la variante par fenêtre + locale)

**État actuel** : un unique dict `VOICE_DEMO_SCRIPT = {"prompt": "AYA, pourquoi la situation Nord est-elle tendue ?", "answer": "...Napié...", "target_latency_s": 6}` est défini en module-level et réutilisé tel quel par trois sites (cockpit, hypervisor, mission-control). Pas de variation horaire, pas de variante anglaise. La QA prod 2026-05-24 note (polish #4) qu'« une variante 25 mai matin "Pourquoi la tension Nord ce matin ?" » renforcerait la trame.

**Plan d'implémentation** :

1. Remplacer la constante `VOICE_DEMO_SCRIPT` par une **table** `VOICE_DEMO_SCRIPT_VARIANTS: dict[tuple[str, str], dict[str, Any]]` indexée par `(window, locale)` où `window ∈ {"morning", "midday", "evening"}` et `locale ∈ {"fr", "en"}`. Minimum 4 variantes packagées pour S+1 :
   - `("morning", "fr")` : prompt « AYA, pourquoi la tension Nord ce matin ? ».
   - `("midday", "fr")` : prompt actuel « AYA, pourquoi la situation Nord est-elle tendue ? ».
   - `("evening", "fr")` : prompt « AYA, où en sommes-nous sur le Nord ce soir ? ».
   - `("midday", "en")` : prompt « AYA, why is the north tense ? » (déjà couvert par le pack résolveur, cf. `aya.explain_why` phrases EN).
2. Nouvelle fonction `resolve_voice_demo_script(workspace, *, locale="fr") -> dict` :
   - lit `resolve_demo_time(workspace)` ;
   - applique la règle `hour < 11 → morning`, `11 ≤ hour < 16 → midday`, `hour ≥ 16 → evening` ;
   - retourne `VOICE_DEMO_SCRIPT_VARIANTS[(window, locale)]` avec fallback `(window, "fr")` puis `("midday", "fr")`.
3. Remplacer les trois `"voice_demo_script": _clone(VOICE_DEMO_SCRIPT)` (lignes 1766, 2677, 3549) par `_clone(resolve_voice_demo_script(workspace, locale=...))`. La locale est dérivée du `workspace.settings.demo.locale` (par défaut `"fr"`).
4. Garder la signature `target_latency_s: 6` identique sur toutes les variantes.

**Critères d'acceptation** :

- À `SENTINEL_DEMO_TIME=09:00` (workspace `sentinel-ci`), le payload cockpit renvoie le prompt « AYA, pourquoi la tension Nord ce matin ? ».
- À `12:00`, prompt midi inchangé.
- À `17:00`, prompt soir.
- Locale `en` (via `workspace.settings.demo.locale = "en"`) → prompt EN.
- Locale inconnue → fallback FR midi (test explicite).

**Tests** (`backend/app/tests/services/test_mission_room.py`) :

- `test_voice_demo_script_morning_fr` (patch `SENTINEL_DEMO_TIME=09:00`).
- `test_voice_demo_script_evening_fr`.
- `test_voice_demo_script_locale_en_falls_back_to_midday_when_not_packaged`.
- `test_voice_demo_script_unknown_locale_falls_back_to_fr`.

**Risques** :

- Les snapshots de cockpit existants peuvent contenir le prompt midi. Mitigation : mettre à jour les golden files dans la même PR.
- Régression sur la trame démo si la variante matin est jouée sans coordination présentateur ↔ cheat-sheet. Mitigation : la cheat-sheet `docs/sentinel-ci-presenter-cheatsheet.md` doit lister les 3 variantes FR + leur fenêtre horaire.

---

## Item 4.3 — Backend `/maps/layers` structuré

**Effort** : ~1 j (backend route + service + tests + migration consommateur front).
**Bénéfice** : sortir la déclaration des layers carto d'un mix backend (`_monitor_layers` dans `mission_room.py:3674`) + état local Angular (`maritimeLayerVisible = true` hardcodé dans `vp-map-preview.component.ts:1098`) au profit d'une API structurée auditable et configurable côté workspace settings. Pré-requis du chantier hypervisor « layer policy par profil » prévu post-démo.
**Fichier(s) cible(s)** :

- `backend/app/api/v1/endpoints/mission_room.py` (nouvelle route `GET /api/v1/mission-room/maps/layers`)
- `backend/app/services/mission_room.py:3674-3682` (`_monitor_layers`) — refactor en `build_map_layers(workspace, ...)` exporté
- `frontend-ng/src/app/features/mission-room/vp-map-preview.component.ts:1093-1158` (consommation de l'API au lieu de l'état local)
- `frontend-ng/src/app/core/services/mission-room.service.ts` (ajouter `getMapLayers()`)
- `backend/app/tests/api/test_mission_room_api.py` (test de la nouvelle route)

**État actuel** : `_monitor_layers` retourne aujourd'hui en dur 4 layers (`territorial-risk`, `open-intelligence`, `visual-streams`, `maritime-traffic`) en `dict[str, Any]` avec `key/label/enabled/count`. La visibilité initiale du layer maritime côté UI est forcée à `true` (`maritimeLayerVisible = true` dans `vp-map-preview.component.ts:1098`) et le compteur (16 navires) est passé via `vesselMarkers.length`. Aucun endpoint REST n'expose ces layers ; ils sont inclus inline dans `/cockpit` et `/mission-control` payloads. Conséquence : impossible pour un autre client (mobile, watch, autre frontend) de consommer la liste sans réémuler le contrat cockpit complet.

**Plan d'implémentation** :

1. Définir un schéma Pydantic `MapLayerDescriptor` :
   ```python
   class MapLayerDescriptor(BaseModel):
       id: str
       label: str
       kind: Literal["zones", "projects", "maritime", "weather", "press", "visual"]
       visible_by_default: bool
       count: int
       source: str  # ex: "workspace_zones", "maritime_ais", "open_meteo", "press_corpus"
       tone: Literal["cyan", "orange", "violet", "amber", "red", "grey"] = "cyan"
       description: Optional[str] = None
   ```
2. Extraire la logique de `_monitor_layers` dans `build_map_layers(workspace, db, *, profile=None) -> list[MapLayerDescriptor]` (fonction publique du module `mission_room.py`). Compléter avec 2 layers manquants à la spec : `zones` (= sous-couche `territorial-risk` réorientée) et `weather` (placeholder pour layer météo Open-Meteo prévu post-démo).
3. Nouvelle route `GET /api/v1/mission-room/maps/layers` dans `backend/app/api/v1/endpoints/mission_room.py` :
   - paramètre query optionnel `profile: Optional[str]` (par défaut `vigie_executive`).
   - retourne `{"layers": [...]}` typé `list[MapLayerDescriptor]`.
4. Mettre à jour `_monitor_layers` pour appeler `build_map_layers(...)` afin que `/cockpit` et `/mission-control` restent cohérents (DRY).
5. Côté frontend (`vp-map-preview.component.ts`) :
   - remplacer `maritimeLayerVisible = true;` par un `signal<boolean>(true)` dont la valeur initiale provient du layer `maritime` retourné par `mission-room.service.getMapLayers()` (champ `visible_by_default`).
   - exposer les autres layers (`zones`, `projects`, `weather`) dans la légende avec leur toggle natif (extension du `legend-toggle` existant).
6. Documenter le contrat dans `docs/sentinel-ci-storyline-postdemo-handoff.md` (annexe API).

**Critères d'acceptation** :

- `GET /api/v1/mission-room/maps/layers` répond 200 avec ≥ 4 descriptors (`zones`, `projects`, `maritime`, `weather`) + tout layer additionnel propre au workspace.
- Le payload cockpit `/api/v1/mission-room/cockpit` conserve `monitoring_layers` au même format que la prod actuelle (back-compat ; le nouveau payload `/maps/layers` est en sus).
- Le frontend ne contient plus de `maritimeLayerVisible = true;` hardcodé ; la valeur vient du `visible_by_default` de l'API.
- L'ajout/retrait d'un layer côté backend est reflété sur le toggle légende sans modification frontend.

**Tests** :

- Backend (`test_mission_room_api.py`) : `test_maps_layers_returns_default_set`, `test_maps_layers_respects_profile_visibility`.
- Backend (`test_mission_room.py`) : `test_build_map_layers_counts_vessels`, `test_build_map_layers_marks_maritime_invisible_by_default_outside_sentinel_ci`.
- Frontend : test Jest sur `vp-map-preview.component.ts` mockant `getMapLayers()` et vérifiant l'état initial du toggle.

**Risques** :

- Désynchronisation entre `_monitor_layers` (cockpit) et `/maps/layers` (nouvelle API). Mitigation : un seul producteur (`build_map_layers`) consommé par les deux.
- Front consomme deux appels HTTP au lieu d'un. Mitigation : `getMapLayers()` peut être appelé en parallèle (`forkJoin`) avec `getCockpit()`.

---

## Item 4.4 — Résolveur fuzzy matching (Levenshtein ≤ 2)

**Effort** : ~1 j (algo + benchmark + tests de non-régression sur les 100+ phrases du pack).
**Bénéfice** : récupérer les fautes de frappe / STT légères (`agendaa`, `dérgation`, `napi`, `Atlntic Trader`) sans avoir à ajouter manuellement N alias supplémentaires par action. Le rapport résolveur 2026-05-24 (section « Top 3 recommandations », point 2) note que les utilisateurs STT abrègent et tronquent — la couche fuzzy attrape les fautes orthographiques que la couche substring ne capture pas.
**Fichier(s) cible(s)** :

- `backend/app/services/actions/registry.py:1342-1368` (`_score_manifest`)
- `backend/app/services/actions/registry.py:1371-1377` (`_normalize`)
- Nouveau module `backend/app/services/actions/fuzzy.py`
- `backend/app/tests/services/test_actions_resolver.py` (nouveau bloc de tests `test_resolver_fuzzy_*`)

**État actuel** : `_score_manifest` repose sur 3 mécanismes : (1) égalité exacte `text == phrase_norm → 0.98` ; (2) substring `phrase_norm in text → 0.86` ; (3) overlap de tokens ≥ 75 % → 0.72 + bonus. Aucun mécanisme tolérant aux fautes (ex : `agendaa` ne matche aucune phrase contenant `agenda`). Conséquence : 20/48 (42 %) des requêtes du QA résolveur tombent en fallback RAG dont une partie significative à cause de typos / STT bruité.

**Plan d'implémentation** :

1. Nouveau module `backend/app/services/actions/fuzzy.py` exposant :
   ```python
   def levenshtein(a: str, b: str, max_distance: int = 2) -> int:
       # implémentation classique avec early-exit quand d > max_distance
   ```
   Implémentation O(min(|a|, |b|) × max_distance) avec early-exit, pas la version O(|a|·|b|) naïve.
2. Pré-calculer au démarrage (module-level lazy `_PHRASE_INDEX`) un index par bucket de longueur : `dict[int, list[tuple[str, ActionManifest]]]` indexé par `len(phrase_norm.split())`. Pour une query de N tokens, on ne compare qu'avec les phrases de N-1, N, N+1 tokens.
3. Étendre `_score_manifest(text, manifest)` :
   - après les 3 mécanismes existants, si `best == 0`, calculer pour chaque phrase du manifest la distance Levenshtein token-à-token (alignement glouton ou Damerau-Levenshtein sur la chaîne complète bornée à 2). Si la somme des distances tokenisées ≤ 2 sur une phrase de ≥ 3 tokens, attribuer un score `0.78 + (1 - distance/max_distance) * 0.05` (donc 0.78 à 0.83 selon proximité).
   - bornes : ne pas appliquer la couche fuzzy aux phrases ≤ 2 tokens (risque de faux positifs sur ultra-courts).
4. Mesurer l'impact perf via un micro-benchmark `python -m timeit` : cible **< 5 ms** par appel `resolve_action` sur le pack `sentinel_ci_aya_v1` (≈ 25 manifests, ≈ 350 phrases).
5. Ajouter un feature flag `RESOLVER_FUZZY_ENABLED` (env var, défaut `1`) pour rollback rapide en démo.

**Critères d'acceptation** :

- `resolve_action(workspace, text="agendaa cacao")` matche `aya.update_meeting_agenda` (vs RAG fallback avant).
- `resolve_action(workspace, text="dérgation atlantic trader")` matche `aya.draft_customs_email`.
- `resolve_action(workspace, text="rapport prefé nawa")` matche `aya.summarize_last_exchanges`.
- Aucune des 102 phrases déjà couvertes par `test_resolver_matches_demo_scenario_phrases` ne régresse.
- Latence `resolve_action` < 5 ms sur le pack sentinel (mesure dans le test).
- Flag `RESOLVER_FUZZY_ENABLED=0` désactive complètement la couche fuzzy (test explicite).

**Tests** (`test_actions_resolver.py`) :

- `test_resolver_fuzzy_matches_single_typo` (3 cas paramétrés).
- `test_resolver_fuzzy_matches_two_typos`.
- `test_resolver_fuzzy_does_not_match_three_typos`.
- `test_resolver_fuzzy_does_not_match_short_phrases` (anti-régression : « cacao » fuzzy-match `nacao` doit échouer).
- `test_resolver_fuzzy_respects_feature_flag`.
- `test_resolver_fuzzy_latency_under_budget` (assertion `< 5ms` sur 100 appels en boucle).

**Risques** :

- Faux positifs sur ultra-courts. Mitigation : bornes ≥ 3 tokens.
- Bucket par longueur de tokens insuffisant pour gérer des queries collées sans espace. Mitigation : la couche substring couvre déjà ce cas ; la fuzzy n'intervient qu'en filet.
- Drift perf en cas d'ajout futur d'un gros pack. Mitigation : test de latence dans la CI.

---

## Item 4.5 — Résolveur embedding multilingue (filet sémantique)

**Effort** : ~2 j (ingestion modèle + index FAISS + intégration + tests + bench).
**Bénéfice** : matcher les paraphrases sémantiques que ni le substring ni le fuzzy ne capturent (« il se passe quoi à Napié » → `aya.explain_why`, « j'aimerais voir le compte rendu douanier » → `aya.show_customs_record`). C'est la couche finale recommandée par le rapport résolveur (section « Top 3 recommandations », point 1 : « ouvrir un layer anglicisme systématique » — l'embedding rend ce layer automatique).
**Fichier(s) cible(s)** :

- Nouveau module `backend/app/services/actions/embeddings.py` (chargement modèle + FAISS index + scoring).
- `backend/app/services/actions/registry.py:1060-1116` (`resolve_action` — intégration filet après fuzzy).
- `backend/requirements.txt` : ajout `sentence-transformers==^3.x`, `faiss-cpu==^1.8`.
- Nouveau dossier `backend/app/services/actions/cache/` (artefacts FAISS + checksum modèle).
- `backend/app/tests/services/test_actions_resolver.py` (bloc `test_resolver_embedding_*`).
- `docs/sentinel-ci-storyline-postdemo-handoff.md` (annexe ML — taille modèle, latence, refresh).

**État actuel** : aucun composant ML dans le résolveur. Le fallback final est l'overlap de tokens à 75 %, qui rate toutes les paraphrases qui n'ont pas d'overlap lexical fort.

**Plan d'implémentation** :

1. **Choix modèle** : `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (HuggingFace, Apache 2.0, ≈ 470 MB sur disque, 384 dims). Couvre FR + EN (et 50 autres langues). Latence d'inférence CPU pour une query unique ≈ 15-25 ms sur un Mac M1, ≈ 30-40 ms sur un container backend standard.
2. **Index FAISS local** :
   - À la première initialisation (build-time idéalement), pour chaque pack actif, calculer les embeddings de toutes les phrases (≈ 350 vecteurs pour `sentinel_ci_aya_v1`) et les indexer dans un `faiss.IndexFlatIP` (inner-product avec vecteurs L2-normalisés = cosine sim).
   - Persister l'index sous `backend/app/services/actions/cache/<pack_id>-<model_checksum>.faiss` + un manifest JSON `{phrase_id → action_id}`.
   - Au démarrage, charger les indexes en mémoire (mmap si possible).
3. **Intégration `resolve_action`** :
   - Après la couche fuzzy, si `best_score < min_confidence (0.78)`, encoder la query, faire un `index.search(query_vec, k=5)` par pack actif, normaliser le top score en cosine sim ∈ [-1, 1].
   - Mapping : `cosine ≥ 0.78 → score = 0.79 + (cosine - 0.78) * 1.0` (donc 0.79 à 1.0 selon proximité), `< 0.78 → ignoré`.
   - Si plusieurs actions remontent, garder celle avec le `cosine` max. Le tie-breaker hardcodé actuel (`_apply_tie_breakers`) reste appliqué après pour la cohérence narrative (cf. item 4.6 pour rendre les tie-breakers déclaratifs).
4. **Latence cible** : ≤ 50 ms par query, mesurée et plafonnée (timeout 100 ms avec fallback no_match).
5. **Feature flag** `RESOLVER_EMBEDDING_ENABLED` (env var, défaut `0` jusqu'à validation perf en staging, puis `1`).
6. **Refresh index** : nouveau CLI `python -m app.scripts.rebuild_action_embeddings` à exécuter lors de tout ajout/retrait de phrase dans `registry.py`. Add hook CI pour rebuild + commit.

**Critères d'acceptation** :

- `resolve_action(workspace, text="il se passe quoi à Napié en ce moment")` matche `aya.explain_why` (cosine ≥ 0.78).
- `resolve_action(workspace, text="j'aimerais voir le compte rendu douanier")` matche `aya.show_customs_record`.
- `resolve_action(workspace, text="any news on the cocoa diversification")` matche `aya.recommend_cacao`.
- Latence p95 < 50 ms sur le pack sentinel (mesurée sur 100 queries).
- `RESOLVER_EMBEDDING_ENABLED=0` désactive complètement la couche (parité avec aujourd'hui).
- L'ajout d'une nouvelle phrase au `registry.py` sans rebuild de l'index ne casse rien (l'index ne contient pas la nouvelle phrase mais le substring / fuzzy peuvent la matcher).
- Aucun appel réseau (modèle local, FAISS local).

**Tests** :

- `test_resolver_embedding_matches_paraphrase` (10 cas paramétrés FR + EN).
- `test_resolver_embedding_does_not_match_unrelated_query` (« quelle est la météo à Paris » → no_match).
- `test_resolver_embedding_respects_feature_flag`.
- `test_resolver_embedding_latency_under_50ms_p95`.
- `test_resolver_embedding_index_rebuild_idempotent`.

**Risques** :

- **Taille image Docker** + cold start. Mitigation : mettre le modèle dans un volume monté ou dans une étape Docker dédiée (`pull` séparé) ; cold-start de l'API < 5s.
- **Hallucinations sémantiques** (matching plausible mais hors-narratif). Mitigation : seuil cosine 0.78 strict + suite de tests anti-régression sur ~50 queries hors-pack.
- **Drift du modèle** entre versions `sentence-transformers`. Mitigation : checksum modèle dans le nom de fichier FAISS, rebuild auto si checksum diffère.
- **Latence sur infra contrainte** (CPU 1 vCPU). Mitigation : test de charge dans le CI ; si > 50 ms, basculer sur quantification int8 (`onnxruntime`).

---

## Item 4.6 — Tie-breaker dynamique du résolveur (règles déclaratives)

**Effort** : ~0,5 j.
**Bénéfice** : sortir le tie-breaker vessel↔customs aujourd'hui hardcodé dans `_apply_tie_breakers` (registry.py:1124) au profit d'un format déclaratif réutilisable pour d'autres conflits (ex : briefing matin vs briefing opérationnel, agenda vs prochain RDV). Permet à un product manager d'ajouter une règle sans toucher au code Python.
**Fichier(s) cible(s)** :

- `backend/app/services/actions/registry.py:1119-1149` (refactor `_apply_tie_breakers`)
- Nouveau module `backend/app/services/actions/tiebreakers.py`
- Nouveau fichier `backend/app/services/actions/data/tiebreakers.yaml`
- `backend/app/tests/services/test_actions_resolver.py` (nouveau bloc `test_resolver_tiebreaker_*`)

**État actuel** : une seule règle hardcodée — si le top match est `aya.show_vessel_evidence` et la query contient un verbe douanes (`pv|procès\s*verbal|dédouanement|dérogation|courrier|email|mail|douanes|customs`), on bascule vers `aya.show_customs_record` / `aya.draft_customs_email` / `aya.propose_customs_email`. Cette règle a été ajoutée pour résoudre le conflit identifié dans `docs/sentinel-ci-aya-resolver-robustness-2026-05-24.md` (« Top 3 recommandations », point 3). Le code est correct mais ne passe pas à l'échelle si on doit ajouter 3-5 règles similaires.

**Plan d'implémentation** :

1. Définir un schéma déclaratif YAML (chargé une fois au démarrage et caché) :
   ```yaml
   tiebreakers:
     - id: vessel-vs-customs
       description: "Quand la query parle de PV ou de courrier douanes, prioriser show_customs_record/draft_customs_email sur show_vessel_evidence."
       when:
         top_action_id_in: ["aya.show_vessel_evidence"]
         query_matches: '\b(?:pv|proces\s*verbal|dedouanement|derogation|courrier|email|mail|douanes|customs)\b'
       prefer_action_ids:
         - aya.show_customs_record
         - aya.draft_customs_email
         - aya.propose_customs_email
       score_boost: 1.5  # multiplicatif appliqué au score des actions préférées qui ont déjà matché
     - id: briefing-vs-focus-projet
       description: "Quand la query parle de briefing opérationnel d'un projet, prioriser focus_zone_with_project sur priority_summary."
       when:
         top_action_id_in: ["aya.priority_summary"]
         query_matches: '\b(?:projet|chantier|napi[eé])\b'
       prefer_action_ids:
         - aya.focus_zone_with_project
       score_boost: 1.5
   ```
2. Nouveau module `backend/app/services/actions/tiebreakers.py` :
   - `load_tiebreakers() -> list[TieBreakerRule]` (cache module-level avec invalidation par mtime du YAML en dev, immuable en prod).
   - `apply_tiebreakers(normalized: str, scored: list[tuple[float, ActionManifest]]) -> tuple[float, ActionManifest]` qui boucle sur les règles et applique le boost multiplicatif aux actions présentes dans `scored`.
3. Remplacer l'appel `_apply_tie_breakers(normalized, scored)` dans `resolve_action` par `apply_tiebreakers(normalized, scored)`.
4. Documenter le format dans le header du YAML (commentaires + exemples).
5. Garder l'ancien `_apply_tie_breakers` privé pendant 1 release comme fallback (alias appelant `apply_tiebreakers`) pour ne pas casser un éventuel import externe.

**Critères d'acceptation** :

- La règle `vessel-vs-customs` produit exactement le même comportement qu'aujourd'hui (tests existants `test_resolver_tiebreaker_customs_*` passent sans modification).
- Ajouter la règle `briefing-vs-focus-projet` dans le YAML (sans modifier de code) bascule la query « brief opérationnel projet Napié » vers `aya.focus_zone_with_project` même si `aya.priority_summary` matche d'abord.
- Un YAML mal formé (clé inconnue, regex invalide) lève une erreur explicite au démarrage (`tiebreakers.yaml line N: ...`), pas un crash silencieux.
- Le test de latence du résolveur (cf. 4.4) reste < 5 ms.

**Tests** :

- `test_tiebreaker_vessel_vs_customs_preserves_existing_behavior` (5 cas paramétrés).
- `test_tiebreaker_briefing_vs_focus_projet_new_rule`.
- `test_tiebreaker_rule_no_match_returns_top_unchanged`.
- `test_tiebreaker_yaml_validation_raises_on_bad_regex`.
- `test_tiebreaker_score_boost_applied_correctly`.

**Risques** :

- Les règles peuvent entrer en conflit (deux règles qui boostent des actions différentes pour la même query). Mitigation : appliquer les règles dans l'ordre de déclaration, première règle qui match remporte ; documenter explicitement.
- Drift entre la doc et la réalité. Mitigation : un test de `tiebreakers.yaml` qui vérifie que chaque action référencée existe dans un manifest.

---

## Item 4.7 — Champ `surface_intent` sur `ActionManifest`

**Effort** : ~0,5 j (champ + remplissage du pack sentinel + tests + préparation router LLM).
**Bénéfice** : préparer l'arrivée d'un layer LLM optionnel post-résolveur substring/fuzzy/embedding. Le LLM router prendra en input la query + la liste des actions matchées par le résolveur déterministe, et utilisera `surface_intent` pour désambiguïser entre actions qui partagent un même pivot lexical mais expriment des **intentions VP différentes** (« briefing » vs « drill » vs « mutate »).
**Fichier(s) cible(s)** :

- `backend/app/services/actions/registry.py:33-60` (`ActionManifest` dataclass)
- `backend/app/services/actions/registry.py:274-1004` (remplir le champ pour les 25 manifests `sentinel_ci_aya_v1`)
- `backend/app/tests/services/test_actions_resolver.py` (test d'exhaustivité de `surface_intent`)
- `docs/sentinel-ci-storyline-postdemo-handoff.md` (annexe taxonomie `surface_intent`).

**État actuel** : `ActionManifest` (frozen dataclass) expose `action_id`, `label`, `description`, `surfaces`, `phrases`, `input_schema`, `required_permission`, `confirmation_policy`, `handler`, `audit_event`, `pack`, `capability_template`, `direct_safe`. Aucun champ ne distingue par exemple `aya.priority_summary` (briefing court) de `aya.focus_zone_with_project` (briefing projet ciblé) de `aya.explain_why` (drill causal) — tous trois sont `direct_safe` et `surface in {chat, voice, ui, flow}`. Le résolveur ne peut donc pas raisonner sur l'intention.

**Plan d'implémentation** :

1. Étendre `ActionManifest` avec un champ optionnel `surface_intent: Literal["briefing", "drill", "propose", "confirm", "mutate"] | None = None`. Sémantique :
   - `briefing` : action qui restitue un état (priorités, prochain RDV, résumé). Aucune mutation.
   - `drill` : action qui **navigue** dans une chaîne causale ou un graphe d'évidence (explain_why, show_vessel_evidence, show_customs_record).
   - `propose` : action qui prépare un brouillon que le VP peut accepter / refuser (propose_customs_email, recommend_cacao, draft_strategic_report, update_meeting_agenda en mode propose).
   - `confirm` : action de confirmation explicite d'une proposition pendante (confirm_agenda_patch).
   - `mutate` : action qui modifie un état persistant (log_decision, start_meeting, schedule_meeting, action_plan_create/cancel/complete).
2. Remplir le champ pour les 25 manifests du pack `sentinel_ci_aya_v1`. Mapping recommandé :
   - **briefing** : `aya.priority_summary`, `aya.action_plan_status`, `aya.open_next_meeting`, `aya.summarize_last_exchanges`, `aya.recall_past_decisions`, `aya.show_maritime_traffic`, `aya.map_focus`, `aya.evidence_explain`.
   - **drill** : `aya.explain_why`, `aya.focus_zone_with_project`, `aya.show_vessel_evidence`, `aya.show_customs_record`.
   - **propose** : `aya.propose_customs_email`, `aya.draft_customs_email`, `aya.recommend_cacao`, `aya.draft_strategic_report`, `aya.update_meeting_agenda`, `aya.schedule_meeting`, `aya.action_plan_create`.
   - **confirm** : `aya.confirm_agenda_patch`, `aya.acknowledge_presence`.
   - **mutate** : `aya.start_meeting`, `aya.log_decision`, `aya.action_plan_cancel`, `aya.action_plan_complete`.
3. Inclure `surface_intent` dans `ActionManifest.to_payload` pour qu'il soit accessible côté API `/api/v1/actions/catalog` (et donc côté observability + dashboards).
4. Préparer le LLM router post-substring (hors scope item 4.7, à traiter en 4.8/Vague 5) en exposant une fonction interne `top_intents_for_router(scored) -> list[dict]` qui retourne pour le LLM `{action_id, surface_intent, label, score}` — utile pour cadrer le prompt système.

**Critères d'acceptation** :

- Tous les 25 manifests `sentinel_ci_aya_v1` ont un `surface_intent` non nul.
- Tous les manifests du pack `andritz_industrial_v1` et `global_voice_v1` peuvent avoir `surface_intent = None` (rétro-compat).
- Le payload `/api/v1/actions/catalog?workspace=sentinel-ci` retourne `surface_intent` pour chaque action sentinel.
- Test d'exhaustivité : si on ajoute un manifest dans le pack sentinel sans `surface_intent`, un test échoue.

**Tests** :

- `test_sentinel_pack_has_surface_intent_for_every_action` (parametrized).
- `test_surface_intent_values_are_in_allowed_set`.
- `test_surface_intent_briefing_actions_are_direct_safe` (cohérence : briefing ⇒ pas de confirmation).
- `test_surface_intent_mutate_actions_have_audit_event_set` (cohérence : mutate ⇒ audit).

**Risques** :

- Mauvaise classification initiale. Mitigation : la classification est révisable, le champ est métadonnées (ne change pas le comportement résolveur tant que le LLM router n'est pas câblé).
- Confusion entre `surface_intent` et `confirmation_policy`. Mitigation : les deux coexistent ; `confirmation_policy` est une règle d'exécution (faut-il un « oui ? »), `surface_intent` est une étiquette de catégorie utile au routing LLM et à l'analytics.

---

## Récapitulatif effort

| Item | Effort | Type | Dépendance |
|---|---|---|---|
| 4.1 — `/calendar/events` `date_from`/`date_to` | 0,25 j | API + tests | — |
| 4.2 — Variantes `voice_demo_script` | 0,5 j | Backend service + tests | — |
| 4.3 — `/maps/layers` structuré | 1 j | API + service + front migration | — |
| 4.4 — Fuzzy matching Levenshtein | 1 j | Résolveur | — |
| 4.5 — Embedding multilingue | 2 j | Résolveur + infra ML | 4.4 (couche fuzzy livrée avant) |
| 4.6 — Tie-breaker déclaratif | 0,5 j | Résolveur + DSL | — |
| 4.7 — `surface_intent` | 0,5 j | Schéma + remplissage pack | préparation 4.8/Vague 5 (LLM router) |

**Total** : ~5,75 j ouvrés pour une équipe d'un dev backend + 0,5 j frontend (item 4.3).

