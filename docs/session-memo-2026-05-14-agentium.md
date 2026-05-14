# Memo session Codex - Agentium / Andritz / SENTINEL-CI

Date de memo: 2026-05-14  
Branche de travail: `demo/agentic`  
VM cible: `omnirag-demo`  
Repo: `/Users/thib/Developer/PAPAI/omnirag`

## Objectif general de la session

La session a transforme Agentium d'une demo orientee Knowledge Capture en socle plus robuste et plus generalisable:

- workspace Andritz exploitable avec Knowledge Capture, IAM, depot externe SFTP/Secure Deposit et ingestion async;
- stack Agentium largement dockerisee sur la VM;
- workspace demo `sentinel-ci` construit comme "AI Government Mission Room";
- VIGIE positionne comme assistant executif outille, branche sur agenda, news, carte, actions, observations visuelles et Knowledge Scopes multi-KB;
- RAG transverse fiabilise sur Qdrant avec isolation stricte par workspace et par collection.

## Andritz - Knowledge Capture

Travaux realises:

- Alignement UX progressif avec les mockups fournis:
  - clarification des modes `guided`, `conversation-only`, capture cockpit;
  - meilleure separation entre preparation, plan, capture et proposition;
  - suppression progressive du meta-discours dans les questions;
  - meilleure visibilite des etats de session, prompts, quality signals et proposal flow.
- Correction du mode conversation:
  - bouton `Start conversation`;
  - messages d'erreur micro plus visibles;
  - mode conversation conserve sans casser le runtime cascade existant.
- Ajout du plan structurel V2V:
  - protocole streaming;
  - inner monologue;
  - oracle de capture;
  - barge-in/VAD en cible;
  - provider local/OpenAI interchangeables.

Etat actuel:

- Knowledge Capture reste system-scoped, avec backend comme source d'autorite.
- Les evolutions voix sont maintenant pensees comme capabilities reutilisables, pas comme code specifique Andritz.

## IAM transverse

Travaux realises:

- Ajout d'un moteur IAM transverse avec role templates et compatibilite legacy.
- Separation claire:
  - AuthN sous `/auth`;
  - IAM/AuthZ sous `/api/v1/iam`.
- Ajout des primitives:
  - `role_template`;
  - `custom_labels`;
  - `WorkspaceIAMConfig`;
  - `AuthorizationEngine`;
  - manifestes capabilities.
- Enforcement Knowledge Capture avec feature flag et allowlist workspace.
- UI admin minimale:
  - matrice IAM;
  - membres;
  - roles templates;
  - labels;
  - flags.
- Corrections UX sur Governance / Members:
  - suppression du scroll horizontal;
  - dropdown roles utilisable;
  - meilleure lisibilite.

Etat actuel:

- IAM est actif pour les surfaces principales, tout en gardant les routes legacy compatibles.
- Les workspaces restent isoles; les routes admin passent par workspace courant.

## Secure Deposit / SFTP Andritz

Travaux realises:

- Ajout d'une capacite `SFTP / Secure Deposit`.
- Portail public `/deposit/:accessId` avec:
  - mot de passe de lien;
  - upload;
  - listing;
  - isolation par lien.
- API publique dediee sans JWT Agentium:
  - session depot;
  - listing fichiers;
  - upload staging.
- API interne `/api/v1/sftp`:
  - creation lien;
  - rotation mot de passe;
  - revoke;
  - staging queue;
  - promotion.
- Ajout du vrai SFTP sur port `2222`:
  - username = `access_id`;
  - password = mot de passe de depot;
  - support des dossiers hierarchiques;
  - preservation du lien Andritz public existant.
- Staging queue amelioree:
  - navigation par dossiers;
  - deplacement des fichiers d'un transfert avorte vers `transfert-aborted-2026-05-11`;
  - download ZIP de la queue;
  - download/preview par fichier;
  - meilleure separation workspace.
- Dockerisation du SFTP apres fin de transfert, en conservant liens, credentials et depots existants.

Etat actuel:

