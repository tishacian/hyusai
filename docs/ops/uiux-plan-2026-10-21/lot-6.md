# Lot 6 — données, connaissances et modèles

État au 21 octobre 2026. Travail intégré dans le checkout commun `feat/uiux-plan-completion`, sans commit ni déploiement par cet agent. Référence : plan UI/UX, pages 28–30. Ce bilan sépare les changements implémentés des recettes réellement exécutées.

## Changements implémentés

| Critère | Réalisation |
| --- | --- |
| Source PostgreSQL exacte et retour | Le dataset transmet base, schéma, table, identifiant et version. La fiche PostgreSQL ouvre la table exacte ; une base reconfigurée déclenche une réserve. Le retour conserve l'identifiant immuable du dataset et sa version. |
| Lecture connaissance en échec | Fragments, faits documentaires, OCR, faits tabulaires, statistiques, diagnostics, sources, guides et usages conservent un état d'erreur distinct du vide. Les réponses d'un ancien espace sont ignorées et les données affichées effacées au changement d'espace. |
| Preuve évaluée | L'investigation distingue les références/configurations des extraits effectivement conservés. Les citations affichent l'extrait figé et la version lorsqu'elle a été enregistrée, sinon l'absence de version. Le résultat du Judge conserve une distinction explicite entre contrôle exécuté et qualité non évaluée. |
| Fraîcheur des contextes | L'API expose `updated_at` et les dates connues des sources, limitées au même espace. L'âge est calculé sur ces dates, avec un seuil strict de 90 jours ; une date absente ou invalide produit une fraîcheur inconnue. Le numéro de version ne détermine plus l'âge. |
| Modèles prêts et appelables | La liste backend expose le précontrôle `callable` et son refus. La liste, le filtre et le KPI « En service » exigent un modèle sélectionné et appelable. La fiche distingue version sélectionnée et appelable et affiche les sept dimensions de disponibilité ; les dimensions non attestées restent inconnues. |
| Préparation autonome | Le lot reconstruit conserve URL d'exécution, brouillon de session, reprise, annulation demandée, erreur par étape, taille d'aperçu et sorties confirmées. Les changements ajoutent la remise à zéro et la protection des réponses lors d'un changement d'espace, y compris compilation, aperçu, annulation et suivi. |
| Qualité | Les moyennes unsupported/drift utilisent les effectifs réellement observés ; l'API fournit le comptage de drift. Les tuiles montrent l'effectif et une réserve sous 30 observations. Les taux de dépassement et composants montrent leurs effectifs et réserves. Une mesure absente reste absente. |
| Préparer l'entraînement | La sélection affiche la version du dataset, la population et le plan existant cible/variables/séparation. Une réserve indique que la préparation ne constitue pas une conclusion de qualité ; une population de test inférieure à 30 est signalée. Les refus/avertissements du plan backend restent affichés. |
| Import Hugging Face | L'envoi confirmé d'une demande reste un import accepté ; il ne fabrique pas un artefact prêt. Une issue réseau inconnue bloque un nouvel envoi jusqu'à relecture des artefacts et des travaux existants. Révision exacte, fichiers, licence et droits restent vérifiés par le parcours existant. |

Impact attendu : le KPI « En service » peut baisser lorsque des versions sélectionnées sont impossibles à appeler. Les badges d'ancienneté changent selon les dates, sans lien avec le nombre de modifications. Les brouillons de préparation restent stockés dans la session du navigateur.

## Vérifications effectivement exécutées

- Compilation TypeScript `tsc --noEmit -p tsconfig.app.json` : réussie au cours de l'intégration.
- Build Angular development : réussi, sortie `frontend-ng/dist/agentium`, journal `/tmp/agentium-lot6-build.log`. Cette réussite concerne l'état construit à ce moment ; la validation finale du checkout commun appartient au contrôle global.
- Tests unitaires ciblés : les sept suites `context-freshness`, `data-provenance`, `quality-sample`, `models.vm`, `data-preparation.vm`, `dataops.api` et `huggingface-connector.component` ont passé. Les tests HF ajoutés couvrent l'issue inconnue suivie d'une vérification, ainsi qu'un import accepté sans artefact prêt. La suite `dataops.models` a aussi passé.
- Tests backend ciblés : deux tests réussis pour l'isolation des dates de sources entre espaces et une version prête/sélectionnée sans artefact qui reste non appelable. Le test modèle invoque directement la coroutine de la route ; ce résultat ne valide pas le transport HTTP. Les tentatives précédentes avec TestClient ont été interrompues après blocage du pont asyncio dans le sandbox.
- Régression globale `ingestion-status.component.spec` : corrigée puis suite ciblée réussie. Le faux objet de test appelait `loadSources` sans le nouveau pipeline de lecture ; il utilise désormais le prototype réel et teste l'erreur explicite ainsi que le rejet d'un inventaire tardif après changement d'espace. Aucun assouplissement du comportement produit.

Commandes reproductibles depuis `frontend-ng` :

```sh
FLOW_UNIT_FILTER=context-freshness,data-provenance,quality-sample,models.vm.spec,data-preparation.vm,dataops.api.spec,huggingface-connector.component FLOW_UNIT_REPORTER=tap npm run test:unit
FLOW_UNIT_FILTER=ingestion-status.component,dataops.models.spec FLOW_UNIT_REPORTER=tap npm run test:unit
```

## Recettes restant sans preuve d'exécution

- `e2e/tests/86-data-evidence-mocked.spec.ts` ajoute dix cas navigateur : sept réponses de lecture connaissance, filtre appelable, fraîcheur par dates et provenance PostgreSQL. L'appel navigateur avec permission réseau est resté bloqué puis a été annulé ; **aucun résultat E2E86 n'est revendiqué**.
- La recette métier complète sur un espace neuf avec CSV indépendant, anomalies, sommes et comptes exacts, traçabilité ligne/run, publication et second lot n'a pas été exécutée.
- Le parcours d'entraînement réel, l'import réel Hugging Face, et la relecture réelle d'une source PostgreSQL n'ont pas été exécutés sur des services connectés.
- La non-régression navigateur de l'atelier Flow reconstruit n'a pas été exécutée par cet agent. Les suites unitaires ne remplacent pas cette recette.
- Les versions historiques de sources absentes des traces ne sont pas reconstituées à partir de leur version actuelle. L'interface indique cette absence. La qualification d'un modèle pour un usage précis ne découle pas automatiquement de son statut prêt ou de son précontrôle d'appel.

Ces limites de validation doivent rester visibles dans le bilan global ; elles interdisent d'annoncer la recette complète du lot comme passée.
