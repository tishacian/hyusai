# Luma — reprise de qualification après la livraison 55415938

## État constaté en service

Le 22 octobre 2026, l'opérateur a confirmé la révision complète
`55415938d1067b61f321cfda6f8ce30d0a449060` sur tous les processus et les migrations
jusqu'à `146_model_usage_budgets`. Son attestation a été enregistrée : le contrôle
Usage retourne `ready=true`, avec une base déclarative opérateur.

L'utilisateur a choisi **2 000 EUR par mois**. La politique préparée porte sur
**Showcase entier, Luma inclus**, dans le fuseau `Europe/Paris` :
`ea7877f3-7f31-4ff6-ab38-88c92ed5260c`, révision 1, **désactivée**. Il ne s'agit pas
de deux enveloppes cumulables. Aucun plafond n'est actuellement opposable.

Les tarifs OpenAI natifs ont été déclarés pour le pilote : `gpt-5`, entrée 1,25,
sortie 10, cache en entrée 0,125 USD par million ; `text-embedding-3-small`, entrée
0,02, sortie 0 USD par million. Sources consultées le 22 octobre :

- <https://developers.openai.com/api/docs/models/gpt-5>
- <https://developers.openai.com/api/docs/models/text-embedding-3-small>

Une enquête réelle du parcours Work, sur le dossier fictif RC-5003, a produit le
Run `7a62253c-015b-423a-8a48-7bcd6c345a25`. Il a atteint `hitl_pending`. Aucune
approbation ni action financière n'a été effectuée. Ce pilote appartient à la
population métier de démonstration, **pas** à la future campagne QA.

| Mesure conservée | Valeur |
| --- | ---: |
| Appels fournisseur envoyés / terminés | 11 / 11 |
| Jetons d'entrée / sortie | 48 303 / 3 484 |
| Jetons totaux | 51 787 |
| Entrée en cache / raisonnement | 18 304 / 2 304 |
| Coût calculé, couverture | 0,074479150000 USD ; 11/11 appels |
| Choix de l'agent | 4 appels ; 0,056338000000 USD |
| Judge | 1 appel ; 0,018138750000 USD |
| Embeddings | 6 appels ; 0,000002400000 USD |

Les coûts proviennent des tokens fournisseur et des tarifs versionnés. Aucune
facture ni économie réalisée n'est attestée. Les tokens de cache et de
raisonnement sont des sous-ensembles, pas des quantités à additionner au total.

## Défauts reproduits et correctifs

1. Le préflight de campagne validait tout le brouillon, y compris le nœud
   `Prepare` inachevé et déconnecté. Le mode `qualified_prefix` projette désormais
   le parcours sélectionné jusqu'à la frontière humaine, conserve ses sources
   et contrats et trace les exclusions. Il ne répare ni ne sauvegarde le Flow.
   Les erreurs et dépendances du parcours retenu restent bloquantes.
2. Le Judge du pilote est **échoué techniquement / non évalué**,
   `JUDGE_RESPONSE_INVALID`, diagnostic `evidence_quote`. Il n'est pas un contrôle
   métier réussi. Les preuves JSON contiennent des passages répétés et échappés,
   fragiles à recopier. Le protocole générique de passages identifiés permet au
   fournisseur de choisir une occurrence ; le serveur reconstruit et vérifie la
   citation exacte. Les anciens résultats ne sont pas réécrits ; le changement
   de protocole distingue les signatures de calibration.
3. Les tarifs acceptent une provenance déclarée et, facultativement, une
   conversion documentée. Le montant converti doit correspondre exactement aux
   taux saisis, avec arrondi moitié paire à 12 décimales. Chaque appel garde son
   snapshot. Il n'y a ni téléchargement automatique de taux ni réévaluation de
   l'historique. Les coûts positifs inférieurs au seuil d'affichage doivent
   rester distinguables d'un vrai zéro.
4. Les décisions AgentLoop ne transmettaient pas de borne de sortie ; un
   plafond actif les aurait refusées comme transport non qualifié. Le moteur
   fournit maintenant une limite de 4 096 tokens, raisonnement compris. Une
   réponse tronquée entraîne une revue humaine, même si son préfixe JSON est
   valide. Les tests vérifient réservation avant envoi, réconciliation et refus
   sans appel fournisseur lorsque le budget est épuisé.

