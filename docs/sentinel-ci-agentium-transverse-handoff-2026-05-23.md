# Note de handoff pour l'agent developpeur Sentinel-CI

Date : 2026-05-23

Objet : reprendre dans Sentinel-CI les ameliorations transverses Agentium issues du travail Andritz, sans casser le cockpit AYA.

## Intention

Les derniers developpements Andritz ne doivent pas rester un specific client. Ils renforcent Agentium comme plateforme multi-workspace : voix conversationnelle, ingestion documentaire interpretable, knowledge guides, actions transverses et chrome UI generique.

Sentinel-CI / AYA doit pouvoir heriter de ces briques quand elles sont utiles, mais son cockpit showcase reste une exception produit assumee. Ne pas uniformiser brutalement les surfaces AYA ou Mission Room avec le chrome generique.

## 1. Voice2Voice et conversation loop

Ameliorations disponibles cote Agentium :

- Couche Voice provider-neutral : `cascade`, `realtime`, `local_stt`, `local_tts`, `local_realtime`, `realtime_gpu`.
- Mode demo-safe : masque provider et modele dans l'UI, tout en gardant la verite effective exploitable quand le mode demo est desactive.
- Mode `Session loop` : boucle vocale persistante qui arme le micro, detecte la fin de parole, transcrit, envoie le tour, joue la reponse TTS, puis rearme le micro.
- Commandes vocales transverses : `stop`, `pause`, `reprends`, `repete`, `reformule`, `question suivante`, `valider`.
- Controle anti-boucle vide : gestion silence / endpointing / min speech pour eviter d'envoyer des chunks vides a la transcription.
- Tandem Oracle : etat visible `listening / thinking / committed / superseded / fallback`, avec partials utilises pour raisonner en arriere-plan sans declencher de side-effect.
- TTS sortant optimise V1 : segmentation faible latence, premiers chunks plus courts, queue de lecture partagee, interruption sur reprise de parole.

Impact Sentinel-CI :

- AYA peut heriter du `Session loop` pour les commandes vocales et les actions cockpit, mais les actions a effet de bord doivent rester confirmables.
- Les partial transcripts ne doivent jamais executer une action AYA directement. Ils alimentent seulement l'oracle / preview.
- Les final transcripts passent par le resolver d'actions.
- En mode demo, AYA ne doit pas afficher `openai`, `gpt-*`, ou les details provider/modele.

Points d'attention :

- Verifier que les commandes existantes AYA restent mappees via l'action pack `sentinel_ci_aya_v1`.
- Garder le fallback legacy AYA tant que tous les handlers ne sont pas encapsules dans le modele d'actions transverse.
- Tester explicitement : "stop", "on peut s'arreter la", "annule", "resume la situation", "montre la carte", "cree une action".

## 2. Modele transverse d'actions Chat / Voice / UI

Nouveau modele conceptuel :

`Action Manifest -> Action Binding -> Resolver -> Executor -> Audit`

Ce modele generalise les actions aujourd'hui partiellement specifiques a AYA.

Champs attendus dans un manifest :

- `action_id`
- `label`
- `description`
- `surfaces` : `chat`, `voice`, `ui`, `flow`, `knowledge_capture`
- `phrases`
- `input_schema`
- `required_permission`
- `confirmation_policy`
- `handler` : `skill`, `flow_node`, `backend_route`, `legacy_adapter`
- `audit_event`

Heritage a respecter :

1. `system override`
2. `assistant_profile`
3. `workspace action pack`
4. `capability template`
5. `global default`

Impact Sentinel-CI :

- Les actions AYA doivent devenir un action pack Sentinel-CI explicite, pas un comportement implicite global.
- Andritz ne doit pas voir les actions AYA par defaut.
- Sentinel-CI doit continuer a voir ses actions cockpit, mission room, evidence graph, action plan, carte, briefing et commandes vocales.

Tests minimaux a rejouer cote Sentinel-CI :

- `GET /api/v1/actions/effective?surface=chat`
- `GET /api/v1/actions/effective?surface=voice`
- une commande AYA existante via chat
- la meme commande via voice final transcript
- un side-effect ambigu doit produire une proposition confirmable, pas une execution directe

## 3. Document Intelligence, Table Intelligence et OCR

Agentium a ete etendu au-dela du RAG top-k classique.

### Table Intelligence

Objectif : transformer Excel/CSV en faits exploitables, pas seulement en texte lineaire.

Briques :

- `TableArtifact` : workbook, sheet, table region, headers, rows, columns, cells, formulas, units.
- `knowledge_table_facts` : fact store Postgres workspace-scoped.
- Multi-vues Qdrant : chunks texte, schema, cell facts, table facts, semantic sentences.
- `TableQueryEngine` : lookup, filtre, comparaison, aggregation, enumeration, evidence gap.
- `TableAnswerComposer` : calculs explicites, evidence rows, exclusions, warnings.

Ce qui est generique :

- lookup cellule/valeur
- moyenne, count, min/max si unites compatibles
- citation fichier / feuille / cellule
- prudence en cas d'ambiguite

Ce qui doit rester dans la config workspace :

- synonymes metier
- aliases de metriques
- politiques d'agregation
- regles d'unites
- Knowledge Guides

### Document Intelligence

Objectif : traiter PDF/DOCX/Markdown/HTML comme structures interpretables.

