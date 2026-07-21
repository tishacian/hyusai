# System 360 — protocole de validation pilote sans coaching

Objectif : recueillir aujourd'hui 1 à 2 observations terrain. Ce protocole produit une preuve pilote ; il ne permet pas encore de revendiquer le statut `user_validated`.

## Mise en place

- Placer le participant sur le System canari Showcase, sans expliquer les quatre tabs.
- Lancer un chronomètre séparé pour chaque question, avec une limite stricte de 60 secondes.
- Ne pas guider, pointer, reformuler la navigation ni expliquer un terme. Il est permis de répéter la question à l'identique.
- Après chaque réponse, demander : « À quel niveau de confiance, de 1 à 5 ? »

## Les quatre questions

| # | Question exacte | Critère de succès |
|---|---|---|
| 1 | « Comment ce System est-il construit ? » | Le participant choisit **Build** et cite au moins deux éléments réels parmi objectif, Capability, flow, Skills, Context ou configuration. |
| 2 | « Comment fonctionne-t-il actuellement ? » | Il choisit **Operate** et cite au moins deux signaux réels parmi Runs, santé, SLA, latence, coût, erreurs, tâches ou HITL, sans confondre une absence de mesure avec zéro. |
| 3 | « Que faudrait-il optimiser ? » | Il choisit **Steer**, identifie un outcome, une recommandation, une policy ou une simulation, et ne présente pas une simulation comme une mesure. |
| 4 | « Qui peut agir et qu'est-ce qui a changé ? » | Il choisit **Govern** et trouve à la fois une autorisation/contrainte effective et une trace d'audit ou de version. |

## Fiche à remplir par participant

- Participant pseudonymisé :
- Rôle : builder / operator / decision owner / governor / transverse
- Date et heure :
- SHA observé : `cfa3f616050bb5f75c9a3709219b52939e7ec0bd`

| Question | Temps (s) | Succès (0/1) | Confiance (1–5) | Élément cité | Confusion critique ? |
|---|---:|---:|---:|---|---|
| Construction |  |  |  |  |  |
| Fonctionnement |  |  |  |  |  |
| Optimisation |  |  |  |  |  |
| Droits et changements |  |  |  |  |  |

Commentaires libres :

## Qualification du résultat

Compter comme confusion critique : changement involontaire de System, Hypervisor pris pour une lens, simulation prise pour une mesure, permission déduite du rôle au lieu de la décision affichée, ou valeur manquante interprétée comme zéro.

Synthèse à consigner : nombre de succès sur 4, confiance moyenne, temps moyen et nombre de confusions critiques. Avec seulement 1 à 2 participants, publier le résultat sous le libellé `pilot_observation` ; le gate complet `user_validated` reste réservé à la campagne prévue avec cinq profils et ses seuils formels.
