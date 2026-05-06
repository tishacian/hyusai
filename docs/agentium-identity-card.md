# Carte d’identité Agentium (alignée au mental model)

Version courte pour onboarding produit et démo. La source normative reste
[`mental-model.md`](./mental-model.md) ; cette carte en extrait la forme stable et relie la
boucle livrée en Vague E (E1.5 / E5 / showcase).

---

## En une phrase

**Agentium** est un cockpit pour piloter des **systèmes intelligents** en entreprise :
objectifs métier, capacités et politiques, exécutions mesurées, gouvernance et amélioration
continue — pas seulement un chat ou un builder d’agents isolé.

---

## Promesse valeur

| Axis | Ce qu’Agentium apporte |
| ---- | ---------------------- |
| **Alignment** | Un **System** relie un objectif à des capacités réelles (skills, RAG, politiques). |
| **Observabilité** | Chaque réponse passe par des **Runs** traçables (coût, latence, contexte). |
| **Qualité** | Les **Evaluations** scorent les sorties ; les seuils et presets rendent la mesure systématique. |
| **Action** | Les **Decisions** (Hypervisor / Steering) matérialisent acceptation, rejet ou recommandations ; la boucle peut aller jusqu’au **replay**, au **feedback** et aux **réponses canoniques**. |
| **Gouvernance** | Audit, politiques, HITL, connecteurs avec traçabilité — le contrôle est explicite, pas implicitement « prompt only ». |

---

## Chaîne métier canonique (Vague E)

Le fil conducteur produit :

```text
System → Run → Evaluation → Decision → Action
```

- **System** — Déclaration d’intention : objectif, graph d’exécution, contexte, politiques.
- **Run** — Instance d’exécution (chat, moteur, réponse canonique sans LLM, replay).
- **Evaluation** — Score composite, dimensions (dont attribution **composants RAG** quand applicable).
- **Decision** — Proposition humaine ou machine (review, recommandation proactive, patch de politique).
- **Action** — Replay avec overrides, application de suggestion, accept/reject avec **feedback**,
  promotion vers **réponse canonique**, etc.

Ce schéma est déroulé pédagogiquement dans
[`showcase-demo-walkthrough.md`](./showcase-demo-walkthrough.md).

---

## Entités persistantes (rappel)

Aligné sur [`mental-model.md`](./mental-model.md) §0.1 : **Workspace**, **System**,
**Capability**, **Skill**, **Context**, **ControlPolicy** / **AdaptivePolicy**, **Run**,
**EvaluationScore**, **Decision**, **Impact**, plus les extensions Vague E (**EvaluationFeedback**,
**CanonicalAnswer**, **EvaluationPreset**, lineage **parent_run_id**).

---

## Personas cockpit (lisible en navigation)

| Persona | Où vivre dans l’app | Résumé |
| ------- | ------------------- | ------ |
| **Executive / portfolio** | Hypervisor, métriques agrégées | Vue valeur, risque, tendances ; recommandations **SCAN**. |
| **Opérateur / SRE** | Runs, observabilité, connecteurs | Santé d’exécution, jobs, intégrations. |
| **Gouvernance / compliance** | Audit, presets, réponses canoniques | Traçabilité, seuils, réponses approuvées. |
| **Builder / PM technique** | Builder, Systems, Chat | Composition du système, tests utilisateur, citations RAG. |

Le workspace vitrine [`showcase-workspace.md`](./showcase-workspace.md) mappe ces personas sur des données seed.

---

## Frontières honnêtes

- Multi-tenant et RBAC avancés : isolation testée ; rôles custom et marketplace restent hors périmètre court terme (cf. mental model « remaining »).
- **E4.2** (release engineering SharePoint) peut être différé sans bloquer la story évaluation ;
  le connecteur et la démo showcase documentent les limites ([`showcase-gaps.md`](./showcase-gaps.md)).
- Simulation offline (« what-if » policy alternative sur run rejoué) : **E6** encore ouverte.

Pour l’état précis au fil du temps : [`vague-e-plan.md`](./vague-e-plan.md) et
[`production-demo-map.md`](./production-demo-map.md).
