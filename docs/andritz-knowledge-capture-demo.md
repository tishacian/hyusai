# Démo Knowledge Capture — scénario Andritz (5 minutes)

Ce scénario est **pédagogique** : les noms d’actifs, numéros de ticket et formulations sont **fictifs** mais calés sur le vocabulaire habituel des activités **hydro / service / automation** d’un groupe industriel type Andritz. La plateforme reste **générique** ; seul le *storytelling* est Andritz-oriented.

---

## 1. Message d’accroche (15 secondes)

> « Les manuels et les procédures Qualité décrivent *le quoi*. Ce qu’on perd quand un ingénieur service part, c’est le *pourquoi* en salle machine : quels signaux faibles on regarde en premier, quelle exception fait dérouter le diagnostic, et quelle trace dans SAP / le rapport d’intervention fait foi. Knowledge Capture prépare un entretien ciblé, évalue la réponse en direct, et sort une **proposition de mise à jour** reviewable — rien n’est ingéré sans validation. »

---

## 2. Données fake « précises » (à afficher ou à coller dans l’UI)

### 2.1 Workspace & contexte (story)

| Élément | Valeur fictive |
| ------- | -------------- |
| **Workspace** | `andritz` (démo) |
| **Context** (sélection UI) | `HYDRO Service — Europe Nord` |
| **Collection / KB** (story) | `runbooks-hydro-v4`, `spare-parts-critical`, `Metris-DCS-notes` |
| **Actif client** | Centrale **« Rivage-Lac »** — groupe **G2**, turbine **Kaplan**, automate **Metris** |
| **Contrat** | SLA **72 h** pour diagnostic à distance + escalade « critical » |

### 2.2 Ce que la KB contient déjà (story)

- Fiche procédure : *« vibration post-révision : contrôler serrage, relecture alignement »* (générique).
- Liste pièces critiques : palier guide, joint arbre, servomoteur régulation.

### 2.3 Ce qui manque (le « gap » métier que la démo illustre)

- **Pourquoi** l’équipe terrain hausse parfois la priorité *avant* d’avoir les mesures complètes.
- **Quel** indicateur Metris / historique SAP fait foi quand la vibration est « limite » mais pas hors spec.
- **Qui** valide une mise à jour runbook quand le client conteste la cause racine.

---

## 3. Champs à saisir avant « Prepare capture plan »

Copier-coller tel quel (ou paraphraser à l’oral).

**Objective**

```text
Capturer le raisonnement tacite des experts service hydro lorsqu'un client signale des vibrations sur G2 après une révision Kaplan : quels signaux Metris et quelles sources (SAP PM, rapport d'intervention, historique oscilloscope) tranchent avant de déclencher une escalade pièces ou un arrêt, et quelles exceptions ne sont pas couvertes par le runbook v4.
```

**Expert profile**

```text
Lead service hydro — 12 ans terrain, responsable escalades critiques Europe Nord.
```

**Duration minutes**

- Pour la **démo 5 min** : mettre **15** ou **20** dans l’UI (le produit calcule le plan en fonction de la durée) ; tu n’utiliseras qu’**une** question principale pour tenir le timing.

---

## 4. Script minute par minute (~5 min)

| Temps | Action | Parole suggérée |
| ----- | ------ | --------------- |
| **0:00–0:40** | Ouvrir `/knowledge/capture`, choisir le Context **HYDRO Service — Europe Nord** (ou équivalent dans ta démo). Coller objectif + profil. | « On ancre la session sur le périmètre knowledge et les ACLs du contexte — ici le service hydro. » |
| **0:40–1:10** | Cliquer **Prepare capture plan**. Montrer les **gaps** et l’**agenda** (2 phrases). | « Le système ne fait pas semblant que tout est dans la doc : il priorise des trous types *rationale*, *exceptions*, *signaux tacites*. » |
| **1:10–1:40** | Montrer la **première question** du plan ; clic pour **TTS** (ou lire à voix haute si pas de son). | « Première question orientée décision sur un cas réel post-révision. » |
| **1:40–3:00** | Coller la **Réponse experte A** (section 5) dans « Expert answer » → **Evaluate answer**. Montrer **verdict / score** et le **next prompt** ; optionnel : **TTS** sur la relance. | « L’évaluation est synchrone : on garde la précision et la traçabilité, pas seulement un joli micro. » |
| **3:00–3:45** | Si le verdict est *sufficient* et qu’un **next prompt** propose la question suivante : dire « on pourrait enchaîner » puis **sauter** pour gagner du temps. Sinon, traiter la relance avec **Réponse courte B** (section 5). | « En 5 minutes on ne fait pas toute la session — on montre le principe. » |
| **3:45–4:40** | **Create proposal** ; faire défiler le markdown (facts + open questions). | « Sortie : proposition structurée, pas ingestion automatique — revue métier obligatoire. » |
| **4:40–5:00** | **Accept proposal** (ou expliquer *reject / changes*) + phrase de clôture. | « C’est la matière pour enrichir la KB et alimenter le prochain RAG sans perdre la gouvernance. » |

