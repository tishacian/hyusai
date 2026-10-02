# Livraison Luma Maison dans Showcase

Cette livraison ajoute le lecteur PostgreSQL borné, six outils, l’application
Work Réclamations et le benchmark humain dans Impact. L’utilisateur a retenu un
déploiement par un opérateur. La cible est `origin/demo/agentic` ; le code n’arrive
sur la VM que par Git et l’orchestrateur de
[deploiement sûr](../../ops/agentium-safe-vm-deployment.md).
Les migrations ajoutent uniquement `claim_actions` (118) et `claim_trials` (119).
Utiliser les attestations, sauvegardes, canaris et contrôles du runbook existant.
Aucune commande Compose isolée, aucun transfert de code, aucun reset de données.

## État vérifié le 2 octobre 2026

- Workspace : `agentium-showcase`, ID `e2ed9e40-5fa6-4e32-8948-3e1220134fd3`.
- Acteur propriétaire : `06a2e190-ae2d-4365-b4f3-9952401f531d`.
- Le test du connecteur PostgreSQL depuis Agentium a réussi à 07:51:59 UTC.
  Cela atteste la connexion, pas le chargement du schéma métier.
- Document Center : 47 originaux ingérés et indexés, dont 36 PDF du benchmark.
  L’ancienne politique reste dans une collection d’archives exclue des outils.
- La recherche réelle a retrouvé le bordereau LM-1042 avec le code postal 75012
  et la politique v2 actuelle. L’adresse de commande du seed est 75011.
- Les temps humains et le ROI n’ont pas été mesurés.

Collections utilisées :
`luma-maison-regles`, `luma-maison-dossier-lm1042`,
`luma-maison-dossier-lm1043`, `luma-maison-dossier-lm1044`,
`luma-maison-benchmark`.
Les identités doivent venir de l’inventaire réel ; ne pas en inventer ni réingérer
les fichiers déjà présents. Les sources doivent être `ready`, accessibles dans
Showcase et correspondre aux SHA des manifests.

## Après le déploiement vérifié du commit

Depuis le checkout VM propre du commit déployé : charger, dans la base métier
prévue, `fixtures/postgres/seed.sql` puis `fixtures/benchmark/seed.sql`. Utiliser
un compte opérateur et `psql -v ON_ERROR_STOP=1 -W -f <fichier>` ; les mots de passe
restent dans le canal sécurisé ou le prompt. Les inserts sont conservateurs et
ne réinitialisent aucune ligne existante. Relire les données si le schéma existe
déjà ; un conflit de contenu n’est pas réparé silencieusement.

Produire le mapping des sources depuis l’environnement backend déployé. Ces
commandes ne déploient aucun code et ne redémarrent aucun service :

```bash
python3 docs/demo-runs/showcase-ecommerce/fixtures/install_payload.py |
  docker exec -i agentium-backend python -m scripts.map_ecommerce_sources \
    --payload-stdin --workspace agentium-showcase \
    --collections luma-maison-regles luma-maison-dossier-lm1042 \
      luma-maison-dossier-lm1043 luma-maison-dossier-lm1044 \
      luma-maison-benchmark > /tmp/luma-source-mapping.sql
```

Revoir `/tmp/luma-source-mapping.sql`, puis le charger avec le même compte
opérateur dans la base métier. La transaction échoue si un ID est déjà différent,
si un SHA ou un nom ne correspond pas, ou si une ligne attendue manque. Affecter
ensuite au connecteur Agentium un compte dédié disposant seulement de `USAGE` sur
`showcase_ecommerce` et de `SELECT` sur ses sept tables. Le lecteur impose aussi
une transaction read-only, des délais et des plafonds de résultats.

Créer et activer les objets nouveaux après vérification des lectures et des
sources :

```bash
python3 docs/demo-runs/showcase-ecommerce/fixtures/install_payload.py |
  docker exec -i agentium-backend python -m scripts.install_ecommerce_demo \
    --payload-stdin --workspace agentium-showcase \
    --actor-user-id 06a2e190-ae2d-4365-b4f3-9952401f531d \
    --collections luma-maison-regles luma-maison-dossier-lm1042 \
      luma-maison-dossier-lm1043 luma-maison-dossier-lm1044 \
      luma-maison-benchmark --activate
```

