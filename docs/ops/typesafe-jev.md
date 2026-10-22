# TypeSafe Jev — décisions typées

Le fournisseur `typesafe` peut exécuter le skill `evaluate_v2` avec l'API native
System One. Il ne devient ni un modèle de conversation, ni un repli de génération
de texte. L'intégration utilise HTTPX déjà présent ; aucun SDK, migration ou
drapeau supplémentaire n'est nécessaire.

## Déploiement avec les budgets existants

Livrer la même révision sur le frontend et tous les composants d'exécution. Si un
plafond Usage est actif, renouveler l'attestation de cette révision via
`POST /api/v1/observability/usage/readiness/attest` après vérification opérateur :
API, worker CPU, worker DataOps, runner de connecteurs et agent LiveKit au même
SHA, workers recréés et sessions LiveKit drainées. Relire la readiness avant de
reprendre les Runs sous budget. L'attestation d'une ancienne révision ne couvre
pas cette livraison ; sans renouvellement les modèles déjà utilisés par Luma
seraient également refusés. Vérifier que `qualified_transports` contient
`model_plane.typesafe.pinned_monetary_v1`. Cette capacité couvre uniquement les
versions et dimensions monétaires décrites ci-dessous.

Ne pas interrompre une campagne ou un Run en cours pour cette livraison.
Comparer avant/après les publications, brouillons, bindings et politiques de
budget ; aucun seed Luma n'est à rejouer.

## Accès et connexion

1. Créer un compte et une clé dans <https://console.typesafe.ai/keys> ; vérifier
   les modèles et les crédits disponibles pour ce compte.
2. Après déploiement sur l'API, le frontend et les workers qui exécutent les
   Skills, ouvrir **Ressources → Fournisseurs → TypeSafe → Configurer**.
3. Enregistrer la clé dans le champ prévu. Elle utilise le stockage de secrets
   existant du workspace et n'est jamais relue par le navigateur. Pour une
   configuration administrée globalement, la variable optionnelle est
   `TYPESAFE_API_KEY`. Une clé de workspace enregistrée mais illisible ne se
   replie pas sur cette variable.
4. Tester la connexion. Le test utilise `GET https://api.typesafe.ai/v1/models`
   avec authentification Bearer ; il ne déclenche aucune décision payante.
   Les modèles réellement retournés deviennent sélectionnables.

La documentation officielle consultée le 22 octobre 2026 annonce `jev-1.13.0`
comme version stable et `jev-1.14.0` en preview. Préférer une version explicite
à un alias mobile pour une qualification reproductible. Conserver dans la trace
le modèle demandé et celui effectivement retourné.

