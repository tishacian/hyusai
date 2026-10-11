# Agentium Andritz - Note de profil du chat transverse

Statut : note operatoire.

Workspace cible : `andritz`.

Surface cible : `Agentium Workspace Chat` / `/chat`.

Derniere mise a jour : 2026-06-18.

Objectif : documenter ce qu'il faut savoir sur la specification fonctionnelle,
l'alignement actuel, les profils en place, l'orchestration du retrieval et les
regles d'usage pour le chat transverse Andritz.

---

## 1. Synthese courte

Le chat transverse Andritz doit se comporter comme un assistant metier de
consultation documentaire, pas comme une interface de moteur de recherche.

L'utilisateur pose une question naturelle sur un projet, un equipement, une
piece, une procedure, une comparaison ou une synthese. Agentium doit alors :

- identifier le workspace et le systeme chat transverse ;
- appliquer le scope documentaire Andritz ;
- choisir le profil de retrieval adapte ;
- choisir le profil de reponse adapte ;
- produire une reponse factuelle, consolidee et citee ;
- masquer toute mecanique interne.

La reponse cible commence par le fait utile :

```text
La pompe utilisee pour le projet AKK200 est une Uraca KD724, associee au groupe
haute pression PHP. [1]
```

Elle ne doit pas commencer par une formule documentaliste :

```text
J'ai trouve dans les documents que la pompe utilisee semble etre...
```

Point important : le profil de reponse ne choisit pas les documents. Il faconne
la reponse a partir du contexte fourni par le retrieval. Si le retrieval donne
un mauvais contexte, le profil doit eviter l'hallucination, mais il ne peut pas
deviner le fait absent.

---

## 2. Couches de profil

Le mot "profil" recouvre plusieurs couches. Elles sont complementaires mais ne
font pas le meme travail.

### 2.1 Profil de navigation metier

Le profil de navigation simplifie l'UX pour les utilisateurs finaux metiers.

Configuration attendue dans `Workspace.settings` :

```json
{
  "navigation_profile": {
    "key": "business_end_user",
    "default_route": "/chat",
    "primary_surfaces": ["chat", "client360-pdr", "knowledge-capture"],
    "advanced_access": "admin_only"
  }
}
```

Effet attendu pour `andritz` :

- les non-admins voient un mini-shell metier ;
- seules les entrees `Chat transverse`, `Client360 PDR` et `Capture de
  connaissances` sont visibles ;
- les routes avancees du cockpit sont redirigees vers `/chat` ou
  `/knowledge/capture` ;
- les admins gardent le cockpit Agentium complet et peuvent previsualiser le
  mode metier.

Ce profil est une simplification UX. Il ne remplace pas les permissions backend
ni l'IAM.

### 2.2 Profil assistant workspace

Le workspace `andritz` utilise le profil assistant :

```text
andritz_spl_advisor
```

Role :

- pointer vers le scope documentaire Andritz ;
- appliquer un ton de conseiller technique ;
- activer le grounding documentaire adapte aux notices SPL et aux donnees
  non-wovens ;
- fournir les valeurs par defaut du chat transverse.

Emplacements utiles :

- `backend/scripts/setup_andritz_notices_spl.py`
- `backend/app/services/systems/bootstrap.py`
- `backend/app/tests/services/test_workspace_chat_system.py`

### 2.3 Profil de reponse industrielle

Le profil de reponse est porte par :

```text
industrial_answer_profile_v1
```

Role :

- classifier l'intention de la question ;
- choisir un profil de reponse ;
- injecter les consignes de style et de forme ;
- nettoyer les fuites de mecanique interne ;
- eviter les reponses contradictoires.

Emplacement principal :

```text
backend/app/services/industrial_answer_profile.py
```

---

## 3. Specification fonctionnelle

La specification fonctionnelle du chat transverse Andritz peut etre resumee en
sept principes.

### 3.1 Repondre a la question posee

La reponse doit traiter la demande utilisateur, pas raconter le chemin de
recherche.

Pour une question factuelle, la reponse doit etre courte :

```text
La largeur utile est de 3 600 mm. [1]
```

Pour une synthese projet, la reponse doit etre structuree et complete, sans
liste brute d'extraits.

### 3.2 Se fonder uniquement sur le contexte documentaire

