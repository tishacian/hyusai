# Agentium — Lot 1 navigation et stabilité workspace

Date du candidat local : 2026-07-15
Branche de travail : `demo/agentic`
État : implémenté localement, non committé, non poussé et non déployé.

Ce document complète la baseline du
[`Lot 0`](./agentium-navigation-lot-0-baseline.md). Il ne modifie ni le modèle
produit décrit dans [`mental-model.md`](./mental-model.md), ni les extensions de
workspace : Showcase garde le shell Agentium standard ; Sentinel-CI et Octocity
gardent leurs Mission Rooms immersives ; Andritz garde son profil métier et ses
trois applications.

## Périmètre

Le Lot 1 corrige cinq instabilités sans introduire de logique métier propre à un
tenant :

1. conserver le workspace d'origine sur chaque retry et chaque stream ;
2. donner à un seul resolver la propriété des décisions de redirection ;
3. conserver une largeur de canvas stable quand le rail s'étend ;
4. classer Client360 dans la lentille `Operate` pour le cockpit admin ;
5. réinitialiser le contexte de façon atomique lors d'un changement de
   workspace.

## 1. Contrat transport

### HTTP et refresh d'authentification

- Une requête capture son `X-Workspace-Slug` avant le premier envoi.
- Un header explicite n'est jamais remplacé par le workspace courant.
- Pour `HttpClient`, le retry après `401`, ainsi que le retry historique des
  erreurs auth enveloppées en `500`, réutilise la requête déjà enrichie.
- Les transports `fetch` directs ne rejouent qu'un vrai `401`, une seule fois.
- Un échange de refresh est partagé entre `HttpClient` et les transports
  `fetch` directs. Il survit au désabonnement d'un consommateur, car un refresh
  token rotatif déjà consommé ne peut pas être rejoué sans risque.
- Une requête métier est rejouée au plus une fois. Un second `401` est terminal.
- Deux requêtes de workspaces distincts peuvent attendre le même refresh ;
  chacune conserve son propre slug sur son retry.

### Streams

- `SseService` et `RunStreamService` utilisent le transport authentifié commun,
  avec un slug immuable capturé à la souscription.
- Un changement de workspace annule le lecteur et complète l'observable sans
  frame métier tardive.
- Une annulation de chat n'émet pas le marqueur synthétique `done` : ce marqueur
  aurait pu valider un buffer partiel de l'ancien workspace.
- Les callbacks de run, HITL, debug, polling et `getRun` sont gardés par
  `{ workspaceSlug, epoch }`.

### Voice et LiveKit

Le navigateur ne permet pas d'ajouter un header arbitraire au handshake
WebSocket. La session Voice transporte donc le slug capturé dans le paramètre
authentifié `workspace_slug`. Il n'existe pas de retry automatique de ce socket ;
aucun replay de commande ou d'audio n'est inventé.

Pour LiveKit, le même slug explicite est conservé sur `config`, `token` et
`agent/dispatch`. L'ordre est :

```text
config → token → room.connect + listeners → agent dispatch → microphone → session.start
```

Les événements immédiats du bridge ne sont donc pas perdus, tandis qu'un échec
de dispatch reste antérieur au premier octet audio et à `session.start`. Un
changement de workspace produit une erreur terminale dédiée : les consommateurs
ne basculent jamais vers un WebSocket du nouveau workspace avec l'ancien ID de
session. Voice et LiveKit invalident leurs handlers synchroniquement avant la
fermeture réseau.

Le reset audio invalide aussi les générations et callbacks avant `stop` ou
`close`, neutralise les événements finaux `dataavailable` / `onstop`, arrête les
`MediaRecorder`, les pistes et les acquisitions micro tardives, puis annule TTS
et URLs audio. VoiceLoop, Knowledge Capture, CaptureEngine et les connexions
realtime ne peuvent ainsi produire aucune continuation de A dans B.

## 2. Propriétaire unique des redirections

`NavigationResolverService` est l'unique propriétaire des décisions de policy :

- profil métier et compatibilités Chat/Capture ;
- route par défaut d'un workspace démo ;
- entrée `/workspace` vers les réglages du workspace actif ;
- activation précoce d'un slug porté par un deep-link workspace ;
- fallback borné de `/workspace` vers `/hypervisor` après l'échec du chargement
  initial puis de son unique retry forcé. Les autres routes ne sont pas
  redirigées par ce fallback.

