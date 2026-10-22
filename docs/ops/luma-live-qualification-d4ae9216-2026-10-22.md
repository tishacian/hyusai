# Luma — clôture initiale et reprise ciblée sur d4ae9216

Le 22 octobre 2026, la campagne initiale de 48 essais s'est terminée avec
**38 résultats conformes, 9 non évalués pour erreur technique et 1 sans la
proposition attendue**. Après déploiement du correctif de transaction, une
seule reprise du deuxième essai a réussi : préparation, scoring ML, enquête
agentique et Judge, puis arrêt à la frontière humaine. Son résultat est ajouté
séparément ; l'échec initial et les 47 autres essais restent inchangés.

Cette note complète le [relevé historique a2be58d1](luma-live-qualification-a2be58d1-2026-10-22.md).
Les heures sont en UTC. Les [preuves minimales](../evidence/luma-live-qualification-d4ae9216-2026-10-22/live-evidence.json)
conservent les identifiants, agrégats et empreintes nécessaires à la comparaison,
sans recopier les dossiers métier, prompts, citations ni le journal complet des appels.

## Révision et admission

API et frontend annoncent la révision vérifiée
`d4ae921669195dc18c95319736808f9d9fef2987`.
L'attestation Usage a été renouvelée à **15:50:49.615893** sur cette révision :
`ready=true`, `USAGE_ADMISSION_READY`, aucun transport manquant dans le contrat.

La base reste une **déclaration opérateur**, portant sur l'API, le worker CPU,
le worker DataOps, le runner de connecteurs et l'agent LiveKit. Ce n'est pas
une découverte automatique des processus. La garantie est l'admission aux
tarifs et bornes configurés, pas le plafonnement d'une facture externe.

Le plafond Showcase de **2 000 EUR/mois**, révision 2, reste actif, en mois
calendaire `Europe/Paris`. Les tarifs et la conversion EUR datée décrits dans
le relevé précédent restent les conventions utilisées. Le compteur workspace
comprend d'autres activités : il ne doit pas être assimilé au seul coût de
cette campagne.

## Bilan conservé des 48 essais initiaux

Campagne `5a8a9d28-e30b-4eff-9efa-56b0fe840d6d`, créée à **13:24:58** et
terminée à **14:59:20** : 12 dossiers, deux versions, deux répétitions.

| Résultat initial | Baseline | Candidat | Total |
| --- | ---: | ---: | ---: |
| Assertions satisfaites | 19 | 19 | 38 |
| Non évalué après erreur technique | 5 | 4 | 9 |
| Proposition attendue absente | 0 | 1 | 1 |

Les statuts techniques sont **39 `cancelled` à la frontière humaine** et
**9 `failed`**. Le statut `cancelled` est ici la clôture prévue du parcours
de qualification avant action ; il ne signifie pas que les 39 essais ont échoué.

- **30 contrôles Judge** sont terminés et conformes.
- **8 parcours conformes**, RC-5007 et RC-5008 sur les deux versions et les
  deux répétitions, demandent l'intervention humaine faute de preuves. Aucun
  Judge de proposition n'est attendu dans ces parcours.
- **8 erreurs `JUDGE_PROMPT_TOO_LARGE`** empêchent une évaluation : cinq côté
  baseline, trois côté candidat. Ce sont des refus techniques, pas des
  jugements négatifs sur les propositions. Ils restent non requalifiés.
- Le candidat RC-5001, première répétition, avait dépassé le délai de scoring
  ML (`recipe_wait_deadline_expired`). C'est l'unique essai repris ci-dessous.
- Le candidat RC-5003, première répétition, a rencontré `APIConnectionError`
  sur GPT-5 ; le secours Ollama a été bloqué avant envoi. L'agent a demandé un
  humain sans produire la proposition attendue. Ses assertions échouent,
  sans preuve de remboursement incorrect ni de verdict Judge erroné. Ce
  parcours n'a pas été requalifié dans cette reprise.

Les 24 paires conservent 17 résultats `unchanged`, 6 `unevaluated` et 1
`not_comparable`. Pour cette dernière, le candidat interrompu au scoring n'a
pas produit le snapshot de l'agent présent côté baseline ; cela ne prouve pas
que le corpus a changé. La comparabilité globale reste `limited`, notamment
par les sources vivantes et les versions externes de modèles. Aucun progrès
du candidat ni taux de fiabilité généralisable n'est démontré.

## Reprise du deuxième essai

La reprise a été demandée depuis la campagne pour
`delivery_contradiction-RC-5001:0`, côté `candidate`.

| Preuve | Identifiant ou état |
| --- | --- |
| Run initial conservé | `2f54f016-e707-4f4f-aea3-b4718f243093` — `failed`, `unevaluated` |
| Tentative ajoutée | `49d6d709-90dc-4f61-a1e4-c4850c580455`, numéro 1 |
| Nouveau Run | `f0f481fb-24cb-4cab-9d65-9d624157b1ff` |
| Job ciblé | `12987c37-6083-4413-bf52-5b05832ba410` — terminé |
| Exécution | **15:50:52 → 15:52:56**, environ 122 secondes techniques |
| Résultat | `passed`, `quality_status=passed` |
| Clôture prévue | `cancelled`, `termination=human_gate` |
| Assertions métier / trajectoire | **14/14** et **12/12** satisfaites |
| Judge | `244ee1d1-3171-47d0-ade8-0927414988a3` |

Le Judge `claims-resolution-review` v1 conserve cinq réponses satisfaisantes
sur cinq et trois ensembles de preuves examinés sur trois. Sa disposition
reste `review` ; la confiance est absente avec le motif
`calibration_not_qualified`. Aucun accord humain ni action métier n'est
simulé pour transformer cet arrêt en succès commercial.

