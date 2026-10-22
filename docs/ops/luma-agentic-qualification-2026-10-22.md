# Luma — qualification agentique, gouvernance et exécution interrompue

État établi à partir du dépôt et des preuves de recette des 21 et 22 octobre. Ce
document ne constitue ni une activation de politique ni un résultat fournisseur
sur la nouvelle livraison. Les tests de moteur utilisent des doubles explicites
du planificateur ; ils ne mesurent pas la qualité d'un modèle.

## Livraison et activation

Cette livraison ajoute des capacités produit réutilisables : sélection explicite
du modèle du planificateur, contexte d'entrée borné et tracé, choix des outils
lisible dans le Flow, historique des décisions dans Work et les Runs, comparaison
de modèles sur une décision figée, historique des instructions des Skills,
règles SAV consultables et configurables, et contrôles de politique adaptés aux
Flows mêlant outils déterministes et appels LLM. Les modèles ML gardent leurs
propres épingles et droits ; ils ne deviennent pas des modèles de langage.

La comparaison produit de nouvelles propositions avec les mêmes entrées figées.
Elle ne lance pas les outils proposés. L'historique des instructions concerne
les Skills `prompt_template` présents dans des publications ; l'objectif du
planificateur natif Luma reste versionné dans le Flow. Restaurer une instruction
ne republie pas automatiquement un système.

Déployer le commit qui contient ce document sur l'API, le frontend et les workers
qui exécutent les Flows, les appels de modèles et `evaluate_v2`. Il n'y a aucune
migration ni nouveau drapeau. Les écrans de catalogue/comparaison et de Flow
utilisent leurs ouvertures produit existantes (`model_portal_beta` et
`flow_workbench_v1`). Relire leur disponibilité dans le workspace au lieu de
changer les drapeaux globaux.

Le plan d'application Luma est séparé du code :
[ACTIVATION.md](../demo-runs/showcase-ecommerce/fixtures/agentic_controls/ACTIVATION.md).
Il contient un candidat issu de la v10 et une restauration distincte du brouillon
utilisateur r38, avec préconditions de concurrence. Le plan n'a pas été appliqué.
Qualifier les trois entrées et les refus avant toute politique `enforce`, puis
coordonner les bindings, le triage et les publications d'applications. Conserver
le champion ML v5, le shadow à 10 %, les pages et les événements en pause.

### Déjà vérifié en service le 22 octobre

- L'application **Pilotage SAV — équipe**, pilote **R2**, a exécuté le Run
  `19263298-c5fa-4698-b174-f9afcb7db692` : **23 dossiers scorés, aucun exclu,
  modèle v5**. Elle consomme la même entrée de file du système Luma publié.
  Création, publication et exécution ont été réalisées dans l'UI ; le réglage
  fin des sélecteurs KPI a utilisé l'API produit, ce qui ne prouve pas encore un
  parcours de configuration intégralement autonome pour un utilisateur métier.
- Le catalogue OpenAI est accessible et les enquêtes ont réellement appelé
  GPT-5. Ollama est configuré mais injoignable ; les autres fournisseurs ne sont
  pas configurés pour cette recette. Ni une bascule de fournisseur ni une
  comparaison effective des nouveaux écrans n'ont encore été qualifiées.
- La nouvelle enquête RC-1044 a atteint l'approbation humaine et a cherché la
  preuve du remboursement antérieur. Son Judge reste invalide sur la révision
  en service : la correction ci-dessous demande une nouvelle recette après
  déploiement. Le Run RC-1043 interrompu reste à clôturer par l'opérateur selon
  la procédure de ce document, sans rejouer l'action.

Les tests locaux couvrent le moteur, les autorisations, les reprises, les refus,
les règles et les parcours navigateur FR/EN, desktop/mobile. Les recettes
navigateur utilisent des réponses contrôlées ; elles vérifient l'interface et
les contrats, pas la qualité d'un fournisseur réel.

Contrôles de livraison : 533 tests backend intégrés réussis ; 13 tests
PostgreSQL réels réussis sur les verrous et la clôture opérateur ; suite frontend
complète de 2 654 tests réussie, puis suites ciblées après les derniers ajustements.
Les parcours navigateur couvrent Réclamations et Studio (45 scénarios), le
catalogue/comparaison et les instructions (9), et les réglages AgentLoop (2).
Deux scénarios supplémentaires vérifient les actions sans saisie, la confirmation
clavier, le retour après Échap et la conservation du focus pendant une exécution.
Le build de production et les contrôles i18n, chrome UI et navigation passent.

