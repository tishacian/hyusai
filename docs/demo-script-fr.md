# Script Démo v2 — Agent Hub & Agent Builder

**Durée :** 10-15 min | **URL :** http://217.182.104.99:8000 | **Mot de passe :** `Presight2026!`

---

## Avant de commencer

**Préparer :**
- Navigateur ouvert sur l'URL (pas encore loggé)
- 2 PDFs prêts pour l'upload (depuis `sample_data/`) :
  - `Vendor_Qualification_Form_Temple.pdf`
  - `Supplier_Prequalification_IRW.pdf`
- Cette note imprimée ou sur un écran secondaire
- Mode sombre activé par défaut (toggle en haut du sidebar si besoin)

**Message-clé :**
> Ce que vous voyez comme un agent unique est en réalité une exécution orchestrée de multiples étapes sous le capot. La plateforme est à la fois l'**interface agent** (la façade) et l'**orchestrateur** (le moteur). papAI orchestre l'ensemble du pipeline.

---

## 1. Login (30s)

**Action :** Se connecter avec `thibaud.ishacian@presight.ai` / `Presight2026!`

**Ce qu'on dit :**
> Accès sécurisé par workspace, RBAC intégré. En production, c'est du Keycloak/OIDC/SSO.

**Points de démo :**
- Design professionnel, mode sombre par défaut
- Login glassmorphism (effet de profondeur)
- Transition fluide vers le hub

---

## 2. Agent Hub — Impact immédiat (2 min)

**Ce qu'on voit :** Le Hub avec 4 agents préconfiguré + KPIs.

**Ce qu'on dit :**
> Voici le Hub. Chaque agent est opérationnel immédiatement. Procurement pour la validation fournisseur, Legal pour l'analyse contractuelle, HR pour le support, Finance pour l'analyse financière. On voit les KPIs temps réel : agents actifs, documents indexés, latence moyenne.

**Actions :**
1. Survoler les cartes (effet de hover/glow)
2. Pointer les KPIs (4 agents actifs, latence < 3s)
3. **Cliquer sur "Procurement Agent"** pour le lancer directement

**Valeur ajoutée :**
- Outcome-first : pas besoin de configurer pour tester
- Multi-agent natif : pas un chatbot, un écosystème
- Monitoring intégré

---

## 3. Interaction avec l'Agent (3-4 min)

**Ce qu'on voit :** Le playground de chat avec le Procurement Agent.

### 3a. Question Q&A simple

**Prompt :** `What documents are required for vendor qualification under our procurement policy?`

**Ce qu'on dit pendant le streaming :**
> Regardez le pipeline en temps réel. 8 étapes visibles :
> 1. **Query Received** — Détection d'intent (Q&A vs validation)
> 2. **Query Rewrite** — Reformulation via GPT-4o-mini pour optimiser le retrieval
> 3. **Embedding** — Vectorisation de la query
> 4. **Retrieval** — Recherche hybride FAISS (vecteur + BM25)
> 5. **Context Filtering** — Filtrage des chunks pertinents
> 6. **Validation** — Vérification de cohérence
> 7. **Synthesis** — Génération par GPT-4o
> 8. **Evaluation** — Métriques de qualité (factuality, relevance, HHEM)

**Points de démo :**
- Chaque étape montre le modèle utilisé, la durée en ms
- Les métriques finales (barres de progression) donnent confiance
- La latence totale est affichée

### 3b. Test Voice (1 min)

**Action :** Cliquer sur le micro, dicter une question, puis activer le speaker.

**Ce qu'on dit :**
> Input/output vocal via Whisper (STT) et OpenAI TTS. Pensez à un opérateur terrain qui interagit vocalement avec l'agent.

### 3c. Deuxième prompt

**Prompt :** `Compare the qualification requirements for IT services vs. construction vendors`

**Ce qu'on dit :**
> Même pipeline, mais cette fois la query rewrite reformule pour une recherche comparative. Notez les métriques qui peuvent varier.

---

## 4. Intégrations (1 min)

**Action :** Cliquer "Integrations" dans le sidebar.

**Ce qu'on dit :**
> L'agent ne vit pas en isolation. Voici les connecteurs disponibles : Microsoft (Dynamics 365, Teams, SharePoint), canaux de communication (Telegram, WhatsApp, email), API REST, MQTT pour l'IoT, et les sources de données (PostgreSQL, S3). Les agents peuvent s'intégrer dans l'écosystème IT existant via papAI.

**Points de démo :**
- "Connected" pour REST API et PostgreSQL (actifs)
- "Available" pour les Microsoft/communications (prêts à activer)
- "Coming soon" pour WhatsApp et Elasticsearch

---

## 5. Orchestration (1 min)

**Action :** Cliquer "Orchestration" dans le sidebar.

