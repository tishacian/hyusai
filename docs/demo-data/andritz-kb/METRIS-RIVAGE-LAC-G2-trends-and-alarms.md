---
title: Metris — Rivage-Lac G2 — Trends et alarmes vibration
doc_id: METRIS-RIV-G2-TREND-01
classification: INTERNAL-DEMO-SYNTHETIC
site: Rivage-Lac
unit: G2
system: Metris DCS
---

# Paramètres trends et alarmes — vibrations G2

> **Document synthétique à des fins de démonstration produit uniquement.**

## Points de mesure

- **VIB-PG-RAD-01 / 02** : palier guide, positions radiales 90° décalées.
- **VIB-PG-AX-01** : palier guide axial.

## Seuils alarme (exemple démo)

| Signal | Préalarme | Alarme | Arrêt |
| ------ | --------- | ------ | ----- |
| Vibration vitesse RMS globale | 4.5 mm/s | 7.1 mm/s | 11.0 mm/s |

*Les valeurs sont des **exemples** ; le site réel peut différer.*

## Exports standard

- Export trend **24 h** : menu *Historian → Export CSV*.
- Export trend **48 h** : même chemin, fenêtre glissante (utilisé pour revues avec client selon **pratique terrain** — procédure formalisée en cours).

## Bandes spectrales

Les écrans Metris du site affichent les bandes **1×**, **2×**, **3×** ligne pour diagnostic rapide. Le runbook v4 renvoie à cet écran sans interprétation détaillée des **élévations 2×–3× sans corrélation vitesse**.

## Lacune volontaire (démo)

- Pas de règle documentée : « si énergie **2×–3×** monte **sans** corrélation vitesse → suspecter rigidité / serrage ».
- Pas de standard unique « **export Metris + photo capteurs** = preuve acceptable en litige » — à capturer via Knowledge Capture.
