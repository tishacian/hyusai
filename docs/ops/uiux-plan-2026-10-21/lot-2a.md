# Lot 2a — décisions et écritures

La branche de travail part du lot reconstruit `reconstruit/lot-2a-decider-ecrire` (`d3517a15`). Les contributions intégrées conservent les états de lecture et d'écriture partagés, les permissions de décision, la réserve avant décision, les confirmations des membres et la vérification des écritures externes.

## Compléments de l'intégration

- La vérification d'une décision exige le reçu de **la décision attendue**. Un Run qui a quitté sa pause, a été annulé ou continue sans ce reçu ne prouve plus que la décision a été enregistrée. Le statut du reçu doit être accepté, refusé ou appliqué ; un autre identifiant ou une lecture en échec conserve l'issue inconnue.
- Les mutations canoniques qui conservaient un repli silencieux propagent maintenant leur erreur par défaut. Les paramètres de compatibilité restent acceptés pour ne pas casser les appelants déjà migrés. Les retours structurés `ok: false` de l'enregistrement/import de Flow restent des erreurs explicites.
- Le constructeur de System n'invente plus un System local quand la création serveur échoue. Une réponse perdue bloque un second envoi ; la vérification ouvre le catalogue pour une création sans identifiant connu, ou relit le System pour une modification. L'échec de création du contexte arrête la création du System ; un contexte confirmé est réutilisé après une erreur ultérieure.
- Les réponses tardives d'un autre workspace sont ignorées. L'échec de lecture d'un System à modifier bloque sa modification et ne transforme pas le formulaire en création.
- La promotion d'un brouillon Flow vers un System suit le même principe : une réponse inconnue ne justifie pas une seconde création. Son résultat de test figure dans le bilan des lots 4/5.

## Preuves et limites

Les suites `run-decision`, `flow-run.service`, `load-state`, `system-builder-writes` et `canonical-api-errors` couvrent notamment les réponses 403/500/504, les coupures, les reçus manquants/incohérents et les changements de workspace. Le bilan global précise le résultat final du runner. Le test d'erreurs canoniques compare l'identité de l'erreur reçue à celle émise par l'API, sans option de propagation explicite.

Les décisions réelles avec trois comptes, les deux administrateurs concurrents, les effets externes, le rendu à 320 px et le parcours Luma navigateur n'ont pas été rejoués dans cette session. Le code et les tests unitaires ne constituent pas une preuve d'exécution de ces recettes. Les migrations et les fournisseurs réels n'ont pas été exercés ici.
