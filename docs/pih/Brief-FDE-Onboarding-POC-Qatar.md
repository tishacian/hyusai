# Brief interne — Onboarding FDE · POC Agentium on-prem au Qatar (PIH)

**Confidentiel Datategy · Juillet 2026 · FDE : Fayçal Benaissa (titre client :
Agentic Tech Lead — on-site delivery lead du pilote) · Interlocuteur
d'onboarding : Thibaud Ishacian**

Bienvenue. Ce brief te donne tout ce qu'il faut pour être opérationnel sur le
POC PIH : le contexte commercial, ce qu'est Agentium, le périmètre du POC
(3–4 agents, déploiement on-prem), la stack, ton rôle, et ton plan de première
semaine. Tu pars de zéro chez Datategy : rien n'est supposé acquis.

---

## 1 · Le contexte en 5 minutes

- **Le client** : PIH (Power International Holding), grand conglomérat qatari
  (construction, industrie, agroalimentaire, services). Programme **« AI
  Factory »** : industrialiser la production d'agents IA à l'échelle du groupe
  — l'ambition affichée est de plusieurs centaines d'agents à terme.
- **Où on en est** : PIH a lancé un RFI, nous avons répondu (réponse v8 +
  annexes de pricing), nous sommes **shortlistés**. Une soutenance de 2h a eu
  lieu (deck + démo live), et les évaluateurs PIH ont un accès hands-on à un
  workspace **Showcase** Agentium hébergé chez nous.
- **La prochaine marche** : un **POC on-prem au Qatar, 3–4 agents**, pour
  prouver que la plateforme et notre modèle de delivery tiennent en conditions
  réelles chez eux. C'est là que tu interviens. Le POC est l'antichambre du
  pilote puis du programme complet — ce qu'on y démontre conditionne un deal
  pluriannuel.
- **Notre positionnement** (à connaître, car tout le monde chez PIH l'a
  entendu en soutenance) : Agentium comme **usine à agents gouvernée** —
  pas un chatbot, pas un framework à assembler. Chaîne canonique
  `System → Flow → Run → Evaluation → Décision → Ledger`, replay des runs,
  audit complet, souveraineté du déploiement (« what you evaluate is what you
  get » : la même plateforme se déploie en SaaS, on-prem ou air-gapped).
- **Sensibilités à respecter** :
  - **Jamais de référence aux Émirats (UAE)** dans un document ou une
    conversation côté PIH — sensibilité géopolitique. KSA est OK.
  - Références clients publiques utilisées : Renault Group, Mobilize
    Financial Services, Andritz, RATP, SNCF, Société du Grand Paris, APRR.
  - Aucune donnée client (Andritz ou autre) ne doit apparaître dans les
    démos/environnements PIH — tout est synthétique ou anonymisé.
  - Le commercial (prix, tiers S/M/C, récurrent) est géré par Mehdi/Thibaud ;
    en cas de question pricing côté client, tu renvoies vers eux.

## 2 · Agentium — le modèle mental (stable, même si l'UI bouge vite)

Agentium est en développement très actif : l'UI évolue chaque jour, mais le
modèle d'objets est stable. Tout s'accroche à une chaîne :

> **System → Flow → Run → Evaluation → Décision → Ledger**

| Objet | Ce que c'est | Où ça se voit |
|---|---|---|
| **System** | Une capacité métier gouvernée (ex. « Hydro Plant Insights »). Porte ses flows, runs, métriques, preuves d'audit. | Portfolio / System 360 |
| **Flow** | La définition exécutable — un DAG visuel de **skills typés**, assemblé dans le Flow Builder. | Flow Builder |
| **Skill** | Unité de travail typée et réutilisable (requête SAP, appel LLM, dispatch RPA…). Les connecteurs « contribuent » des skills au catalogue. | Palette de nœuds / catalogue |
| **Run** | Une exécution : stateful, resumable, tracée pas à pas (I/O, timing, coût), **rejouable** (Rerun). | Runs / détail de run |
| **Décision / Gate** | Checkpoint human-in-the-loop dans un run, avec règles d'expiration. | Détail de run / inbox |