Le test authentifié réalisé le 22 octobre avec la clé fournie a répondu **200**.
Le compte expose `jev-latest` et `jev-preview` ; aucun identifiant figé n'était
retourné par sa découverte. La documentation [Models](https://docs.typesafe.ai/models.md)
précise que les identifiants versionnés restent acceptés même si la liste ne
retourne que les alias. Une version saisie explicitement n'est pas présentée
comme découverte ou testée. Aucun appel d'inférence n'a encore été effectué.
La clé est enregistrée uniquement dans les secrets du workspace Showcase,
jamais dans le dépôt, une configuration locale ou l'environnement de l'instance.

## Utilisation dans un Flow

Sélectionner un nœud **Typed Evaluation**, puis choisir le modèle TypeSafe dans
le sélecteur **Modèle d'évaluation**. Cette sélection utilise l'identité
fournisseur/modèle du tarif publié. Le tarif et sa référence doivent être revus
pour ce modèle ; les prix d'un autre fournisseur ne sont pas transférés.
Vérifier également que la politique du système autorise précisément le modèle
retenu ; la sélection du moteur n'élargit pas cette politique.

| Question Agentium | Primitive Jev | Conversion |
| --- | --- | --- |
| Booléen | Noul | `p > 0,5` ; égalité exacte à 0,5 : abstention |
| Probabilité | Noul | Probabilité « oui » conservée, seuils d'acceptation métier existants |
| Choix unique | Choice | Options publiées et distribution conservées ; égalité en tête : abstention |
| Score | Score | Bornes entières définissant 2 à 10 niveaux ; position attendue décalée sur l'échelle publiée |

Pour un contrôle sensible, utiliser une question Probabilité avec des seuils
d'acceptation explicitement revus plutôt que d'interpréter le seuil booléen de
0,5 comme une confiance suffisante. Les descriptions des niveaux d'un score
doivent être précisées dans la question.

Le contexte envoyé conserve les sources autorisées, leur identifiant et leur
empreinte. Jev ne produit pas de justification rédigée ni de citation par réponse.
Une question exigeant ces citations est refusée à la publication et à l'exécution,
avant tout appel. Les choix multiples et les images ne sont pas pris en charge
par cet adaptateur. Aucun de ces critères n'est désactivé automatiquement.

Les distributions et la confiance fournisseur sont conservées dans
`typed_decisions` et affichées dans le résultat du Judge, distinctement de la
confiance qualifiée pour la grille métier. Le résultat conserve `disposition=review`.
Une probabilité fournisseur ne vaut ni validation humaine ni qualification locale.
Le workflow existant de calibration des juges génératifs ne qualifie pas encore
le protocole natif TypeSafe ; aucune confiance qualifiée n'est revendiquée ici.

## Usage, budgets et limites d'activation

Les appels utilisent le contrôle de politique et la comptabilité d'usage communs.
Les compteurs fournisseur permettent de calculer le coût au tarif déclaré ; un
compteur absent reste inconnu. Un résultat invalide peut être facturé : son usage
mesuré reste comptabilisé. Les reprises réutilisent le résultat canonique ; il
n'existe aucun retry réseau ni fallback automatique.

**Les plafonds monétaires sont qualifiés pour `jev-1.13.0` et `jev-1.14.0`,
avec un tarif de sortie nul et le contexte standard.** Les alias mobiles restent
non qualifiés et sont refusés sous plafond (`USAGE_TRANSPORT_UNQUALIFIED`).

Le contrat fournisseur documente 64k tokens par requête, comprenant l'état et
toutes les questions ; l'état n'est facturé qu'une fois. Le transport réserve
conservativement **65 536 tokens d'entrée** au tarif déclaré. Il n'envoie jamais
le header `TypeSafe-Danger-Zone-Long-Context` qui ouvrirait 262k tokens. Une
requête dépassant la limite native est refusée par le fournisseur. Le calcul
utilise le payload natif validé, aucune borne fournie par le client.

La sortie est gratuite mais son nombre de tokens n'est pas borné par le
protocole. Il reste donc inconnu avant réponse : aucun zéro fictif n'est
enregistré. Un plafond portant sur les **tokens totaux** refuse cet appel
(`USAGE_BOUND_REQUIRED`). Un tarif de sortie non nul empêche aussi l'admission
monétaire, faute de borne. Les compteurs absents restent inconnus ; le coût
peut être calculé sur les seules dimensions effectivement facturées. Sans
mesure d'entrée, la réserve monétaire reste en attente.

Le modèle retourné doit correspondre à la version demandée. Un autre modèle
est refusé : ses compteurs restent tracés, son coût ne peut pas être établi avec
le tarif du modèle demandé, la réserve est conservée et une réconciliation est
requise. Une réponse avec des compteurs mais sans identité de modèle ne suffit
pas non plus à lever cette réserve. Aucun nouvel essai automatique n'est lancé.

Les réservations workspace et Judge restent atomiques. Le budget local du Judge
doit accepter les 65 536 tokens d'entrée réservés et sa provision de sortie ;
ses limites cumulées sont réconciliées après réponse. `max_output_tokens` reste
une provision locale, pas une limite transmise à Jev. Ces garanties reposent sur
le tarif déclaré et le contrat fournisseur, pas sur une facture rapprochée.

Sources du contrat : [limites et tarifs](https://docs.typesafe.ai/models.md),
[refus de contexte](https://docs.typesafe.ai/api/errors.md),
[facturation d'un lot de questions](https://docs.typesafe.ai/cookbooks/parallel_questions.md).

## Recette et Luma

La recette locale utilise un transport simulé : schémas natifs, erreurs et
masquage, absence de retries, accès aux clés, catalogue, refus en chat, refus des
contrats de citation incompatibles, persistance du Judge, usage et réutilisation
idempotente. Elle ne prouve pas la qualité métier, la latence ou le coût d'un
appel réel Jev.

La validation de cette livraison couvre les tests ciblés de transport, de ledger,
de Judge et de préflight, le build frontend et les parcours navigateur FR/EN.
Les tests PostgreSQL de concurrence sont présents mais n'ont pas été exécutés
dans cet environnement, faute de `MODEL_USAGE_POSTGRES_URL` de test. Le test
SQLite de réservations simultanément engagées vérifie le refus du deuxième appel
et le règlement idempotent ; il ne remplace pas une recette des verrous PostgreSQL.

Le fournisseur est connecté dans Showcase. Le tarif EUR de `jev-1.13.0` est
enregistré : 0,037386505252 EUR par million de tokens d'entrée, sortie gratuite.
Il reprend le prix officiel de 0,042 USD/Mtok et la convention de conversion
déjà utilisée par le workspace : 0,890154886950 EUR/USD, observation du
21 octobre 2026, référence BCE. Le plafond reste à 2 000 EUR/mois, révision 2.

Après déploiement et nouvelle attestation, utiliser les cas synthétiques et
le parcours de nœud isolé dans [la recette Jev](../demo-runs/showcase-ecommerce/jev/README.md).
Ils produisent de vrais Runs rattachés au système Luma, sans sauvegarder le
graphe fourni dans r38, sans publier une version et sans envoyer de remboursement.
Vérifier l'identité du modèle, les distributions, les compteurs, le tarif et les
traces. Les deux options existantes `flow_workbench_v1` et `flow_publication_v1`
sont déjà ouvertes dans Showcase ; aucun nouveau drapeau n'est nécessaire.

Le raccordement au parcours principal est préparé dans
[`jev/main-flow-plan.json`](../demo-runs/showcase-ecommerce/jev/main-flow-plan.json) :
enquête → second avis Jev → Judge GPT-5 cité → validation humaine → action simulée.
Ce fichier n'est pas une publication ni une preuve d'exécution. La vérification
en service du 22 octobre trouve encore `ec2a15f4`, v10 publiée et le brouillon r38 ;
le transport Jev qualifié sous plafond n'y est pas encore disponible.

La composition utilise deux capacités génériques : les entrées explicites d'une
étape empêchent l'enveloppe de résultat du premier Judge d'être interprétée comme
les preuves du second ; les budgets locaux des Judges sont isolés par nœud dans
le Run ou la fenêtre de service. Les deux contrôles relisent les preuves du Run
via leurs sélecteurs publiés. Le plafond workspace de 2 000 EUR reste commun.
Le contrat GPT-5, ses citations requises et la porte humaine sont conservés.

La publication d'un candidat revu peut préserver intégralement le brouillon
serveur, y compris son mandat en cours d'édition. Elle reprend le mandat publié
et exige les empreintes de revue, de graphe et de contrat ainsi que les versions
attendues du brouillon et de la publication. Après qualification, basculer les
trois bindings et les deux applications Work avec leurs contrôles de concurrence.
Ne pas publier les pages en cours d'édition de « Pilotage SAV — équipe » : son
brouillon diffère de sa version servie. La procédure de raccordement conserve
les pages déjà publiées et ne renouvelle que leurs liens d'exécution.

Une mise à jour du code ne réalise aucune de ces mutations Luma. Livrer d'abord
la révision complète, renouveler l'attestation Usage sur des faits vérifiés par
l'opérateur, qualifier Jev, puis suivre la recette de publication et de bascule
Work. Ne pas désactiver le budget pour contourner un transport non qualifié.

Sources officielles : [API](https://docs.typesafe.ai/api/system-one),
[démarrage](https://docs.typesafe.ai/introduction/quickstart),
[Noul](https://docs.typesafe.ai/primitives/noul),
[Choice](https://docs.typesafe.ai/primitives/choice),
[Score](https://docs.typesafe.ai/primitives/score).
