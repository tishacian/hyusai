# Jev dans le Flow principal Luma

**Statut de ce dossier : candidat préparé et testé hors ligne, pas publié ni
qualifié en service.** Le déploiement du code, la publication du Flow et la
bascule des applications Work sont trois étapes distinctes.

Le parcours proposé est :

**Enquête agentique → dossier prêt → second avis Jev → revue GPT-5 avec citations
→ décision humaine → reçu d'action simulée.**

Jev répond à trois questions structurées : traitement à examiner, possibilité
de proposer un remboursement et prochaine étape à soumettre au responsable SAV.
Sa grille reste exploratoire, sans calibration locale ni seuil d'acceptation
revendiqué. Une erreur technique arrête le parcours ; aucun modèle de repli
ni validation automatique n'est ajouté. La branche dossier incomplet continue
vers `sink.blocked` et n'appelle aucun des deux juges tant que l'enquête n'est
pas prête.

## Ce qui change exactement

Le candidat [main-flow-plan.json](main-flow-plan.json) dérive de la publication
v10 `b8eb64d3-e417-41bf-898a-7b1ad232d64a`, empreinte `77d4d521…`.
Il ajoute `quality.second_opinion_jev` avec le modèle figé `jev-1.13.0`.
Ses sélecteurs de preuves sont copiés de la revue existante : proposition,
politique, commande, remboursements, expéditions et cinq références documentaires.
Les deux juges prennent chacun un instantané gouverné des invocations du Run.

Le contrat GPT-5 — questions, citations exigées, budget, tarif et sélecteurs —
est inchangé. Il ne reçoit pas les conclusions de Jev comme s'il s'agissait
de preuves métier. Les deux nœuds utilisent la fonction générique
`config.input_mode = "mapped"` avec des entrées vides ; leur configuration
`run_evidence` détermine leurs preuves. Les budgets Judge sont isolés par nœud,
tout en restant soumis au plafond global du workspace.

Les entrées, connecteurs, DataOps, modèle SLA, prévision, porte humaine et action
simulée sont conservés. Quatre nœuds de la branche de revue sont décalés d'une
colonne pour garder une lecture fluide. Le brouillon utilisateur r38, dont la
préparation inachevée, n'est ni publié, ni remplacé, ni restauré.

## Où le responsable SAV verra le second avis

Dans **Work → Réclamations → un dossier → Enquêter**, la zone **Votre décision**
présente les résultats des invocations `evaluate_v2` avant les boutons humains.
Le composant générique de revue affiche chaque invocation : Jev puis GPT-5.
Jev y apporte les choix structurés et la distribution fournisseur ; GPT garde
ses réponses citées et ses abstentions. La proposition métier reste celle de
l'enquête. Jev ne la réécrit pas et ne vote pas automatiquement à sa place.

Le résultat se retrouve aussi dans **la trace du Run → invocation Typed
Evaluation → résultat**, ainsi que dans le lecteur de résultat du nœud dans
**Flow**, après sélection du Run concerné. L'historique des évaluations et Usage
conservent les deux appels et leurs coûts. Ouvrir un résultat ne relance pas
le modèle.

Phrase à prononcer après la recette réelle : **« Avant de décider, le responsable
SAV compare un second avis structuré et un contrôle des preuves. Il conserve
la décision ; les deux avis et leurs coûts sont traçables. »** Jusqu'à cette
recette, présenter ce parcours comme préparé, pas comme exécuté.

## Préparer sur une lecture fraîche

Capturer `GET /api/v1/systems/f3ea83de-df89-45ec-8a85-c00d676b2713/flow-state`,
puis :

```bash
python docs/demo-runs/showcase-ecommerce/jev/prepare_main_flow.py \
  --flow-state /chemin/flow-state.json \
  --out /chemin/main-flow-plan.json
```

Le script ne fait aucun appel réseau. Il vérifie les empreintes du brouillon et
de la publication, refuse une topologie de revue différente et écrit un nouveau
fichier. Il ne fournit aucun jeton et ne lit aucune clé fournisseur. Le candidat
livré a l'empreinte `4cb64b3df75c96141540b6367b51ca1a9ec638a41c1e6b01437fe9701deadca4`.
Repréparer et revoir si l'état serveur a changé ; ne pas remplacer une
précondition pour forcer une publication.

## Déployer et publier sans toucher au brouillon

1. Déployer les fonctions génériques de composition Judge, d'entrées explicites
   et de publication candidate sur l'API, le frontend et les workers. Renouveler
   l'attestation Usage pour la révision réellement vérifiée par l'opérateur.
   Le transport qualifié `model_plane.typesafe.pinned_monetary_v1`, le tarif EUR,
   la connexion TypeSafe et le mandat du système doivent autoriser le pin.
   Le budget Showcase de 2 000 €/mois reste en place.
2. Envoyer exactement `review_request.body` à
   `POST /api/v1/systems/{system_id}/flow/review-candidate`. Examiner les erreurs,
   le contrat compilé et les différences. La requête contient le Flow candidat,
   son empreinte et les préconditions sur r38 et la publication courante.
