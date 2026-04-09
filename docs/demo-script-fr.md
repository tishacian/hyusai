# Script Démo — Agent de Validation Documentaire Fournisseurs

**Durée :** 8-12 min | **URL :** http://217.182.104.99:8000 | **Mot de passe :** `Presight2026!`

---

## Avant de commencer

**Préparer :**
- Navigateur ouvert sur l'URL (pas encore loggé)
- 2 PDFs prêts pour l'upload (depuis `sample_data/`) :
  - `Vendor_Qualification_Form_Temple.pdf` — formulaire de qualification réel (Temple University)
  - `Supplier_Prequalification_IRW.pdf` — questionnaire prequalification fournisseur (Islamic Relief)
- Cette note imprimée ou sur un écran secondaire

**Message-clé à garder en tête tout du long :**
> Ce que vous voyez comme un agent unique est en réalité une exécution orchestrée de multiples étapes sous le capot. La plateforme est à la fois l'**interface agent** (la façade) et l'**orchestrateur** (le moteur).

---

## Ouverture (30s)

**Ce qu'on dit :**

> Nous allons vous montrer comment notre plateforme permet de créer, configurer et exécuter un agent IA dans un contexte enterprise. L'objectif n'est pas de montrer un produit fini, mais d'illustrer une capacité industrielle : comment on passe d'un besoin métier — ici la validation documentaire fournisseur en procurement — à un agent opérationnel en quelques minutes.

> Ce qui est important de comprendre : derrière ce qu'un utilisateur voit comme un simple assistant, la plateforme orchestre en réalité un pipeline complet — retrieval, analyse, validation, génération — avec traçabilité de bout en bout.

---

## Login (15s)

**Action :** Sélectionner un compte → saisir `Presight2026!` → cliquer Sign In

**Ce qu'on dit :**
> La plateforme dispose d'un contrôle d'accès par rôles, intégrable avec un fournisseur d'identité OIDC comme Keycloak. Chaque utilisateur a des permissions spécifiques.

---

## Step 1 — Création de l'Agent (45s)

**Actions dans l'interface :**
- Montrer le nom pré-rempli : `Vendor Compliance Agent`
- Montrer le type `Procurement`
- Lire le system prompt à voix haute (les 2 premières lignes)
- Cocher/décocher une capability pour montrer que c'est interactif

**Ce qu'on dit :**

> Première étape : on définit l'agent. Son identité, son périmètre, et ses instructions système. Ici, un agent de validation documentaire fournisseur.

> Le system prompt définit le comportement : l'agent vérifie les trade licenses, certificats d'assurance, états financiers, certifications réglementaires et NDA. C'est configurable, pas codé en dur.

> Les capabilities sont modulaires : on active le RAG Retrieval et le Document Parsing. On pourrait activer des APIs externes ou des sorties structurées selon le besoin.

**Valeur ajoutée à souligner :**
> Ce qui est fondamental, c'est que la plateforme est déclarative. On ne code pas un agent : on le configure. Et ce que vous voyez comme un agent unique cache en réalité un orchestrateur qui va coordonner plusieurs étapes — on le verra au Step 6.

**Action :** Cliquer **Next Step**

---

## Step 2 — Connexion au Modèle (45s)

**Actions dans l'interface :**
- Montrer OpenAI sélectionné (checkmark visible)
- Cliquer sur "Anthropic" ou "Self-hosted" pour montrer le multi-provider → revenir sur OpenAI
- Montrer le modèle GPT-4o et bouger le slider temperature
- Montrer les Retrieval Settings (Top-K, Vector weight, Similarity threshold)
- Optionnel : cliquer **Save** sur les Retrieval Settings

**Ce qu'on dit :**

> Deuxième étape : le choix du modèle. La plateforme n'est pas verrouillée sur un fournisseur. On peut basculer entre OpenAI, Anthropic, ou des modèles self-hosted via Ollama ou vLLM. C'est une architecture **model-agnostic**.

> Pour du compliance, on reste à temperature basse — 0.3 — pour des réponses précises et déterministes. Pour de la créativité, on monterait.

> En dessous, les paramètres de retrieval : combien de chunks on récupère (Top-K), le poids entre la recherche vectorielle et lexicale, le seuil de similarité minimum. Ces paramètres sont exposés et ajustables.