## Ce que la démonstration établit

Le Run `64a9aac5-2ecd-4f37-821a-e171dfb9386c` a exécuté quatre décisions de
planification : PostgreSQL, politique documentaire, preuve de perte, proposition.
Le modèle choisit les recherches dans un mandat de cinq outils. Les règles
métier, le montant et l'approbation sont contrôlés séparément. Une exécution
avec données fictives et action financière simulée reste une démonstration,
même lorsque les lectures et les appels de modèles sont réels.

La v10 publiée porte un AgentLoop `recommend`, douze tours maximum et une sortie
sur épuisement. Sa ControlPolicy est explicitement `not_configured`. Cela ne
supprime ni les ACL, ni l'allowlist, ni les contrats publiés, ni le contrôle
humain. Cela ne démontre pas non plus une politique centrale de coût/latence
activée. Le brouillon r38 n'est pas à remplacer pour ajouter ces contrôles.

## Coûts et budgets : ne pas confondre les mesures

Les quatre décisions du Run cité totalisent **38 021,84 ms** de durée technique
cumulée et **44 583 tokens** rapportés par le fournisseur : 41 469 en entrée,
3 114 en sortie. Ce n'est pas le temps humain économisé ni la durée complète
du traitement. Le quatrième appel seul consomme 21 884 tokens : la croissance
des observations doit être mesurée après les changements de contexte.

Chaque décision affiche 0,003 USD dans `cost` et `provider_cost_usd`, mais sa
preuve précise `method=catalog_unit_price`. Le total **0,012 USD est un calcul
au tarif catalogue par appel**, pas une facturation fondée sur les tokens.
À titre de reconstruction, au tarif GPT-5 déclaré pour Judge de 1,25 USD par
million de tokens d'entrée et 10 USD par million de sortie, ces quatre appels
représenteraient **0,08297625 USD**. Cette reconstruction suppose le même tarif,
ignore la remise cache et ne remplace ni facture ni preuve de coût enregistrée.

La présente livraison corrige la projection du ledger pour les nouvelles
invocations LLM : un prix catalogue reste disponible comme coût déclaré, mais
ne renseigne plus `provider_cost_usd`. Sans tarif fournisseur raccordé,
`provider_cost_evidence` indique `not_measured` et le montant fournisseur reste
`null`, y compris après erreur ou annulation. Le total fournisseur du Run reste
également inconnu si un de ses appels modèle est explicitement non tarifé ; les
sous-totaux connus restent consultables sur les invocations. Aucun prix courant
n'est inventé et aucun ledger historique n'est réécrit. Les tarifs spécifiques
du Judge et du labeling restent accessibles dans leurs résultats propres ; ils
ne deviennent pas automatiquement une grille fournisseur générale.

Le `max_cost` de l'AgentLoop consomme l'accumulateur `invocation.cost` du Run,
donc potentiellement les coûts des étapes précédentes et des devises distinctes.
Il est contrôlé entre les tours, pas réservé avant chaque appel fournisseur.
Ne pas le présenter comme un plafond de facture garanti en USD ou en EUR.

Le Judge a un budget distinct réellement configuré : un appel, 48 000 tokens,
0,14 USD, 90 secondes, 32 000 octets de prompt. Il réserve avant dispatch et
ne réessaie pas silencieusement. Son plafond ne couvre pas le reste du Flow.

### Candidat à qualifier, non appliqué

