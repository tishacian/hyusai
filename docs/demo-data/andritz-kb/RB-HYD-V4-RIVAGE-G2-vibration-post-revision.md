---
title: Runbook hydro — Vibrations post-révision — G2 Kaplan — Rivage-Lac
doc_id: RB-HYD-V4-RIV-G2-01
version: 4.2
classification: INTERNAL-DEMO-SYNTHETIC
site: Rivage-Lac
unit: G2
technology: Kaplan, Metris DCS
---

# Vibrations après révision — contrôle générique (Runbook v4)

> **Document synthétique à des fins de démonstration produit uniquement.**

## Périmètre

Ordre d’intervention type après **révision majeure** du groupe **G2** (turbine **Kaplan**, automation **Metris**).

## Séquence minimale obligatoire

1. **Vérifier** que le groupe est stabilisé en régime nominal (débit, chute, position runner) pendant au moins 30 minutes.
2. **Contrôler** les capteurs de vibration radiaux et axiaux du **palier guide** : valeurs instantanées et tendance 24 h.
3. **Comparer** aux seuils **ISO usine** configurés dans Metris (voir fiche paramètres site).
4. Si vibration **hors tolérance** : appliquer la procédure d’arrêt sécurisé et ouvrir un ordre SAP PM catégorie **CORR**.
5. Si vibration **dans la tolérance** mais **plainte client** : documenter les mesures dans le rapport d’intervention et escalader au **support niveau 2** selon grille interne.

## Contrôles mécaniques standard

- Relecture **couples de serrage** palier / joint d’arbre selon fiche joint (réf. fournisseur).
- Contrôle visuel **alignement** et marquage position brides (photos obligatoires dans le rapport PM).

## Limites connues du document (volontaire pour démo)

- Ne prescrit **pas** comment interpréter une élévation **spectrale 2×–3× ligne** avec vibration globale encore dans la tolérance.
- Ne définit **pas** la source « faisant foi » en cas de désaccord client (export Metris vs oral).
- La **hausse de priorité interne *critical*** avant dépassement ISO n’est **pas** détaillée ici — renvoi au lead service régional.

## Références croisées (fictives)

- Liste pièces critiques : `SPARE-PARTS-CRITICAL-KAPLAN-G2.md`
- Paramètres Metris : `METRIS-RIVAGE-LAC-G2-trends-and-alarms.md`
