# Corpus KB fictif — démo Andritz / Knowledge Capture

**Tout le contenu de ce dossier est synthétique** (noms de sites, numéros SAP/CRM, historiques). Il sert uniquement à **indexer** une base de connaissance dans le workspace démo pour coller au script [`../../andritz-knowledge-capture-demo.md`](../../andritz-knowledge-capture-demo.md).

## Rôle pédagogique

Les fichiers couvrent volontairement :

- ce que la KB « a déjà » : procédures **génériques**, listes pièces, seuils d’alarme de base ;
- ce qui **manque** pour le scénario : raisonnement sur priorités *critical* avant dépassement ISO, sources faisant foi en litige client, validation runbook.

L’expert en capture vient **combler** ces trous ; le RAG peut retrouver les fiches génériques pendant l’atelier.

## Ingestion (workspace Andritz)

1. Créer ou utiliser une **collection** alignée sur le Context démo (ex. `runbooks-hydro-v4` ou une collection unique `andritz-demo-hydro`).
2. Uploader **tous les `.md`** (API documents / UI Knowledge) dans cette collection ou répartir par tags si votre pipeline le permet.
3. Lier le **Context** « HYDRO Service — Europe Nord » aux `data_refs` / collection correspondante (selon votre modèle Agentium).
4. Vérifier une requête test du type : *« vibration post révision Kaplan G2 Rivage-Lac »* — vous devez voir le runbook V4 et la liste pièces, **sans** la finesse de la note SP-HYD-1127 tant qu’elle n’est pas ingérée post-revue capture.

## Fichiers

| Fichier | Rôle |
| ------- | ---- |
| `RB-HYD-V4-RIVAGE-G2-vibration-post-revision.md` | Runbook officiel **v4** (générique) |
| `SPARE-PARTS-CRITICAL-KAPLAN-G2.md` | Pièces critiques G2 / Kaplan |
| `METRIS-RIVAGE-LAC-G2-trends-and-alarms.md` | Paramètres trend / alarmes Metris |
| `SAP-PM-ORDER-TEMPLATE-HYDRO-SERVICE.md` | Gabarit d’ordre d’intervention SAP PM |
| `SAP-PM-EXAMPLE-4500123789-RIVAGE-G2.md` | **Exemple** d’ordre fictif (joint arbre) |
| `SLA-HYDRO-EU-NORD-critical-escalation.md` | SLA 72 h & définition *critical* (sans arbitrage vibration limite) |
| `SP-HYD-1127-internal-note-reserrage-balancing.md` | Note interne citée dans la réponse experte démo |
| `CRM-SERVICEMAX-27-4418-ticket-excerpt.md` | Extrait ticket CRM aligné avec la **réponse B** (preuve Metris) |
