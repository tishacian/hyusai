# Luma — préparation, Judge, événements et ML, 19 octobre 2026

La [recette après déploiement du 20 octobre](luma-four-lots-qualification-2026-10-20.md)
décrit l'état actuel, les publications suivantes et les blocages observés.
Les résultats ci-dessous sont le relevé historique du 19 octobre.

Cette activation conserve le System `f3ea83de-df89-45ec-8a85-c00d676b2713`
et l'application `reclamations`. Les changements métier sont de la configuration
des fonctions produit ; les corrections de stockage, de sélection shadow et
d'identité d'exécution s'appliquent à tous les workspaces.

## État en service et limites

Le déploiement applicatif testé est `718c99bf`. La configuration a été publiée
indépendamment de ce déploiement :

| Objet | État vérifié |
| --- | --- |
| Flow | v8, `5c1580d3-cc0f-464a-b188-ee766027c712` |
| Empreinte Flow | `368249d6dfab2a3208137c58b2eba0facee661671dc5eae962f7b1cea3097666` |
| Brouillon Flow | r31 ; nœud utilisateur `flow.mv95zi21.1` conservé, non publié |
| Work | release 7, `fdb3d139-31fa-4be7-b010-bc2a33a72b8b` |
| Brouillon Work | r11 ; restauré séparément de la release, avec ses propres bindings et son ordre conservés |
| Bindings | enquête, file et prévision épinglés à la même v8 |
| SLA en service | v5, `2e71ce6f-800f-4d02-b59e-498e40fe48eb`, inchangé |
| Prévision | classique v2 entraîné, appel direct réussi ; parcours Work bloqué avant déploiement du correctif Delta |
| Challenger | forêt aléatoire v6 qualifiée ; TreeSHAP vérifié dans Play ; shadow non activé |
| Événements | entrées présentes dans le Flow ; hook et planning créés en pause |

La v6 intermédiaire a révélé un conflit de lignée de dataset ; la v7 corrige
le nom de sortie de la préparation, puis la v8 ajuste les preuves et le budget
du Judge. Les deux brouillons ont été
restaurés après chaque publication avec leur révision attendue. Les paramètres
de prévision du brouillon initial étaient identiques au publié ; les helpers
refusent désormais une divergence avant remplacement.

## Parcours de recette

### File SAV : PostgreSQL → préparation visuelle → modèle → Work

Depuis Work, **Recalculer la file** a créé le Run
`d028ebaf-42fe-41b0-aba2-dafead8bd514`, terminé avec succès : extraction
PostgreSQL, préparation native `data_prep_v1`, puis scoring SLA v5.
Les 23 dossiers sont préparés et scorés. Les trois cas de présentation affichent
respectivement environ 80 %, 17 % et 2 % de risque de résolution longue.

La préparation sélectionne les variables utiles, calcule les contrôles
`evidence_gap` et `duplicate_refund_check`, puis trie les dossiers. Elle produit
la lignée **Luma — Préparation visuelle SAV**, dataset
`c22a80a9-f8f8-4356-bd2e-9953323ec1cb` pour ce Run ; le dataset scoré est
`fbbb2b09-2ac8-492b-afde-d88dc65fb1ed`. La lignée SQL historique reste intacte.
Les contrôles de qualité orientent l'enquête ; ils ne décident pas du remboursement.

Le Run v6 `f94e4662-44ac-435b-a88a-67afa6cc9603`, refusé pour
`DATAPREP_OUTPUT_SLUG_TAKEN`, reste dans les preuves. Le contrôle de propriété
de lignée n'a pas été contourné.

Le recalcul après publication v8 réussit également : Run
`e4fe28c1-f9ae-425d-87c1-4c127f6937a0`, terminé le 19 octobre, file Work à jour.

Voir la [configuration de préparation](../demo-runs/showcase-ecommerce/fixtures/showcase_visual_prep/README.md).

### Enquête → Judge → validation humaine

Le nœud `quality.review` utilise `evaluate_v2` après la proposition documentée.
Le contrôle humain reste nécessaire avant tout reçu simulé. Le catalogue a été
complété par les Skills Luma déjà utilisés et `evaluate_v2` ; le System référence
explicitement `data_prep_v1` et `evaluate_v2`. Aucune permission globale n'a été
élargie.

La recette utilise une nouvelle enquête du dossier RC-1043, Run
`eaf83c63-83b7-4209-bdf3-4c982512d6ee`, lancée depuis **Réexaminer le dossier**.
Le reçu simulé historique reste conservé ; aucune nouvelle décision humaine
n'est prise à la place de l'utilisateur.

