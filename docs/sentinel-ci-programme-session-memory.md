# SENTINEL-CI — Mémo session programme (reprise)

> Dernière MAJ : 2026-05-26  
> Workspace : `sentinel-ci` · Branche démo : `demo/agentic` · Prod : https://agentium.papai.ai

---

## Objectif programme

Déploiement **SENTINEL-CI** (cockpit Vice Premier Ministre Côte d'Ivoire) sur stack **Agentium/PAPAI** souveraine, hébergée **en CI uniquement** (pas France en OPEX).

---

## Artefacts budget & contractuels (source de vérité)

| Fichier | Rôle |
|---------|------|
| [`sentinel-ci-infra-shopping-list.xlsx`](sentinel-ci-infra-shopping-list.xlsx) | CAPEX VP Safe (~426 k€) + OPEX hébergement CI (Raxio ~174 k€/an, Equinix ~230 k€/an) |
| [`sentinel-ci-mvp-prerequis-mitigations.xlsx`](sentinel-ci-mvp-prerequis-mitigations.xlsx) | Baseline DEV 322 k€ + prérequis + mitigations additives + Lot 0 + TCO |

### Lecture rapide Excel prérequis

```
Lot 0 checklist  →  ce que le CLIENT apporte
Baseline         →  322 k€ HT / 216 JH si prérequis OK (INTOUCHABLE)
Mitigations      →  change orders ADDITIFS (JH × 1 550 €)
Scénarios TCO    →  DEV one-shot | CAPEX infra | OPEX/an
```

---

## Baseline DEV prestataire — 322 000 € HT / 216 JH

**Règle contractuelle validée** : baseline = plancher **intouchable** si prérequis max validés au Lot 0. Mitigations **jamais** prélevées sur les 216 JH.

| Poste | JH | € HT |
|-------|-----|------|
| Gouvernance programme | 15 | 20 000 |
| Setup env. souverain | 20 | 31 100 |
| Veille média & social listening | 30 | 46 649 |
| Hyperviseur | 36 | 55 980 |
| Gestion agenda | 33 | 51 315 |
| Sécurité frontières | 45 | 69 976 |
| Assistant vocal AYA | 27 | 41 980 |
| Formation | 10 | 5 000 |
| **Total** | **216** | **322 000** |

TJM implicite ~1 491–1 555 €/JH.

### Avis baseline (si prérequis OK)

- **Défendable** comme enveloppe dev ESN senior.
- **Réutilisation démo obligatoire** : cockpit UI, Security Monitor S3, AYA resolver, seeds presse — ne pas refacturer.
- **Sous-estimé hors baseline** : infra greenfield (M2.x), Exchange réel (M5.x), douanes/VMS (M6.x).
- **Formation 5 k€** = doc light + 1 session, pas formation cabinet étendue.
- **Hors baseline** : CAPEX matériel, OPEX colo, abonnements API (X, AIS, OSINT).

---

## Infra souveraine CI

- **Pas d'hébergement France** en OPEX.
- Sites Abidjan : Grand-Bassam/VITIB (Equinix AB1, Raxio CIV1, ST Digital) · Cocody (PAIX ABJ-1).
- VP Safe : ~12 kW IT → cage 12–15 kW.
- **Recommandation RFP colo** : Raxio CIV1 (rapport qualité/prix) ou Equinix AB1 (premium SLA).

### TCO indicatifs an 1

| Scénario | Montant HT |
|----------|------------|
| Baseline DEV seule (best case prérequis) | 322 k€ |
| Baseline + VP Safe + Raxio OPEX | ~1,0 M€ |
| Baseline + mitigations P1 + infra | ~1,2 M€ |
| Mitigations complètes greenfield | +370–565 k€ DEV additif |

---

## Mitigations — exemples chiffrés

TJM mitigation : **1 550 €/JH**.

| Cas prérequis manquant | Code | DEV additif HT | Récurrent État |
|------------------------|------|----------------|----------------|
| Pas de compte API X | M3.2 (+ M3.3 optionnel) | 15,5–23 k€ (+ 23–31 k€) | API X ou OSINT 1–40 k€/an |
| Pas SI douanes (PDF/papier) | M6.1 + M4.2 | 35–69 k€ | — |
| Pas Exchange/Graph | M5.1 | 31–54 k€ | — |
| Infra non prête (colo/GPU/K8s) | M2.1–M2.3 | 70–108 k€ | CAPEX/OPEX infra séparé |
| Lot 0 audit prérequis | M0.1 | 15–23 k€ | **Pré-contrat MOA, hors baseline prestataire** |

**Option dégradée sans API X** : RSS presse seul = **0 € dev additif**, social en fixtures (comme démo actuelle).

---

## État technique démo (ne pas repayer en baseline)

| Module | Démo | Prod gap |
|--------|------|----------|
| Cockpit / hyperviseur | UI ~70 % + fixtures `mission_room.py` | Connecteurs ministères réels |
| Veille presse | RSS live + fixtures social frozen | API X / OSINT |
| Agenda | `SENTINEL_CALENDAR_SEED` | Exchange/Graph (catalog only) |
| Security Monitor S3 | Fixtures + webcams publiques proxy | VMS/RTSP, douanes live |
| AYA | Resolver ~80 % trame + OpenAI default | LLM/STT/TTS local souverain |
| SFTP Secure Deposit | Platform (`secure_deposit_sftp.py`), pas sentinel-ci default | Activer par workspace |
| KB | `docs/demo-data/sentinel-ci-kb/` | Ingestion docs ministères |

Fichiers clés :
- `backend/app/services/mission_room.py`
- `backend/app/services/workspace_calendar.py`
- `backend/app/cli/seed_sentinel_ci.py`
- `docs/demo-aya-storytelling-trame.md`
- `docs/sentinel-ci-osint-sources-from-osiris.md`

---

## QA & readiness (session antérieure)

- Smoke 26/26 · S3 resolver 12/12 · deck 14/14
- Readiness ~90 % GO VP show · Plan B Quick Panel **texte** (STT salle bruyante)
- Gate : `scripts/qa_demo_gate.sh`
- **Pas de commit** sauf demande explicite utilisateur

---

## Contraintes & décisions

1. Hébergement **CI uniquement** (Equinix/Raxio/Orange CI DC — clarifier pas backhaul France).
2. Baseline 322 k€ = **DEV only** ; infra = budgets séparés.
3. Lot 0 (10–15 JH) avant signature → checklist 14 questions.
4. Jalon go/no-go à **108 JH** : prérequis tombé = change order, pas extension baseline.
5. Date simulée démo : **25–26 mai 2026**, Abidjan.

---

## Prochaines actions possibles

- [ ] Remplir Lot 0 checklist avec le cabinet VPM
- [ ] RFP colo Equinix/Raxio/ST Digital
- [ ] Annexer Excel prérequis au contrat prestataire
- [ ] Variante VP Safe Lean (~6 kW colo) si demandée
- [ ] Commit readiness 100 % (non fait — attendre demande)

---

## Historique session

1. Analyse chiffrage presta dev 322 k€ MVP
2. Liste prérequis data/système + mitigations JH par poste
3. Excel `sentinel-ci-mvp-prerequis-mitigations.xlsx`
4. Alignement baseline verrouillée + onglet Baseline contractuelle + fix TCO
5. Exemple lecture doc + exemple coût sans API X (M3.2)
