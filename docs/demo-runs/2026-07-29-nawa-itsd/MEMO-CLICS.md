# Mémo de clics — NAWA WE, démo du 29/07 à 12h00

Tout ce qui suit a été joué sur `https://agentium.papai.ai` le 29/07 au matin,
frontend `f6f79acd`. Les identifiants de démo : `Staff ID 40219`, code `553017`.

## Catch phrases (EN) — à planter pendant les clics

**Headline**
> One front door. One live service. Thirty-nine recognised.

**Assistant (onglet A)**
> The desk stops being a portal — the conversation *is* the request.
> Same intake for every service. Only Password Reset acts for real.
> Ask a policy question → you get a citation. Raise a request → you get a run.
> Identity first. Privileged write second. Always.

**Live vs Preview**
> One path runs. The others play as they will run — and the banner says so.
> Preview is honest simulation. Not a promise, not a fake go-live.

**Cas de bord / quality (onglet B — Noura)**
> The model said verified. The evidence record was empty. The graph stopped the write.
> Policy enforced by the platform — not by the model's mood.
> When the bridge is down, we withhold the write and we ledger it.

**Trace / Rerun**
> Every decision leaves a trail. Click Rerun — same input, same graph, same proof.
> Auditability is a product feature, not a slide.

**Builder / OS (parcours plateforme)**
> The business sees a desk. The builder sees the same automate.
> Real inference. Simulated directory write. Written in the node — not in the pitch.
> The ledger records what was prevented, not only what was done.

**Observability / coût**
> Ninety-two runs. Zero failures. Cost per ticket: a few cents, measured.
> Observability is live — not a report we send next week.

**Catalogue**
> Thirty-nine services from your workbook. Two live. The rest in the rollout plan.

**Clôture produit**
> Recognised by code. Executed under gates. Proven in the trace.

---

## 0. Cinq minutes avant

Un onglet propre, connexion, et vérifier la pastille de workspace en haut à
droite : elle doit dire **Nawa**. Trois onglets préparés, dans cet ordre
d'usage :

| Onglet | Adresse | Ce qu'on y fait |
| --- | --- | --- |
| A | `/nawa/itsd/assistant` | le parcours principal, l'assistant comme porte d'entrée |
| B | `/nawa/itsd/password-reset` | la file de demandes entrantes et les cas de bord |
| C | `/nawa/itsd` | le catalogue des 39 services |

Le bouton **Auto** en haut à droite fixe le thème en un clic (Auto → Light →
Dark). Si la salle est claire, mets Light avant d'entrer, pas pendant.

Aucun autre onglet de la plateforme ouvert : les autres espaces de travail sont
d'autres clients.

## 1. Parcours principal — onglet A, 12 minutes

Quatre saisies, dans cet ordre. Elles sont testées ; ne pas improviser au
clavier pendant cette séquence.

1. `I lost my password.` → l'assistant reconnaît le service, dit qu'il traite la
   demande ici, et demande l'identité avant de changer quoi que ce soit.
2. `Staff ID 40219, code 553017` → le run réel démarre. Classification, contrôle
   d'identité (deux preuves au dossier), action annuaire en dry-run, mot de passe
   temporaire, message bilingue au demandeur, ticket clôturé. Un lien **Open the
   full trace** apparaît en bas du tour.
   → La phrase à dire : *une seule voie agit, et elle agit vraiment.*
3. `Can my line manager collect my temporary password for me?` → réponse issue de
   leurs politiques publiées, avec le passage cité en dessous. C'est la
   bibliothèque, pas un service.
4. `Remove a colleague from the sales distribution list.` → badge **PREVIEW**, la
   procédure du client déroulée pas à pas, l'étape de dépôt marquée
   `SUBMITTED HERE` puisque la conversation vient de la satisfaire, puis arrêt sur
   la porte **Line Manager**. Cliquer **Approve** : le déroulé reprend et clôture.

Option voix, si la salle est calme : **Speak** dicte avec le transcript qui
s'écrit dans l'invite, **Voice off/on** coupe la réponse parlée.

## 2. Les cas de bord — onglet B, 5 minutes

Cinq demandes en attente, chacune prouve une chose différente. Cliquer la
demande, puis **Handle this request**.

| Demande | Canal | Ce qu'elle prouve |
| --- | --- | --- |
| Hassan Al-Mansouri, 08:34 | téléphone | le chemin nominal, reset complet |
| Youssef Benali, 08:47 | téléphone | l'appelant dit « reset », le symptôme dit verrouillage — et la demande est en français |
| Layla Haddad, 09:02 | e-mail | preuves d'identité insuffisantes → porte humaine |
| Omar Al-Kuwari, 09:11 | guichet | la passerelle vers l'annuaire est indisponible → incident, écriture retenue au registre |
| Noura Al-Emadi, 09:26 | téléphone | **le modèle dit « vérifié », le dossier de preuves est vide → la règle des deux preuves arrête l'action** |

