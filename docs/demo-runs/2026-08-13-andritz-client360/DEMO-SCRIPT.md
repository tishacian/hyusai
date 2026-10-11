# Démo Client360 — workspace `andritz`

Préparée le 13/08/2026 contre la prod `demo/agentic@664e68b7` (canaris 6/6,
QA complète consignée dans `docs/ops/agentium-safe-vm-deployment.md`,
itération du 13/08 après-midi). Tous les chiffres ci-dessous ont été vérifiés
en prod le jour de la préparation.

## État des données (vérifié)

| Donnée | Valeur |
|---|---|
| Opportunités | 402 (dont 396 `detected`) |
| Annuaire clients | 179 |
| Sources SFTP | 21 (registre projets, sales orders, installed base SPC, histo achats) |
| Alertes | 117 — 94 `long_delivery`, 19 `incomplete_data`, 2 `due_soon`, 2 `draft_no_response` |
| Fiche Septona | 2 projets, 2 machines, 14 achats, 2 échéances, 260 opportunités, potentiel 2 142 659 € |
| Campagne seedée | « Relance échéances PDR — S35 » (`draft`) — potentiel 2 316 421,78 €, expected_value 295 343,78 € |

## Fil narratif (12–15 min)

Pitch d'ouverture : « Client360 transforme des exports SAP bruts (Excel via
SFTP) en un cockpit commercial pièces de rechange : opportunités calculées,
échéances déterministes, mails de relance assistés par IA — toujours validés
par un humain. »

### 1. Landing Opportunités (2 min)

- Ouvrir l'app Client360 → la page atterrit sur les opportunités.
- Montrer le **digest d'alertes** (6 plus urgentes, chips filtrables par type,
  bouton déplier avec scroll interne) — « 117 alertes mais l'écran reste
  digeste ».
- Tableau : 402 opportunités, 25 lignes affichées, « voir plus » ; trier /
  filtrer rapidement.
- Message : tout est calculé depuis les fichiers sources, chaque ligne est
  traçable (evidence refs).

### 2. Assistant (3 min) — quatre requêtes, toutes revalidées 3/3 en prod

Dans l'ordre, verbatim :

1. `hello` → l'assistant se présente et cadre son périmètre (lectures bornées
   et sourcées, jamais de SQL libre). Message : pas un chatbot généraliste.
2. `montre les opportunités urgentes en Grèce` → 18 opportunités, potentiel
   cumulé 2 142 659 €, 9 sources citées.
3. `audite Septona` → audit complet : 260 opportunités, potentiel 2,14 M€,
   projets, parc machines, 10 sources.
4. `quelles pièces à prévoir chez Septona ?` → **2 échéances déterministes**
   (O'ring Dia 47.22, Ball bearing D.476). Message : prévision calculée
   (dernier achat + périodicité), pas une hallucination — disclaimer inclus.

Chaque réponse porte un CTA de navigation → cliquer celui de l'audit pour
enchaîner sur la fiche.

### 3. Fiche client Septona (3 min)

- La fiche charge en ~2 s ; le **résumé IA arrive en asynchrone** sous loader
  — le montrer comme une feature (« la donnée d'abord, l'IA ensuite »).
- Parcourir : projets registre (2), machines (JETLACE HFR200), historique
  achats (14, paginé), bloc « À prévoir » avec les 2 échéances.
- Assumer les dates d'échéance passées (06/07/2026) : « ces clients sont **en
  retard** sur leur maintenance — c'est exactement la cible de la relance ».

### 4. Génération du mail de relance (3 min) — voie fiche opportunité

- Depuis la fiche, sélectionner l'opportunité à échéance (Ball bearing D.476
  Ball Ø20) → générer le brouillon mail.
- Résultat vérifié : mail `ai_assisted` (gpt-5), sujet « Septona JETLACE
  HFR200 – Vérification PDR et prochaine échéance de maintenance », ton
  professionnel, **`prompt_hash` tracé sur le brouillon**, et une **action de
  validation humaine** créée — « aucun mail ne part sans validation ».
- **NE PAS cliquer Envoyer** (SMTP réel configuré : ssl0.ovh.net, from
  noreply@datategy.net — un clic partirait vraiment).

### 5. Campagnes (2 min) — montrer, ne pas générer

- Ouvrir « Relance échéances PDR — S35 » : ciblage par filtres + sélection
  clients, **stats** : potentiel 2,32 M€, expected_value 295 k€ **avec
  disclaimer** (proxy de conversion 0,15 = poids contrat, recalé dès les
  premiers retours observés). Message : chiffrage déterministe et honnête.
- **NE PAS lancer « générer les brouillons en lot »** : les exports SAP
  actuels ne portent aucun email de contact → le lot sortirait à
  0 brouillon (374 × `missing_contact_email`). Si la question vient :
  « le dédoublonnage écarte les clients sans email — ici les exports n'en
  contiennent pas encore, c'est une donnée d'entrée à brancher ».

### 6. Settings — Mail & suivi (1 min)

- Montrer le **system prompt du rédacteur de mails** : défaut
  `client360_pdr_mail_v2`, éditable par workspace, bouton réinitialiser,
  traçabilité `prompt_hash` par brouillon (boucle bouclée avec l'étape 4).
- SMTP par workspace avec repli global ; envoi toujours validé par un humain.

## Pièges connus (à ne pas montrer / assumer)

1. **Génération en lot = 0 brouillon** (pas d'emails de contact dans les
   données). Voie mono-brouillon uniquement.
2. **Ne jamais cliquer Envoyer** — le SMTP est réel et fonctionnel.
3. La campagne S35 affiche `targeted_customers=5` pour 3 clients réels
   (clés dupliquées, vestige de normalisation) — ne pas zoomer dessus.
4. Échéances Septona passées → vocabulaire « en retard », pas « à venir ».
5. Le résumé IA de la fiche prend quelques secondes : enchaîner le discours
   pendant le loader, il tombe tout seul.

## Filets de sécurité

- Rollback images : `AGENTIUM_IMAGE_TAG=0a3534f2a14d` puis `up`
  (`scripts/agentium-vm-deploy.sh`).
- Si le chat déraille sur une requête exotique : revenir aux quatre requêtes
  verbatim ci-dessus, toutes revalidées 3/3 après le fix `664e68b7`.
- Client alternatif si Septona a déjà servi : requête chat
  `audite Eruslu` (registre) ou passer par l'annuaire (recherche).