| Contrôle | Proposition et portée |
| --- | --- |
| AgentLoop | Conserver 12 tours et `recommend` ; examiner `deadline_ms=120000` pour la boucle, avec sortie explicite. C'est une limite contrôlée entre appels, pas une interruption garantie d'un fournisseur lent. |
| Outils | Construire l'allowlist centrale depuis le contrat publié complet : les 5 outils d'enquête ne couvrent pas les entrées file et prévision. La v10 utilise 14 compétences distinctes. Toute nouvelle compétence exige une revue. |
| Modèles | Lier les identités effectives des routes autorisées ; vérifier les appels imbriqués de recherche et le Judge avant de restreindre. Un modèle ML servi est une épingle distincte d'une route LLM. |
| Tokens système | Candidat de qualification : 220 000 tokens cumulés. Douze décisions extrapolées à partir de la moyenne observée donnent environ 133 749 tokens ; il faut ajouter la réserve Judge de 48 000 et les autres appels. Cette extrapolation ne prédit pas la croissance du contexte. |
| Latence système | Candidat de qualification : 240 000 ms de durée technique cumulée, sans assimiler l'attente humaine à du calcul. Vérifier la sémantique du compteur et la couverture sur les trois entrées. |
| Tentatives | Candidat : 40 tentatives maximum, 2 échecs, avec contrôles spécifiques aux actions. Les appels de planification, outils, préparation et évaluation comptent ; ce n'est pas un nombre de dossiers. |
| Montants | Ne pas activer un plafond global de coût tant que les monnaies et méthodes du ledger ne sont pas comparables. Conserver le budget Judge séparé et les sous-totaux par devise. |

Commencer la qualification des valves centrales en `shadow` si les mesures sont
incomplètes. En mode `enforce`, une couverture de coût, tokens ou latence inconnue
peut légitimement bloquer ; ne pas la remplacer par zéro. Passer en `enforce`
seulement après les cas normaux et les refus, sur une nouvelle publication revue
dont la politique fait partie du hash. Tester file, enquête et prévision, les
consentements événementiels et les bindings ; conserver le brouillon utilisateur.

## Harness et comparaison honnête avec un workflow déterministe

Les tests `test_agent_loop_qualification.py` complètent les suites existantes :
arrêt avant le prochain tour après seuil de coût catalogue ou deadline, attente
d'une pièce manquante, relecture après réponse humaine, refus humain sans nouvel
outil, et suppression d'un outil par une politique figée jusque dans le prompt.
Les suites existantes couvrent les outils hors mandat, écritures interdites,
épuisement des tours, versions figées et mesures manquantes. Un passage de tests
ne constitue pas une campagne adversariale fournisseur ni une certification.

Pour comparer la valeur du planificateur :

1. Figer les mêmes données, sources, versions de règles, modèles ML et outils
   pour les deux bras. Utiliser des dossiers indépendants des trois cas de scène.
2. Bras déterministe : même PostgreSQL, même politique, branche explicite
   remboursement antérieur/perte/livraison, même proposition contrôlée, Judge et
   HITL. Il ne fait pas appel au planificateur. Ne pas lui imposer artificiellement
   de lire toutes les pièces si une branche conditionnelle suffit.
3. Bras agentique : mêmes capacités et limites ; le planificateur choisit les
   recherches. Inclure cas réguliers, pièces absentes, contradictions, doublons,
   révisions périmées et instructions malveillantes dans les documents.
4. Répartir l'ordre des bras, conserver tous les essais, échecs, abstentions,
   demandes humaines et coûts. Ne pas relancer jusqu'au succès en supprimant les
   échecs. Séparer jeux de réglage et de validation ; garder les cas non vus.
5. Faire évaluer à l'aveugle la résolution et les preuves par un autre humain.
   Mesurer conformité, couverture, mauvaises actions évitées, temps humain actif,
   temps technique, nombre de recherches et tokens/coûts documentés par devise.
6. L'avantage agentique n'est acquis que si la qualité reste suffisante et qu'un
   bénéfice observé compense le surcoût de planification. Sur ces règles simples,
   un workflow déterministe peut être meilleur. Publier aussi ce résultat.

Le benchmark humain SAV existant compare manuel/assisté, **pas déterministe/LLM**.
Ne pas détourner ses étiquettes pour une comparaison de moteurs. Le correctif de
verrouillage ci-dessous permet de reprendre sa qualification ; les hypothèses
8 min/2 min/40 €/h/0,50 € restent des hypothèses tant que la mesure manque.

## Benchmark SAV : correction du verrou