Sans `--activate`, la release est installée en pilote propriétaire/admin.
L’installateur utilise les services natifs : draft, publication figée, binding,
ready-check, release et déploiement. Il refuse un System ou une application déjà
présents, plutôt que de les écraser. Conserver les IDs retournés. Aucun autre
workspace ni System existant n’est modifié.

## Vérification métier et visuelle

Ouvrir Work → Réclamations (`/work/reclamations/studio`). Contrôler les montants,
les remboursements, les originaux, les passages cités et les dates de lecture.
Lancer une enquête sur chaque cas et conserver les liens vers les vrais Runs :

1. LM-1042 : contradiction 75011/75012 → enquête transporteur, aucun remboursement.
2. LM-1043 : perte confirmée → proposition de 49,90 €, puis validation humaine.
3. LM-1044 : reçu RF-1044 → clôture de la demande déjà remboursée, aucun second remboursement.

Les chemins d’outils doivent différer : recherche de livraison ou de perte pour
les deux premiers, recherche du reçu antérieur pour le troisième. Le modèle
choisit les recherches ; les contrôles serveur autorisent la proposition et le
reçu. La validation automatique d’un TTL ne suffit pas. Le reçu porte
`status=simulated` et `external_payment_called=false`. Une répétition du même
Run est idempotente ; une action identique sur la même commande est bloquée.

Tester aussi une preuve manquante, une source devenue inaccessible, une politique
modifiée, un montant invalide, une approbation insuffisante au-delà de 300 € et une
actualisation du dossier. Vérifier FR/EN, thèmes clair/sombre, clavier, mobile et
retour du justificatif au même dossier. Après déploiement, valider les vrais
services : les tests locaux avec API simulée ne prouvent pas leur fonctionnement.

## Mesure dans Work et lecture dans Impact

Ouvrir « Expérimentation et impact ». Les dix paires utilisent RC-5001 à RC-5020,
avec ordre alterné manuel/assisté. Un humain commence, met en pause quand il
cesse de travailler, reprend pour les corrections et termine après la décision.
Ne pas utiliser les interactions de QA automatique comme temps humain.
La condition manuelle dispose des mêmes faits et originaux ; le bouton d’enquête
est désactivé. Toute enquête native lancée pendant une session manuelle invalide
sa fin. Un second membre habilité vérifie la décision et les justificatifs. Une
revue non conforme reste visible ; la correction reprend le chronométrage et
préserve les preuves précédentes.

Impact → Synthèse affiche les observations, les paires et les liens vers les Runs,
avec la convention **40 €/h, hypothèse de démonstration**. Ce benchmark ne crée
aucune baseline de production. Aucun résultat n’est annoncé avant dix paires
complètes de qualité comparable. Un gain négatif reste négatif.

La couverture des coûts peut rester inconnue : les tarifs du catalogue ne
prouvent pas les coûts des appels imbriqués. Pour clôturer cette couverture,
un propriétaire/admin soumet à `POST /api/v1/ecommerce-claims/benchmark/cost-review`
une revue des factures et allocations en EUR : `ledger_sha256` retourné par la
synthèse, `provider_eur`, `infrastructure_eur`, `licence_eur`, `integration_eur`,
les quatre champs correspondants `*_evidence_ref`, `conversion_convention` et
`note`. Inclure tous les essais, échecs, corrections, infrastructure, licence et
intégration dans la fenêtre annoncée. Un zéro doit lui aussi être justifié.
Le serveur lie cette décision humaine au protocole et au ledger des exécutions ;
un ledger modifié rend la revue caduque. Le coût reste explicitement qualifié de
facturation/allocation approuvée par un humain. Il ne devient pas une mesure
fournisseur automatique. Aucun montant de coût n’est prérempli.

Le bénéfice net vaut capacité valorisée moins coût incrémental ; le ROI n’est
calculé qu’avec un coût positif et complet. Aucune économie de trésorerie ni
projection mensuelle n’est déduite de cette expérimentation exploratoire.