La dernière est le meilleur moment de la démo pour l'audit et la qualité : la
politique du client est appliquée par le graphe, contre l'avis du modèle.

Le bandeau en haut dit « Preview environment — directory changes run in dry-run,
everything else runs for real ». Le laisser à l'écran, il répond d'avance à la
question. **Technical view** en haut à droite montre les étapes.

## 3. La preuve — 5 minutes

Depuis la conversation ou la file : **Open the full trace** → la page de run.
Étapes de compétences, entrée, points de contrôle, et un bouton **Rerun** qui
rejoue le même run. C'est l'écran pour qui parle d'auditabilité et
d'observabilité. `/orchestration` donne la vue transverse si on la demande.

## 3 bis. Le parcours plateforme — 10 minutes

Le passage app → OS → builder → configuration → rejeu → observabilité. Tout ce
qui suit a été cliqué le 29/07 vers 11h00 ; les écrans répondent et aucune API
n'échoue.

**1. Le pivot.** Depuis la file de demandes (onglet B), bouton **Flow Builder**
en haut à droite → `/systems/571d067a…/flow`. Même espace de travail, même
marque NAWA, chrome sombre de l'OS. La phrase : *le métier voit un desk, le
constructeur voit le même automate.*

**2. Le graphe.** 29 nœuds, et ils sont libellés comme un récit : `Step 1 ·
Classify the request (model call)`, `Step 2 · Assess the identity evidence`,
`Step 2b · Human approval before a privileged reset`, `Step 3a · Dispatch the
reset to the automation bridge`, `Step 6 · Write the audit ledger entry`. Le
bandeau au-dessus est le manifeste d'exécution (unités vivantes, source, clés de
configuration).

**3. La configuration.** Cliquer `Step 2 · Assess the identity evidence (model
call)` : le panneau de droite donne l'identité du nœud (type `llm`, kind `task`),
son libellé, sa description, ses ports typés et **RUNTIME PARAMETERS ·
CONFIGURED**. La description est votre meilleure phrase, elle est écrite dans le
graphe : *REAL inference. Weighs the evidence the agent collected against the
Nawa ITSD policy (two independent proofs, one of them a line-manager
confirmation…)*.

Deux autres nœuds valent le clic selon le public :

- gouvernance et audit → `Step 6 · Record the held reset in the audit ledger`,
  dont la description dit que **le registre consigne ce qui a été empêché, pas
  seulement ce qui a été fait** ;
- si on te pousse sur le périmètre → `task.ad_reset`, qui dit noir sur blanc
  *SIMULATED privileged gesture. No directory is contacted… dry-run semantics*.
  C'est le nœud qui prouve que la frontière entre réel et simulé est écrite dans
  le produit, pas dans le discours.

**4. Les versions.** Bouton **Versions** : l'historique du flow. Ouvrir, montrer,
refermer.

**5. Le rejeu.** Le bouton **Replay** du builder est inactif (il attend un run
chargé) : ne pas le cliquer. Le rejeu se montre sur la page de run —
`/runs/a29a6189-3a95-41ec-ba30-ee1503d4eba1` est le run nominal de ce matin, 6 s,
`approved`, gardé sous la main. On y voit **Skill trail**, **Input**,
**Checkpoints**, **Output**, et le bouton **Rerun** rejoue la même entrée sur le
même graphe. C'est la réponse à « comment on audite une décision d'agent ».

**6. L'observabilité.** `/observability` → **Workspace monitor** avec les vraies
données de l'espace : 92 runs, 88 terminés, 4 en cours, **0 échec**, P95 11 s,
décisions de recherche documentaire (hybride 27, contournement trivial 2), liste
des Systems. Onglets OPERATIONS / QUALITY / PERFORMANCE / RUNS.

Puis `/runs` : la liste avec le **coût par exécution, 0,013 à 0,032 $**. C'est
l'argument le plus concret de la démo — le prix d'inférence d'un ticket traité,
mesuré, pas estimé.

### Les trois phrases à avoir prêtes sur ce parcours

- **« 49 warnings » dans la checklist** — ce sont des avertissements de
  conception, **zéro erreur** : neuf disent « ce nœud ne porte pas de
  compétence » et visent les nœuds du banc qui fabriquent les cas de démo,
  quarante sont des indices de variables que le résolveur d'écran ne voit pas
  mais que le moteur résout. La preuve est à côté : 88 runs terminés, aucun en
  échec. Rien ne bloque l'enregistrement ni l'exécution. (À nettoyer côté
  plateforme après la démo : le résolveur client ignore le pool de variables du
  moteur.)
- **« 27 eval breaches » sur l'observabilité** — ce sont des seuils de qualité
  que la plateforme applique à ses propres réponses, pas des exécutions en
  échec ; la colonne FAILED est à zéro.
