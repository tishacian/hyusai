# ADR 0002 — Nomenclature projet par client, isolation générique

- **Statut** : Accepté
- **Date** : 2026-09-22
- **Portée** : `rag/project_references.py`, familles de workspace, dépôt sécurisé, planificateur de corpus, multi-client
- **Contexte source** : revue de l'ontologie documentaire ANDRITZ et de ses consommateurs dans la pile de récupération
- **Commit associé** : `db90635f` — *gate Andritz project grammar to the Andritz workspace*

---

## Contexte

La grammaire d'identifiants ANDRITZ — jetons SPL compacts (`BBA120`, `BAO100`,
`ELM001Y`), codes Needlepunch à cinq chiffres issus de la structure de dépôt,
série machine extraite à côté du projet — était compilée en Python et s'exécutait
pour **tous** les workspaces. Aucun garde par client, aucune notion de famille dans
le module.

Les champs qu'elle produit ne sont pas décoratifs. `project_code` irrigue la pile de
récupération : filtres durs côté Qdrant via le planificateur de corpus, inventaires
projet déterministes, décomposition des requêtes comparatives, repondération lexicale,
re-classement. `source_family` alimente des bonus additifs et un plancher de rappel sur
les listes de pièces détachées.

Un second client industriel héritait donc des règles ANDRITZ sans que personne ne
l'ait décidé. Le risque n'était pas la panne — les chemins de filtrage sont gardés et
échouent ouverts — mais le bruit : une référence de pièce, une norme ou un composé
allemand de forme `[A-Z]{3}\d{2,4}` devenait un code projet, entrait dans la pondération
lexicale et le re-classement, et pouvait faire répondre au planificateur qu'aucune
source ne correspondait.

---

## Décisions

### D1 — Le verrou est le stamp `family`, jamais le slug — **Acté**

La grammaire ne s'exécute que dans un workspace dont `settings.family` vaut `andritz`.
Le slug ne suffit plus.

Cette décision n'en est pas vraiment une : elle applique la doctrine déjà écrite dans
`app/services/workspace_features.py`, qui dit que le code d'exécution ne doit jamais
déduire une spécialisation métier d'un slug mutable. On aligne un module qui y
échappait.

### D2 — Défaut fermé — **Acté**

Le schéma actif est porté par une variable de contexte dont le défaut est vide. Un
bind oublié n'active pas la grammaire, il la désactive. Entre fabriquer un faux
identifiant chez un tiers et n'en fabriquer aucun, le second est le moins coûteux.

Là où le workspace est déjà sous la main, le schéma se passe en argument explicite
plutôt que par la variable de contexte. C'est la forme à privilégier : elle ne peut
pas être perdue au franchissement d'un thread ou d'une tâche.

### D3 — La nomenclature est cliente, l'isolation est générique — **Acté**

C'est la couture qui rend la décision tenable.

| Reste spécifique ANDRITZ | Reste générique |
| --- | --- |
| Jetons SPL | `reject_cross_project_sources` |
| Codes Needlepunch | `project` dans les types préservés |
| Série machine | Politique de réponse industrielle |

Un second industriel obtient ainsi la **capacité** de cloisonnement par affaire sans
hériter de la **nomenclature** d'un autre client.

### D4 — Un pack de règles par client, pas un réglage produit — **Acté**

On refuse un réglage `project_reference_scheme` exposé au produit. Un nouveau client
industriel reçoit son propre pack de règles, écrit par Datategy et versionné comme du
code, derrière une garde par famille.

Raison : ces expressions portent des gardes nées d'incidents. L'une existe parce que
« tous les 16 000 heures » fabriquait le code inventé `LES16` et empoisonnait le tour
de conversation suivant ; une autre rejette les unités de mesure. Ce ne sont pas des
artefacts qu'un administrateur client peut écrire. Tant que le nombre de clients reste
petit, le modèle de service coûte moins cher qu'un langage de règles.