Cette première enquête échoue au Judge : la projection des résultats bruts de
recherche dépasse 32 000 octets par source. La v8 sélectionne les huit citations
contenant les mêmes passages, avec leurs références document/page/chunk/SHA,
sans les métadonnées de recherche redondantes. Le prompt reconstitué pèse
28 407 octets. Aucun passage ni contrôle d'accès n'est supprimé.
Le budget déclaré est de 40 000 tokens et 0,07 USD pour un seul appel, afin de
couvrir la réservation conservatrice du moteur (37 931 tokens estimés avant
appel). Le plafond de sortie reste 2 048 tokens, le prompt 32 000 octets et le
délai 45 secondes. Ces réservations ne sont pas des coûts mesurés.
La nouvelle enquête de qualification porte l'ID
`a2892cb0-fca5-46b8-bbb5-bebcc46435a4`.
Elle atteint la validation humaine, mais le résultat métier du Judge est
`failed / JUDGE_PROVIDER_UNAVAILABLE`, avec zéro réponse sur cinq. L'invocation
technique est terminée : cela ne signifie pas que la qualité a été évaluée.
Work affiche **Non évalué** et demande la revue humaine. Aucun jugement positif,
coût nul ou confiance calibrée n'est inventé. L'échec fournisseur reste à corriger
et à requalifier.

Le fournisseur a refusé la requête avec `BadRequestError` après environ 1,53 s ;
ce n'est pas le délai maximal. La compilation inclut une branche de citation
image même pour ces questions textuelles. Son champ `kind` était défini par
`const` seul, sans type explicite. Le correctif générique émet
`{"type":"string","enum":["image"]}`, compatible avec le contrat structuré
strict ; les autres validations restent inchangées. Le défaut de schéma est
reproduit et testé jusqu'au client OpenAI. Le corps HTTP 400 n'étant pas conservé,
il faut encore confirmer en service que ce correctif résout ce refus précis,
puis examiner les cinq réponses et leurs citations. Le Flow n'a pas besoin
d'être republié pour ce changement du compilateur.

### Charge et capacité

Le modèle classique v2 est épinglé et ses liens Work corrigés. L'historique
s'arrête au 8 octobre ; les prévisions couvrent le 9 octobre au 5 novembre,
avec intervalle nominal à 80 %. L'appel direct produit bien 28 lignes.

Le premier Run Work `8cd37d8b-7ab7-4fb6-be56-6c96c61b1841` a échoué lors de
la matérialisation du dataset : les footers Parquet conservaient des timestamps
nanosecondes alors que le commit Delta annonçait des microsecondes. Le correctif
générique normalise UTC/microsecondes par cast sûr ; une précision non
représentable est refusée, jamais tronquée silencieusement.

Après déploiement, relancer depuis Work et vérifier la sortie de prévision,
l'assemblage de 42 jours historiques avec 28 jours prévus, puis le graphique.
Ne pas annoncer le parcours rétabli avant cette recette.
Voir [la qualification prévision](luma-forecast-qualification-2026-10-19.md).

### Challenger explicable et shadow

La forêt aléatoire v6 `6d9c2eee-60b9-4995-afb5-6dc9c148de6c` est prête,
appelable et possède une référence de 256 observations. Elle ne remplace pas
le champion. La comparaison sur 1 141 cas communs hors entraînement ne démontre
pas une meilleure AUC : environ 0,811 contre 0,821 pour v5.

Dans Play, TreeSHAP restitue six contributions, de la base 44,2 % à la prédiction
89,9 %, avec additivité vérifiée. La prédiction UI est
`d60fb4f3-f1bb-43ae-b7f7-4e8425a728fe`.

Le shadow reste en attente du correctif de sélection : le meilleur score
historique désignait un artefact legacy non appelable. Le produit choisit
désormais le meilleur candidat compatible et montre les motifs d'exclusion,
sans changer l'alias historique du registre et sans repli après un échec d'appel.
Après déploiement, vérifier que v6 est sélectionnée, activer un échantillonnage
borné, comparer les nouvelles prédictions et conserver v5 en service.
Voir [la qualification challenger](../demo-runs/showcase-ecommerce/CHALLENGER-QUALIFICATION-2026-10-19.md).

## Événements préparés, activation après déploiement

| Source | Identifiant | Configuration conservée |
| --- | --- | --- |
| Réclamation entrante | `f7f54df5-2af7-4114-bec0-af8b150126f9` | webhook signé, désactivé |
| Actualisation de la file | `1feaa7f7-ca60-408f-95f2-ddf4d182646c` | `0 8 * * 1-5`, Europe/Paris, désactivé |

Le mode événement du System reste `dry_run`. Aucun tick, notification externe
ou livraison webhook n'est annoncé comme qualifié.

Le moteur actuel ne fournit pas d'identité d'autorisation à ces Runs automatiques,
alors que ML et Judge exigent des droits vérifiables. La correction générique
ajoute une délégation explicite du compte qui configure la source, liée à la
publication consentie et révocable. L'événement reste l'initiateur du Run ;
aucune identité humaine fictive n'est ajoutée à son historique. Les sous-flows
délégués ne sont pas pris en charge par cette première livraison.