La comparaison locale des snapshots avant/après reprise confirme : **une seule
tentative ajoutée**, mêmes 48 Runs initiaux, mêmes résultats et coûts initiaux,
mêmes 24 comparaisons, même manifeste de campagne, mêmes dates de campagne et
même job initial. Seuls les champs de reprise et son éligibilité évoluent.
Ce résultat ne remplace donc pas le bilan initial par « 39/48 réussis ».

## Usage et coûts, avec périmètres distincts

Les trois pages initiales ont le même `as_of`, **15:49:43.550213**, antérieur
à la reprise. Leurs 462 identifiants sont uniques, rattachés à cette campagne
et aux seuls 48 Runs initiaux. Quarante-sept Runs ont des appels fournisseur ;
l'essai ML interrompu n'avait pas atteint le LLM. Les 11 appels de la reprise
ont des identifiants distincts et sont tous rattachés au nouveau Run.

| Périmètre | Appels | Tokens connus | Sous-total calculé EUR |
| --- | ---: | ---: | ---: |
| 48 essais initiaux | 462, dont 460 terminés | 2 573 576 | 3,128947721215 |
| Reprise ciblée | 11, tous terminés | 54 014 | 0,069011224853 |

Les appels initiaux comprennent 200 tentatives de décision d'agent, 30 appels
Judge et 232 embeddings. Leur coût connu se répartit en **2,710348495643 EUR**,
**0,418515444190 EUR** et **0,000083781382 EUR**. La reprise comporte quatre
décisions, un Judge et six embeddings ; sa couverture est complète pour les
appels conservés, au relevé de **15:55:23.932638**.

Les tokens initiaux connus sont 2 400 821 en entrée et 172 755 en sortie.
Les 1 073 536 tokens d'entrée en cache et 127 552 tokens de raisonnement en
sont des sous-ensembles ; ils ne sont pas ajoutés une seconde fois.

L'appel GPT-5 initial échoué ne fournit aucun reçu de consommation. Sa
réservation de **0,120868568631 EUR** est distincte d'un coût mesuré. Le secours
Ollama est enregistré comme bloqué avant envoi, sans mesure monétaire.
Les **3,197958946068 EUR** combinés représentent uniquement la somme des
sous-totaux tarifés connus sur ces deux périmètres disjoints. Aucune facture
n'est disponible ; ce n'est pas un coût total d'exploitation ni un ROI.

Les champs historiques `execution_cost` de 47 résultats initiaux restent
`null` avec couverture partielle. Le seul zéro complet correspond au Run
arrêté au scoring. Ces champs ne doivent pas être additionnés pour produire
un total financier : les chiffres ci-dessus proviennent du registre Usage.

## Préservation et QA finale

Les snapshots **après déploiement**, puis les nouvelles lectures **après la
reprise**, ont été comparés aux snapshots antérieurs à la campagne :

- Flow et brouillon **r38**, publication **v10** et binding Work identiques ;
- champs `data` et `receipts` des douze dossiers RC-5001 à RC-5012 inchangés ;
- champion SLA **v5** et configuration de serving inchangés ; seuls les
  compteurs/dates de prédiction et la date de mise à jour du modèle évoluent.

La relecture finale du budget confirme `ready=true`, le plafond workspace
2 000 EUR en révision 2, **3,203022894795 EUR consommés** et
**0,121630852769 EUR réservés** sur l'ensemble du workspace. Ce périmètre est
plus large que les deux sous-totaux de campagne ci-dessus.

La QA visuelle sur écran de 1 440 pixels a contrôlé quatre vues chargées :

- l'expiration de l'accord RC-1042 est expliquée dans une [alerte ambre](../evidence/luma-live-qualification-d4ae9216-2026-10-22/work-expired-approval.png), avec
  l'enquête conservée et la nécessité de réexaminer les sources ;
- la [campagne](../evidence/luma-live-qualification-d4ae9216-2026-10-22/campaign-targeted-retry.png) affiche « Reprise 1 », la revue humaine et les critères satisfaits,
  avec les résultats initiaux séparés ;
- la [qualité du nouveau Run](../evidence/luma-live-qualification-d4ae9216-2026-10-22/retry-quality.png) affiche les cinq réponses « Oui » ;
- son [Usage](../evidence/luma-live-qualification-d4ae9216-2026-10-22/retry-usage.png) affiche 11 appels terminés, aucun échec, 54 014 tokens et
  0,069011 EUR calculés.

Les relevés de ces vues ne contiennent pas d'erreur page/HTTP ni de débordement
horizontal. Une faiblesse UX demeure : pendant le chargement de la campagne,
les compteurs et listes affichent transitoirement un état vide. Attendre les
résultats chargés avant projection. L'audit Axe en service n'a pas pu être
exécuté, son module étant indisponible : aucune validation d'accessibilité
complète n'est revendiquée.

La reprise qualifie le Judge natif du Flow. Les jobs disponibles ne prouvent
pas une exécution en production du worker automatique `run_evaluation` après
ce déploiement ; son correctif dispose de tests PostgreSQL, ce qui reste une
preuve distincte. Les datasets métier, délégations, prévision, événements et
tous les autres écrans ne sont pas requalifiés par cette note. Aucun résultat
Giskard, aucune calibration du Judge, aucune facture ni économie réalisée ne
sont déduits de ces essais.

Pour présenter le résultat, ouvrir la campagne puis sa section de reprises,
ou directement le [nouveau Run](https://agentium.papai.ai/runs/f0f481fb-24cb-4cab-9d65-9d624157b1ff).
Attendre le chargement effectif des données avant d'interpréter les compteurs.
