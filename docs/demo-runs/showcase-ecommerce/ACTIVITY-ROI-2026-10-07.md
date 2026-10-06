# Luma — activité et projection financière du 7 octobre 2026

La campagne a créé **20 Runs Work natifs sur 10 dossiers synthétiques**, en deux
vagues dans Showcase. PostgreSQL a été lu en direct, les preuves ont été
retrouvées dans Document Center/OmniRAG et le planificateur LLM a choisi ses
recherches. Les validations déléguées sont annotées comme QA automatisée.
Aucun essai humain chronométré n’a été créé.

Les dates serveur sont en UTC, le 6 octobre entre 22:03 et 22:22 ; la campagne
est datée du **7 octobre en Europe/Paris**. Elle utilise la publication v3 du
System `f3ea83de-df89-45ec-8a85-c00d676b2713`, release Work 2, sur la révision
déployée `d1b620a576c627fa226f40ab1e502157a79a0b46`.
La [composition DataOps/MLOps](COMPOSITION.md) attend encore son déploiement et
son activation opérateur. Ces essais attestent le parcours déjà déployé.

## Résultats et volume

| Indicateur | Résultat |
|---|---:|
| Exécutions nouvelles | 20 |
| Dossiers distincts | 10 |
| Appels tracés, relances et échecs inclus | 204 |
| Propositions conformes à la grille automatique | 20/20, soit 10/10 dossiers |
| Reçus simulés distincts | 8 |
| Relances bloquées car l’action existe déjà | 8 |
| Essais arrêtés sur pièce manquante | 4, sur 2 dossiers |
| États techniques terminaux | 12 `completed`, 8 `failed` |
| Médiane de durée technique cumulée des appels | 46,70 s |
| Essais humains et paires complètes | 0 et 0/10 |

Le statut technique `completed` comprend les quatre sorties `blocked` après
refus de poursuivre sans pièce : **il ne signifie pas douze dossiers résolus**.
RC-5008 et RC-5016 attendent toujours un justificatif. Les variantes manuelles
RC-5001, 5003, …, 5019 n’ont pas été lancées.

Les propositions attendues sont : enquête transporteur pour une adresse
contradictoire (RC-5002, 5010, 5018), remboursement simulé de 49,90 € pour une
perte confirmée (RC-5004, 5012, 5020), clôture du doublon déjà remboursé (RC-5006,
5014) et demande d’information (RC-5008, 5016). Le contrôle automatique compare
l’action, le montant, le snapshot PostgreSQL et les références effectivement
citées à la grille figée. Il ne remplace pas une revue humaine indépendante.
Tous les reçus portent `status=simulated`, `evidence_kind=synthetic_demo` et
`external_payment_called=false`.

La répétition de la même clé Work sur RC-5002 retrouve le Run
`33114164-3273-4492-ba7e-cc208b3fdb20`, avec `idempotent_replay=true`, sans nouveau
Run. Une nouvelle enquête avec une nouvelle clé rencontre, sur la version
déployée, `CLAIM_ACTION_ALREADY_RECORDED` pour les huit dossiers déjà traités.
La livraison corrige cette reprise : une action strictement identique retrouve
son reçu simulé après une approbation du nouveau Run et les contrôles de preuve,
sans nouvelle action. Les identités du reçu d’origine sont conservées ; les
identités de réutilisation sont ajoutées. Les huit échecs historiques restent
dans les preuves.

## Coûts disponibles

Le sous-total identifié au tarif catalogue est **0,294 USD**, pour 98 appels de
planification à 0,003 USD/appel. Les opérations internes tarifées ont un
sous-total catalogue de **0 EUR**. La couverture est de **160/204 appels** ;
44 recherches documentaires n’ont pas de prix configuré. Leurs compteurs
d’usage sont conservés, sans traiter un tarif absent comme zéro.

Les fournisseurs ont rapporté 1 320 223 tokens GPT-5 et 2 430 tokens
`text-embedding-3-small`. Le prix forfaitaire du catalogue n’est pas une facture
du fournisseur. L’export API expose la provenance tarifaire, mais pas le drapeau
ORM `cost_measured` : le ledger conserve cette limite. La nouvelle route
d’activité vérifie aussi ce drapeau serveur avant d’agréger un coût.
Infrastructure, licence et intégration sont exclues de ces sous-totaux, qui
restent séparés par devise. Ils ne permettent pas un ROI observé complet.

