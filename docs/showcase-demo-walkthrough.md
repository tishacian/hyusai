# Agentium Showcase — Guide De Démo For Dummies

Ce guide sert à dérouler une démo d’Agentium devant un spectateur qui ne
connaît ni le produit, ni le vocabulaire “agentic”. L’objectif n’est pas de
montrer des écrans au hasard, mais de raconter une histoire simple :

> Agentium transforme des objectifs business en systèmes intelligents
> mesurables, gouvernés, améliorables et auditables.

Le workspace à utiliser est :

- Workspace : `Agentium Showcase`
- Slug technique : `agentium-showcase`
- Compte : `thibaud.ishacian@datategy.net`

## Message D’Ouverture

Avant de toucher l’interface, poser le cadre :

> “Agentium n’est pas un simple chatbot et ce n’est pas seulement un
> builder d’agents. C’est un cockpit pour piloter des systèmes
> intelligents en production : on définit des objectifs, on les relie à
> des capacités, on observe les exécutions, on mesure la qualité, puis on
> améliore le système en continu.”

La phrase clé :

> “Le mental model d’Agentium, c’est : System → Run → Evaluation →
> Decision → Action. On ne se contente pas de générer une réponse ; on
> sait pourquoi elle existe, combien elle vaut, si elle est fiable, et
> quoi faire quand elle ne l’est pas.”

## Parcours Rapide

Durée recommandée : 20 à 30 minutes.

1. Login et sélection du workspace vitrine.
2. Hypervisor : valeur, signaux, recommandations.
3. Systems : les systèmes intelligents comme actifs business.
4. Chat : expérience utilisateur et réponses sourcées.
5. Runs : traçabilité d’une exécution.
6. Quality : mesure de qualité et santé des composants RAG.
7. Review Queue : boucle d’amélioration actionnable.
8. Governance : audit, canonical answers, presets, SharePoint.
9. Conclusion : pourquoi c’est une plateforme complète.

## 1. Login Et Workspace

Aller sur :

```text
https://agentium.papai.ai
```

Se connecter avec le compte disponible, puis sélectionner le workspace :

```text
Agentium Showcase
```

Ce qu’il faut dire :

> “Ici, on est dans un tenant de démonstration complet. Tout ce que vous
> allez voir est synthétique, mais les données passent par les vraies
> tables, les vrais endpoints et les vrais écrans du produit.”

À porter à l’attention :

- Le workspace est isolé.
- Les données sont préchargées pour représenter une entreprise réaliste.
- Le parcours est multi-persona : direction, builder, opérateur, quality
  owner, admin.

## 2. Hypervisor — Vue Direction

Route :

```text
/hypervisor
```

Persona :

```text
Executive / Portfolio Owner
```

Ce que l’écran raconte :

- Le portefeuille d’IA a un coût.
- Il produit une valeur.
- Il génère des signaux.
- Il produit des recommandations actionnables.

Ce qu’il faut dire :

> “L’Hypervisor est la vue direction. Il répond à une question simple :
> est-ce que mes systèmes intelligents créent de la valeur, et où dois-je
> intervenir ?”

Pointer les éléments :

- Les métriques portfolio : valeur, coût, ROI, confiance.
- Les signaux récents.
- Le panneau `Recommendations`.
- Le bouton `SCAN`.

Expliquer `SCAN` :

> “Le bouton SCAN ne lance pas un gadget. Il relit les scores
> d’évaluation récents, détecte des patterns de dégradation, puis génère
> des Decisions dans l’Hypervisor. C’est la couche proactive de la
> plateforme.”

Valeur ajoutée :

- Pour la direction : visibilité ROI et risque.
- Pour le COO / Head of AI : priorisation des actions.
- Pour le client : preuve que l’IA est pilotée comme un actif, pas comme
  une boîte noire.

## 3. Systems — Les Systèmes Comme Actifs Business

Route :

```text
/systems
```

Persona :

```text
Builder / AI Architect
```

Systèmes vitrine :

- `Contract Risk Copilot`
- `Compliance Review Loop`
- `Tender Response Analyst`

Ce qu’il faut dire :

> “Dans Agentium, on ne vend pas un agent isolé. On modélise un System :
> un objectif, des capacités, des skills, un contexte, des règles de
> contrôle et un historique d’exécution.”

À montrer :

- Les noms des systèmes sont business, pas techniques.
- Chaque système a un objectif.
- Certains systèmes sont simples, d’autres ont un flow plus gouverné.
- `Compliance Review Loop` illustre le Human-in-the-loop.
- `Tender Response Analyst` illustre un flow debug-friendly.

Valeur ajoutée :

- Pour l’architecte : structurer l’IA en composants réutilisables.
- Pour le métier : comprendre ce que chaque système fait.
- Pour l’IT : gouverner des systèmes au lieu d’empiler des prompts.

