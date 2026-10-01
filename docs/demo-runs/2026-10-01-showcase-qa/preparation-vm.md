# Préparer Showcase sur la VM

Ces commandes sont préparées d’après les scripts présents dans `hyusai`. Elles **n’ont pas été exécutées sur la VM** : l’alias SSH `omnirag-demo` n’est pas configuré dans l’environnement cloud. Utiliser le checkout et l’environnement Python du backend réellement déployé, avec sa configuration de base de données. Aucun chemin d’un poste local n’est nécessaire.

## S1 — Seed du scénario

Depuis le dossier `backend` du checkout déployé, lancer la fixture MCP dans un processus supervisé accessible depuis le backend et ses workers :

```bash
.venv/bin/python -m scripts.mcp_fixture_server --host 127.0.0.1 --port 8765
```

Si le backend tourne dans un conteneur, `127.0.0.1` doit désigner le même environnement réseau que celui de la fixture. Adapter les URL aux adresses internes réellement accessibles dans ce cas.

Dans un second terminal, seed PR to PO avec des URL explicitement dirigées vers les fixtures et les écritures SAP scellées :

```bash
MCP_FIXTURE=1 \
MCP_SAP_URL=http://127.0.0.1:8765/sap \
MCP_HIKMA_URL=http://127.0.0.1:8765/hikma \
SAP_WRITE_UNSEALED=0 \
.venv/bin/python -m scripts.seed_nawa_pr_to_po \
  --workspace-slug agentium-showcase
```

Le workspace doit déjà exister, ce qui a été confirmé dans l’interface. Le seed active MCP et Work, crée les objets PR to PO et met à jour les paramètres du workspace. **`MCP_FIXTURE=1` ne redirige pas tous les connecteurs** : les entrées BAPI supplémentaires conservent des URL externes. Dans la configuration MCP de Showcase, désactiver ces entrées pour cette répétition et vérifier que SAP/Hikma utilisent bien les fixtures. Les variables `MCP_<ID>_URL` priment sur les valeurs par défaut du seed.

Puis seed Data Demo :

```bash
RECIPE_EXECUTION_ENABLED=true WORKER_EAGER_MODE=true \
.venv/bin/python -m scripts.seed_nawa_data_demo \
  --workspace-slug agentium-showcase \
  --workspace-name 'Agentium Showcase'
```

`WORKER_EAGER_MODE=true` exécute les jobs inline en l’absence de worker Celery. Contrôler aussi la configuration des services qui exécuteront les prochains runs : ces variables limitées à la commande ne changent pas les processus déjà démarrés. Ne pas ajouter `--reset` ni `--refresh` pour une simple répétition. Une nouvelle clé API peut être imprimée par le seed : ne pas copier cette sortie dans le compte rendu ou les captures.

Relever les IDs workspace/datasets/modèles/systèmes, les versions et le champion. Relancer une fois les mêmes commandes pour vérifier la réutilisation des objets et le maintien du champion. Le seed peut ajouter un historique d’exécutions ; l’absence de duplications ne signifie pas qu’il ne produit aucune nouvelle écriture. Les scripts touchent aussi le catalogue global de skills ; le paramètre de workspace borne les objets métier de ce scénario, pas l’intégralité des écritures en base.

Après la dernière relance, remettre la langue de présentation de Showcase en français : Data Demo force actuellement `presentation.locale` à `en`. Vérifier le résultat dans un navigateur sans préférence de langue déjà enregistrée.

## S2 — Valeur et coût déclarés

Préparer la Capability PR to PO et les prix des skills après **la dernière relance** du seed PR to PO, qui remet `value_per_outcome` et son prix à zéro. Conserver les hypothèses métier, leur unité, leur origine et leur période. Le brief ne fournit pas de montants à appliquer : aucune économie ou valeur ne doit être inventée.

Vérifier dans Impact que la valeur est explicitement déclarée, que les coûts renseignés ont leur provenance et que le nouveau run est attribué au bon système. Une baseline déclarée et un gain mesuré restent deux preuves distinctes.

## Répétition de qualification

1. Choisir **Agentium Showcase** et confirmer PR to PO + Retention Board dans Work ; vérifier Data et Models.
2. Ouvrir MCP, constater les URL fixtures et le scellement SAP ; tester une découverte/import en lecture seule.
3. Parcourir Churn Radar : lineage du dataset, versions du modèle, comparaison et promotion du champion ; vérifier la skill publiée.
4. Exécuter PR to PO avec ses données synthétiques, lire le DAG et la politique de mandat historique.
5. Montrer la décision humaine attendue et la preuve du blocage de l’écriture SAP. Ne pas désceller une écriture réelle pour la démonstration.
6. Ouvrir la trace du résultat, retrouver son audit par `run_id`, contrôler les coûts et revenir au résultat métier.
7. Ouvrir Impact en présentation, distinguer valeurs déclarées et observées, puis terminer dans Work avec l’utilisateur métier.

Capturer chaque étape après chargement en FR, en thèmes clair et sombre, à 1440 px et à 1024 px. Relever le texte exact, les interactions clavier, les liens, les débordements et les preuves disponibles. Un statut « terminé » ne suffit pas à qualifier le mandat, la qualité, les économies ou la provenance des données.
