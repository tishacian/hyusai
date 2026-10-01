# Agentium Showcase — QA utilisateur du 1er octobre 2026

> Évolution du cadrage : le demandeur a retenu une nouvelle démo **e-commerce — réclamations et remboursements**, décrite dans le [brief dédié](../showcase-ecommerce/BRIEF.md). La préparation PR to PO/Data Demo ci-dessous correspond à la piste initiale et ne constitue plus le plan du nouveau scénario.

Le parcours réel **Work → Operational Analysis → résultat → exécution → audit → retour à l’exécution** fonctionne sur `https://agentium.papai.ai`, dans le workspace `agentium-showcase`. La trame complète de 35–40 minutes n’est pas encore prête : PR to PO, Retention Board, les datasets et les modèles attendus ne sont pas disponibles dans ce workspace au moment du contrôle.

Les défauts corrigés dans ce lot sont validés sur un build local avec des réponses API simulées. Ils ne sont pas déployés sur la VM. La révision de production observée dans la trace est `65767cb606d6681d118a8b2ed73e603b40d302b4`. La branche `ux/l40-demo-qa-utilisateur` inclut aussi le lot C3 précédent (`3847de8`), qui explicite les limites PostgreSQL et la provenance des aperçus HANA.

## Parcours réellement essayé

Connexion et sélection de Showcase, puis visites de Work, MCP, HANA, Data, Models, Systems, Observabilité, Impact en mode présentation et de l’exemple Operational Analysis. Les pages ont été contrôlées après leur chargement, en français et à 1440 × 1000.

Une seule nouvelle exécution synthétique a été déclenchée depuis **Analyser l’exemple** :