## Déploiement du correctif

Aucune migration, dépendance ou option nouvelle. Déployer le commit contenant
ce document sur l'API, le frontend et les processus existants qui exécutent les
Skills ou appellent les modèles. Recréer les processus selon le runbook habituel,
avec drainage des sessions LiveKit ; conserver la tête Alembic
`146_model_usage_budgets`. Ne pas rejouer l'installation Luma.

La base worker exclut désormais les tests Python, **sauf le kit de certification
des connecteurs utilisé au runtime**. Le retrait mesuré représente environ
10,72 MiB de fichiers sources ; ce n'est pas une mesure de l'image compressée.
Reconstruire la base worker puis le runner et exécuter les contrôles de taille.
Le plafond de 1652 MiB n'est pas relevé. La dernière image opérateur mesurait
1651,92 MiB : un build sans nouvelle mesure ne suffit pas à qualifier la marge.

Comparer les relevés avant/après : brouillon r38 et son hash, publication v10 et
ses épingles, bindings `showcase.claims.*`, champions/shadow, expériences. Le
pilote a déjà confirmé l'égalité des lectures Flow, v10 et binding d'enquête.

## Reprise en service après déploiement

1. Vérifier le SHA servi et les processus. L'attestation Usage de 55415938 ne
   couvre pas une autre révision ; la renouveler pour le nouveau SHA après
   confirmation opérateur de la flotte et du drainage.
2. Rejouer un seul dossier pilote jusqu'à HITL. Dans Run → Qualité, distinguer
   disponibilité technique, questions évaluées, abstentions et appréciation
   métier. Dans Usage, retrouver tous les appels, tarifs et liens. Une simple
   invocation `evaluate_v2` terminée ne qualifie pas son verdict.
3. Enregistrer les tarifs EUR documentés des routes effectivement utilisées,
   puis seulement activer la politique workspace existante avec sa révision
   relue. Conserver les appels USD historiques dans leur devise. Vérifier aussi
   les autres applications de Showcase : un tarif absent ou dans une devise
   sans plafond entraîne un refus avant envoi. Aucun taux arbitraire ni plafond
   USD parallèle ne doit être présenté comme une enveloppe unique de 2 000 EUR.
   `openai/gpt-4o-mini` est aussi déclaré par cinq systèmes de Showcase : couvrir
   son tarif et qualifier leurs limites de sortie pour les maintenir accessibles.
   Les routes Ollama `qwen3:8b` et vLLM souverain restent non qualifiées sous
   plafond ; leur attribuer un prix ne change pas ce statut.
4. La référence BCE consultée le 22 octobre porte la date du 21 octobre 2026 :
   `1 EUR = 1,1234 USD`, soit `0,890154886950 EUR par USD` à 12 décimales.
   Source : <https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml>.
   C'est une convention de valorisation datée, pas une garantie de change ou de
   facturation. Conserver source, date et taux dans les nouveaux tarifs.
5. Tester admission puis refus sur un périmètre de recette, sans épuiser
   artificiellement l'enveloppe métier. Tout plafond actif refuse les nouvelles
   sessions vocales LLM continues non qualifiées ; STT/TTS restent hors de ce
   budget. Ce comportement a été indiqué lors du choix utilisateur du plafond.
6. Les critères de la [suite proposée](../demo-runs/showcase-ecommerce/qa-2026-10-22/criteria-review.proposal.md)
   ont été validés par l'utilisateur et enregistrés dans la suite
   `7ff7e53f-f9fc-4df1-827b-c31ff84714da`, révision 1. Les 48 essais correspondent à
   12 dossiers × 2 versions × 2 répétitions, avec trafic QA et arrêt avant action.
   Choisir une baseline gelée, relire r38 et examiner le préflight avant lancement.
7. Les préfixes de v10 et r38 reprennent actuellement le même parcours utile :
   la campagne mesure la répétabilité et la non-régression, pas l'amélioration
   d'une nouvelle politique. Ce corpus déjà examiné est de développement ; ce
   n'est pas un holdout aveugle ni un benchmark de temps humain ou de ROI.

La qualification des 48 Runs, le verdict du nouveau protocole Judge en service,
l'admission sous plafond EUR et la taille reconstruite des images restent à
recetter. Des tests locaux ne permettent pas de les déclarer effectués.
