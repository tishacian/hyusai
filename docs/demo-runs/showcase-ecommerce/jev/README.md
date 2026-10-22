# Jev dans Luma — second avis SAV en aperçu isolé

Ces quatre essais préparent un usage réel de **Typed Evaluation → TypeSafe Jev**
sur des dossiers synthétiques existants. Ils sont rattachés au système Luma,
sans second système, publication, modification de r38 ni changement de binding
Work. Le fichier `prepared-plan.json` est une préparation, pas un résultat.

**Ce que le responsable SAV peut faire :** comparer un second avis structuré sur
la suite à donner au dossier, puis examiner sa distribution de probabilités et
son coût dans la trace du Run. Jev ne fournit pas de citation par réponse. Le
Judge GPT-5 cité, la porte humaine et les actions de la démo restent inchangés.

## Périmètre et sources

| Cas | Faits synthétiques | Direction attendue selon la politique v2 |
| --- | --- | --- |
| RC-1042 | Commande 75011, bordereau 75012, réception contestée | Enquête transporteur, aucun remboursement proposé |
| RC-1043 | Perte confirmée, 49,90 € payés, aucun remboursement | Proposition de 49,90 € à examiner par un humain |
| RC-1044 | 89 € déjà remboursés dans la fixture | Clôture sans nouveau remboursement |
| RC-5007 | Livraison contestée, bordereau absent | Demander le justificatif et reprendre ensuite |

Les entrées proviennent du [jeu source](../fixtures/fixture_spec.json), de ses
textes Markdown et du [générateur de cohorte](../fixtures/build_benchmark.py).
RC-5007 reprend exactement sa transformation documentée de RC-1042 ; le bordereau
absent n'est pas recréé. Ce sont des lectures **hors ligne de fixtures**, pas une
nouvelle extraction PostgreSQL ou Document Center. Chaque texte envoyé et chaque
fichier source a sa propre empreinte ; aucune empreinte Markdown n'est présentée
comme celle d'un PDF servi.

Les orientations métier reprennent les familles de scénarios déjà discutées.
Les trois **nouvelles questions Jev restent exploratoires, non revues et non
calibrées**. Les attentes sont conservées hors du payload modèle, sans annotation
humaine ni résultat préremplis. Aucun seuil de probabilité n'est transformé en
certification qualité : le résultat peut rester `unassessed` et `review`.

## Modèle, prix et prérequis

- Modèle figé : `jev-1.13.0`. La [documentation fournisseur](https://docs.typesafe.ai/models.md)
  autorise ce pin même si la découverte renvoie seulement `jev-latest` et
  `jev-preview` ; l'accès du compte est toujours vérifié lors de l'appel.
- Prix déclaré du lot Judge : **0,042 USD / million de tokens d'entrée**, sortie
  non facturée. Chaque cas a son propre lot d'un appel, limité à 0,003 USD.
- Provision maximale monétaire du transport : 65 536 tokens d'entrée, soit
  **0,002752512 USD**. C'est une réservation prudente, pas la consommation attendue
  des petits cas fournis. Au tarif EUR déclaré le 22 octobre, elle représente
  0,002450162009 € après arrondi prudent ; la comptabilité finale utilise l'usage mesuré.
- `max_tokens=131072` est l'allocation du lot Judge ; `max_output_tokens=2048`
  demeure une provision locale. Ces paramètres ne sont pas des limites de sortie
  transmises à Jev et ne qualifient pas un plafond de tokens bloquant.
- La livraison doit annoncer le transport
  `model_plane.typesafe.pinned_monetary_v1` dans la readiness Usage, avec
  l'attestation de la révision courante renouvelée. Le helper refuse l'ancien
  transport non qualifié, un plafond de tokens actif, une réconciliation ouverte
  ou un budget insuffisant. Il ne change aucune limite.
- La connexion TypeSafe du workspace doit être active. Un tarif EUR pour le pin
  doit exister. La conversion est une convention déclarée séparément du tarif USD.
- `flow_workbench_v1` et `flow_publication_v1` doivent être ouverts. La capture de
  configuration du 22 octobre les indique ouverts ; le helper les relit.

Le mandat du système reste appliqué par le serveur. Ce helper ne l'élargit pas,
n'active pas de feature et ne contourne aucun refus de modèle ou de budget.

## Préparer puis exécuter un seul cas

Reprendre une capture fraîche de `GET /api/v1/systems/{id}/flow-state`, puis :

```bash
python docs/demo-runs/showcase-ecommerce/jev/prepare.py \
  --flow-state /chemin/flow-state.json \
  --out /chemin/jev-plan.json
```

Le plan livré a été préparé à partir de r38 et v10 (`b8eb64d3…`, `77d4d521…`).
Il conserve leurs empreintes et celles des politiques. Une divergence exige une
nouvelle lecture et préparation ; ne pas remplacer arbitrairement une précondition.

Utiliser l'environnement Python backend qui fournit déjà HTTPX. Le jeton Agentium
est lu par invite masquée, ou via `AGENTIUM_BEARER_TOKEN` fourni par l'environnement
du processus. Ne pas mettre le jeton ou la clé TypeSafe dans le plan, une ligne de
commande, le dépôt ou un fichier de résultats.

```bash
python docs/demo-runs/showcase-ecommerce/jev/run_preview.py \
  --plan /chemin/jev-plan.json --case RC-1042
```

Sans `--execute`, seules les lectures de préflight ont lieu. Pour créer **un**
Run réel, après ces contrôles :

```bash
python docs/demo-runs/showcase-ecommerce/jev/run_preview.py \
  --plan /chemin/jev-plan.json --case RC-1042 \
  --execute --record /chemin/receipts/jev-rc1042-01.json
```

Le seul POST autorisé par le helper est `/systems/{id}/flow-workbench/node-runs`.
L'API reçoit un graphe éphémère avec un seul nœud `evaluate_v2`; le runtime
l'isole entre une entrée et une sortie. Aucun sélecteur `run_evidence` amont n'est
utilisé : les textes et leurs hashes sont conservés dans l'entrée de ce Run.
Les attentes de la table ci-dessus ne sont pas envoyées au fournisseur.

Le reçu contient l'identifiant et le lien du Run. Un Run en file ne prouve pas une
inférence réussie : ouvrir **Run → invocation Typed Evaluation → résultat et usage**,
contrôler modèle demandé/retourné, valeurs, distribution, compteur et tarif. Montrer
qu'il s'agit de trafic d'aperçu et d'un second avis, pas d'un dossier métier traité.
Le helper compare ensuite Flow et politiques budgétaires avant/après.

L'endpoint d'aperçu n'a pas de clé d'idempotence : **aucun retry automatique**.
Le chemin de reçu doit être neuf et est réservé avant le POST. En cas de timeout,
conserver le reçu `starting` et chercher le Run dans l'interface avant toute
nouvelle tentative. Ne pas supprimer ce reçu pour forcer un replay.

## Passer dans Work ultérieurement

L'aperçu n'ajoute pas Jev au parcours Work publié. Pour cela, préparer un ajout
au Flow après `decision.ready`, conserver `quality.review` GPT puis `hitl.review`,
qualifier les dossiers avec les vraies lectures de l'enquête, puis publier avec
les contrôles de concurrence et mettre à jour les bindings/releases de façon
cohérente. Le brouillon utilisateur et sa préparation inachevée doivent rester
préservés. Ce plan ne réalise pas cette bascule.

Validation hors ligne :

```bash
python -m unittest discover -s docs/demo-runs/showcase-ecommerce/jev -p 'test_*.py' -v
```