Pour les faits workspace, projet, equipement, piece, procedure ou valeur
technique, la source de verite est le contexte documentaire fourni par le
retrieval et les fiches expertes validees.

Le modele ne doit pas completer par analogie avec un autre projet, une autre
machine ou une connaissance generale.

### 3.3 Consolider les faits multi-documents

Si plusieurs documents disent la meme chose, la reponse doit fusionner les
faits.

Mauvais comportement :

```text
- Le document A mentionne une pompe.
- Le document B mentionne une pompe.
- Le document C mentionne un groupe haute pression.
```

Comportement attendu :

```text
Le projet utilise une pompe haute pression Uraca KD724 dans l'ensemble PHP. Les
documents associes decrivent le groupe haute pression et les fonctions de
maintenance correspondantes. [1][2]
```

### 3.4 Citer sans exposer la mecanique

Les sources doivent etre citees sous forme d'identifiants numeriques quand elles
existent.

La reponse ne doit pas mentionner :

- `chunk` ;
- `score` ;
- `retrieval` ;
- `RAG` ;
- `Qdrant` ;
- nombre de documents candidats ;
- taux de confiance ;
- details de ranking.

### 3.5 Assumer l'insuffisance documentaire

Si le contexte ne contient pas le fait demande, la reponse doit le dire
clairement.

Elle ne doit pas faire :

```text
Je n'ai aucune information exploitable. Le projet utilise une pompe Uraca KD724.
```

Le garde-fou actuel detecte ce pattern et supprime le preambule contradictoire.

### 3.6 Eviter le ton documentaliste

Le style attendu est celui d'un expert metier qui repond, pas celui d'un moteur
de recherche qui decrit ce qu'il a trouve.

Formules a eviter :

- `J'ai trouve...`
- `Les sources indiquent que...`
- `Les documents mentionnent que...`
- `Selon les documents...`
- `Voici les elements trouves...`

Forme attendue :

```text
Le manuel couvre principalement l'unite d'hydroentanglement, le groupe haute
pression, le Jetlace set, les fonctions d'entrainement et les procedures de
maintenance associees. [1][2][3]
```

### 3.7 Garder les listes pour les vrais inventaires

Les listes sont utiles pour :

- inventaires transverses ;
- comparaisons ;
- pieces de rechange ;
- procedures en etapes ;
- demandes explicitement formulees en liste.

Pour une question directe, la liste a la Prevert degrade la reponse. La reponse
doit alors privilegier un paragraphe factuel court.

---

## 4. Alignement actuel avec la specification

### 4.1 Points alignes

Le systeme Andritz actuel aligne deja les elements principaux :

- le workspace `andritz` porte un scope documentaire dedie ;
- le systeme `Agentium Workspace Chat` est le point d'entree transverse ;
- `andritz_spl_advisor` est le profil assistant par defaut ;
- `industrial_answer_profile_v1` encadre les reponses ;
- le prompt interdit les termes internes ;
- les citations sont attendues sous forme numerique ;
- les questions transverses declenchent un retrieval plus exhaustif ;
- les reponses contradictoires `absence + fait affirme` sont filtrees ;
- les preambules documentalistes sont maintenant evites et nettoyes.

### 4.2 Patch de style deploye

Le patch deploye le 2026-06-18 renforce le comportement suivant :

- commencer par la reponse factuelle ;
- ne pas ouvrir par `J'ai trouve...` ;
- ne pas transformer une reponse factuelle en liste de sources ;
- reserver les listes aux inventaires, comparaisons et demandes explicitement
  listees ;
- nettoyer en post-traitement les preambules comme `Les sources indiquent que`.

Fichiers concernes :

```text
backend/app/services/industrial_answer_profile.py
backend/app/agents/procurement_agent.py
backend/app/services/systems/bootstrap.py
backend/app/tests/services/test_industrial_answer_profile.py
```

Tests associes :

```bash
cd backend
poetry run pytest app/tests/services/test_industrial_answer_profile.py
poetry run pytest app/tests/services/test_workspace_chat_system.py
```

### 4.3 Points de vigilance restants

Le principal risque restant n'est pas le profil de reponse, mais le scoping du
retrieval.

Le diagnostic AKK200 a montre que le planner pouvait filtrer le corpus sur des
pages de navigation (`menu`, `index`, `section_I`, `section_II`) et exclure les
sections techniques utiles (`section_IV`, groupe haute pression, PHP, Jetlace,
Drive).

