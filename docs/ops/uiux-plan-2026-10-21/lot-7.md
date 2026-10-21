# Lot 7 — exploitation, impact et gouvernance

État de la contribution au 21 octobre 2026 : modifications présentes dans le workspace partagé, sans commit ni déploiement. Le plan de référence est le PDF « Agentium plan d’implémentation UI UX (demo agentic) », pages 30–33. Ce bilan distingue le code réalisé des vérifications encore absentes.

## Critères et réalisation

| Critère | Réalisation | Vérification / limite |
| --- | --- | --- |
| Impact US53 | Tracés linéaires et graduations entières pour les comptages ; tableau des Runs filtré au jour sélectionné ; formule du gain et du ratio affichée. Période et périmètre étaient déjà visibles dans l’en-tête du bloc. | Tests des chemins SVG, graduations et filtre journalier. Pas de vérification navigateur du graphe. |
| Secrets US13 | Rotation, désactivation et destruction d’une version passent par une confirmation avec les consommateurs observés ; noms des Systèmes résolus dans le workspace ; saisie conservée jusqu’au succès ; gardes contre les réponses d’un ancien contexte. | Tests composant de la conservation de saisie et de la confirmation. La liste représente les consommateurs observés dans le journal, pas une analyse statique exhaustive des dépendances. |
| Modules | Étapes du plan lisibles ; empreintes repliées ; avertissement sur les effets avant application. | Structure existante conservée. Aucun nouveau scénario navigateur de mise à jour/retour exécuté par cette contribution. |
| Missions US49 | Sauvegarde du brouillon séparée du lancement ; relecture objectif/agent/livrable ; tentatives séparées et ancien livrable conservé ; erreurs de lecture et 404 distinctes ; états queued/interrupted/unverified ; reprise explicite du même checkpoint. | API et tests du worker passés. E2E écrit mais non exécuté. Assistant de rédaction et périmètre réels explicités ci-dessous. |
| Runs et invocations US48 | Les surfaces existantes issues des lots intégrés portent entrée/résultat/preuve, décision humaine et contexte. | Pas de nouvelle modification ni de revalidation navigateur dédiée par cet agent ; ne pas considérer ce seul bilan comme une certification de l’intégralité US48. |
| Amélioration US47/52 | Réentraînement : bénéfice attendu non garanti, population et effets avant autorisation. Boucle de valeur : références exactes Run/proposition/simulation approuvée/application/mesure ; simulation approuvée conservée même si une prévision plus récente existe ; gain non démontré sans causalité et recul explicitement attestés ; confirmation avant autorisation/application ; permissions effectives par scénario. | Tests du modèle de vue, de la confirmation, de la simulation exacte et de l’absence de preuve causale. Test API des droits reviewer/viewer. |
| Services US30/31 | Choix de politique par nom à partir des qualifications enregistrées ; reçu lisible destination/période/version/heure/auteur, JSON replié ; incident avec responsable et vérification avant republication. Séparation enregistrement/activation et résultat non confirmé conservés des lots intégrés. | Tests du modèle de reçu passés. Pas de publication réelle ni de test navigateur de ce formulaire. Le catalogue est issu des qualifications existantes ; il ne crée pas une politique nouvelle. |
| Cycle de vie US56 | Archive : portée et délai de restauration visibles. Restauration : connexions à reconnecter jusqu’à test réel réussi sur la révision actuelle. Compte : reçu identité/profil/autorisations, conservation du contenu partagé, résultat partiel explicite ; réponse perdue affichée non confirmée sans répétition automatique. | Tests API de restauration, délai expiré, reçu complet et échec de nettoyage local. Aucun appel au fournisseur d’identité réel. La purge effective après rétention n’a pas été exercée. |
| Gouvernance US57 | Événement : auteur, règle, proposition et reçu. Règle figée du Run visible lorsqu’elle existe ; sinon configuration actuelle explicitement identifiée. Propositions/politiques filtrées par leurs permissions de lecture ; couverture appliquée inconnue explicitée. | Tests isolation workspace et règle figée face à une politique modifiée. Une ancienne trace sans version figée ne permet pas de reconstruire une règle historique certaine. |

## Worker : garanties et limites exactes

La conception est dans `docs/design/mission-execution-worker.md`. La migration `143_task_executions` crée un historique séparé. Le registre en base conserve une demande avant envoi Celery. La récupération rediffuse les demandes encore en attente ; une exécution ayant perdu son bail devient interrompue et exige une reprise explicite.

L’acquisition, les checkpoints et le renouvellement du bail sont contrôlés par un numéro de propriétaire (`fence`) et un bail non expiré. Les droits sont revérifiés à l’acquisition, au heartbeat et au checkpoint. Une révocation invalide le propriétaire et les résultats tardifs. Les événements HTTP ne possèdent pas le travail ; les lectures du flux revérifient l’appartenance au workspace.

