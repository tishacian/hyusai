# ADR 0003 — Généraliser les frontières, pas les cas d'usage

- **Statut** : Accepté
- **Date** : 2026-09-23
- **Portée** : IAM par défaut, drapeaux de workspace, contenu client dans le moteur, application Work, contrat de valeur, écriture externe, BRD
- **Contexte source** : analyse de généralisation de la plateforme après les portes F1–F6, vérifiée sur `demo/agentic` (`275332ff`)
- **Prolonge** : [ADR 0002](0002-nomenclature-projet-par-client.md) et la doctrine de `backend/app/services/workspace_features.py`

---

## Contexte

Agentium a grandi avec trois clients qui servent aussi de validateurs : ANDRITZ
(industriel, RAG), NAWA (automatisation gouvernée, PR → PO) et PIH (BRD → System).
La question était de savoir si ces clients avaient dévié la plateforme.

La vérification dit que non pour le moteur récent, et oui à quelques frontières.

- Les services F1–F6 (préparation, dossiers, portfolio, édition) ne contiennent aucun
  identifiant client.
- Aucun code d'exécution ne branche sur un slug client : tout passe par la famille
  estampillée ou un drapeau de workspace.
- En revanche, sept portes lisaient encore une liste de slugs dans la configuration
  globale ou en dur, dont l'enforcement IAM. Seul ANDRITZ était gouverné ; NAWA et
  tout nouveau workspace étaient ouverts par omission.
- Du contenu client vivait dans des modules génériques : scénarios de démo Sentinel CI
  dans l'exécuteur d'actions, règles PIH dans le prompt de génération BRD, vocabulaire
  Sentinel CI appliqué à tous les tenants par le grounding.

La posture retenue tient en une phrase : **généraliser les frontières de confiance et
de configuration, pas les cas d'usage métier.** Un client reste spécifique dans ses
corpus, ses prompts, son thème, ses BRD et ses applications. Il ne l'est plus dans les
permissions, les contrats de preuve, les connecteurs sensibles, les interfaces publiées
et le pilotage de la valeur.

---

## Décisions

### D1 — Un client est une fixture ou un adapter, jamais une dépendance du moteur — **Acté**

La règle devient un contrat exécuté en CI :
`backend/app/tests/infra/test_tenant_neutral_contract.py`. Il compte les identifiants
client dans le code exécutable et les données du backend et du frontend. Les
commentaires et docstrings sont exclus : ils portent le retex et doivent pouvoir
nommer les clients.

Chaque fichier qui en contient encore figure dans `tenant_neutral_baseline.json`, avec
son compte exact et une catégorie :

| Catégorie | Sens | Cible |
|---|---|---|
| `adapter` | code qu'une famille, un pack ou un manifest sélectionne volontairement | reste |
| `family` | les noms de famille canoniques | reste |
| `tooling` | exemples en ligne de commande | reste |
| `fixture` | contenu ou règle d'un client dans un module générique | **0** |
| `demo` | contenu de démo scénarisé parmi les services | déplacé vers les seeds |
| `client-app` | application ou habillage client dans le shell produit | lot 2 |

Le compte est un cliquet : un fichier qui gagne un identifiant échoue, un nouveau
fichier échoue, et un fichier qui en perd échoue tant que son entrée n'est pas
abaissée. Trois règles complètent : aucun réglage ne liste des slugs de workspace,
aucune porte n'y retombe, aucun code ne branche sur un slug client.

### D2 — Plus aucune liste de slugs — **Acté**

La migration `111_freeze_ws_slug_fallbacks` écrit sur chaque workspace ce que
répondaient les sept listes (IAM, OpenAI Realtime, STT temps réel, et les trois
connecteurs du showcase). Elle lit l'environnement du déploiement quand la liste était
configurable, n'écrase jamais une valeur explicite et note ce qu'elle a écrit pour que
le downgrade retire exactement cela. `feature_enabled` perd son paramètre de repli :
une nouvelle liste n'est plus possible en un mot-clé. La liste d'enregistrement
LiveKit, affichée mais jamais appliquée, disparaît.

### D3 — Un nouveau workspace naît gouverné — **Acté**