Symptome utilisateur :

- reponse pauvre ;
- impression que l'assistant ne connait que le sommaire ;
- refus prudent mais frustrant ;
- biais vers des sections peu interessantes du manuel.

Cause probable :

- shortlist documentaire trop etroite ;
- ranking base sur le code projet et le nom de fichier ;
- top 20 coupe avant les sections techniques ;
- facts/document scope pouvant introduire du bruit cross-project.

Correctifs recommandes :

- elargir l'allowlist projet pour les questions projet/equipement ;
- injecter les hits exacts metadata avant le filtre `document_filename` ;
- demoter les fichiers `menu`, `index`, `accueil`, `pictures`, frames ;
- renforcer les gardes cross-project quand un code projet est explicite ;
- faire traiter `project_summary` comme une demande potentiellement exhaustive.

---

## 5. Mecanique runtime du chat transverse

### 5.1 Entree utilisateur

L'utilisateur interagit avec `/chat`.

En mode navigation metier :

- le system selector est masque ;
- le lien Flow est masque ;
- l'utilisateur est oriente vers le chat workspace transverse ;
- l'ajout de fichiers reste une action secondaire si disponible ;
- la capture de connaissances reste accessible via `/knowledge/capture`.

### 5.2 Resolution du systeme

Le frontend identifie le systeme workspace chat actif et envoie la question au
backend avec le systeme cible.

Le backend applique ensuite les defaults du flow du systeme :

- assistant profile ;
- knowledge scope ;
- source policy ;
- retrieval defaults ;
- answer policy ;
- prompt contract.

Fichiers utiles :

```text
frontend-ng/src/app/features/chat/chat-workspace.component.ts
backend/app/api/v1/endpoints/chat.py
backend/app/services/systems/bootstrap.py
backend/app/services/systems/flow_manifest.py
```

### 5.3 Grounding

Le chat Andritz est un chat metier documentaire.

Pour les faits workspace, il doit s'appuyer sur le contexte fourni. En mode
`business_interpretation`, les demandes documentaires ou industrielles doivent
eviter l'invention de faits.

La politique de source Andritz favorise :

- references exactes ;
- preservation des termes utilisateur ;
- types de references industriels ;
- citations ;
- rejet des sources d'autres projets quand la question est projet-specifique.

### 5.4 Profil de reponse

Apres application des defaults du flow, le backend classe la question via
`resolve_answer_profile()`.

Le resultat est stocke dans `answer_profile_decision` et injecte dans le prompt
via `answer_policy_prompt()`.

Le post-traitement `apply_answer_policy_to_text()` nettoie ensuite la sortie
finale.

---

## 6. Profils de reponse

### 6.1 Vue d'ensemble

| Profil | Declencheurs typiques | Forme attendue | Retrieval associe |
| --- | --- | --- | --- |
| `precise_fact` | `Quelle pompe...`, `Quelle pression...`, `Combien...` | Reponse courte, valeur/reference/unite | Scope cible, pas de contexte inutile |
| `project_summary` | `Resume le projet AKK200`, `Synthese projet` | Synthese structuree par themes | Devrait etre large sur le projet |
| `transversal_inventory` | `Quels projets utilisent...`, `Liste toutes les pompes...` | Inventaire consolide | Exhaustive/deep |
| `equipment_detail` | `Fiche technique`, `Details pompe`, `Caracteristiques` | Fiche consolidee par attributs | Cible equipement + contexte technique |
| `comparison` | `Compare`, `difference`, `vs` | Tableau ou sections comparatives | Sources pour chaque objet compare |
| `insufficient_context` | Pas de question ou contexte inutilisable | Absence claire, sans invention | Aucun fait ajoute |

### 6.2 `precise_fact`

But : repondre au fait demande, sans decor.

Exemple :

```text
Question : Quelle pompe est utilisee dans le projet AKK200 ?

Reponse cible :
La pompe utilisee est une Uraca KD724, dans l'ensemble haute pression PHP. [1]
```

Regles :

- commencer par la valeur ou reference ;
- inclure unite et condition si disponibles ;
- ne pas ajouter l'historique du projet ;
- ne pas lister les documents consultes.

### 6.3 `project_summary`

But : produire une synthese projet exploitable.

Exemple de structure :