- Le depot Andritz historique reste actif.
- La queue est workspace-scoped.
- Les dossiers SFTP sont preserves cote Agentium.

## Dockerisation et runtime VM

Travaux realises:

- Mise en place d'une stack Docker Compose Agentium dediee:
  - `agentium-backend`;
  - `agentium-frontend`;
  - `agentium-worker-cpu`;
  - `agentium-rabbitmq`;
  - `agentium-pg`;
  - `agentium-kc`;
  - `qdrant`;
  - `agentium-sftp`.
- Nginx reste sur l'hote.
- Blue/green backend via port `8001`.
- Frontend conteneurise via `8081`.
- Postgres, Keycloak, Qdrant, MinIO et SFTP progressivement rationalises sans perte de donnees.
- Qdrant standardise avec volume existant.
- Ajout de RabbitMQ/Celery pour ingestion async.
- Ajout d'un runbook dockerisation.

Etat actuel verifie en fin de session:

- `agentium-backend` healthy;
- `agentium-frontend` healthy;
- `qdrant` healthy;
- `agentium-sftp` healthy;
- `agentium-pg` healthy;
- `agentium-kc` healthy.

## Ingestion async, Qdrant et RAG

Travaux realises:

- Integration du ledger `KnowledgeCollection` / `WorkerJob`.
- Ingestion async avec worker Celery.
- ObjectStore local partage backend/worker.
- Debut de canonicalisation documents/collections.
- Preparation du retrieval worker et durcissement SSE:
  - chunks d'erreur controles;
  - timeout;
  - `[DONE]` garanti;
  - persistence dans `Run.output_ref`.
- Integration OpenAI Responses API derriere flag.
- Correction de la resolution vector DB:
  - Qdrant est priorise sur la VM;
  - FAISS reste fallback/local.
- Correction des limites Qdrant:
  - `ulimit nofile` monte a `65535`;
  - correction des erreurs RocksDB `Too many open files`.
- Limitation de concurrence ingestion/sync pour eviter de saturer Qdrant.
- Correction critique du cache RAG:
  - avant: cache global par query/top_k;
  - apres: cache namespace par `workspace:vector_db:collection`.

Etat actuel:

- Les collections SENTINEL-CI sont bien en Qdrant.
- Le RAG multi-KB ne reutilise plus par erreur les resultats d'une autre collection.

## Mental model, Surface Catalog et Blueprints

Travaux realises:

- Mise a jour du mental model Agentium:
  - `Workspace`;
  - `Capability`;
  - `System`;
  - `Workbench`;
  - `Run`;
  - `Knowledge`;
  - `Review Queue`;
  - `Connector`;
  - `Governance`.
- Ajout d'une cartographie UI/API:
  - routes canoniques;
  - routes compatibility;
  - routes internal/public external;
  - ownership produit.
- Surface Map admin/dev.
- Workspace Blueprints:
  - export/import;
  - capture settings, systems, capabilities, skill bindings, presets, collections metadata-only.

Etat actuel:

- Andritz et SENTINEL-CI servent de cas reels, mais les patterns sont progressivement generalises au framework Agentium.

## Voice2Voice multi-provider

Travaux realises:

- Canonisation des capabilities voice:
  - `voice_realtime_session_v1`;
  - `voice_realtime_transcribe_v1`;
  - `voice_realtime_speak_v1`;
  - `voice_realtime_translate_v1`;
  - `voice_oracle_turn_v1`;
  - `voice_tandem_oracle_v1`.
- Runtime provider-neutral:
  - `cascade_openai`;
  - `openai_realtime`;
  - `local_stt`;
  - `local_tts`;
  - `local_realtime`;
  - `realtime_gpu`.
- Ajout de la resolution provider:
  - node;
  - system;
  - workspace;
  - global default.
- Ajout du mode demo pour masquer provider/modele dans l'UI.
- Alignement conceptuel KAME / Thinking Machines:
  - tandem oracle loop;
  - latest oracle wins;
  - micro-tours;
  - background reasoning.

Etat actuel:

- OpenAI Realtime est une lane possible, pas un verrou.
- Les providers locaux restent une contrainte d'architecture explicite.

## SENTINEL-CI - Workspace demo ministeriel

Travaux realises:

- Creation du workspace `sentinel-ci` en mode `demo`.
- Ajout d'une Mission Room immersive:
  - `/hypervisor/mission-room/cockpit`;
  - `/briefing`;
  - `/pilotage`;
  - `/agenda`;
  - `/messages`;
  - `/bibliotheque`;
  - `/projets`;
  - `/presse`;
  - `/reputation`;
  - `/veille`;
  - `/decisions`;
  - `/strategie`;
  - `/monitor`;
  - `/recherche`;
  - `/assistant`.
- Alignement charte graphique avec Agentium:
  - suppression du nom ARIA comme marque principale;
  - VIGIE devient l'assistant;
  - SENTINEL-CI reste le workspace/app;
  - theme plus sobre, institutionnel, confidentiel.
- Ministerialisation des vues:
  - Cockpit;
  - Presse;
  - Agenda;
  - Decisions;
  - Strategie;
  - Monitor.
- Ajout des capabilities gouvernementales:
  - `government_mission_room`;
  - `ministerial_daily_briefing`;
  - `open_intelligence_watch`;
  - `strategic_project_pilotage`;
  - `territorial_action_map`;
  - `executive_instruction_drafting`;
  - `visual_situation_watch`.

Etat actuel:

- SENTINEL-CI est une web app immersive gouvernee par Agentium OS, pas une app isolee.
- Les donnees restent demo-safe: synthetiques ou sources publiques.

## News Lab / veille presse

Travaux realises:

- Audit du systeme News Lab dans SENTINEL-CI.
- Ajout de sources Afrique / Afrique de l'Ouest / Cote d'Ivoire:
  - Africanews;
  - AllAfrica West Africa;
  - Jeune Afrique;
  - BBC Africa;
  - RFI Afrique;
  - France 24 Afrique.
- Run fonctionnel News Lab.
- Vue Presse ministerialisee:
  - "A retenir maintenant";
  - alertes prioritaires;
  - couverture de veille;
  - decisions et langage.
- Liaison Cockpit:
  - KPI presse;
  - top signaux;
  - etat dernier run.
- Les donnees consolidees et brutes sont synchronisees vers Knowledge.

Etat actuel:

- News Lab reste l'atelier analyste.
- Mission Room consomme sa synthese comme couche executive.

## Agenda institutionnel et actions cabinet

Travaux realises:

- Ajout du Workspace Calendar:
  - table `workspace_calendar_events`;
  - API `/api/v1/calendar`;
  - seed ministeriel;
  - connecteur `institutional_calendar`.
- Vue Agenda refaite:
  - timeline journee;
  - semaine compacte;
  - detail evenement;
  - conflits;
  - prochaines echeances;
  - actions ajouter/deplacer/annuler/synthese.
- VIGIE peut:
  - lire l'agenda;
  - creer un evenement;
  - deplacer un evenement;
  - annuler un evenement;
  - produire une synthese.
- Ajout des Action Plans:
  - `workspace_action_items`;
  - API `/api/v1/action-plans`;
  - lien possible avec agenda/news/carte;
  - actions cabinet dans la vue Decisions.

Validation de fin de session:

- Resume agenda VIGIE OK.
- Creation agenda par VIGIE OK.
- Annulation agenda par VIGIE OK.
- L'evenement QA cree a ete annule immediatement.

## Cartographie, Strategie et Monitor

Travaux realises:

- Ajout d'une primitive Workspace Map.
- Ajout de l'API `/api/v1/maps`.
- Ajout d'un Map Command Protocol:
  - `focus_zone`;
  - `set_layers`;
  - `set_basemap`;
  - `reset_view`;
  - `show_sources`;
  - `show_action_window`.
- Ajout de la vue Strategie.
- Ajout de la vue Monitor inspiree de Worldmonitor:
  - situation posture;
  - zones;
  - signaux presse;
  - projets;
  - agenda;
  - observations visuelles;
  - correlations.