Ce mécanisme garantit la protection des écritures persistées, **pas une exécution exactement une fois chez un fournisseur externe**. Un appel de modèle peut avoir été traité avant un arrêt du worker sans checkpoint. Une reprise explicite peut répéter cet appel et son coût ; les étapes déjà enregistrées comme terminées sont sautées. Un appel déjà envoyé ne peut pas être rétracté. Aucun outil externe à effets de bord ne doit être ajouté sans contrat distinct d’idempotence et de reçu par étape.

**Périmètre fonctionnel explicite :** le moteur actuel produit un rapport par appels LLM, sans exécuter de Flow ni interroger de connecteur. Le sélecteur de Système inactif a été retiré ; création, relecture et détail indiquent un assistant de rédaction LLM. Les anciens `agent_id` sont qualifiés de références historiques, et la création refuse un nouvel `agent_id` non nul (`MISSION_SYSTEM_EXECUTION_UNSUPPORTED`). Le plan US49 exige de relire l’agent réellement utilisé et le livrable ; il n’exige pas d’ajouter l’exécution d’un Flow à ce moteur.

Le déploiement nécessitera la migration puis le redémarrage du worker général et de Celery beat. Aucun de ces actes n’a été effectué. Concurrence PostgreSQL réelle, transport Celery réel, arrêt brutal de processus et déconnexion navigateur ne sont pas validés ici.

## Vérifications effectuées

- Backend final : **19 tests passés**, 143 avertissements, 2,45 s, journal local `/tmp/lot7-final-verified.log`. Huit tests worker : double acquisition, conservation des anciens livrables, bail expiré, ancien propriétaire refusé, reprise du checkpoint, isolation du workspace, révocation, heartbeat et saut des étapes terminées. Neuf tests API : compte complet/partiel, restauration et délai, brouillon sans dispatch, isolation/404, viewer, ancien livrable en relance, permissions de boucle, refus d’un paramètre Système inexécuté. Deux tests audit : isolation et version figée.
- Les tests API nouveaux utilisent HTTPX ASGITransport avec dépendances asynchrones. Le pont de threads de TestClient était bloqué dans le sandbox sans réseau ; aucune réussite de l’ensemble historique TestClient n’est revendiquée.
- Frontend : **sept bundles ciblés passés dans le contrôle final** (1,21 s) : SVG, Impact, Secrets, reçus Services, autorisation réentraînement, audit, boucle de valeur. Le journal final ciblé est `/tmp/lot7-final-unit.log`.
- i18n : contrôle final passé (14 070 clés), y compris le texte de rédaction LLM. Le journal du dernier contrôle est `/tmp/lot7-final-i18n.log`.
- E2E `frontend-ng/e2e/tests/87-operations-mocked.spec.ts` : **écrit, non exécuté**. La première tentative a échoué avant navigateur (`listen EPERM 127.0.0.1:4327`). La seconde, nécessitant le réseau additionnel pour le serveur local, a été annulée pendant l’attente d’autorisation. Aucun résultat, capture ou conformité visuelle ne doit en être déduit.
- Le build production et les contrôles globaux sont coordonnés par l’agent principal ; ce bilan ne leur attribue pas de réussite.

## Écarts restants avant certification complète du lot

1. Exécuter les scénarios navigateur du lot, puis les parcours US48 et modules non rejoués ici, dans les deux langues et avec changement de workspace.
2. Valider migration/déploiement, concurrence PostgreSQL et cycle Celery réel (rediffusion, interruption du worker, reprise, révocation et déconnexion client).
3. Pour les anciennes traces sans version figée, conserver la mention de couverture/version inconnue ; aucune donnée historique ne doit être inventée.

## Correctif final — aperçu de projection

`shared/cockpit/impact-preview.component.ts` ne transforme plus une erreur en absence de projection et ne conserve plus les chiffres d’une ancienne requête. Le composant distingue attente, chargement, résultat disponible, accès refusé et erreur ; il propose une relance explicite, borne l’attente à 15 secondes et affiche les mesures absentes ou non finies comme inconnues. Les changements de paramètres/workspace annulent la lecture précédente et invalident les réponses tardives. Le flux défaillant ne bloque pas les essais suivants.

Vérification supplémentaire : le bundle `impact-preview.component.spec.ts` passe (journal `/tmp/lot7-impact-preview.log`, 0,45 s), avec huit cas couvrant 403/500/504/réseau, réponse nulle, ancien workspace, requête remplacée et distinction zéro/inconnu. Le contrôle i18n repasse avec 14 090 clés (`/tmp/lot7-impact-i18n.log`). Aucun build ni navigateur supplémentaire n’a été lancé pour ce correctif.