## 4. Chat — L’Usage Métier

Route :

```text
/chat
```

Persona :

```text
Business User / Operator
```

Question de démo possible :

```text
What is the enterprise SLA?
```

Ou :

```text
Which contract terms should we flag as risky?
```

Ce qu’il faut dire :

> “Le chat est l’entrée naturelle pour l’utilisateur métier. Mais derrière
> chaque réponse, Agentium crée un Run, garde les sources, déclenche une
> évaluation et peut alimenter la boucle d’amélioration.”

À montrer :

- La réponse est ancrée dans le contexte du workspace.
- Les documents synthétiques sont ingérés dans la base de connaissance.
- Certaines réponses peuvent venir d’une canonical answer.

Expliquer canonical answer :

> “Quand une réponse est critique, par exemple une politique SLA ou une
> règle de conformité, on peut la figer comme réponse canonique. La
> prochaine fois que la même question est posée, Agentium n’improvise pas :
> il renvoie la réponse validée.”

Valeur ajoutée :

- Pour l’utilisateur métier : réponse rapide.
- Pour le compliance owner : cohérence et réduction du risque.
- Pour l’entreprise : les bonnes corrections deviennent réutilisables.

## 5. Runs — La Trace D’Exécution

Route :

```text
/runs
```

Persona :

```text
Operator / Platform Owner
```

Ce qu’il faut dire :

> “Un Run est une exécution réelle d’un System. C’est la preuve de ce qui
> s’est passé : input, output, coût, valeur, confiance, skills appelés,
> checkpoints et décisions.”

À montrer :

- Liste des runs.
- Ouvrir un run completed.
- Montrer l’input et l’output.
- Montrer la skill trail.
- Montrer les runs `replay` et `canonical_answer`.

Expliquer replay :

> “Quand une réponse est mauvaise, on ne se contente pas de la noter. On
> peut rejouer le même run avec des overrides : meilleur mode RAG,
> température plus basse, prompt plus strict. Le replay est lié au run
> parent, donc on garde l’historique de remédiation.”

Valeur ajoutée :

- Pour l’ops : debug et observabilité.
- Pour le métier : comparaison avant/après.
- Pour la gouvernance : traçabilité complète.

## 6. Quality — Mesurer La Fiabilité

Route :

```text
/observability
```

Persona :

```text
Quality Owner / AI Governance
```

Ce qu’il faut dire :

> “La plupart des plateformes s’arrêtent à la réponse. Agentium mesure ce
> qui se passe après : qualité, hallucination, composant fautif, tendance
> dans le temps.”

À montrer :

- Threshold monitoring.
- Component health.
- Les composants RAG :
  - Generator
  - Retriever
  - Rewriter
  - Router
  - Knowledge Base
- Les claims audités.

Expliquer la taxonomie :

> “On utilise une taxonomie inspirée de Giskard/RAGET. Si une question
> échoue, on ne dit pas seulement ‘la réponse est mauvaise’. On essaye de
> comprendre si le problème vient du retriever, du générateur, de la
> knowledge base ou du rewriter.”

Valeur ajoutée :

- Pour le quality owner : savoir quoi corriger.
- Pour le builder : éviter les optimisations à l’aveugle.
- Pour le client : auditabilité de la fiabilité.

## 7. Review Queue — La Boucle D’Amélioration

Route :

```text
/steering/review-queue
```

Persona :

```text
Quality Owner / Operator
```

Ce qu’il faut dire :

> “La review queue est là où la qualité devient actionnable. Un run passe
> sous un seuil, Agentium crée une Decision, propose une action et permet
> de corriger.”

À montrer :

- Un item `review_required`.
- Le score composite.
- Les raisons du breach.
- `ACTIVE SUGGESTION`.
- Boutons :
  - `ACCEPT`
  - `REJECT`
  - `RE-RUN`
  - `APPLY`

Expliquer les boutons :

- `ACCEPT` : c’était un faux positif, la réponse était acceptable.
- `REJECT` : le problème est confirmé.
- `RE-RUN` : on tente une réponse améliorée.
- `APPLY` : on applique la suggestion active et on crée un replay.

Phrase importante :

> “C’est ici que la plateforme devient game-changing : on passe d’un score
> passif à une boucle fermée. Evaluer, décider, corriger, apprendre.”

Valeur ajoutée :

- Pour l’opérateur : moins de friction.
- Pour l’équipe IA : meilleur signal d’amélioration.
- Pour le management : preuve que la qualité est pilotée.

## 8. Canonical Answers — Réponses Validées

Route :

```text
/governance/canonical-answers
```

Persona :

```text
Admin / Compliance / Knowledge Owner
```

Ce qu’il faut dire :

> “Certaines réponses ne doivent pas varier. Une politique SLA, une règle
> de conformité, une consigne contractuelle : on peut transformer une
> correction validée en réponse canonique.”

