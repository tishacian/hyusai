---
title: "Note interne SP-HYD-1127 — Cas reserrage + balancing léger post-révision Kaplan"
doc_id: SP-HYD-1127
classification: INTERNAL-DEMO-SYNTHETIC
status: DRAFT-LESSON-LEARNED
---

# SP-HYD-1127 — Retour d’expérience (synthétique)

> **Document synthétique à des fins de démonstration produit uniquement.**  
> Cette note est **volontairement** rédigée comme un brouillon court pour simuler une knowledge « dispersée » ; en prod on l’étendrait après validation Quality.

## Contexte

Site **anonymisé** (profil proche **Rivage-Lac**) — turbine **Kaplan**, **G2**, automate **Metris**. Après révision et **remplacement joint arbre**, apparition d’une **élévation d’énergie** entre **2× et 3×** ligne sur palier guide **sans** montée brutale du RMS global.

## Décision terrain

- Reserrage **contrôlé** des brides palier selon couples **JNT-ARB-KAP** + contrôle marquage.
- **Re-run** balancing léger sur arbre groupe après accord client (fenêtre arrêt courte).

## Résultat

- Spectre revenu dans le profil **référence Metris** archivé T0 post-intervention.
- Aucune commande palier complet ; retour service normal < 5 j.

## Leçon (brouillon)

Les cas « **RMS OK mais spectre 2×–3× suspect** » après joint méritent une **fiche runbook** dédiée — **non publiée** dans la v4 générique au moment de la démo.

## Liens (fictifs)

- Ordre SAP PM de référence : plage **4500xxxxxx** (voir exemple **4500123789**).
- Ticket CRM ServiceMax cité dans scripts oraux démo : **27-4418** (aucune donnée réelle).
