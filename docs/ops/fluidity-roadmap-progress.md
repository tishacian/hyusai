# Fluidité — état de livraison

Base: `demo/agentic` @ `d9290569b4dbd4e9adcd39c985d06f6c3452a3b9`.

## Livré dans cette tranche

### F1 — Le compagnon comprend l’objet ouvert

- Le contexte est dérivé des routes canoniques `System`, `Run` et `SkillInvocation`, y compris le nœud focalisé.
- Le compagnon latéral affiche l’objet actif, permet de l’ouvrir et de l’épingler.
- Chaque tour capture sa référence d’objet ; la reprise réseau rejoue exactement cette référence.
- Le serveur borne et valide `object_context`, résout le System du Run, applique les contrôles de visibilité et dérive la portée pilote depuis un Run visible.
- La session, la portée, les derniers tours et leurs références reprennent après rechargement, par workspace.
- Le changement de workspace retire l’épinglage et isole les conversations.

### F2 — Premier diagnostic de préparation

- `inspect_system` inclut désormais la projection existante `dispatch_readiness`.
- Un System sans surface déclarée affiche « contrôle non effectué » et la raison ; il n’est pas marqué prêt par défaut.
- Les refus de publication/ingress gardent leur code, leur message et leurs surfaces concernées.

## Vérifications

- `frontend-ng/scripts/run-unit.mjs`: 1 557 tests passés.
- `frontend-ng/scripts/check-i18n.mjs`: OK.
- `frontend-ng/scripts/check-nav-links.mjs --fail-closed`: OK.
- `frontend-ng/scripts/check-ui-chrome.mjs`: OK.
- `frontend-ng` production build: OK.
- Backend targeted tests: 31 passed (`test_assistant_turns_api.py`, `test_assistant_tools.py`).

Les tests backend ont été exécutés dans un environnement Python 3.11 isolé, sans modifier `poetry.lock`.

## Reste

- F3: relier le nouveau contexte au parcours complet SPARK-089, notamment correction relue et comparaison sans perte d’objet.
- F4/F5: lignes de dossiers reliées aux Runs, puis vues actualisables et éditions figées avec provenance par point.
- F6: formulaires d’appel dérivés du contrat publié et qualification sur Work, conversation et API.

Aucun déploiement ni activation client n’a eu lieu dans cette tranche.