Briques :

- `DocumentArtifact` : pages, sections, headings, paragraphs, tables, procedures, warnings, parameters.
- `knowledge_document_facts` : fact store documentaire.
- `DocumentQueryEngine` : procedure lookup, parameter lookup, warnings, troubleshooting, definitions, comparisons.
- Citations enrichies : fichier, page, section, paragraphe/table.

### OCR / Visual Document Intelligence

Objectif : rendre visibles scans, images et PDF sans couche texte.

Briques planifiees :

- `OcrProvider` provider-neutral : `ppocr_service`, `tesseract_local`, futur provider cloud/local.
- `ocr_artifacts` dans `DocumentArtifact` : blocs, bounding boxes, confidence, provider, langue.
- OCR automatique sur PDF scanne ou faible densite texte.
- OCR direct sur `png/jpg/jpeg/tiff/webp`.
- UI future : preview image/page avec zones OCR et confidence.

Impact Sentinel-CI :

- Le corpus Sentinel-CI peut beneficier de Document Intelligence pour notes, briefings, rapports, fiches, procedures et preuves.
- Les captures ou images operationnelles peuvent beneficier de l'OCR, mais attention aux donnees sensibles et a la politique de conservation.
- Ne pas reprendre de regles Andritz dans Sentinel-CI. Les Knowledge Guides et profils table/document doivent etre workspace-scoped.

## 4. Knowledge Guides et configuration workspace

Les Knowledge Guides sont maintenant une primitive importante :

- Markdown
- rattache a une collection ou un Knowledge scope
- versionne et auditable
- utilise pour query expansion + interpretation + prompt
- affiche comme source de contexte distincte des documents bruts
- ne remplace jamais une preuve documentaire brute

Impact Sentinel-CI :

- Creer des guides Sentinel-CI dedies pour les vocabulaires AYA : briefing, evidence graph, action plan, mission room, carte, signaux, sources presse/projets/agenda.
- Les guides doivent expliquer comment lire les sources, pas inventer des faits.
- Les guides peuvent aider AYA a mieux interpreter les demandes floues sans polluer les workspaces industriels.

## 5. Design UI et chrome Agentium

Le chrome generique Agentium a ete uniformise vers `Cockpit Lean`.

Regles :

- titres blancs / gris clair, pas de gradient title
- eyebrow mono cyan discret
- cartes sobres avec radius 6-8px
- bordures fines, glow minimal
- formulaires/selects alignes avec le style `Systems` / `Capabilities`
- accents cyan limites aux focus, etats actifs, metriques utiles

Document de reference :

- `docs/agentium-ui-chrome.md`
- script de garde : `npm run check:ui-chrome`

Exception Sentinel-CI :

- Ne pas modifier le cockpit AYA / Mission Room par uniformisation automatique.
- Les styles `mission-room`, `vigie-*`, AYA showcase et Sentinel-CI cockpit restent hors scope du chrome generique.
- Si une page Sentinel-CI est une surface plateforme generique, elle peut adopter `Cockpit Lean`. Si elle est une surface demo AYA, elle garde son langage propre.

## 6. Recommandation d'integration Sentinel-CI

Ordre conseille :

1. Brancher Sentinel-CI sur le modele d'actions transverse en gardant le legacy adapter AYA.
2. Activer `Session loop` voice sur AYA avec commandes direct-safe seulement.
3. Ajouter les confirmations pour les actions a effet de bord.
4. Creer un Knowledge Guide Sentinel-CI pour les termes AYA et Mission Room.
5. Valider Document Intelligence sur un petit corpus Sentinel-CI avant bulk ingestion.
6. Garder le design AYA hors uniformisation, mais appliquer `Cockpit Lean` aux pages generiques de configuration/admin.

## 7. QA cible pour l'agent Sentinel-CI

Scenarios voice :

- Dire "stop" ou "on peut s'arreter la" : la boucle doit s'arreter, pas envoyer une nouvelle question.
- Dire "repete" : AYA rejoue la derniere reponse sans refaire un side-effect.
- Dire une commande metier ambiguë : AYA propose une action confirmable.
- Reprise de parole pendant TTS : l'audio se coupe ou se met en pause proprement.

Scenarios actions :

- AYA voit ses actions Sentinel-CI.
- Andritz ne voit pas les actions AYA.
- Une action AYA legacy continue de fonctionner via adapter.
- Les actions side-effect sont auditees.

Scenarios documentaires :

- Une question sur une procedure cite document/page/section.
- Une question sur une preuve cite la source brute, pas seulement le guide.
- Une image ou un scan sans texte signale clairement si OCR absent, faible ou indisponible.

Scenarios design :

- `/systems` et `/capabilities` restent la reference visuelle plateforme.
- Les pages generiques Workspace/Governance suivent `Cockpit Lean`.
- Mission Room / AYA ne regressent pas visuellement.

## 8. Ligne rouge

- Pas de hardcode Andritz dans Sentinel-CI.
- Pas d'action AYA rendue globale par defaut.
- Pas d'execution de side-effect depuis un transcript partiel.
- Pas de stockage audio brut par defaut.
- Pas de Knowledge Guide utilise comme preuve prioritaire.
- Pas d'uniformisation visuelle du cockpit AYA sans validation produit.