- Plusieurs iterations cartographiques:
  - basemap geographique;
  - MapLibre/deck.gl;
  - meilleur contraste;
  - tentative d'alignement sur frontieres Cote d'Ivoire;
  - ajout d'un document dedie `docs/sentinel-ci-cartography.md`.

Etat actuel et limite:

- La carte est fonctionnelle et liee a VIGIE, mais le rendu n'a pas encore atteint le niveau attendu.
- Le point dur restant est l'alignement parfait des zones sur des frontieres administratives officielles fines, comparable a Worldmonitor.
- Prochaine vraie vague recommandee:
  - importer/versionner de vraies limites administratives Cote d'Ivoire;
  - rendre les zones comme choropleth administratif, pas comme polygones heuristiques;
  - clarifier la legende;
  - fournir 2D flat par defaut;
  - garder overlays Agentium uniquement au-dessus du territoire officiel.

## Visual Intelligence / webcam layer

Travaux realises:

- Ajout du connecteur `visual_streams`.
- Ajout des modeles:
  - `workspace_visual_sources`;
  - `workspace_visual_captures`;
  - `workspace_visual_observations`.
- Ajout de l'API `/api/v1/visual-intelligence`.
- Ajout d'une source snapshot publique Abidjan.
- Ajout d'une capture manuelle.
- Ajout d'analyse VLM optionnelle:
  - OpenAI vision possible;
  - contrat compatible provider local futur.
- Synchronisation vers Knowledge:
  - collection `sentinel-ci-visual-intelligence`.
- UI Monitor avec panneau flux visuels.

Etat actuel:

- Il ne s'agit pas d'un flux live continu.
- Le produit cible est plutot: snapshots/timelapses periodiques + analyse VLM + Knowledge sync.
- Pas de biometrie, pas de reconnaissance faciale, pas de suivi individuel.

## VIGIE - Assistant executif

Travaux realises:

- Ajout du concept generique `Assistant Profile`.
- Profil `vigie_executive`:
  - langage executif;
  - sources qualifiees;
  - mode demo sans fuite provider/modele;
  - controles techniques deplaces dans tracabilite/advanced.
- Knowledge Scopes multi-KB:
  - `Workspace.settings.knowledge_scopes`;
  - chat accepte `knowledge_scope`;
  - Run conserve `knowledge_scope`, `collections_touched`, `rag_context`, metrics.
- VIGIE est branche sur:
  - agenda;
  - action plans;
  - news;
  - carte;
  - visual intelligence;
  - RAG multi-collections.
- Correction du stream VIGIE qui pouvait bloquer:
  - quick replies;
  - handlers deterministes pour actions;
  - prevention de blocages backend.

Validation finale VIGIE:

- `agenda`: present, action `calendar_daily_summary`;
- `actions`: present, action `action_plan_status`;
- `map`: present, action `map_command`, commande produite;
- `visual`: present, action `visual_observation_read`;
- `news`: present, reponse executive, sources disponibles.

## Collections Knowledge SENTINEL-CI

Etat verifie en production en fin de session:

| Collection | Status | Documents | Chunks |
| --- | --- | ---: | ---: |
| `sentinel-ci-ministerial-briefs` | ready | 4 | 32 |
| `sentinel-ci-open-intelligence` | ready | 240 | 455 |
| `sentinel-ci-projects` | ready | 4 | 19 |
| `sentinel-ci-territorial-intelligence` | ready | 3 | 52 |
| `sentinel-ci-territorial-map` | ready | 6 | 26 |
| `sentinel-ci-visual-intelligence` | ready | 10 | 10 |

Scope VIGIE verifie:

- `sentinel-ci-open-intelligence`;
- `sentinel-ci-projects`;
- `sentinel-ci-ministerial-briefs`;
- `sentinel-ci-territorial-map`;
- `sentinel-ci-territorial-intelligence`;
- `sentinel-ci-visual-intelligence`.

Smoke RAG multi-KB apres correction cache:

- 6 collections touchees;
- 0 erreur;
- resultats retournes repartis entre les 6 collections;
- plus de pollution cache inter-collection.

Isolation verifiee:

- `sentinel-ci` avec scope `vigie` pointe vers les 6 collections Sentinel;
- `andritz` avec tentative `vigie` retombe sur `workspace_default` et `documents`;
- aucune fuite Andritz/Sentinel detectee dans ce smoke.

## Commits structurants recents

Extrait des derniers commits utiles:

- `04725ad Scope RAG cache by collection`
- `76db6fd Expose RAG collection scope metadata`
- `160c244 Raise Qdrant file descriptor limit`
- `7c12949 Limit RAG sync ingestion concurrency`
- `2fc656f Stabilize Sentinel knowledge sync on Qdrant`
- `925b1a2 Wire Sentinel knowledge scopes for Vigie`
- `9ac4820 Use official Cote d'Ivoire map boundaries`
- `d315fcf Align Sentinel map zones to country boundary`
- `745d526 Improve secure deposit queue navigation`
- `c678589 Improve Sentinel ministerial map readability`
- `29679da Add visual VLM analysis for Sentinel captures`
- `babc0a5 Add Sentinel webcam snapshot layer`
- `3eb229b Polish Sentinel visual monitor`
- `ecd32ff Polish Sentinel executive assistant and map`

## Tests et validations significatifs

Tests locaux passes lors de la session:

- `poetry run pytest app/tests/services/test_rag_cache.py app/tests/services/test_rag_context_worker.py app/tests/api/test_chat_stream_hardening.py -q`
  - resultat: `10 passed`
- tests calendrier/action plans/maps/mission-room vises lors des vagues precedentes;
- `npx tsc -p tsconfig.app.json --noEmit` et builds Angular prod executes sur les vagues UI/deploiement.

Checks VM repetes:

- backend health: `http://127.0.0.1:8001/api/v1/health`;
- frontend health: `http://127.0.0.1:8081/healthz`;
- Qdrant healthy;
- SFTP healthy;
- Postgres/Keycloak healthy;
- pulls/deploiements Docker sans recreation inutile des volumes.

## Risques residuels / prochaine passe recommandee

1. Cartographie ministerielle:
   - le rendu doit passer en vraies frontieres administratives officielles;
   - supprimer les polygones approximatifs;
   - clarifier couche/legende/source;
   - viser un rendu comparable a Worldmonitor, mais ministerialise et Agentium-native.

2. Reranker:
   - warning observe: `NoneType object is not callable`;
   - le fallback marche, mais le reranking n'est pas actif;
   - a corriger pour ameliorer la qualite C-HAH.

3. Metadonnees sources:
   - certains chunks reviennent sans `document_title`;
   - enrichir les metadonnees pour ameliorer la restitution VIGIE.

4. VIGIE tool calling:
   - les handlers deterministes sont robustes;
   - la prochaine etape est une couche tool registry plus explicite, auditable et visible dans Flow Builder.

5. Visual Intelligence:
   - passer de snapshots ponctuels a timelapses controles;
   - cadrer clairement les sources autorisees;
   - ajouter un tableau de fraicheur/cadence/analyse.

6. Blueprints:
   - verifier export/import complet de SENTINEL-CI apres toutes les nouvelles primitives;
   - s'assurer que le workspace peut etre recree from scratch.

## Notes operationnelles

- Ne pas commiter `docs/status-screenshots/` sauf demande explicite.
- `backend/poetry.lock` est reste non suivi pendant la session; verifier avant tout commit si ce fichier devient necessaire.
- Pour les deploiements Docker applicatifs usuels:
  - rebuild/restart `agentium-backend` et/ou `agentium-frontend` uniquement;
  - ne pas recréer Postgres, Keycloak, Qdrant, MinIO ou SFTP sauf migration infra explicite.
- Pour un changement documentation uniquement:
  - un `git pull --ff-only origin demo/agentic` sur la VM suffit;
  - pas besoin de redemarrer les conteneurs.