Le guard appelle le resolver, enregistre sa décision et laisse Angular exécuter
le `UrlTree`. Le shell et `WorkspaceRedirectComponent` ne prennent plus de
décision. La valeur d'audit canonique est `navigation_resolver`. Le backend
accepte temporairement les anciens propriétaires puis les canonicalise, afin de
permettre un rollout frontend/backend sans rupture.

Les alias statiques déclarés dans la configuration Angular restent exécutés par
le routeur et sont audités comme `angular_router`; ils ne constituent pas une
seconde policy de résolution.

## 3. Canvas, rail et Client360

- Le host du rail réserve toujours `56px` dans le layout.
- Le rail interne passe de `56px` à `200px` en overlay, sans modifier le
  `flex-basis` du canvas.
- Client360 (`/client360`) appartient désormais aux matches de la lentille
  `Operate` dans le cockpit admin standard.
- Les exceptions visuelles Mission Room / Sentinel-CI / AYA restent inchangées,
  conformément à [`agentium-ui-chrome.md`](./agentium-ui-chrome.md).

## 4. Transaction atomique de workspace

`WorkspaceService` publie une seule valeur composite :

```text
{ list, activeSlug, epoch }
```

Lors d'une transition A → B :

1. le service construit `{ previousSlug, nextSlug, previousEpoch, nextEpoch }` ;
2. tous les resetters enregistrés s'exécutent synchroniquement pendant que A
   est encore le scope courant ;
3. la clé du workspace actif est écrite ;
4. `activeSlug`, `epoch` et la liste sont publiés dans une seule écriture de
   signal.

Les réponses asynchrones capturent un scope immuable et vérifient l'epoch avant
de muter l'UI. Les streams, connexions, pollings, overlays, panels, sélections,
caches et stores partagés sont fermés ou vidés dans la phase de reset.

Angular réutilisant normalement un composant quand seul `:slug` change, la
stratégie de route recrée tout le subtree `/workspace/:slug/*`, y compris le
Chat focus. Les changements de workspace sur une route globale identique
conservent la surface sémantique mais recréent la page, comme le faisait déjà le
title bar admin.

### Persistance locale

Toute donnée métier conservée côté navigateur est workspace-scopée. Une valeur
legacy sans slug n'est jamais attribuée au workspace qui se trouve simplement
actif au moment de la mise à niveau :

- les valeurs sensibles ou métier sans provenance sont supprimées/ignorées ;
- seules les préférences non sensibles peuvent être migrées une fois ;
- les identifiants de session Chat, brouillons Flow/System, contexte
  Chat→Quality, configs Connectors et préférences Mission Room ne traversent
  plus A → B.

## 5. Compatibilité des workspaces de référence

| Workspace | Contrat préservé |
|---|---|
| Andritz | profil `business_end_user`, Recherche, Client360 PDR, Capture |
| Showcase | cockpit et rail Agentium standards |
| Sentinel-CI | shell immersif, AYA, carte et Mission Room spécifiques |
| Octocity | généralisation Mission Room/OCTAVE, sans identifiants Sentinel |

Les workspaces restent des assemblages de configuration, données, Systems et
Capabilities sur le socle Agentium. Le Lot 1 n'ajoute aucune logique produit ou
de navigation conditionnée par un slug métier. La seule exception technique est
la migration bornée de l'ancienne clé `sentinel-ci-aya-morning-dismissed` vers
son stockage workspace-scopé ; elle ne peut donc pas modifier Octocity.

## 6. Gates du candidat

Résultats exécutés sur l'état local final :

- tests unitaires frontend : `156/156`, dont retries concurrents, streams,
  route reuse, reset atomique et réponses tardives A → B ;
- `tsc -p tsconfig.app.json --noEmit` : succès ;
- build Angular : succès, avec les warnings de budget/CommonJS déjà connus ;
- `check:ui-chrome`, `check:i18n` et `git diff --check` : succès ;
- matrice backend Andritz/navigation/Mission Room : `71 passed` ;
- revue finale du diff transport, persistance locale et continuations
  asynchrones workspace-scopées.

Non exécutés dans ce lot local : tests E2E live opt-in, commit, push et
déploiement. Ils nécessitent une autorisation explicite propre au Lot 1.