Les durées techniques additionnent les latences des appels. Le délai jusqu’à
la fin du Run, incluant l’attente de validation, figure séparément dans les
preuves. Aucun de ces temps ne devient du travail humain économisé.

## Scénario financier approuvé

L’utilisateur a retenu **8 minutes en manuel, 2 minutes de validation assistée,
40 €/h et 0,50 €/dossier de budget incrémental complet**. Ce budget inclut appels,
infrastructure, licence et intégration amortie. Ces hypothèses restent ajustables.

```text
Capacité projetée par dossier = (8 - 2) / 60 × 40 = 4,00 €
Net projeté par dossier = 4,00 - 0,50 = 3,50 €
ROI projeté = 3,50 / 0,50 = 700 %
Seuil de rentabilité = 0,50 / 40 × 3 600 = 45 secondes gagnées
```

Un volume illustratif et modifiable de 1 000 dossiers/mois donne **3 500 € nets
projetés/mois**. Ce volume n’est pas le trafic constaté. La projection concerne
un dossier traité conformément aux règles et valorise une capacité disponible.
Les essais ne démontrent ni une économie de trésorerie réalisée, ni les deux
minutes de travail humain, ni le budget complet.

Dans **Impact → Synthèse**, la nouvelle carte expose l’activité et le scénario
déclaré, avec liens vers les Runs. Modifier les hypothèses agit localement et
n’écrit aucune valeur sur un Run ou une session humaine. Le
[benchmark humain](ROI-PROTOCOL.md) reste à 0/10, avec gains, coûts incrémentaux,
net et ROI observé `null`.

## Preuves et activation

- [Ledger JSON](ACTIVITY-EVIDENCE-2026-10-07.json) : Runs, 204 invocations,
  snapshots, citations, reçus, tarifs, usages, révision et contrôle d’idempotence.
- [Dataset CSV d’activité](fixtures/dataops/luma_sav_activity_2026-10-07.csv) :
  20 lignes, une par tentative ; `human_trial=false`. SHA-256 :
  `8cbacbb458123b1e5f86a956ae17e12146883f4a7287114a4bf8e88a43681c81`.

Le CSV est aussi disponible dans [Data Center](https://agentium.papai.ai/data/b0dc7653-fc00-4632-ba59-3502a45b406a),
sous **Luma — Activité SAV, essais du 7 octobre 2026**. Le dataset natif v1 est
`ready`, avec 20 lignes et 20 colonnes ; son aperçu réel a été vérifié. Cet
export d’activité ne sert pas de dataset d’apprentissage. Le CSV du dépôt est
normalisé en LF ; le ledger conserve aussi l’empreinte du fichier téléversé
en CRLF, dont les données sont identiques.

L’activité est déjà créée sur le site. La carte Impact et la correction des
relances nécessitent le déploiement du commit livré depuis `demo/agentic`, via
le miroir Bitbucket et le [runbook VM](../../ops/agentium-safe-vm-deployment.md).
Aucune migration ni modification du protocole n’est requise. La composition
conserve le plan et l’empreinte de [COMPOSITION.md](COMPOSITION.md) ; ne pas
rejouer les seeds, l’ingestion ou l’entraînement.

Après déploiement, ouvrir Impact dans Showcase, vérifier l’activité bornée aux
sept derniers jours et ses liens, puis tester une relance identique : elle
retrouve un reçu existant sans créer de seconde action. Les comptes évoluent
avec l’activité et la fenêtre, contrairement au ledger figé.

Validation locale : **43 tests backend**, **1 941 tests unitaires frontend**,
compilation de production et contrôles i18n, navigation et chrome. La QA
navigateur isolée couvre cinq scénarios, dont FR/EN, sombre/clair et mobile
390 px ; les nouvelles API y sont simulées. La compilation désactive
temporairement l’inlining des polices externes dans l’environnement cloud,
sans modifier la configuration livrée. La QA avec les services déployés reste
à effectuer après déploiement opérateur.