3. Avant toute publication ou bascule Work, qualifier le Flow complet via
   `POST /api/v1/systems/{system_id}/flow-workbench/preview-runs`. Combiner
   `qualification_before_publication.body` avec les deux champs
   `flow_definition` et `expected_flow_sha256` de `review_request.body` :
   l'entrée est `source.request`, de type `manual`, avec le dossier RC-1042.
   C'est un véritable Run `builder_preview` avec PostgreSQL, documents, DataOps,
   scoring, enquête et les deux juges ; s'arrêter à `hitl.review`, sans approuver
   l'action simulée. Conserver l'identifiant retourné et suivre la trace. Aucun
   retry automatique : si la réponse est perdue, rechercher le Run avant de
   recommencer. Les autres scénarios reprennent le même candidat avec un autre
   `claim_id`, un à un.

   **Vérifier le mandat avant ces essais :** l'aperçu hérite du mandat du
   brouillon, alors que la publication candidate conserve celui de la publication
   courante. Les deux empreintes doivent être égales et correspondre au mandat
   du contrat revu. La capture r38/v10 annonce `b451dc8f…` pour les deux. Une
   divergence ne se corrige pas en modifiant le brouillon : ce test ne peut plus
   qualifier la publication sous un mandat différent. Relire aussi ces empreintes
   après les essais et contrôler la règle figée dans la trace d'exécution.
4. Après réussite de la recette, relire les préconditions et refaire la revue
   si nécessaire. Envoyer le même corps à
   `POST /api/v1/systems/{system_id}/flow/publish-candidate`,
   en ajoutant le message du plan et les deux empreintes retournées par la revue :
   `expected_review_sha256 = candidate.review_sha256` et
   `expected_execution_contract_sha256 = candidate.execution_contract_sha256`.
   Une différence de contenu, d'état ou de contrat exige une nouvelle revue.
   Aucun `PUT flow-draft` ni remplacement temporaire du brouillon n'est nécessaire.
5. Relire `flow-state`. Le nouveau numéro de publication est celui retourné par
   le serveur, jamais un numéro supposé. Le brouillon doit rester strictement
   identique, y compris révision, base de publication et métadonnées. La nouvelle
   publication doit porter exactement l'empreinte candidate et le mandat revu.

La publication seule ne fait pas utiliser Jev par Work. Les anciennes releases
restent épinglées à leur historique. Appliquer ensuite le
[parcours de bascule Work](WORK-CUTOVER.md) : bindings concernés, contrat de triage,
release issue du contenu déjà déployé, puis déploiement de cette release.
Les brouillons des applications restent préservés. Les consentements d'événements
sont liés à une version ; webhook et planning restent en pause tant que leur
nouvelle délégation n'a pas été examinée.

## Recette à effectuer en service

- Relire le Flow, ses bindings, les deux applications, les budgets et les
  champions. Conserver les références avant/après et les identifiants des Runs.
- Rejouer RC-1042 jusqu'à la porte humaine : Jev doit proposer d'examiner une
  enquête transporteur ; GPT doit évaluer les preuves du même Run, sans reprendre
  la réponse Jev comme preuve. Examiner séparément qualité métier et réussite
  technique. Aucun clic d'approbation n'est nécessaire pour vérifier les deux avis.
- Faire de même sur RC-1043 et RC-1044 : proposition de remboursement de 49,90 €,
  puis clôture sans doublon selon les faits réellement relus. Un dossier déjà
  actionné peut produire un reçu idempotent après validation ; ne pas créer un
  nouveau reçu pour gonfler le volume.
- Pour RC-5007, constater la demande de pièce et l'arrêt de l'enquête. L'absence
  des deux juges sur cette branche est attendue. Les essais Jev sur ce cas isolé
  restent explicitement des aperçus, distincts du parcours principal.
- Vérifier l'affichage des deux résultats dans Work et Flow, le modèle demandé
  et retourné, les preuves, compteurs, tarifs, réservations et dépenses. Un résultat
  Jev sans justification citée ne doit jamais être présenté comme un contrôle cité.
- En cas d'échec, conserver la trace et la révision ; ne pas désactiver les
  contrôles ni relancer automatiquement une action. Les Runs historiques restent
  associés à leur publication d'origine.

## Validation locale livrée

Les tests du candidat reconstruisent exactement le hash v10 en retirant les
seules modifications déclarées. Ils vérifient l'absence de mutation du brouillon,
les ports, la branche bloquée, la porte humaine et l'intégrité du contrat GPT.
Le test backend charge ce candidat réel, le valide, puis exécute les deux wrappers
avec capture de preuves et persistance réelles dans une base de test. Seules les
réponses fournisseurs sont simulées : deux évaluations, preuves de même contenu
dans deux instantanés distincts, budgets séparés et réutilisation idempotente.
Ce test ne mesure ni qualité métier, ni latence, ni coût d'un appel Jev réel.

```bash
python -m unittest discover -s docs/demo-runs/showcase-ecommerce/jev -p 'test_*.py' -v
PYTHONPATH=backend python -m pytest \
  backend/app/tests/services/test_luma_jev_main_flow_candidate.py -q
```