`iam_enforced` devient un défaut de code, au sens de la doctrine de
`workspace_features.py` : absent signifie gouverné, `false` est un opt-out explicite.
La migration 111 a écrit `false` sur chaque workspace qui était ouvert avant elle :
aucun ne change. Un workspace créé ensuite démarre gouverné : un contributeur peut
créer et tester un draft ; publier, gérer les membres ou configurer un connecteur
sensible demande un rôle. Les gabarits owner et admin ont une règle pour chacune des
45 paires (ressource, action) que le code appelle, donc un nouveau workspace ne bloque
pas ses propres administrateurs. `iam_generic_engine` gouverne toujours partout.

### D4 — Ne pas abstraire avant le deuxième cas réel — **Acté**

Le framework d'actions externes attend une deuxième action réelle. Le contrat BRD
générique attend un deuxième BRD réel. D'ici là, les propriétés de sûreté d'une
écriture (idempotence, un timeout n'est pas un succès, réconciliation, décision
humaine nommée) se vérifient sur l'action PO existante : elles relèvent de la
frontière de confiance, pas de la généralisation.

### D5 — Une feuille de route par lots livrables — **Acté**

Pas de branche unique pour toute la feuille de route : chaque lot est une unité qui se
relit, se déploie et se retire seule. Chaque lot met à jour cet ADR.

| Lot | Contenu | Déclencheur | Critère de fin |
|---|---|---|---|
| **1** | D1, D2, D3 ; vocabulaire Sentinel CI réservé à sa famille ; libellés NAWA retirés du catalogue de skills | — | contrat vert, 0 liste de slugs |
| **1b** | sortir les 9 `fixture` : exécuteur d'actions, table des wrappers, prompt BRD, agent procurement, flow PR → PO, scénarios de `core/workspace-experience.ts`, client SharePoint, deux placeholders | lot 1 déployé | `fixture` = 0 |
| **2** | Work comme application de workspace : page d'accueil, `features/nawa`, habillages NAWA du shell et du chat, export brandé | lot 1 déployé | `client-app` hors `features/<client>` = 0 |
| **3** | contrat de valeur du portfolio : responsable, indicateur, unité, cible, période, convention, source, approbation | définition produit | saisie gouvernée en place |
| **4** | sûreté de l'action SAP PO (D4) | — | propriétés vérifiées et testées |
| — | framework d'actions ; contrat BRD générique | deuxième action ; deuxième BRD | — |

Porte 0 (un contributeur NAWA crée et lance un System) se ferme en parallèle : c'est
une validation, pas du développement.

---

## Métriques

Mesurées sur la branche du lot 1, code exécutable seulement :

| Indicateur | Avant | Après lot 1 |
|---|---|---|
| Listes de slugs dans la configuration ou en dur | 7 | **0** |
| Workspaces nouveaux gouvernés par défaut | non | **oui** |
| Fichiers `fixture` / occurrences | — | 9 / 77 |
| Fichiers `client-app` / occurrences | — | 25 / 753 |
| Fichiers `demo` / occurrences | — | 9 / 203 |
| Fichiers `adapter` / occurrences | — | 37 / 254 |

Le lot 1b se mesure à `fixture`, le lot 2 à `client-app` ; les chiffres viennent de
la baseline, pas d'une estimation.

---

## Conséquences

- Ouvrir un workspace aux contributeurs sans rôle devient une décision enregistrée
  (`features.iam_enforced: false`), plus une omission.
- Une variable d'environnement retirée (`IAM_ENFORCED_WORKSPACE_SLUGS`,
  `OPENAI_REALTIME_ENABLED_WORKSPACE_SLUGS`, `VOICE_REALTIME_STT_WORKSPACE_SLUGS`,
  `LIVEKIT_RECORDING_ALLOWED_WORKSPACE_SLUGS`) reste inoffensive dans l'environnement
  d'un conteneur ; dans un fichier `.env` lu par les réglages, elle bloque le
  démarrage. La VM lit l'environnement (`AGENTIUM_DISABLE_DOTENV=1`).
- Le grounding d'un tenant générique ne se durcit plus sur « rapport » ou
  « important » : `port` était un terme Sentinel CI comparé en sous-chaîne.
- Nommer un client dans un module générique fait échouer la CI ; l'expliquer dans un
  commentaire, non.

## Seuil de réouverture

Rouvrir D3 si un workspace créé après la migration 111 doit être ouvert par défaut
pour une raison produit, pas par commodité de démo. Rouvrir D4 à l'arrivée de la
deuxième action externe ou du deuxième BRD.