---

## 5. Réponses toutes faites (drill down)

### 5.1 Réponse experte A — réponse « complète » (question sur la décision / les signaux)

À utiliser pour le **premier** envoi sur la question du type *décision difficile à retrouver dans la documentation* ou *signaux / diagnostic* (le plan peut formuler en français selon le gap).

**Texte à coller :**

```text
Sur Rivage-Lac G2, après une révision Kaplan, nous ne nous basons pas uniquement sur le seuil vibration ISO affiché dans Metris parce que le client a souvent déjà une charge variable sur le réseau. En salle machine je regarde d'abord la tendance spectrale sur les capteurs radiaux du palier guide — si l'énergie monte entre 2× et 3× ligne sans corrélation vitesse, je suspecte un problème de rigidité ou de serrage plutôt qu'un déséquilibre classique. Je croise ensuite le rapport d'intervention SAP PM 4500xxxx et la fiche de couple de serrage : si la dernière intervention mentionne un remplacement joint arbre et que le trend Metris est apparu moins de six heures après remise en eau, je fais monter la priorité interne en "critical" même si la valeur absolue est encore dans la tolérance usine, car nous avons déjà vu ce scénario conduire à une dégradation rapide du palier. Pour trancher avec le client, la source qui fait foi côté Andritz est le export trend Metris + la photo des capteurs dans le rapport d'intervention, pas seulement le commentaire téléphonique du contremaître. Un exemple typique : en 2023 sur un site comparable, un profil spectral similaire avec rapport PM silent sur le couple des brides a été résolu par un reserrage contrôlé et un re-run du léger balancing — documenté dans notre note interne SP-HYD-1127.
```

**Effet attendu (Phase 0)** : texte long, marqueurs *parce que*, *exemple*, *SAP*, *Metris*, *rapport* → score élevé, verdict typiquement **`sufficient`**. Le système peut proposer la **question suivante** du plan en `next_prompt`.

### 5.2 Réponse courte B — si une relance « précision » apparaît

Utiliser seulement si l’UI affiche une relance du type *précision* / *source*.

**Texte à coller :**

```text
Si le client conteste, j'ouvre le ticket CRM ServiceMax 27-4418 et je demande la courbe brute exportée depuis Metris sur 48 h parce que c'est la seule trace horodatée acceptée en revue de cause racine avec le client ; sans cet export, je ne valide pas de recommandation pièces.
```

**Effet attendu** : complète bien une relance « source / preuve » avec marqueurs *parce que*, *Metris*, *ticket*.

### 5.3 Réponse « à éviter » en démo (anti-pattern)

Ne pas utiliser, sauf si tu veux montrer une **relance** (timing +30 s).

```text
On vérifie les vibrations et on serre si besoin.
```

Trop court → verdict **`needs_precision`** ou **`partial`** et **follow-up** utile pour la pédagogie.

---

## 6. Transition oral vers la proposition

> « Si on s’arrêtait là dans un vrai atelier, on enchaînerait les autres questions du plan. Ici je **fige** la session : je génère la **Knowledge update proposal** — vous voyez les faits capturés, les questions ouvertes restantes, et le bloc prêt pour une future ingestion **après** validation du domaine expert et du Quality. »

---

## 7. Rappels pour le présentateur

- **Clé OpenAI** sur l’environnement de démo : sinon prévoir **collage texte** uniquement (la valeur métier reste visible).
- **Durée** : 5 minutes = une question riche + proposition ; ne pas lire toute la liste des gaps.
- **Conformité** : rappeler que les données ci-dessus sont **fictives** ; ne pas présenter comme des cas clients réels.

---

## 8. Corpus KB fictif à indexer (aligné démo)

Des **fichiers Markdown synthétiques** (runbook v4, pièces critiques, Metris, SAP PM, SLA, note SP-HYD-1127) sont prêts à l’upload pour enrichir la base **avant** la démo :

- Dossier : [`demo-data/andritz-kb/`](./demo-data/andritz-kb/README.md) — voir le `README.md` pour l’ordre d’ingestion et le rôle de chaque document.

Idée de narration : le RAG retrouve le **runbook générique** et l’**ordre PM exemple** ; la **réponse experte A** (section 5) apporte ce que ces documents ne formalisent pas encore — d’où l’intérêt de la **proposition** post-session.

---

## 9. Liens utiles

- Documentation technique feature : [`expert-knowledge-capture.md`](./expert-knowledge-capture.md)
- Runbook déploiement VM : [`vm-deploy-chat-runbook.md`](./vm-deploy-chat-runbook.md)