- **« Azure OpenAI » dans la palette de compétences** — c'est le catalogue de
  compétences de la plateforme ; la cible d'exécution se choisit au déploiement,
  et en on-prem c'est votre endpoint souverain.

> Un System de l'espace s'appelait « Agentium Workspace Chat » et s'affichait
> dans la liste de l'écran d'observabilité : renommé **NAWA Workspace Chat** le
> 29/07 à 11h05. Ce nom est réécrit par l'amorçage si le backend redémarre — donc
> ne pas redémarrer le backend avant la démo.

## 4. Le catalogue — onglet C, 3 minutes

39 services du classeur, deux marqués **AVAILABLE** (Password Reset, User Q&A),
les autres **IN THE ROLLOUT PLAN**. La bascule **Business case** en haut à droite
sort les volumes et les gains : ne l'ouvrir que si la conversation va sur le
chiffrage.

## 5. Écrans et gestes à éviter

- Le parcours plateforme est en §3 bis, avec ses trois phrases prêtes : il se
  montre, mais dans cet ordre-là et sans s'attarder sur la checklist.
- **Le bouton Replay du builder** est inactif : le rejeu se montre sur la page de
  run, avec **Rerun**.
- **`/orchestration`** ouvre un brouillon de flow (4 nœuds, « Scratchpad ») : utile
  seulement pour montrer la palette de primitives si on demande « comment on en
  crée un nouveau ». Ne rien y enregistrer.
- **Réglages de modèles / portail fournisseur** : masqués par le mode démo, ne
  pas aller les chercher.
- **Trois services arrivent avec une procédure vide** dans le classeur —
  `providing-vpn-avd-access-for-users`, `closure-of-non-responsive-tickets`,
  `collecting-user-hardware-information`. L'assistant le dit honnêtement plutôt
  que d'inventer des étapes. C'est une bonne remontée pour leur BA, ce n'est pas
  un moment de démonstration : ne pas demander de VPN.
- **Les demandes d'imprimante** (« printer code ») : trois services se
  ressemblent trop, la réponse part en bibliothèque. Éviter.
- **Improviser des phrases très courtes hors catalogue** : le repli est propre
  (réponse de politique sourcée) mais ce n'est pas ce qu'on veut montrer.

## 6. Phrases sûres, mesurées ce matin

Demandes qui atteignent leur service : `I lost my password.` ·
`I forgot my password and I cannot sign in this morning.` ·
`My account is locked.` · `I am locked out of my account.` ·
`My password expired and I cannot log in.` ·
`I need an email account for a new joiner starting Sunday.` ·
`We have a new hire on Monday, he needs an email.` ·
`Please add two members to the finance distribution group.` ·
`Remove a colleague from the sales distribution list.` ·
`I need Power BI installed on my laptop.` ·
`Please install Adobe Acrobat on my machine.` ·
`A colleague is leaving on Friday, block his account.` ·
`Please reactivate the mailbox of a colleague who came back.` ·
`Please create a shared mailbox for the project team.`

Questions qui restent des questions : `How many failed sign-ins lock an account,
and how long does it stay locked?` · `What identity evidence do you need before
you reset a password?` · `Can my line manager collect my temporary password for
me?` · `What is the response target for a priority 2 ticket?`

## 7. Si le modèle lâche pendant la démo

Le jumeau sans modèle est en place, à jour ce matin (29 nœuds, zéro appel de
modèle, règle des deux preuves et voie chat comprises). Depuis un terminal
local :

```bash
python docs/demo-runs/2026-07-29-nawa-itsd/nawa_flow_switch.py            # où on en est
python docs/demo-runs/2026-07-29-nawa-itsd/nawa_flow_switch.py fallback    # jumeau simulé
python docs/demo-runs/2026-07-29-nawa-itsd/nawa_flow_switch.py primary     # retour
```

Le script lit un jeton dans `/tmp/tok` ; le régénérer si besoin par un login sur
l'API. La bascule prend une seconde et ne change rien à l'écran côté demandeur.

**Une seule commande touche la pile déployée** : `sudo /root/nawa-deploy.sh up`
sur la VM. Toute invocation `docker compose` à la main perd la configuration —
c'est exactement l'incident de ce matin, il a coûté une heure.

## 8. Trois réponses courtes aux questions probables

- *« C'est simulé ? »* — L'intention est reconnue par le même code sur les 39
  services. Une voie agit réellement, avec l'annuaire en dry-run pour la démo ;
  les autres se jouent telles qu'elles tourneront, et le bandeau le dit à
  l'écran.
- *« Quel modèle ? »* — Runtime managé pour cette démo. En on-prem, le même
  graphe s'exécute contre votre endpoint souverain, sans changer le graphe.
- *« Qu'est-ce qui vous manque pour automatiser un service ? »* — Une procédure
  écrite. Trois des leurs arrivent vides ; c'est le premier livrable de l'intake.
