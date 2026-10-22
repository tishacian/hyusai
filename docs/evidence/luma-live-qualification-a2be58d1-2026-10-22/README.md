# Recette en production — a2be58d1

Captures réelles du workspace Showcase sur `agentium.papai.ai`, Chromium,
1440 × 1000, français, le 22 octobre 2026. Les dossiers SAV sont fictifs.

- [Judge du pilote](pilot-judge-fr.png) : cinq critères satisfaits, explications
  et liens vers les preuves ; l'approbation métier reste requise.
- [Budget workspace](workspace-budget-fr.png) : plafond actif de 2 000 EUR,
  révision 2, montants consommés et réservés pendant le premier essai QA.
- [Usage du premier essai](qa-run-usage-fr.png) : 11 appels, 53 134 tokens,
  0,065231404665 EUR calculés, couverture 11/11 et provenance tarifaire.
  Le statut Run « Annulé » correspond à l'arrêt prévu à la frontière humaine
  dans cette campagne ; ce n'est pas un abandon manuel de l'enquête.
- [Relevé intermédiaire](live-evidence.json) : attestation, pilote, tarifs,
  activation, premier résultat QA et contrôles de préservation.
- [Validation expirée RC-1042](expired-approval-evidence.json) : échéance,
  rejet automatique et refus de l'action faute d'approbation humaine.

Le pilote métier conserve 17 citations exactes : les textes des trois sources
ont été reconstruits depuis les invocations, leurs SHA vérifiés, puis les
citations comparées aux sous-chaînes indiquées par leurs offsets. La confiance
du Judge reste non calibrée. Aucun rapport Giskard n'a été exécuté ici.

Les contrôles Axe ciblant la comparaison et l'Usage du Run n'ont relevé aucune
violation. Les pages inspectées n'avaient ni erreur navigateur ni débordement
horizontal à cette largeur. Ce contrôle ciblé ne certifie pas l'accessibilité
de toute l'application. La liste de 24 comparaisons reste longue et le statut
technique « Annulé » manque de contexte dans l'en-tête du Run QA.

Le relevé est **intermédiaire**, pas un bilan de 48 essais réussis. Le deuxième
essai est resté sur le scoring ML après la préparation. Son diagnostic et la
suite de la recette sont consignés dans le
[rapport de qualification](../../ops/luma-live-qualification-a2be58d1-2026-10-22.md).
Les données financières sont des coûts calculés aux tarifs versionnés, sans
facture fournisseur ni économie ou ROI réalisé attestés.