**Ce qu'on dit :**
> Ici on voit le DAG d'exécution — les 8 étapes du pipeline qu'on a vu en action. papAI orchestre ce flux. Chaque composant a son modèle dédié. L'évaluateur de qualité en bout de chaîne assure la fiabilité des réponses.

**Points de démo :**
- Les composants avec leurs modèles (gpt-4o-mini, text-embedding-3-small, FAISS, gpt-4o)
- Les features d'orchestration (multi-agent routing, streaming, évaluation)
- Le workflow builder en "coming soon" pour la construction visuelle de pipelines custom

---

## 6. Knowledge Base (1 min)

**Action :** Cliquer "Knowledge Base", uploader un PDF.

**Ce qu'on dit :**
> La base de connaissances est alimentée par upload. Parse automatique (PDF, DOCX, Markdown), chunking, embedding, indexation FAISS. Le retrieval hybride combine vecteurs et BM25 pour une précision maximale.

**Actions :**
1. Montrer les stats (documents, chunks, dimensions)
2. Uploader un PDF → montrer l'indexation temps réel
3. Cliquer sur un document pour la preview

---

## 7. Agent Builder — Drill-down optionnel (2 min)

**Action :** Déplier "Agent Builder" dans le sidebar, naviguer dans les steps.

**Ce qu'on dit :**
> Pour ceux qui veulent construire un agent de zéro, le builder pas-à-pas est là. Nom, type, system prompt, choix du modèle (GPT-5, Claude Opus 4.6, ou self-hosted), RAG settings, tools, gouvernance.

**Steps à montrer rapidement :**
1. **Step 1** — Définition (nom, type, system prompt)
2. **Step 2** — Modèle (3 providers, RAG settings exposés)
3. **Step 3** — Knowledge (même KB, upload inline)
4. **Step 4** — Tools (8 intégrations, coming soon)
5. **Step 5** — Governance (audit trail, tracing)
6. **Step 6** — Execution (le playground)
7. **Step 7** — Save (persist dans la bibliothèque)

**Valeur ajoutée :**
- Pas juste un chatbot : un *builder* de pipeline complet
- Chaque réglage est transparent et contrôlable
- L'agent sauvé rejoint le Hub

---

## 8. Gouvernance (30s)

**Action :** Montrer Access & Roles et Audit Logs.

**Ce qu'on dit :**
> RBAC natif avec Keycloak. Audit trail exhaustif : chaque exécution, chaque upload, chaque acteur loggé. Enterprise-grade.

---

## 9. Theme Toggle (bonus, 10s)

**Action :** Cliquer le toggle dans le sidebar.

**Ce qu'on dit :**
> Dark/light mode, parce que chaque utilisateur a ses préférences.

---

## Closing (30s)

**Ce qu'on dit :**
> Ce que vous avez vu : une plateforme qui permet de créer, déployer et opérer des agents IA en enterprise. Multi-agent, multi-provider, multi-canal. Orchestration papAI sous le capot. Traçabilité, qualité mesurée, intégration dans l'écosystème IT existant. Et tout ça en mode self-service.

> La question n'est pas "est-ce qu'on peut faire un chatbot", c'est "comment on industrialise l'IA agentique en enterprise avec gouvernance, traçabilité et intégration native".

---

## FAQ Anticipées

| Question | Réponse |
|----------|---------|
| C'est en prod ? | C'est un démonstrateur fonctionnel. Le pipeline est réel (RAG, LLM, évaluation). Les intégrations Microsoft sont UI-only pour l'instant mais techniquement prêtes via papAI. |
| Pourquoi pas un framework agent (LangChain, CrewAI) ? | On est agnostique. Le moteur d'orchestration est papAI, qui peut intégrer n'importe quel framework. L'important c'est le contrôle du pipeline. |
| Quel modèle en prod ? | N'importe lequel. L'architecture est multi-provider. On démo avec OpenAI mais on supporte 20+ providers dont self-hosted. |
| Voice en prod ? | Oui, via API OpenAI (Whisper + TTS). Adaptable à d'autres providers (Azure, Google). |
| Les métriques sont fiables ? | Factuality et relevance sont calculées via cosine similarity avec le contexte source. HHEM est un indicateur de hallucination. C'est un début, extensible avec des benchmarks custom. |
| Sécurité des données ? | Déploiement on-premise possible. FAISS local. Pas de données envoyées à des tiers (hors LLM API, configurable). |

---

## Troubleshooting rapide

| Symptôme | Solution |
|----------|---------|
| Login refuse le mdp | `Presight2026!` (P majuscule, ! à la fin) |
| Agent ne répond pas | Vérifier la KB n'est pas vide (uploader un doc) |
| Streaming bloqué | Rafraîchir la page, re-login |
| Voice ne marche pas | Vérifier permissions micro dans le navigateur |
| Dark theme pas activé | Toggle en haut du sidebar (icône soleil/lune) |