Le début et la fin d'une session de benchmark détenaient un verrou `FOR UPDATE`
sur le workspace avant de relire PostgreSQL. L'audit de résolution du secret,
effectué dans une autre session, attendait ce même workspace pour sa clé étrangère.
Le verrou passe à `FOR NO KEY UPDATE` : les transitions restent sérialisées, et
l'audit peut obtenir `KEY SHARE`. Les autres occurrences SAV examinées ne montrent
pas ce motif restant : la simulation est déjà corrigée ; les vérifications de
source et l'installation n'acquièrent pas ce verrou exclusif sur le workspace.

La recette PostgreSQL teste réellement le vieux conflit, la sérialisation de
simulation, puis le début et la fin du benchmark avec audit indépendant. Elle
ne contacte ni PostgreSQL métier distant ni fournisseur de modèles.

## Clôturer proprement le Run inline interrompu

Après la mise en service de `550807bf`, les lectures PostgreSQL ont repris mais
le Run `64a9aac5-2ecd-4f37-821a-e171dfb9386c` est resté `running` sans nouveau
reçu. Son checkpoint d'approbation indique **`plane=inline`** : c'est le processus
API qui portait la continuation, pas le worker CPU. L'approbation
`80a3ede7-9d77-4faf-8c8c-45e68fac67ae` reste acceptée.

La commande ci-dessous appartient à la livraison qui contient ce document ; elle
n'est pas disponible dans `550807bf`. Elle clôture un Run isolé en **échec**,
avec `execution_interrupted_outcome_unknown` sur l'invocation. Elle ne reprend
aucun outil, ne recrée aucune approbation et ne produit aucun reçu. Les entrées,
sorties partielles, citations, compteurs existants et décision humaine sont
conservés. Les durées inconnues restent inconnues. Un checkpoint et un audit
transactionnel enregistrent l'opérateur et le hash de sa preuve.

L'ancien inline ne disposait pas d'une lease de propriétaire. L'opérateur doit
donc établir et documenter que **le processus API qui exécutait cette continuation
a cessé d'exister**. Une nouvelle image ou une readiness 200, seule, ne le prouve
pas. Les verrous `NOWAIT` détectent un écrivain concurrent en base ; ils ne
détectent pas un ancien processus encore occupé dans un appel externe.

Dans le conteneur backend de la nouvelle livraison, commencer par cette lecture :

```bash
python -m app.cli.reconcile_interrupted_run \
  --workspace-id e2ed9e40-5fa6-4e32-8948-3e1220134fd3 \
  --run-id 64a9aac5-2ecd-4f37-821a-e171dfb9386c \
  --decision-id 80a3ede7-9d77-4faf-8c8c-45e68fac67ae \
  --invocation-id 474522a1-f530-4979-b43d-ee27d543d013
```

Relire le résultat ; conserver son `state_sha256`. Après vérification physique
de l'arrêt et préparation d'une preuve non secrète dans le conteneur, reprendre
la même commande en ajoutant les paramètres suivants, remplacés par les valeurs
réelles. Aucun fichier de preuve ni hash n'est fourni fictivement par ce runbook.

```text
--apply
--expected-state-sha256 <hash exact de l'aperçu relu>
--operator <identité de l'opérateur>
--evidence <fichier local non secret prouvant l'arrêt du processus>
--confirm-process-stopped
```

La commande refuse un état changé, un autre workspace, une autre invocation,
une décision non confirmée humainement, un écrivain concurrent ou une exécution
ayant un autre propriétaire (Celery, Temporal, sous-flow). Un nouveau passage
sur un Run déjà clos est refusé, sans nouvelle mutation. Ne pas changer
manuellement un statut pour contourner ce refus.

Après application, relire le Run, sa décision, l'invocation, l'audit et le dossier
RC-1043. Attendu : décision toujours acceptée ; Run et invocation en échec
documenté ; aucun nouveau reçu. Une nouvelle enquête éventuelle est une autre
opération, après contrôle des preuves et des effets possibles ; cette commande
ne l'autorise ni ne la lance.

## Règles SAV : consultation et paramètres du workspace

Dans Work → Réclamations → dossier → **Règles de résolution**, la section repliée
montre la politique documentaire applicable et le seuil d'approbation responsable.
Les administrateurs et propriétaires du workspace peuvent modifier la devise,
le seuil et la référence documentaire (clé, version et SHA-256). Un lecteur
métier peut consulter les règles sans obtenir le droit de les modifier. Une
proposition issue d'autres règles est signalée et doit être recalculée.