### D5 — Seuil de réouverture — **Acté**

**Au troisième pack écrit à la main, rouvrir D4.**

À ce moment, le coût marginal d'un schéma déclaratif — grammaire d'identifiants,
conventions de dossiers, listes de jetons bilingues, précédences — redevient inférieur
au coût d'un pack de plus, et le risque de divergence entre packs commence à dominer.

Deux signaux avancés valent réouverture avant le seuil : un client qui change sa
nomenclature en cours de contrat, ou un pack qui doit être modifié plus d'une fois par
trimestre.

### D6 — Ce qui reste hors périmètre — **Acté**

Trois motifs restent hors de ce verrou : les positions de ligne (`J1`, `C1`), les
marques machine du planificateur agentique (Uraca, Jetlace), le motif technique
générique `AVA200`.

Le critère retenu est : *ne produit pas de `project_code` chez un tiers*. Vérifié
empiriquement à la date de cette note :

| Motif | Hors ANDRITZ | Dans ANDRITZ |
| --- | --- | --- |
| `J1`, `C1` | aucun code | aucun code |
| Uraca, Jetlace | aucun code | aucun code |
| `AVA200` | aucun code | `AVA200` |

La dernière ligne est le point à retenir : `AVA200` a la forme d'un jeton SPL, donc il
**devient** un code projet à l'intérieur du workspace ANDRITZ. Ce n'est pas un défaut
du verrou, qui fait exactement son travail, mais un résidu interne au client, inchangé
par cette note. Savoir si ce motif doit être un projet est une question ANDRITZ.

Ce critère doit devenir un test plutôt que rester une note : c'est la propriété qui
dérive au premier remaniement, et c'est le dernier rempart entre un client tiers et un
filtre dur.

---

## Risques connus, assumés à la date de cette note

1. **Le défaut fermé était silencieux — traité.** La variable de contexte porte
   désormais une sentinelle, ce qui distingue « ce locataire n'est pas ANDRITZ » d'un
   « personne n'a lié de schéma sur ce chemin ». Les deux échouent fermé, seul le second
   est compté et tracé. Le compteur est exposé par `project_reference_unbound_calls()`.

2. **La liaison doit atteindre l'appelant — un piège de plateforme, rencontré.** Le
   premier bind du routeur conversationnel était une dépendance FastAPI *synchrone* à
   `yield`. Ces dépendances tournent dans un thread de travail : la variable était posée
   dans un thread et libérée dans un autre, l'endpoint ne la voyait jamais et le
   démontage levait une erreur. La grammaire était donc éteinte sur toute la surface
   conversationnelle. Seule une dépendance **asynchrone** porte une variable de contexte
   jusqu'à l'endpoint. Gravé par un test.

3. **La récupération traverse Celery, pas la variable de contexte.** Le cas est traité,
   la tâche relie le schéma. Chaque nouvelle tâche ou saut de thread reste un chemin non
   lié : c'est ce que le compteur du point 1 rend visible.

4. **Rien ne garantit que le workspace ANDRITZ reste stampé.** La migration 058 a
   estampillé une fois. Un workspace restauré depuis un dump antérieur perd son stamp, et
   sa grammaire avec. `backend/scripts/audit_project_scheme_stamps.py` compare, par
   workspace, la présence de codes projet dans le registre et la capacité du locataire à
   en produire ; un écart sort en `ORPHANED` et en code de retour non nul. À appeler après
   une restauration et après toute release touchant les réglages de workspace.

5. **La valeur n'est pas mesurée.** Aucune ablation n'existe. On chiffrera le prochain
   pack sans connaître le bénéfice.

6. **Le vocabulaire `source_family` reste incohérent**, indépendamment de cette note :
   plusieurs valeurs attendues par les consommateurs ne sont jamais émises par le
   producteur. Du réglage mort qui donne l'illusion d'un levier.