**Valeur ajoutée à souligner :**
> En production, le routage de modèles peut être piloté par des politiques — coût, latence, résidence des données. Un agent de qualification fournisseur en zone régulée pourrait être forcé sur un modèle local.

**Action :** Cliquer **Next Step**

---

## Step 3 — Base de Connaissances (1min 30s)

**Actions dans l'interface :**
- Montrer les 3 documents pré-indexés (Vendor Qualification Policy, ISO 9001, NDA Template) → cliquer sur un pour la preview
- Fermer la preview
- **ACTION LIVE** : drag & drop `Vendor_Qualification_Form_Temple.pdf` dans la zone d'upload
- Attendre le badge "Indexed" (quelques secondes)
- **ACTION LIVE** : drag & drop `Supplier_Prequalification_IRW.pdf`
- Attendre "Indexed"
- Montrer le pipeline RAG en bas : Parse → Chunk → Embed → FAISS → Hybrid Retrieval

**Ce qu'on dit :**

> La base de connaissances est le cœur du système RAG — Retrieval-Augmented Generation. L'agent ne devine pas, il cherche dans vos documents.

> Ici, trois documents de référence sont déjà indexés : la politique de qualification fournisseur, la checklist ISO 9001, et un template NDA. On peut les prévisualiser directement.

**Pendant l'upload (moment clé) :**

> Je vais maintenant uploader en direct deux vrais documents de procurement. Ce sont des formulaires de qualification fournisseur réels, publiquement disponibles.

> *(Drop du premier fichier)*

> Le système parse le PDF, le découpe en chunks, génère des embeddings vectoriels, et les indexe dans FAISS. C'est un pipeline complet qui s'exécute en temps réel.

> *(Drop du second fichier)*

> Et voilà — deux documents indexés en quelques secondes. L'agent pourra maintenant s'appuyer dessus pour ses analyses.

**Valeur ajoutée à souligner :**
> Le retrieval est hybride : BM25 pour la recherche lexicale exacte, plus recherche vectorielle sémantique. C'est la combinaison qui donne les meilleurs résultats en production — on ne rate ni les termes exacts ni le sens global.

**Action :** Cliquer **Next Step**

---

## Step 4 — Règles et Outils (45s)

**Actions dans l'interface :**
- Montrer le bandeau vert "5 rules auto-extracted from 3 knowledge base documents"
- Parcourir les 5 règles et leurs niveaux de sévérité
- Cliquer sur une règle pour voir la preview du document source
- Fermer la preview
- Cliquer **Edit rules** → montrer qu'on peut changer la sévérité (cliquer les flèches swap_vert) → cliquer **Done**
- Montrer les 2 outils : Knowledge Search et Rule Engine

**Ce qu'on dit :**

> Les règles de validation. Ce qu'on voit ici, c'est que la plateforme a analysé les documents de la base de connaissances et en a extrait 5 règles de conformité, classées par sévérité.

> Deux règles **CRITICAL** — Trade License et Insurance Certificate — qui bloquent l'approbation si absentes. Deux règles **MAJOR** — Financial Statements et Regulatory Certifications — qui nécessitent une remédiation. Et une règle **MINOR** — NDA — qui est advisory.

> Ces règles sont éditables : un compliance officer peut ajuster les niveaux de sévérité selon la politique interne.

> En bas, deux outils à disposition de l'agent : la recherche dans la base de connaissances et un moteur de règles de conformité.

**Valeur ajoutée à souligner :**
> L'agent ne fait pas que générer du texte — il orchestre de la logique. Les règles sont des politiques configurables, pas du code. Et en cliquant sur une règle, on voit la source documentaire d'où elle est issue — traçabilité complète.

**Action :** Cliquer **Next Step**

---

## Step 5 — Gouvernance et Audit (45s)