```text
AKK200 concerne une ligne non-wovens avec une unite d'hydroentanglement et un
ensemble haute pression. Les elements documentes couvrent principalement les
fonctions de production, les sous-ensembles Jetlace/PHP, les interfaces
d'entrainement et les points de maintenance.

Points techniques documentes :
- Unite : ...
- Equipements : ...
- Donnees d'exploitation : ...
- Maintenance : ...
- Limites documentaires : ...
```

Regles :

- grouper par themes ;
- eliminer les repetitions ;
- citer les sources utiles ;
- ne pas faire une liste brute de sections ;
- nommer les limites si le corpus ne couvre pas tout.

### 6.4 `transversal_inventory`

But : repondre a une question transverse sur plusieurs projets ou documents.

Exemple :

```text
Question : Quels projets utilisent une pompe Uraca ?

Reponse cible :
Les projets documentes avec une pompe Uraca sont :
- AKK200 : Uraca KD724, groupe haute pression PHP. [1]
- ...

Je ne qualifie cette liste d'exhaustive que pour les sources effectivement
couvertes par le retrieval de ce tour.
```

Regles :

- fusionner les doublons ;
- garder les references equipement ;
- ne pas presenter un echantillon comme exhaustif ;
- expliciter les limites documentaires quand necessaire.

### 6.5 `equipment_detail`

But : faire une fiche technique consolidee.

Exemple :

```text
La pompe documentee pour AKK200 est rattachee au groupe haute pression PHP. Sa
fonction est d'alimenter l'unite d'hydroentanglement. [1]

Caracteristiques documentees :
- Type / reference : ...
- Fonction : ...
- Conditions d'exploitation : ...
- Maintenance : ...
- Pieces associees : ...
```

Regles :

- commencer par la conclusion technique ;
- consolider par attribut ;
- ne pas inventer les references manquantes ;
- eviter le catalogue source par source.

### 6.6 `comparison`

But : comparer uniquement ce qui est documente.

Regles :

- utiliser un tableau si cela rend la comparaison plus lisible ;
- ne comparer que les dimensions disponibles ;
- nommer les trous documentaires ;
- ne pas extrapoler d'un projet vers un autre.

### 6.7 `insufficient_context`

But : refuser proprement quand le contexte ne permet pas de repondre.

Exemple :

```text
Je n'ai pas d'information documentaire exploitable sur la pompe du projet AKK200
dans le contexte fourni.
```

Regles :

- ne pas ajouter de fait apres l'absence ;
- proposer le manque documentaire de facon precise si possible ;
- ne pas exposer la mecanique interne.

---

## 7. Orchestration du retrieval

### 7.1 Scope documentaire

Le chat transverse Andritz part d'un knowledge scope workspace.

Scope principal :

```text
andritz-spl-knowledge-experiment
```

Collections associees :

```text
andritz-manuals-bba120-pilot
andritz-notices-techniques-spl-pilot
andritz-non-wovens-france-excel-pilot
```

Role :

- permettre les questions transverses ;
- couvrir les notices techniques SPL ;
- integrer les essais et donnees metier non-wovens ;
- garder un seul point d'entree utilisateur.

### 7.2 Planification

Le planner construit un `CorpusPlan`.

Il decide notamment :

- collections a interroger ;
- filtres metadata ;
- scope par document ;
- intent retrieval ;
- mode dense/sparse/hybride ;
- budgets ;
- profil de latence ;
- nombre de sources affichees.

Elements observes dans les traces :

```text
latency_profile
retrieval_profile
top_k
candidate_pool_k
synthesis_k
source_display_k
filters
scope_reason
dense_policy
```

### 7.3 Detection des codes projet

Pour des requetes comme `AKK200`, le planner detecte un code projet et cherche a
restreindre la recherche aux documents correspondants.

Ce comportement est utile pour eviter la pollution cross-project.

Il devient dangereux si :

- la restriction est trop precoce ;
- les documents retenus sont seulement des menus/sommaires ;
- les sections techniques sont exclues ;
- le classement repose trop sur le nom de fichier.

### 7.4 Retrieval exhaustif

Le profil `transversal_inventory` active aujourd'hui une exigence de retrieval
exhaustif.

Effet :

- `deep_retrieval = true` ;
- `latency_profile = deep` ;
- `retrieval_profile = deep_async` ;
- budgets plus hauts.

