# Séries d'activités : colonnes typées et lecture SQL allégée

Date : 17 octobre 2026. Base : `demo/agentic` à `d814837b`.

Ce dossier est une preuve locale. Il ne vaut ni attestation de production ni
qualification sur la VM. Il reprend la charge R2 laissée ouverte dans
[`operations-activities-flow-2026-10-16/report.md`](../operations-activities-flow-2026-10-16/report.md).

## Changements mesurés

1. **La garde de cohérence des invocations est limitée à la population lue.**
   - Avant, un `SELECT 1 … JOIN skill_invocations … LIMIT 1` parcourait tout
     l'historique du workspace, en boucle imbriquée, dès qu'aucune ligne ne
     différait. C'était 0,9 à 1,4 s par lecture, davantage que l'agrégat
     lui-même.
   - Elle compte maintenant, par jointure de hachage, les seules lignes que la
     requête peut sélectionner. Une ligne hors population n'atteint aucun des
     deux lecteurs : le résultat est identique.
2. **Deux colonnes typées sont ajoutées à `activities`, par la migration 138.**
   - `finished_at` et `duration_ms` sont dérivées du snapshot avec les parseurs
     mêmes du lecteur natif. Un index `(workspace_id, finished_at)` les
     accompagne.
   - La projection et un événement ORM les tiennent à jour. Le snapshot reste
     la source, et le lecteur natif reste l'oracle des tests différentiels.
   - Une date que Python ne peut pas normaliser est stockée NULL. Le chemin SQL
     cède alors la main au lecteur natif, qui lève comme avant.
3. **La requête n'interroge que les tables utiles.**
   - Elle ne joint que les tables natives que le type demandé peut concerner.
   - Pour compter les activités, elle omet la jointure des invocations lorsque
     la garde prouve qu'aucune n'est orpheline.
   - La preuve de coût est lue une fois par ligne au lieu de deux : 563 ms
     ramenées à 310 ms pour 80 000 invocations, sur un plan série.
4. **Une seule matérialisation, sans réévaluation.** Le montant et sa
   validation de devise sont évalués une seule fois par ligne. Les lignes sans
   date de fin y portent un indicateur, au lieu d'une seconde lecture.
5. **La mémoire de travail est réglable.** `ACTIVITY_SERIES_WORK_MEM_MB`, 16 Mo
   par défaut et borné entre 4 et 256, s'applique en `SET LOCAL` à la seule
   transaction de lecture.
   - Avec les 4 Mo par défaut de PostgreSQL, les lignes matérialisées, les tris
     et les tables de hachage débordaient sur disque.
   - L'échantillonnage de `pg_stat_activity` sous 20 lecteurs donnait 20 %
     d'attente `IO:BufFileWrite`.

Le chemin natif (IAM `shadow` et `enforce`, PostgreSQL de version inférieure à
16, fenêtres et reçus protégés) n'est pas modifié.

## Méthode

- Le script est `backend/scripts/qualify_activity_series.py`, inchangé hors
  portabilité : RSS par `psutil` et informations d'hôte par `sysctl` hors Linux.
- Le corpus compte 100 000 activités sur 30 jours (10 % de Runs, 80 %
  d'invocations, 5 % de calculs, 5 % de jobs).
- La lecture est faite par 10 ou 20 lecteurs simultanés, aux droits
  différents, pendant qu'un écrivain persiste des travaux.
- PostgreSQL 16.2 local tourne avec ses réglages par défaut (`work_mem` 4 Mo,
  `shared_buffers` 128 Mo).
- La machine est un Apple M2 (8 cœurs) avec 16 Gio.
- Vingt lecteurs sur ces 8 cœurs donnent à peu près la charge par cœur de dix
  lecteurs sur le conteneur à 4 CPU de la mesure du 16 octobre. La base à
  20 lecteurs l'a d'ailleurs reproduite : 5,2 s et 7,4 s, contre 5,5 s et 9,5 s.

**Réserve.** Le poste était chargé par d'autres applications pendant la série
finale, avec une charge moyenne de 13 à 30. Les valeurs absolues n'y sont pas
fiables : la même base a mesuré 2,8 s puis 10,6 s à deux heures d'intervalle.
Seules les comparaisons entrelacées, base puis version finale prises à la suite
dans les mêmes conditions, sont interprétables.

## Résultats entrelacés

| p95 | Base `d814837b` | Version finale | Gain |
|---|---:|---:|---:|
| Activité, 10 lecteurs | 10,59 s | 1,89 s | × 5,6 |
| Coût d'invocations, 10 lecteurs | 11,36 s | 3,55 s | × 3,2 |
| Activité, 20 lecteurs | 13,67 s | 2,90 s | × 4,7 |
| Coût d'invocations, 20 lecteurs | 32,63 s | 6,06 s | × 5,4 |

- Dans les huit mesures, les comptes autorisés sont exacts pour chaque lecteur,
  l'écrivain n'est pas bloqué et le surcroît de RSS reste sous 256 Mio.
- Les JSON correspondants sont `series-{base,final}-{10,20}readers-{activity,cost}.json`.
- Leur champ `source.git_head` vaut `d814837b`, car la version finale a été
  mesurée avant son commit. Ses `file_sha256` identifient les fichiers
  mesurés.
- Après ces mesures, la sous-requête de la preuve de coût a reçu une garde
  `:metric = 'cost'`. Elle n'agit que sur un comptage d'activités qui contient
  des invocations orphelines, absentes de ce corpus.

**Lecteur seul, sur le même poste chargé.**
- Activité : 2,0 s pour la base contre 0,6 s pour la version finale.
- Coût : 2,9 s contre 0,73 s.
- Plus tôt dans la journée, sur le poste moins chargé, une version
  intermédiaire mesurait 0,29 s pour l'activité et 0,37 s pour le coût. Il lui
  manquait le réglage de mémoire et la lecture unique de la preuve de coût.

## Ce qui reste à qualifier

Ces mesures ne prouvent pas le seuil de 2 s sur la VM. La qualification reste
une étape de la recette R5, à faire par l'opérateur sur la configuration cible
avec le même script : voir
[l'ouverture des séries](../../agentium-execution-operations.md#ouverture-des-séries-et-de-la-vue-du-flow).

## Tests

- **Backend.** Les tests de séries, d'observabilité, d'autorisation des reçus,
  de vue d'exécution, de contrôle d'exécution et des migrations 133 et 138,
  ainsi que les tests d'infrastructure, ont été exécutés en parallèle sur
  PostgreSQL 16.2 local : 189 réussis, 70 ignorés et 4 échecs.
  - Les 4 échecs sont dans `test_agentium_control_deploy.py`. Ils se
    reproduisent à l'identique sur `d814837b` et tiennent à l'exécution locale
    des scripts Compose.
- **Tests ajoutés.**
  - La garde limitée à la population : écart dans la fenêtre ou hors fenêtre,
    et population de Runs seuls.
  - Le débordement de date, qui garde l'erreur native.
  - L'élision de la jointure d'invocations, avec ou sans orphelin.
  - La séparation entre dates analysées et dates illisibles au-delà de la
    borne de 128 valeurs.
  - La migration 138 : remplissage par lots, schéma égal au modèle,
    réversibilité, et copie figée de la dérivation égale à celle du modèle.
- **Lint.** Ruff 0.14 passe sur les fichiers modifiés.