**Actions dans l'interface :**
- Montrer les 3 cartes : Access Control, Audit Trail, Execution Tracing
- Montrer le compteur d'events audit (s'il y en a)
- Montrer les recent audit events (s'ils sont affichés)
- Cliquer sur **Audit Logs** dans la sidebar → montrer la table des logs
- Cliquer sur **Access & Roles** dans la sidebar → montrer les utilisateurs, le provider Keycloak, les rôles
- Revenir dans le flow agent : cliquer **Agents** dans la sidebar

**Ce qu'on dit :**

> Avant d'exécuter l'agent, la gouvernance. Trois piliers visibles ici.

> **Contrôle d'accès** — intégration OIDC/SSO via Keycloak. Rôles Admin, User, avec isolation des permissions.

> **Audit trail** — chaque exécution de l'agent est loguée. Qui a exécuté quoi, quand, avec quel résultat.

> **Traçabilité d'exécution** — chaque étape du pipeline est capturée avec son timing en temps réel via Server-Sent Events.

> *(Si on navigue vers Audit Logs)* Ici la vue complète des événements d'audit, avec timestamp, type, acteur, et sévérité.

> *(Si on navigue vers Access & Roles)* Et ici la gestion des accès, avec les rôles, le provider d'identité, et les sessions actives.

**Valeur ajoutée à souligner :**
> La gouvernance n'est pas un module ajouté après coup — c'est intégré dans l'architecture dès le départ. C'est un point fondamental pour les déploiements enterprise, surtout dans des contextes régulés.

**Action :** Retourner sur Agents → avancer au **Step 6**

---

## Step 6 — Exécution Live (2-3 min)

C'est le moment clé de la démo. On montre l'agent en action.

### Première requête — Compliance partielle

**Action :** Cliquer sur la première suggestion : **TechCorp Solutions — Trade license OK, insurance OK, missing financial statements 2024-2025, ISO 27001 valid, NDA not submitted**

**Ce qu'on dit pendant que le pipeline s'exécute :**

> On soumet un dossier vendeur. TechCorp a fourni certains documents mais pas tous. Regardez ce qui se passe.

**Quand les tool cards apparaissent (pointer chaque carte) :**

> *(QueryRewriter apparaît)*
> D'abord, un **query rewriting** — la question est reformulée par GPT-4o-mini pour optimiser le retrieval. Ce n'est pas la question brute qui va dans la base.

> *(Router apparaît)*
> Le **router** sélectionne l'agent approprié — ici l'agent Procurement.

> *(KnowledgeRetriever apparaît)*
> Le **Knowledge Retriever** cherche dans notre base — hybride BM25 + vecteur. Il récupère les chunks les plus pertinents des documents qu'on a indexés.

> *(ComplianceEngine apparaît)*
> Le **moteur de conformité** applique les règles de validation qu'on a configurées au Step 4.

> *(ReportGenerator apparaît — c'est ici que le texte stream)*
> Et le **générateur de rapport** produit l'analyse de conformité complète via GPT-4o en streaming.

**Quand le rapport apparaît :**

> Le rapport est structuré : un résumé, puis le statut document par document avec la sévérité, un verdict global — ici "Partial Compliance" — et des recommandations concrètes.

> Ce qui est essentiel : chaque affirmation du rapport est **ancrée dans les documents de la base**, pas inventée. L'agent cite les exigences de la politique de qualification qu'on a indexée.

**Quand les métriques de qualité apparaissent (dernière carte) :**

> Et enfin, les **métriques de qualité en temps réel** : relevance, factuality, coherence, HHEM. Plus les latences — temps LLM et temps total du pipeline.

> La factuality mesure à quel point la réponse est fidèle aux sources. La coherence vérifie la cohérence interne du rapport. Le HHEM est un score composite qui combine ces dimensions.

**Valeur ajoutée à souligner :**
> Ce pipeline complet — du query rewriting à la génération du rapport avec métriques de qualité — s'exécute en moins de 10 secondes. Chaque étape est visible, tracée, et auditée. Ce n'est pas une black box.

### (Optionnel) Deuxième requête — Question libre

**Action :** Taper manuellement : `What documents are required for vendor qualification under our procurement policy?`

**Ce qu'on dit :**

> On peut aussi poser une question ouverte. L'agent va chercher dans la base de connaissances et répondre en citant la politique.

> Ça démontre que le même agent gère à la fois l'analyse structurée de dossiers et le Q&A libre sur les documents de référence.

---

## Closing (30s)

**Ce qu'on dit :**

> Pour résumer ce qu'on a vu :

> 1. **Création déclarative** d'un agent avec system prompt et capabilities modulaires
> 2. **Connexion model-agnostic** — multi-provider, paramètres exposés
> 3. **Base de connaissances RAG** avec ingestion live et retrieval hybride
> 4. **Règles de conformité** extraites des documents, éditables, avec niveaux de sévérité
> 5. **Gouvernance native** — audit trail, RBAC, traçabilité d'exécution
> 6. **Exécution transparente** — chaque étape du pipeline visible en temps réel, avec métriques de qualité

> Ce que vous avez vu est une **illustration simplifiée**. Les déploiements en production impliquent des couches additionnelles d'intégration — ERP, GED, IdP client — mais l'architecture est là, et elle est conçue pour scaler sur de multiples agents et use cases.

---

## Points de différenciation à placer naturellement dans la conversation

| Point | Où le placer | Formulation |
|---|---|---|
| **Orchestrateur, pas chatbot** | Step 1 / Step 6 | "Ce n'est pas un chatbot — c'est un pipeline orchestré avec des étapes spécialisées" |
| **Model-agnostic** | Step 2 | "Aucun vendor lock-in — on bascule entre providers selon les contraintes (coût, data residency, latence)" |
| **RAG hybride** | Step 3 | "BM25 + vecteur sémantique — la combinaison qui couvre à la fois la recherche exacte et le sens" |
| **Retrieval, pas hallucination** | Step 6 | "Chaque affirmation est ancrée dans vos données — grounded, pas hallucinated" |
| **Gouvernance native** | Step 5 | "L'audit et le RBAC sont architecturaux, pas ajoutés après coup" |
| **Métriques de qualité live** | Step 6 | "On ne fait pas confiance aveuglément au LLM — factuality, relevance, coherence sont mesurées en temps réel" |
| **Pipeline < 10s** | Step 6 | "Un pipeline complet de validation en moins de 10 secondes — query rewriting, retrieval, analyse, génération, métriques" |
| **Configurable, pas codé** | Step 4 | "Les règles sont des politiques — un compliance officer les ajuste, pas un développeur" |

---

## Si on vous pose des questions

| Question | Réponse |
|---|---|
| "C'est en production ?" | "C'est un démonstrateur fonctionnel. L'architecture est production-ready, le déploiement production nécessite l'intégration au SI client (IdP, ERP, GED)." |
| "Ça marche avec d'autres modèles ?" | "Oui, la couche LLM-as-a-Service supporte 20+ providers. On peut router par politique." |
| "Les documents sont stockés où ?" | "Vectorisés en local (FAISS). En production : Qdrant, Azure AI Search, ou Pinecone selon l'infra client." |
| "Et pour d'autres use cases ?" | "L'architecture est la même. On change le system prompt, la base de connaissances, et les règles. HR, Finance, Legal — même plateforme." |
| "RGPD / data sovereignty ?" | "Le modèle peut être self-hosted (Ollama, vLLM). Les données restent dans l'infra du client. L'audit trail couvre les accès." |
| "Et le coût ?" | "Tracking des tokens et du coût par modèle, par agent, par utilisateur. Optimisable via le routage intelligent." |
| "C'est quoi HHEM ?" | "Hughes Hallucination Evaluation Model — un score composite qui mesure le risque d'hallucination. Plus c'est bas, plus la réponse est fidèle aux sources." |
| "Combien de temps pour aller en prod ?" | "Architecture prête. Intégration IdP : 2-3 semaines. Migration DB : 1 semaine. Première release opérationnelle : 6-8 semaines." |

---

## Troubleshooting rapide

| Problème | Solution |
|---|---|
| Page blanche | `ssh omnirag-demo "curl http://localhost:8000/health"` |
| Serveur down | `ssh omnirag-demo "cd /home/ubuntu/omnirag && bash run.sh"` |
| Chat ne répond pas | Vérifier les logs : `ssh omnirag-demo "tail -50 /home/ubuntu/omnirag/server.log"` |
| Réponse lente | Normal — GPT-4o prend 5-8s pour un rapport complet. Le pipeline total fait ~10s. |
| Upload échoue | Vérifier la taille (max 10MB) et le format (PDF, DOCX, TXT, MD) |
