# Luma : Judge, événements et amélioration du modèle

État vérifié le **17 octobre 2026**. Les changements de cette livraison sont des
fonctions produit réutilisables ; Luma en reçoit une configuration. Ce rapport
distingue le code testé, la configuration préparée et les résultats observés
sur `agentium.papai.ai`.

## Parcours et couverture

Le parcours conserve un System métier et une application Work : réception d'un
dossier → PostgreSQL → dataset et préparation → score de priorité SLA → enquête
documentaire et proposition → Judge → validation SAV → reçu simulé. La mise à
jour de la file et la prévision restent des entrées distinctes de ce même Flow.

| Capacité | Livraison produit | Situation de Luma au contrôle |
| --- | --- | --- |
| PostgreSQL et DataOps | Lecture, données préparées et scoring déjà composés | La route des dossiers répond 503 `POSTGRESQL_READ_UNAVAILABLE` |
| Documentation et agent | Collections du Flow et outils d'enquête existants | La publication v4 conserve ces sources |
| Judge | Capture de preuves dans le même Run, questions typées, abstention et revue Work | Nouveau raccordement préparé ; aucun résultat live du Judge attesté |
| Événements | Setup webhook signé et cron dans l'inspecteur, création en pause | Aucun hook ni schedule Luma au contrôle ; mode événements `dry_run` |
| MLOps | Readiness du couple shadow et qualité par échantillon | Reconstruction SLA lancée ; aucune promotion ni boucle récurrente activée |
| Prévision | Chronos et vue Charge existants | Sa présence ne prouve pas une inférence disponible ; hors réentraînement automatique actuel |
| Impact | Exécutions et scénario financier distincts | Les essais techniques ne constituent ni mesure humaine ni économies réalisées |

La surveillance crée un Flow technique géré par Model Center. Il ne constitue
pas une deuxième application métier ni un second récit de démonstration.

## Changements d'interface

- Work affiche les questions et motifs du Judge au niveau de la décision.
  Une abstention reste visible ; les métriques techniques sont repliées dans
  les détails. La validation humaine reste une action séparée.
- L'inspecteur montre le setup correspondant à la source sélectionnée.
  Le cron expose le fuseau, les entrées, la prochaine échéance et le dernier
  Run. Les créations restent en pause jusqu'à leur activation explicite.
- Le shadow explique l'indisponibilité d'un artefact ou d'un runtime et conserve
  la possibilité de désactiver une configuration existante.

Les recettes navigateur locales utilisent des réponses simulées identifiées
comme telles. Elles vérifient l'affichage et les interactions ; elles ne
qualifient pas les fournisseurs, workers ou données de la VM.

Captures : [Judge desktop](qa-2026-10-17/judge-work-desktop.png),
[Judge mobile](qa-2026-10-17/judge-work-mobile.png),
[planification](qa-2026-10-17/schedule-setup.png),
[webhook mobile](qa-2026-10-17/webhook-mobile.png),
[shadow](qa-2026-10-17/shadow-fr.png).
Le Builder complet reste dense sur petit écran : sa barre d'outils et ses
bannières précèdent l'inspecteur. Le panneau de setup est utilisable, mais cela
ne constitue pas une refonte de toute la navigation mobile du Builder.

## Validation locale

- **2 319 tests unitaires frontend** et compilation Angular de développement
  réussis ; contrôles TypeScript, traductions et liens de navigation réussis.
- **176 tests backend** réunis sur Judge, preuves de Run, contrats de Flow,
  composition métier, shadow/API et chargement ML réel réussis.
- **32 scénarios navigateur** réussis : 18 Work, 10 shadow, 4 déclencheurs.
  Les panneaux testés passent les contrôles d'accessibilité et de débordement ;
  les actions des déclencheurs restent à 36 px ou moins.
- Le contrôle chrome global conserve un échec préexistant :
  `src/styles.scss:halo`, 7 occurrences pour un budget de 6. Aucun nouveau
  dépassement n'est introduit dans les composants modifiés.

## Contrôles des preuves