À montrer :

- Question.
- Réponse validée.
- `hit_count`.
- Source run / decision / feedback si disponible.
- Suppression possible.

Valeur ajoutée :

- Réduction des hallucinations sur sujets critiques.
- Cohérence des réponses.
- Capitalisation des corrections humaines.

## 9. Governance / Audit

Route :

```text
/governance/audit
```

Persona :

```text
Admin / Compliance / Security
```

Ce qu’il faut dire :

> “Toute action importante est tracée : feedback, replay, canonical
> answer, recommandation proactive, sync SharePoint. C’est indispensable
> pour passer de la démo à une plateforme gouvernable.”

À montrer :

- Événements `canonical_answer.created`.
- Événements `canonical_answer.hit`.
- Événements `run.replayed`.
- Événements `recommendation.proactive.generated`.
- Événement SharePoint simulé.

Valeur ajoutée :

- Pour compliance : auditabilité.
- Pour sécurité : responsabilité.
- Pour la direction : confiance dans l’usage de l’IA.

## 10. Presets — Configurer Le Comportement

Route :

```text
/presets/evaluation
```

Depuis `/presets`, cliquer sur :

```text
Evaluation thresholds
```

Ce qu’il faut dire :

> “Agentium permet de configurer les seuils de qualité. Le workspace est
> auto-onboardé : l’évaluation est activée par défaut, mais un admin peut
> ajuster ou désactiver.”

À montrer :

- Auto-evaluation ON.
- Seuil composite.
- Hallucination max.
- Sample rate.

Valeur ajoutée :

- Chaque client peut adapter les seuils.
- Les exigences ne sont pas hardcodées.
- Le pilotage qualité devient un réglage produit.

## 11. SharePoint — Connecteur Et Ingestion

Route :

```text
/connectors/sharepoint
```

Ce qu’il faut dire :

> “Le connecteur SharePoint permet de faire entrer les documents
> d’entreprise dans la base de connaissance. Ici, le workspace showcase
> contient un job de sync simulé pour montrer l’expérience opérateur.”

À montrer :

- Recent syncs.
- Job `showcase-guest-link`.
- Bouton `Prefill showcase key`.
- Collection `documents`.
- Fichiers téléchargés / ingérés.

À ne pas survendre :

> “Dans cette vitrine, le job SharePoint est simulé. Le pipeline Guest Link
> existe, mais une vraie sync nécessite une session capturée ou un OAuth
> configuré.”

Valeur ajoutée :

- Pour admin : connecter les sources documentaires.
- Pour le métier : le chat répond sur la connaissance interne.
- Pour IT : mode OAuth ou Guest Link selon les contraintes client.

## 12. Conclusion À Dire Au Spectateur

Phrase de synthèse :

> “Agentium n’est pas seulement un endroit où l’on parle à un modèle. C’est
> une plateforme pour créer, mesurer, gouverner et améliorer des systèmes
> intelligents. Le point différenciant, c’est la boucle fermée : un système
> produit un run, le run est évalué, une décision est créée, une action est
> appliquée, et la correction devient réutilisable.”

Les killing features à rappeler :

1. **Mental model business-first** : Systems, Capabilities, Runs,
   Decisions.
2. **Hypervisor** : valeur, ROI, signaux, recommandations.
3. **Evaluation loop** : score automatique, review queue, feedback.
4. **Actionability** : replay, active suggestion, apply.
5. **Canonical answers** : réponses validées, déterministes.
6. **Governance** : audit trail, presets, access.
7. **Extensibilité** : SharePoint, RAG, flows, skills, policies.

## Parcours Court 10 Minutes

Si le temps est limité :

1. Login → `Agentium Showcase`.
2. `/hypervisor` : montrer valeur + recommandations.
3. `/chat` : poser “What is the enterprise SLA?”.
4. `/runs` : ouvrir le run, montrer input/output/skills.
5. `/observability` : montrer component health.
6. `/steering/review-queue` : montrer APPLY / replay.
7. `/governance/canonical-answers` : montrer hit_count.
8. `/governance/audit` : montrer trace complète.

Message final :

> “Ce que vous venez de voir, c’est un cycle complet : usage, mesure,
> décision, correction, capitalisation.”

## Limites À Dire Honnêtement

Ne pas cacher ces points si on pose la question :

- Le job SharePoint du showcase est simulé.
- Le seed vitrine doit être relancé avec `--reset` pour garder une story
  propre.
- Les canonical answers peuvent être listées et supprimées, mais pas encore
  éditées depuis l’UI.
- Le workspace vitrine est unique dans l’environnement : les capability
  slugs `showcase_*` sont globaux.

Formulation recommandée :

> “La vitrine est volontairement synthétique, mais elle utilise les vrais
> objets de la plateforme. Les limites restantes sont connues et
> documentées ; elles ne changent pas la valeur du mental model.”