- [Exécution `73cd8d35-4fe6-45e7-bd03-55789da97f72`](https://agentium.papai.ai/runs/73cd8d35-4fe6-45e7-bd03-55789da97f72), terminée en 21,89 secondes, avec cinq nœuds et trois invocations de skills.
- Résultat affiché : **4 ordres, 35 minutes de dépassement net, 3 ordres en retard**. Les données sont explicitement synthétiques NorthForge.
- **Examiner ce résultat** ouvre la trace ; **Journal d’audit de cette exécution** retrouve un événement `experience.binding.invoked` associé au même `run_id` ; **Voir l’exécution** revient à la trace.
- Le mandat historique est `not_configured`, et l’interface annonce l’absence de preuve. Cette exécution ne valide donc pas un mandat appliqué ni un circuit HITL.
- Le contrôle numérique Python a tourné ; le contrôle automatique de qualité affiché dans la trace reste « Non exécuté ». Le premier ne valide pas la prose du modèle.
- Le coût enregistré est 0,012 USD, avec couverture et facturation non vérifiées. Aucune économie métier n’est démontrée.

[Capture du résultat réel](screenshots/prod-operational-analysis-result.png).

## Défauts corrigés et preuves visuelles

| Observation utilisateur | Correction locale | Validation |
| --- | --- | --- |
| L’avertissement MCP est presque illisible en thème clair. | Couleurs sémantiques et statut accessible pour les avertissements MCP/HANA et leurs erreurs. | Axe sur les composants, clair et sombre. |
| « Ouvrir les systèmes » présente un contraste de 2,42:1 en thème sombre. | Bouton secondaire avec tokens du thème ; Enregistrer reste l’action principale. | Le contrôle de contraste passe. |
| Le formulaire HANA affiche des titres, boutons et aides en anglais dans une interface française. | Traductions FR/EN, typographie lisible, boutons et champs adaptés aux deux thèmes. | Connexion simulée au clavier et retour d’état en français. |
| L’aide du mot de passe HANA fait partie de son nom accessible. | Libellé explicite et aide liée par `aria-describedby`, champ vide pour conserver le secret enregistré. | Ciblage du champ par son nom et requête de test sans mot de passe. |
| Les colonnes de l’aperçu HANA demandent un défilement horizontal. | Zone nommée et accessible au clavier, tables sélectionnées avec `aria-pressed`, cibles d’au moins 24 px. | Flèche droite à 1024 × 768 ; pas de débordement horizontal de la page. |
| Work expose « Run has high hallucination rate (33.3%) » et « Run below composite threshold (69/100) ». | Messages automatiques connus traduits ; valeurs conservées, virgule française ; titres personnalisés conservés tels quels. | Tests unitaires et navigateur FR/EN, clair/sombre. |
| Le résumé Work affiche « 1 applications ». | Forme singulière. | Vérification FR/EN dans le navigateur. |

| Avant : production | Après : build local, API simulées |
| --- | --- |
| [Work](screenshots/prod-work-before.png) | [Work en français](screenshots/local-work-fr-light.png) |
| [MCP en thème clair](screenshots/prod-mcp-before.png) | [MCP en thème sombre](screenshots/local-mcp-dark.png) |
| Formulaire HANA partiellement anglais et badges peu contrastés | [Formulaire HANA sombre](screenshots/local-hana-form-dark.png), [aperçu HANA clair](screenshots/local-hana-preview-light.png) |

Les captures locales contiennent uniquement des fixtures. Le statut « Connecté » HANA y provient d’une réponse simulée ; il ne constitue pas un test de la base réelle. Les nombres et noms diffèrent volontairement des données de production. Les corrections de provenance du lot C3 rendent le jeu de démonstration explicite et laissent les sources ou nombres inconnus indéterminés.

## Préparation et points restant ouverts

| Priorité | Constat au contrôle | Prochaine preuve attendue |
| --- | --- | --- |
| P0 — S1 | MCP désactivé, aucun serveur ; Data et Models vides ; seule Operational Analysis disponible dans Work. | Seed PR to PO et Data Demo sur la VM, scoped sur Showcase, puis répétition de bout en bout. Voir le [mode opératoire](preparation-vm.md). |
| P0 — S2 | Pas de base PR to PO avec hypothèses de valeur et prix renseignés. | Valeur déclarée documentée, skills tarifés, exécution attribuée ; aucune valeur inventée. À faire après la dernière relance du seed PR to PO. |
| P1 — connecteurs | Aperçu HANA réel en fallback `demo_dataset`. PostgreSQL non joignable depuis ce cloud avant authentification, bien que le demandeur s’y connecte. | Connecteur PostgreSQL en lecture seule et bridge snapshot à réaliser ; test réseau depuis la VM. La configuration enregistrée ne prouve pas un accès SQL. |
| P1 — rendu métier | Operational Analysis empile les KPI et aplatit l’explication en un long paragraphe. | KPI groupés et texte structuré, puis capture utilisateur du résultat. |
| P1 — langue | Observabilité conserve plusieurs titres anglais ; les contenus créés par les seeds sont anglais. | Traduire le chrome restant et préparer des descriptions métier françaises pour la présentation. |
| P1 — répétition | Work contient 11 relectures, certaines âgées de 98 jours ; aucun élément HITL en attente au début du contrôle. | Préparer les décisions du scénario choisi sans assimiler ces relectures à des décisions humaines. |
| P1 — seed | Data Demo force `presentation.locale = en` ; PR to PO réinitialise sa valeur à zéro. | Restaurer FR et appliquer S2 après les seeds ; rendre ces préférences persistantes dans un lot dédié. |

Impact en mode présentation distingue correctement valeur déclarée et mesure observée. Les nombres visibles ne constituent pas une mesure causale de gains sur le nouveau parcours synthétique. Aucun serveur MCP Agentium ni pipeline OTel n’a été implémenté dans ce lot.

## Vérification du lot

- `check:i18n` : OK, 9 698 clés ; `check:nav-links --fail-closed` : OK ; `check:ui-chrome` : OK dans la baseline existante.
- `test:unit` : **1 889 tests passent**.
- Playwright : **22 scénarios passent**, sur `127.0.0.1:4310`, réseau externe bloqué, API simulées ; vérifications Axe ciblées, parcours clavier, FR/EN et thèmes clair/sombre.
- Backend : **107 tests passent**, services HANA, API HANA, contrat de conformité et présence des sources dans le dépôt.
- `build:prod` : OK. Le proxy bloque Google Fonts ; l’inlining des polices a été temporairement désactivé pendant le build, puis `angular.json` a été restauré. Les optimisations JS/CSS restent activées. Aucun troisième build de production n’a été effectué.

Les vérifications ciblées d’accessibilité ne certifient pas toutes les surfaces du produit. Aucun seed ni déploiement n’a été lancé sur la VM, aucun push n’a été effectué et aucun secret n’est inclus dans ce dossier. Les sorties de build et de tests navigateur sont supprimées après conservation de ces captures.