La livraison comprend la migration additive **`141_event_execution_principal`**
après `140_mlops_prod_explanations`. Les sources existantes restent sans
délégation ; aucun backfill et aucun drapeau global changé. Un downgrade refuse
de supprimer des délégations ou preuves d'exécution existantes.

Déployer une image cohérente sur API, frontend, CPU, DataOps, `ml-ts`, beat,
scheduler/runner de connecteurs ; appliquer la migration avant reprise des
processus qui lisent les nouveaux champs. Aucun accès SSH au déploiement n'est
disponible dans cet environnement de recette : cette étape relève de l'opérateur.

Ensuite, depuis les déclencheurs du Flow :

1. Relire publication, bindings, triage et brouillons ; ne pas écraser une édition.
2. Consentir **Utiliser mes accès** sur les deux sources, sur la v8 courante.
3. Passer le System en exécution événementielle et activer le hook. Envoyer un
   dossier de recette signé, vérifier Judge et arrêt à la validation humaine ;
   rejouer exactement la requête pour vérifier l'idempotence sans second Run.
4. Qualifier un tick cron borné, vérifier préparation et scoring, puis conserver
   l'horaire ouvré à 8 h Europe/Paris. Ne pas laisser un cron fréquent de test.
5. Vérifier le journal d'activité, les liens vers les Runs, l'acteur délégué et
   les refus après révocation. Les envois d'alertes restent hors de cette activation.

Les snapshots complets et captures sont conservés hors dépôt dans
`/workspace/scratch/luma-four-lots-2026-10-19/`. Les secrets et jetons ne font
pas partie de cette documentation.

## Points d'UX vérifiés

Work montre le parcours PostgreSQL → données préparées → modèle → file scorée,
avec liens vers les objets réellement produits. Le résultat TreeSHAP est lisible
depuis Play. Pour raconter l'exécution publiée, préférer le Flow du Run ; l'éditeur
montre volontairement le brouillon utilisateur et son nœud « Prepare » isolé.
Ce dernier n'a été ni supprimé, ni publié pour rendre la capture plus propre.

L'atelier montre les quatre étapes de préparation. Sur la révision actuellement
en service, son aperçu ne reprend pas les sorties du banc d'essai isolé, et le
test global du brouillon est bloqué par le nœud isolé. Le raccordement générique
des sorties de test à l'aperçu doit être déployé : aucune épingle de dataset ni
sauvegarde de brouillon ne doit être nécessaire pour cette lecture.

Après déploiement : sélectionner **Lire les faits SAV dans PostgreSQL**, ouvrir
**Exploiter → Banc d'essai → Nœud**, renseigner `{}`, confirmer les effets réels
du test et exécuter ce seul nœud. Après réussite, fermer le banc, sélectionner
la préparation puis **Ouvrir l'atelier**. Garder **Utiliser la sortie amont** :
l'origine doit être **Sortie du dernier test**. L'aperçu et le SQL utilisent cette
sortie éphémère ; une modification du Flow ou du contexte l'invalide.

Deux limites visuelles restent visibles dans cette recette : le statut technique
« Contrôle qualité · Terminé » peut côtoyer un résultat métier « Non évalué », et
la présence du reçu historique demande de distinguer l'ancienne action de la
nouvelle enquête. La recette ne les présente pas comme une validation du Judge.

## Vérifications de la livraison

Les suites suivantes ont été exécutées séparément ; leurs comptes ne sont pas
additionnés car certaines se recouvrent :

- 270 tests backend pour la délégation, les API, les reprises, la migration,
  Judge, ML et les lectures documentaires ; 31 tests Judge après le correctif
  de schéma, dont le contrat envoyé au vrai client avec SDK substitué.
- 43 tests de stockage multipart et matérialisation de prévision ; relecture
  indépendante du cast UTC/us, y compris conservation des instants.
- Tests de sélection shadow et d'API, avec exclusion des artefacts legacy,
  conservation du classement et refus sans repli après échec du candidat choisi.
- Préparation native et scoring réellement exécutés dans le test d'intégration,
  contrôle d'équivalence SQL sur les 23 lignes et conservation de l'ancienne lignée.
- Tests UI des déclencheurs, du shadow et de l'aperçu de préparation en français
  et anglais, contrôle des contextes périmés et absence d'enregistrement implicite.
- Compilation Angular de production, contrôles i18n/chrome et contrôle des diffs.

Les tests avec fournisseurs substitués ne remplacent pas les recettes après
déploiement décrites ci-dessus. Le build conserve des avertissements sur le budget
CSS de Studio et le module CommonJS dagre, hors des fichiers modifiés.
