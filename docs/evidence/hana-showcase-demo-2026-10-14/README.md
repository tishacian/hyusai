# Showcase HANA : choix de démonstration et validation locale

Le 14 octobre 2026, l'utilisateur choisit `demo_mode=true` pour Showcase, avec
`encrypt=true`, `ssl_validate_certificate=true`, `HANA_ALLOW_INSECURE_TLS=false`
et `HANA_WRITES_ENABLED=false`. L'activation sur la VM reste différée jusqu'à la
qualification des images candidates. Aucun réglage distant, fusion ni déploiement
n'est effectué par cette validation.

Le formulaire conserve les trois paramètres du connecteur, omet le mot de passe
inchangé et explique le repli synthétique. Le test de connexion utilise seulement
la configuration enregistrée ; il ne transforme pas un aperçu de démonstration
en succès HANA. Le backend existant n'est pas modifié.

## Résultats et périmètre

| Contrôle | Résultat | Preuve brute |
|---|---|---|
| Backend HANA, sécurité et API HANA/RPA | 48 réussites, 3,45 s pytest | [hana-48.log](hana-48.log) |
| Composant HANA | 10 réussites | [unit-hana.log](unit-hana.log) |
| Suite frontend complète | 2 204 réussites, aucun échec ni test ignoré | [unit-full.log](unit-full.log) |
| i18n, navigation, interface | Réussis | [i18n.log](i18n.log), [nav-links.log](nav-links.log), [ui-chrome.log](ui-chrome.log) |
| Build frontend de production | Réussi, 57,449 s | [build-prod.log](build-prod.log) |

Le build garde des avertissements sur d'autres templates, les budgets globaux
et CSS, ainsi que `dagre` CommonJS. Aucun seuil n'a été relevé. Ce build n'est
pas une construction ni une mesure d'image Docker.

Les tests HANA simulent le pilote. Un audit hook Python bloque `socket.connect`,
`socket.getaddrinfo` et `socket.sendto` ; aucun de ces événements n'a été observé.
Cette garde n'est pas une isolation réseau du système. La suite backend complète
n'est pas relancée. Aucun résultat ici ne démontre une connexion SAP vivante,
l'expiration de l'essai, une activation Showcase ou une recette sur la VM.

[validation.json](validation.json) lie les résultats aux empreintes des sources
frontend et tests HANA, au tree backend inchangé et aux empreintes des logs.
Le commit de base est `2e49c1aa4859a508675a54d8087b70528f3a450f` ; le correctif
frontend était non commité pendant l'exécution. Les empreintes des sources
identifient donc le contenu effectivement testé. Le plan initial et la revue
indépendante sont inchangés. Les preuves SSH antérieures restent dans leur
[bundle propre](../dataops-vm-check-2026-10-14/README.md).

## Commandes de validation

Depuis `/workspace/hyusai/backend`, Python 3.12.14, le runner a été passé
initialement sur l'entrée standard par heredoc :

```bash
PYTHONDONTWRITEBYTECODE=1 /workspace/hyusai/.venv/bin/python -
```

[run_hana_48.py](run_hana_48.py) conserve ce contenu, reconstitué à l'identique
après l'exécution. Il retire les variables de base/registre de l'environnement,
utilise Celery en mémoire, installe la garde Python puis lance ces fichiers :

```text
app/tests/services/test_hana_security.py
app/tests/services/test_hana_preview.py
app/tests/api/test_hana_rpa_admin_api.py
```

Depuis `/workspace/hyusai/frontend-ng`, Node 24.19.0 et npm 11.9.0 :

```bash
mkdir -p /workspace/hana-ui-validation-2026-10-14/tmp

FLOW_UNIT_FILTER=hana-connector.component \
TMPDIR=/workspace/hana-ui-validation-2026-10-14/tmp \
GOMEMLIMIT=3GiB GOMAXPROCS=2 npm run test:unit

npm run check:i18n
npm run check:nav-links
npm run check:ui-chrome

TMPDIR=/workspace/hana-ui-validation-2026-10-14/tmp \
GOMEMLIMIT=3GiB GOMAXPROCS=2 npm run test:unit

TMPDIR=/workspace/hana-ui-validation-2026-10-14/tmp \
GOMEMLIMIT=3GiB GOMAXPROCS=2 npm run build:prod
```

Les sorties stdout/stderr ont été redirigées vers les fichiers du tableau,
d'abord sous `/workspace/hana-ui-validation-2026-10-14`, puis copiées ici sans
modification. Les trois contrôles ont tourné en parallèle ; les tests ciblés,
la suite complète et le build ont tourné successivement. `FLOW_UNIT_FILTER`
n'était pas défini pour la suite complète.

Depuis la racine du dépôt, `python scripts/agentium_compliance.py --check`
réussit également (16/22 déclarations vérifiées statiquement ; attestations
d'exécution séparées), ainsi que `git diff --check`.

La [note de décision](../../dataops-release-blockers-2026-10-14.md) et le
[runbook](../../ops/hana-security-s0.md#showcase--démo-explicite-retenue-le-14-octobre-2026)
décrivent l'activation différée et sa recette. Les plafonds d'images restent
inchangés ; les archives backend et worker existantes restent référencées par
`bd724044`, dont le code backend n'a pas changé. Le frontend corrigé doit être
embarqué dans l'image de la future livraison.