Les routes produit `GET/PUT /api/v1/ecommerce-claims/policy` utilisent l'accès à
l'application Work. L'écriture exige `expected_sha256` et vérifie le document
présent dans PostgreSQL, sa source indexée, son empreinte et les ACL de sa
collection avant le verrou du workspace. Sous ce verrou, elle revérifie les
droits, les règles et le périmètre des sources ; réglages et audit sont validés
dans la même transaction. Une réponse d'enregistrement inconnue impose une
relecture dans l'interface avant une nouvelle modification.

Sans configuration explicite, les paramètres historiques restent applicables :
`refund-policy-v2`, version `2`, empreinte déjà configurée, EUR, responsable
au-delà de 300 €. Aucune lecture n'écrit ces valeurs. Enregistrer ces mêmes
paramètres les rend explicites sans changer leur empreinte et sans invalider
les propositions historiques. Changer les paramètres invalide les propositions
préparées sous d'autres règles, même si leur montant reste identique. La
simulation revérifie aussi cette empreinte sous verrou avant tout nouveau reçu.

Ces paramètres ne permettent ni paiement réel, ni suppression de l'approbation
humaine, ni contournement des preuves et des doublons. Les règles de détection
des cas SAV restent déterministes ; ce complément n'est pas un moteur de règles
universel. Il ne requiert aucune migration ni nouveau drapeau, et ne modifie
ni brouillon Flow ni publication. Après déploiement, on peut relire puis
enregistrer les paramètres inchangés pour démontrer leur configuration produit ;
aucune nouvelle politique n'est activée automatiquement par cette livraison.

## Judge : citations exactes résolues côté serveur

La recette réelle du Run `47b52fd5-ea6b-404a-b640-f837ed6d6e33` sur la révision
`550807bf` atteint l'approbation humaine pour RC-1044. Le choix de rechercher les
preuves de remboursement puis de proposer `close_duplicate` est visible dans
les invocations. Le Judge a cependant refusé la première citation de la première
question (`evidence_span`). Son appel a consommé 11 538 tokens, dont 2 734 en
sortie, pour 0,038345 USD au tarif déclaré ; ce n'est pas une troncature signalée.
La réponse brute n'étant pas conservée, le nombre incorrect ne peut pas être
reconstitué à partir du diagnostic. Cette recette ne prouve donc pas une
évaluation Judge valide.

La correction produit remplace le calcul des offsets demandé au modèle par un
contrat de transport `evidence_id + quote`. Le modèle doit copier un passage
court, contigu et exact, avec assez de contexte pour qu'il soit unique dans la
source choisie. Le serveur cherche ce passage dans cette seule source autorisée
et immuable, sans normaliser Unicode, espaces, accents, casse ou sauts de ligne.
Une absence ou plusieurs occurrences, y compris chevauchantes, restent des
échecs de validation. Les offsets Unicode calculés repassent dans le schéma et
le contrôle de citation canoniques ; le résultat enregistré conserve donc
`evidence_id`, `start`, `end` et `quote`. Les citations d'images ne changent pas.
Un fournisseur qui renvoie encore des offsets est refusé par le nouveau schéma,
et non corrigé silencieusement.

Ce protocole ne décide pas qu'une citation démontre une conclusion : le Judge
reste chargé de cette appréciation et la revue humaine reste requise. Une
ambiguïté produit un diagnostic `evidence_quote_ambiguous`, avec les mêmes
règles de coût, d'absence de reprise automatique et de retenue pour revue.
Les empreintes du prompt et du schéma changent ; une ancienne réponse en cache
ne peut pas être réutilisée sous le même identifiant et les profils de
calibration d'un autre protocole ne sont pas transférables.

Déployer ce code sur l'API et les workers exécutant `evaluate_v2`. Aucune
migration, aucun nouveau drapeau, aucune modification du Flow publié, de son
brouillon, de la grille de questions ou des budgets n'est nécessaire. Après
déploiement, qualifier une nouvelle enquête métier et vérifier la présence de
citations exactes dans l'évaluation, sa qualité et l'approbation humaine. Ne pas
relancer aveuglément le Run existant et ne pas annoncer cette qualification
fournisseur comme déjà acquise : les tests locaux utilisent un transport simulé.
