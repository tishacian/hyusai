# Déploiement VM — mémoire opérateur (session dev / chat)

<!-- markdownlint-disable MD013 -->

Note courte pour **reproduire un déploiement “build + push + migrate + restart”**
sur la VM de démo sans repasser par tout l’historique du chat. Le runbook détaillé
historique reste [`operator-deploy-vague-d.md`](./operator-deploy-vague-d.md) ;
les chemins ci-dessous sont alignés sur l’unité **systemd livrée dans le repo**
(`deploy/agentium-backend.service`).

---

## Cible typique

| Élément | Valeur usuelle |
| ------- | --------------- |
| App HTTPS | `https://agentium.papai.ai` |
| SSH | `sudo` (souvent `ubuntu` / `deploy`, selon bastion) |
| Code sur la VM | `/home/ubuntu/omnirag` |
| Backend (cwd uvicorn) | `/home/ubuntu/omnirag/backend` |
| Venv Python | `~/omnirag/venv` (voir service ; souvent **pas** `.venv`) |
| Service | `agentium-backend` → `sudo systemctl restart agentium-backend` |

Si ton serveur utilise encore `/srv/agentium/omnirag` et `.venv`, adapte les `cd` et
`source …/activate` en conséquence ; la source de vérité locale est
`deploy/agentium-backend.service` sur la branche déployée.

---

## Flux standard (après merge / push Git)

### 1. Côté dépôt (machine locale ou CI)

- Pousser la branche déployée (souvent `demo/agentic` ou `main`).
- Optionnel : `cd backend && pytest …` et `cd frontend-ng && npx tsc --noEmit`.

### 2. Côté VM — code + deps + migrations

```bash
ssh <user>@agentium.papai.ai   # ou l’hôte bastion habituel

cd /home/ubuntu/omnirag
git fetch origin
git checkout <branche-déployée>
git pull --ff-only origin <branche-déployée>
# Conflits locaux : git stash, pull, stash pop — éviter untracked qui bloquent.

source /home/ubuntu/omnirag/venv/bin/activate
pip install -q -r backend/requirements.txt

cd /home/ubuntu/omnirag/backend
alembic -c alembic.ini upgrade head
deactivate
```

### 3. Frontend — build puis fichiers statiques

**Recommandé sur la VM** si le poste local a Node &lt; 18 (Angular / toolchain
moderne) :

```bash
cd /home/ubuntu/omnirag/frontend-ng
npm ci
npx ng build -c production
# Sortie : frontend-ng/dist/frontend-ng/browser/
```

**Alternative depuis le laptop** : même `ng build`, puis `rsync` du dossier
`browser/` vers le répertoire servi par Nginx / FastAPI (voir
[`operator-deploy-vague-d.md`](./operator-deploy-vague-d.md) §2 — cible type
`/srv/agentium/frontend/` selon la conf nginx réelle).

Après copie des assets : pas toujours besoin de redémarrer le backend si **seul** le
JS/CSS a changé ; en cas de doute ou de changement d’`index.html` / routes, un
restart ne nuit pas.

### 4. Redémarrage backend

```bash
sudo systemctl restart agentium-backend
sudo systemctl status agentium-backend --no-pager
```

Sans systemd (rare) : arrêter le process `uvicorn app.main:app` puis relancer depuis
`backend/` avec le même `venv` que le service.

---

## Vérifications rapides post-deploy

```bash
curl -sS -o /dev/null -w "%{http_code}\n" https://agentium.papai.ai/
curl -sS -o /dev/null -w "%{http_code}\n" https://agentium.papai.ai/openapi.json
# Option Vague E : taxonomy / health éval
curl -sS -o /dev/null -w "%{http_code}\n" \
  https://agentium.papai.ai/api/v1/evaluation/taxonomy
```

Smoke plus large : `backend/scripts/smoke_vague_d.sh` (variables dans
`operator-deploy-vague-d.md`). Showcase :
`python -m scripts.smoke_showcase_workspace` avec `--backend-url` public. E2E :
sur la VM, `cd frontend-ng && npx playwright test` (Node ≥ 18).

---

## Rappels utiles (pièges vus en session)

- **Migrations** : toujours `upgrade head` **après** `git pull` et **avant** de
  compter sur une nouvelle colonne / table côté API.
- **Venv** : sur la VM le service pointe vers `…/venv/bin/uvicorn` ; activer le
  même venv pour `pip` / `alembic` évite les surprises.
- **Orchestrateur** : certaines routes exigent l’orchestrateur initialisé ; les
  smokes qui touchent au chat complet le vérifient implicitement.
- **Keycloak** : rotation / redeploy = scripts sous `deploy/`
  (`redeploy-keycloak.sh`, etc.) — hors périmètre d’un simple “push code”.

---

## Liens

- Runbook long (D7) : [`operator-deploy-vague-d.md`](./operator-deploy-vague-d.md)
- Secrets / rotation : [`ops/secrets.md`](./ops/secrets.md)
- Cartographie preuves démo : [`production-demo-map.md`](./production-demo-map.md)
