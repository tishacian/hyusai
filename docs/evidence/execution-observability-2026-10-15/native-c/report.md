# Candidat C : port Temporal natif — qualification locale

Le ciblé final du 15 octobre 2026 passe : **29 tests, aucun échec ni skip,
33,03 secondes**. Il couvre 15 cas du port métier, 2 courses PostgreSQL,
2 compositions sur un vrai serveur Temporal et 10 cas de dispatch/réconciliation
(dont un PostgreSQL). Le code testé est l'arbre de travail non commité basé sur
`0b63fcec0be57a87b7578142a15c2b797dbe98cc` ; les empreintes des sources concernées
sont dans `validation.json`. Le SHA de base seul n'identifie pas ce candidat.

## Ce qui est exécuté

Le SDK est `temporalio 1.34.0`, sans import du plugin LangGraph/Temporal pour ce
candidat. La CLI Temporal est 1.9.1, avec Server 1.32.0 et UI 2.54.1. Les tests
SDK démarrent chacun leur serveur de développement sur localhost avec une base
SQLite persistante jetable. La base applicative de ces deux compositions est
SQLite ; les trois tests PostgreSQL distincts utilisent des schémas isolés du
PostgreSQL local partagé.

Les deux profils fermés sont exécutés jusqu'à un vrai `DeliveryReceipt` :

- `agent_data_agent` : Skill agent → DataPrep → Skill agent → revue → livraison ;
- `data_agent_delivery` : DataPrep → Skill agent → `evaluate_v2` → revue → livraison.

Les Skills agents sont des doubles locaux du fournisseur ; le juge utilise son
wrapper et ses validations réels avec un fournisseur de réponses simulé. La
préparation matérialise réellement ses datasets. Le Flow publié, son contrat
figé, les SkillInvocation, la filiation, la ServiceWindow, la qualification
humaine, la Decision et le reçu sont les autorités applicatives réelles.

L'entrée par `service_tick` est couverte : publication explicite du profil,
création atomique de la tentative et de l'intention Temporal, absence d'envoi
au moteur legacy, refus avec rollback lorsque les options requises sont fermées.
Les contrôles de révision, périmètre et appartenance sont repris avant effet
et avant publication d'un résultat. La révocation pendant l'appel bloque la
publication ; une réponse tardive ne remplace pas un résultat déjà marqué perdu.

## Attente, reprise et autorités

Les tests SDK désactivent le mode eager. DataPrep reste d'abord `queued` avec
une intention durable, alors que Temporal n'a **aucune Activity en cours**.
Le point d'entrée natif `run_preparation` est ensuite appelé hors Activity.
La livraison attend aussi la revue sans Activity occupée. Un signal Temporal
ne donne aucune approbation. Le worker SDK est arrêté proprement ; le processus
du serveur Temporal est tué puis redémarré sur sa base persistante. La revue
est enregistrée sans worker SDK actif, puis un nouveau Worker reprend et produit
un seul reçu. Ce test ne tue pas un processus worker au milieu d'un appel.

Les tests de concurrence PostgreSQL confirment qu'une soumission concurrente
partage une identité SkillInvocation stable et n'appelle le fournisseur qu'une
fois. Un second scénario bloque la réponse du fournisseur, scelle l'invocation
comme perdue depuis une autre session, puis vérifie que son retour tardif ne
réécrit ni cet état ni sa sortie. La réconciliation du starter respecte un verrou
natif détenu par une autre transaction. Les résultats inconnus ne sont jamais
réexécutés automatiquement.

L'échéance absolue de chaque calcul enfant est bornée par celle du Run avant
la mise en file. La recette couvre les contrôleurs activé et legacy ; un enfant
expiré avant démarrage n'exécute pas son calcul. Le défaut qui transformait un
Run actif refusé en `cancelled` au lieu de `failed` est couvert par les tests du
starter ; les états terminaux antérieurs restent préservés.

Les entrées de l'agent utilisent la fusion canonique du DAG. Les recettes de
sortie DataPrep unique implicite et de split avec `from_port` explicite imposent
un schéma exigeant `dataset_id`, puis vont jusqu'au juge, à la revue et au reçu.
Le champ `output_port` du profil choisit exactement le dataset présenté à cette
revue ; il est obligatoire pour une sortie DataPrep multiple et fait partie du
digest figé. Un port absent ou ambigu est refusé dès le gel du profil.

## Limites de cette preuve

- Aucun fournisseur LLM vivant, HANA ou client externe n'a été appelé. Les coûts
  ou tokens non mesurés restent inconnus ; le tarif du juge simulé ne devient pas
  une mesure complète de tous les appels agents.
- Les deux compositions SDK ne passent pas par un broker ou un worker Celery
  réel pour DataPrep. Elles vérifient l'intention durable et invoquent le point
  d'entrée métier séparément. La recette RabbitMQ du dossier voisin reste une
  preuve de transport distincte, pas un parcours métier complet de ce candidat.
- Aucun graphe général, `agent_loop`, boucle, branche parallèle ou sous-flow
  n'est porté par ces deux profils. Le scoring possède un port de soumission,
  mais aucune composition SDK avec un modèle réel n'est qualifiée ici.
- Le SDK, le serveur dev et les fixtures ne qualifient ni haute disponibilité,
  ni charge, ni coût opérationnel. Aucune comparaison de performance A/B/baseline
  n'est déduite des 33,03 secondes de tests.
- L'image d'orchestration C n'a pas été construite ou mesurée sur la VM. Aucun
  déploiement, changement de plafond, secret ou activation production n'a eu lieu.
- La suite générale est exécutée séparément. Ce dossier conserve uniquement le
  ciblé final réussi ; il ne prétend pas en connaître le résultat.

`validation.json` donne la commande reproductible (DSN fourni par variable
d'environnement, sans valeur secrète), les versions et les empreintes des
sources. `SHA256SUMS` couvre les fichiers de ce dossier, sauf lui-même. Le serveur
standalone de préparation sur le port 17233 a été arrêté après qualification ;
les serveurs appartenant aux tests sont nettoyés par leurs fixtures. Le PostgreSQL
partagé est conservé pour la suite générale.