Recommandation : `project_summary` devrait beneficier d'une strategie plus large
quand un code projet explicite est present, car une synthese projet exige de
parcourir plusieurs sections et pas seulement les premiers fichiers du manuel.

### 7.5 Reranking et synthese

Apres retrieval, les chunks/documents candidats sont synthetises pour constituer
le contexte fourni au modele.

Le profil de reponse intervient apres cette etape.

Ordre logique :

```text
Question utilisateur
  -> resolution workspace/system/profile
  -> planning corpus
  -> retrieval
  -> synthesis/context
  -> answer profile
  -> generation
  -> post-processing answer policy
  -> reponse citee
```

---

## 8. Lecons du diagnostic AKK200

### 8.1 Observation utilisateur

L'utilisateur a observe un feeling etrange :

- l'assistant donnait surtout des informations de menu/accueil ;
- les reponses semblaient documentaires mais peu utiles ;
- la question sur la pompe ne trouvait pas l'information technique attendue ;
- la synthese projet restait superficielle.

### 8.2 Diagnostic

Le probe a montre que, pour plusieurs questions AKK200, le retrieval etait
filtre sur 20 documents du type :

```text
AKK200__English version__files__menu__accueil.html
AKK200__English version__files__menu__index.html
AKK200__English version__files__menu__menu.html
AKK200__English version__files__pictures__...
AKK200__English version__files__section_I__...
AKK200__English version__files__section_II__...
```

Des documents techniques AKK200 existent pourtant dans le corpus, par exemple
autour de :

```text
section_IV
Hydroentanglement-unit
High pressure set
PHP
Jetlace set
Drive
```

Conclusion : la donnee existe, mais le filtre documentaire peut l'exclure.

### 8.3 Interpretation

Le profil de reponse n'etait pas la cause principale. Il a plutot evite de
fabriquer une reponse quand le contexte etait pauvre.

Le probleme principal etait :

```text
retrieval planning / document scope
```

Le probleme secondaire etait :

```text
style de reponse trop documentaliste
```

Le probleme secondaire est corrige par le profil de reponse. Le probleme
principal necessite une evolution du planner.

---

## 9. Regles de redaction des reponses

### 9.1 Forme preferree

Pour une question factuelle :

```text
<reponse directe>. [source]
```

Pour une question projet :

```text
<synthese courte>

<themes documentes>

<limites documentaires si necessaire>
```

Pour une question transverse :

```text
<phrase de cadrage>

- <projet/equipement> : <fait consolide>. [source]
- ...

<limite d'exhaustivite si necessaire>
```

### 9.2 Formules interdites ou deconseillees

Eviter :

```text
J'ai trouve...
Les sources indiquent que...
Les documents mentionnent que...
Voici les informations trouvees...
Dans les documents indexes...
Le retrieval a retourne...
```

Preferer :

```text
La pompe utilisee est...
Le projet couvre...
Les elements documentes sont...
La documentation disponible ne precise pas...
```

### 9.3 Gestion des sources

Les citations doivent etre utiles mais secondaires.

Bon :

```text
La pompe utilisee est une Uraca KD724. [1]
```

Moins bon :

```text
Source [1] : mentionne Uraca KD724.
Source [2] : mentionne pompe.
Source [3] : mentionne groupe haute pression.
```

### 9.4 Gestion des limites

Si une information n'est pas presente :

```text
La documentation disponible ne precise pas la reference de la pompe. Elle
documente seulement le groupe haute pression PHP et ses procedures associees.
[1]
```

Ne pas dire :

```text
Je n'ai rien trouve, mais la pompe est probablement...
```

---

## 10. Usage operateur des profils

### 10.1 Ajouter ou modifier un assistant profile

Verifier :

- `Workspace.settings.assistant_profiles` ;
- `assistant_profile_default` ;
- `default_knowledge_scope` ;
- `grounding.default_mode` ;
- `grounding.strict_guard` ;
- `source_policy` ;
- `retrieval_defaults`.

Ne pas dupliquer un profil si un ajustement de `industrial_answer_profile_v1`
suffit.

### 10.2 Modifier le style de reponse

Toucher en priorite :

```text
backend/app/services/industrial_answer_profile.py
```

Puis verifier :

```text
backend/app/agents/procurement_agent.py
backend/app/services/systems/bootstrap.py
```