**System 360** = 4 perspectives sur le même objet : **Build** (flows &
skills), **Operate** (runs & incidents), **Steer** (coût/valeur/ROI — le
Hypervisor), **Govern** (décisions, preuves d'audit).

Briques importantes pour le POC :

- **Connecteurs** : SAP HANA Cloud (config chiffrée par workspace, test &
  query, skill `sap_hana_query_v1`), **RPA Bridge** (contrat REST générique
  vers un orchestrateur — mappe 1:1 vers UiPath Orchestrator ; un mock répond
  dans le Showcase), pattern connecteur SQL réutilisable pour Databricks.
- **Models & Providers** : portail de routage LLM par workspace (Azure AI
  Foundry câblé ; supporte l'inférence auto-hébergée type vLLM/Ollama — c'est
  le mode pertinent en on-prem).
- **Orchestration** : triggers (cron, webhooks signés HMAC, arrivée de
  fichier), gates durables, run inbox pour les process longs.
- **Document Center** : ingestion/indexation documentaire et RAG à l'échelle
  (Qdrant en backend vectoriel).

## 3 · Le POC — périmètre et critères de succès

**Calendrier et organisation (fixés avec le sponsor, 23 juillet)** :

- **Semaine du 28 juillet** : PIH nous envoie les prérequis techniques et un
  **premier use case** (via leur Business Analyst) pour évaluation.
- **2–8 août** : **déplacement sur site au Qatar** (fenêtre demandée par le
  sponsor).
- La boucle use case a un **double objectif explicite** du sponsor :
  1. On répond avec les **prérequis et questions** nécessaires pour compléter
     le use case (notre grille d'intake / design card fait ce travail).
  2. Chaque itération sert à **calibrer le process d'échange** entre le CoE,
     PowerMind et PIH : quels contenus capturer, sous quel format, quand un
     échange direct avec les demandeurs métier est nécessaire. Autrement dit,
     la *façon* dont on traite le use case est évaluée autant que la réponse
     elle-même — soigne la forme, documente la méthode, chronomètre le
     turnaround.

- **Format** : 3–4 agents en conditions réelles, sur une infrastructure
  **on-prem chez PIH** (ou tenancy dédiée qu'ils contrôlent), données PIH.
- **Méthodologie de capture** : la chaîne est outillée de bout en bout —
  grille d'intake (`docs/pih/Use-Case-Intake-Template-PIH.xlsx`) pour le
  triage, puis les templates méthodologie delivery (alignés ISO/IEC 42001 &
  12792, dans `docs/render/out/`) : **Business Requirements** (personas,
  As-Is → To-Be, KPIs) → **Target Operating Model** (value streams
  humain+agent, HITL, RACI) → build → **QA Acceptance Record** (PV de recette
  avec gates golden-set pour le go-live). Utilise-les tels quels : c'est notre
  méthodologie vendue dans le dossier.
- **Sélection des agents** : à figer avec PIH au kickoff via nos **design
  cards** (une page par agent : périmètre, systèmes touchés, golden set,
  critères d'acceptation). Attends-toi à un mix représentatif de leur
  demande : au moins un agent **SAP** (lecture — ex. insights/reporting sur
  données ERP), un agent **documentaire/RAG** (Document Center sur un corpus
  PIH), et un agent avec **orchestration/RPA** ou human-gate. C'est
  volontairement le triptyque démontré en soutenance.
- **Ce qu'on doit prouver** (c'est le vrai livrable, au-delà des agents) :
  1. La plateforme **s'installe et tourne chez eux** — souveraineté réelle.
  2. Un agent se construit **vite** avec le Flow Builder et le catalogue de
     skills (notre pitch usine : la vitesse vient de la réutilisation).
  3. **Gouvernance démontrable** : traces complètes, replay, gates, ledger —
     à montrer sur les runs du POC, pas sur des slides.
  4. **Évaluation objective** : chaque agent validé contre son **golden set**
     (jeux de cas de référence — les golden sets construits sur données PIH
     sont IP PIH et restent chez eux, c'est un engagement de notre réponse RFI).
- **Ce que le POC n'est pas** : pas un développement produit custom pour PIH,
  pas un engagement de volume, pas une négociation commerciale. Si un besoin
  produit remonte (feature manquante), il redescend vers l'équipe core via
  Thibaud — tu ne forkes rien.

## 4 · L'architecture on-prem que tu vas déployer

Le déploiement est **docker-compose** (référence vivante : la VM de démo
`omnirag-demo`). Services :

| Service | Rôle |
|---|---|
| `agentium-backend` | API FastAPI (Python) — cœur plateforme |
| `agentium-frontend` | UI Angular (`frontend-ng`) |
| `agentium-worker-cpu` | Workers d'exécution (Celery/RabbitMQ) |
| `agentium-kc` | Keycloak — IAM, invitations, SSO (realm `papai-org`) |
| `agentium-pg` | PostgreSQL — base plateforme (et base Keycloak) |
| `qdrant` | Base vectorielle (Document Center / RAG) |
| `agentium-minio` | Stockage objet S3-compatible |
| `agentium-rabbitmq` | Bus de messages |
| `agentium-livekit` (+ agent) | Temps réel / voix |
| `agentium-sftp` | Dépôt sécurisé de fichiers entrants |

**Qui déploie quoi** : l'installation initiale est **anticipée et jouée par
Thibaud à distance** dès que PIH fournit l'accès à l'infrastructure (VM +
SSH/VPN) — tu n'as pas à découvrir le déploiement sous pression sur site.
Toi, tu **reprends la main ensuite** : exploitation au quotidien, upgrades
épinglées pendant le POC, et capacité à re-déployer seul si l'accès distant
est coupé (certains environnements on-prem finissent fermés). D'où la
répétition générale en semaine 1 : tu dois savoir le faire, même si tu ne le
fais pas en premier.

Points d'attention on-prem au Qatar :

- **Compose & env** : `docker/compose.agentium.yml` + fichiers
  `docker/env/*.env`. Le déploiement épinglé par SHA passe par
  `scripts/deploy-vm.sh` (déploie par service, vérifie les healthchecks et
  les labels OCI `revision`). Lis ce script en premier : c'est notre façon
  de déployer proprement.
- **Prérequis à obtenir de PIH pour le déploiement anticipé** : VM(s)
  provisionnée(s) avec Docker, accès SSH (idéalement via VPN/bastion), DNS et
  certificats TLS, ouverture des flux nécessaires (SMTP sortant, provider
  LLM le cas échéant, registre d'images ou transfert des images hors-ligne).
  C'est la première checklist à faire signer au kickoff — chaque jour de
  retard d'accès décale l'installation.
- **SMTP** : Keycloak envoie les invitations/reset par email — il faudra un
  relais SMTP joignable depuis leur réseau (chez nous : OVH ; chez PIH : leur
  relais interne, à qualifier au kickoff).
- **LLM** : en on-prem, prévoir soit une sortie contrôlée vers Azure AI
  Foundry (région Qatar), soit de l'inférence auto-hébergée (vLLM/Ollama sur
  GPU fournis par PIH) — les deux modèles sont décrits dans notre réponse
  RFI ; la décision appartient à PIH, toi tu qualifies la faisabilité réseau/GPU.
- **Accès SAP/Databricks/UiPath** : les connecteurs existent, mais les accès
  (comptes de service, endpoints, sandboxes) sont fournis par PIH — c'est
  systématiquement le chemin critique. Pousse la checklist d'accès dès le
  jour 1.

## 5 · Ton rôle de FDE

Tu es notre présence technique en première ligne chez le client :

- **Opérer** la plateforme on-prem après l'installation initiale (jouée à
  distance par Thibaud) : upgrades épinglées, santé des services, sauvegardes
  PG/MinIO/Qdrant — et être capable de re-déployer seul si besoin.
- **Construire les 3–4 agents** avec le Flow Builder et le catalogue de
  skills, en binôme avec le CoE (nearshore) qui te backe sur le build.
- **Faire vivre la gouvernance** : golden sets, runs d'évaluation, replays en
  séance devant le client — c'est notre différenciateur, montre-le à chaque
  occasion.
- **Remonter le terrain** : besoins produit, frictions, signaux commerciaux —
  vers Thibaud (technique/delivery) et Mehdi (commercial). Tu es nos yeux sur
  place ; un signal remonté tôt vaut de l'or.
- **Tenir la ligne sur le discours** : mental model stable, plateforme en
  développement actif (c'est assumé et dit au client), pas de promesses de
  features datées, pas de chiffres commerciaux.

## 6 · Ta première semaine

**Jour 1–2 — le dossier et la plateforme (chez nous)**

1. Lire : la réponse RFI (`docs/pih/RFI-PIH-AI-Factory-Response-v8.docx`),
   le deck de soutenance (`docs/render/out/Datategy-PIH-Shortlist-Presentation.pptx`),
   la note d'onboarding participants (`docs/pih/Agentium-Showcase-Onboarding-PIH.md`)
   et `docs/mental-model.md`.
2. Obtenir un compte sur le workspace **Showcase** et dérouler soi-même le
   parcours : ouvrir un System, éditer le flow SAP hydro insights dans le
   Flow Builder, l'exécuter, inspecter la trace, faire un Rerun, parcourir
   connecteurs et Models & Providers.
3. Cloner le repo `omnirag`, monter backend (`backend/`, venv + pytest) et
   frontend (`frontend-ng/`, `npx ng build`) en local.

**Jour 3–4 — le déploiement**

Rappel : l'installation chez PIH sera anticipée et jouée à distance par
Thibaud. Ces deux jours servent à ce que tu saches **opérer et re-déployer**
l'environnement, pas à faire l'install initiale toi-même.

4. Étudier `docker/compose.agentium.yml`, les env files et
   `scripts/deploy-vm.sh` ; accès SSH à la VM de démo pour voir un
   déploiement sain de référence.
5. **Répétition générale : déployer Agentium from scratch sur une VM vierge**
   (même topologie que la cible PIH), avec SMTP et un provider LLM configurés.
   Objectif : autonomie complète le jour où l'accès distant n'est plus
   possible.

**Jour 5 — préparation client**

6. Passer en revue avec Thibaud : la grille d'intake use case
   (`docs/pih/Use-Case-Intake-Template-PIH.md`) et le premier use case reçu
   du BA PIH, la checklist d'accès (réseau, SAP, comptes de service, GPU,
   SMTP), et le calendrier (déplacement 2–8 août).
7. Point discours/sensibilités (section 1) + logistique Qatar.

## 7 · Contacts & rituels

| Sujet | Qui |
|---|---|
| Delivery, technique, arbitrages POC | Thibaud Ishacian |
| Commercial, relation PIH, pricing | Mehdi Chouiten |
| Build backup (CoE) | Équipe CoE — pôle build (à préciser au kickoff) |
| Comptes PIH côté client | 5 évaluateurs invités sur le Showcase (b.timothy, m.bakr, n.abdulrahman, s.abdulla @powerholding.com · z.mandouli @powermindinc.com) |

Rituels proposés : point quotidien 15 min avec Thibaud pendant le POC,
weekly écrit (avancement par agent, blocages accès, signaux client).

---

*Une règle simple pour finir : chez PIH, tout ce que tu montres doit être
reproductible devant eux — un run tracé et rejouable vaut mieux que dix
slides. C'est exactement la promesse qu'on a vendue.*
