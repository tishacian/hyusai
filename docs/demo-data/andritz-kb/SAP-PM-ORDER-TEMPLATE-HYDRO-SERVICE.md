---
title: Gabarit ordre SAP PM — interventions service hydro
doc_id: SAP-PM-HYD-TPL-01
classification: INTERNAL-DEMO-SYNTHETIC
---

# Gabarit d’ordre SAP PM — service hydro (démo)

> **Document synthétique à des fins de démonstration produit uniquement.**

## Types d’ordre utilisés

| Type | Usage |
| ---- | ----- |
| PM01 | Maintenance préventive planifiée |
| PM02 | Correction / défaut |
| PM06 | Révision majeure |

## Champs obligatoires (synthèse)

- **Équipement** : hiérarchie fonctionnelle centrale / groupe / auxiliaires.
- **Code activité** : révision Kaplan, contrôle paliers, remplacement joint, etc.
- **Texte long** : symptômes, mesures, références photos (chemins SharePoint fictifs en démo).
- **Couples de serrage** : renvoi à la fiche joint fournisseur (pièce jointe PDF).

## Numérotation (fictive)

Les ordres européens démo utilisent la plage **4500xxxxxx** pour les rapports d’intervention terrain archivés dans l’exemple `SAP-PM-EXAMPLE-4500123789-RIVAGE-G2.md`.

## Lacune volontaire (démo)

Le gabarit ne prescrit pas comment **croiser** trend Metris et ordre PM pour décider d’une escalade *critical* en moins de six heures après remise en eau.