Ajouter un test dans :

```text
backend/app/tests/services/test_industrial_answer_profile.py
```

### 10.3 Modifier le retrieval

Toucher plutot :

```text
backend/app/services/rag/corpus_planner.py
backend/app/services/rag/context.py
backend/app/services/rag/retrieval_policy.py
```

Ajouter ou mettre a jour des golden tests :

```text
backend/app/resources/retrieval_golden/
backend/app/tests/services/test_rag_context_worker.py
backend/app/tests/services/test_retrieval_policy.py
```

### 10.4 Modifier la navigation metier

Toucher plutot :

```text
frontend-ng/src/app/core/navigation-profile.service.ts
frontend-ng/src/app/app.routes.ts
frontend-ng/src/app/shell/
frontend-ng/src/app/features/workspace/general.component.ts
backend/alembic/versions/
```

Verifier :

- non-admin Andritz redirige vers `/chat` ;
- `/client360` reste accessible dans le mini-shell metier ;
- `/knowledge` redirige vers `/knowledge/capture` ;
- `/systems/:id/capture` redirige vers `/knowledge/capture?systemId=:id` ;
- admin conserve le cockpit complet ;
- workspace sans `navigation_profile` conserve le shell standard.

---

## 11. Checklist de validation

### 11.1 Tests style/profil

```bash
cd backend
poetry run pytest app/tests/services/test_industrial_answer_profile.py
poetry run pytest app/tests/services/test_workspace_chat_system.py
```

### 11.2 Tests frontend si navigation modifiee

```bash
cd frontend-ng
npx tsc -p tsconfig.app.json --noEmit
npm run check:i18n
npm run build
```

### 11.3 Probes retrieval

Pour un diagnostic retrieval, capturer :

- query utilisateur ;
- `answer_profile_decision` ;
- `retrieval_profile` ;
- `scope_reason` ;
- `filters` ;
- sources affichees ;
- sources techniques attendues mais absentes.

Questions de regression utiles :

```text
Quelle pompe est utilisee dans le projet AKK200 ?
Detaille le contenu du manuel AKK200.
Resume le projet AKK200.
Quels projets utilisent une pompe Uraca ?
Donne la liste des pieces de rechange du projet AKK200.
```

### 11.4 Smokes post-deploiement

```bash
curl -fsS https://agentium.papai.ai/api/v1/health
```

Sur la VM docker :

```bash
cd /home/ubuntu/omnirag
bash scripts/deploy-vm.sh --check-only --branch demo/agentic
```

---

## 12. Decision log

### 2026-06-18 - Ajustement du style de reponse

Decision :

- garder le profil documentaire strict ;
- ne pas transformer le chat en moteur de recherche visible ;
- commencer les reponses par le fait ;
- nettoyer les preambules documentalistes ;
- garder les listes pour les demandes qui justifient une liste.

Raison :

- l'utilisateur final metier attend une reponse exploitable ;
- les formulations `j'ai trouve` donnent une impression de recherche brute ;
- les listes d'extraits degradent la comprehension ;
- la citation doit soutenir la reponse, pas la remplacer.

### 2026-06-18 - Diagnostic AKK200

Decision :

- separer le probleme de style et le probleme retrieval ;
- corriger immediatement le style ;
- garder comme chantier retrieval le scoping projet trop etroit.

Raison :

- les documents techniques AKK200 existent dans le corpus ;
- le retrieval peut les exclure par filtre `document_filename` ;
- le profil de reponse ne doit pas compenser un mauvais retrieval par invention.

---

## 13. Resume pour onboarding

Pour travailler sur ce sujet, retenir ceci :

1. Le profil de navigation simplifie l'UX Andritz pour les non-admins.
2. Le profil assistant `andritz_spl_advisor` branche le chat sur le bon scope.
3. Le profil `industrial_answer_profile_v1` faconne la reponse, pas le retrieval.
4. Le retrieval planner choisit les documents ; c'est le point critique pour la
   qualite factuelle.
5. Une bonne reponse Andritz commence par le fait metier, cite ensuite, et ne
   parle jamais de sa mecanique interne.
6. Si le contexte est pauvre, l'assistant doit nommer le manque documentaire.
7. Si un code projet est explicite, les sources d'autres projets doivent etre
   traitees comme suspectes sauf demande transverse explicite.