Le Judge lit les champs explicitement sélectionnés dans des invocations du
même Run. La dernière tentative doit être terminée ; un échec récent ne permet
pas de reprendre silencieusement une ancienne réussite. Le snapshot conserve
les références et versions de ses sources. L'accès est revérifié avant et
après l'appel, y compris pour une exécution automatique sans utilisateur dans
le contexte du worker. Une révocation retire le résultat, sans effacer le coût
déjà engagé. Aucun score de confiance calibré n'est inventé.

Le shadow associe la vérité terrain au `sample_id` et au même index dans les
deux résultats. Les labels de lots ambigus, les données non conservées et les
lignes hors workspace sont exclus. Un label corrigé remplace l'ancien pour
le calcul ; l'accord entre modèles reste distinct d'une qualité observée.

## Vérifications de l'environnement déployé

Les routes frontend `/build-info.json` et backend `/api/v1/build-info`
annoncent toutes deux `f4329db35d428e5f646028c783d7ee335de76e3b`.
Les corrections `37d4e064`, `06a77b6f` et cette livraison ne sont donc pas
attestées sur le site au moment de ce contrôle.
Les [observations API](qa-2026-10-17/live-observations.json) datent le contrôle
final à 07:39 UTC et conservent uniquement des informations non secrètes.

Le System `f3ea83de-df89-45ec-8a85-c00d676b2713` publie toujours la v4
`0c18cb17-ee28-4cbc-acd8-aafb6bcce150`, 24 nodes, empreinte
`fad0507f94c836d392a5822c81aed47e482329b5f240398661c72c12b7944556`.
Le draft r23 possède un node supplémentaire et doit être conservé. Les trois
bindings Work et la configuration de priorité doivent être réépinglés lors
de la nouvelle publication. L'ancien runbook d'installation ne doit pas être
rejoué sur cette composition déjà installée.

Le fournisseur OpenAI répond au contrôle du catalogue. La route courante est
`openai/gpt-5` ; ce contrôle annonce explicitement `generation_verified=false`.
Le tarif public vérifié sur
[la page du modèle](https://developers.openai.com/api/docs/models/gpt-5) est
de 1,25 USD par million de tokens entrants et 10 USD sortants. Le tarif déclaré
ne représente pas une facture et ne déduit pas les remises de cache.

Un entraînement a été soumis avec le dataset synthétique existant
`e1141f15-820e-46e5-87f8-9c6f3dc9a430` (4 573 lignes), les six variables SLA,
la même régression logistique, une partition de test de 25 % et trois plis.
Le candidat est `cd2d0692-7586-4e19-b541-8363118e031c`, v3 de la lignée SLA.
Le champion v1 est conservé. Attendre un état final puis une inférence épinglée
réussie avant de considérer ce candidat utilisable.

## Activation et limites

Déployer la livraison sur API, frontend et workers, réconcilier le catalogue,
puis rétablir la lecture PostgreSQL. Utiliser ensuite le plan de configuration
avec une revue fraîche de la publication, du draft et des bindings.
Le [plan préparé](fixtures/showcase_quality_events/reviewed_plan.review.json)
contient 27 nodes, 28 edges et cinq entrées ; il est explicitement marqué
`activation_ready=false` tant que le modèle n'est pas qualifié.
Le [runbook d'activation](fixtures/showcase_quality_events/ACTIVATION.md)
décrit les mises à jour de publication, draft, bindings, triage et release.
Le test webhook doit démontrer une seule exécution malgré une livraison
répétée. Le test cron doit être borné à une occurrence avant remise en pause.

La boucle complète d'amélioration porte sur le SLA tabulaire : inférence,
retours admissibles, surveillance, proposition et approbation d'un
réentraînement, comparaison, puis promotion séparée. Aucun retour humain ou
résultat futur n'a été inventé pour la déclencher. Chronos peut recevoir des
observations datées, mais sa famille `forecasting_deep` n'est pas prise en charge
par la boucle de réentraînement planifiée actuelle.

Voir les contrats génériques :
[déclencheurs](../../agentium-flow-trigger-operations.md) et
[activation MLOps](../../agentium-mlops-activation.md).
