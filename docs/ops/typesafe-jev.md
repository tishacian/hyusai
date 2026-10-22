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
seraient également refusés. Cette attestation ne qualifie pas TypeSafe pour les
plafonds bloquants.

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
retourné par sa découverte. Ne pas présenter un identifiant absent comme
disponible pour ce compte. Aucun appel d'inférence n'a été effectué et la clé
n'a pas été enregistrée dans le dépôt ou dans une configuration locale.

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

**Les plafonds monétaires bloquants ne sont pas encore qualifiés pour TypeSafe.**
L'API native n'expose pas le même contrat de borne des tokens que les transports
texte qualifiés. Avec un plafond bloquant applicable, l'admission refuse l'appel
avant envoi (`USAGE_TRANSPORT_UNQUALIFIED`). La connexion et la découverte des
modèles restent utilisables. Ne pas désactiver un plafond existant pour contourner
ce refus ; la qualification du transport budgétaire nécessite un travail distinct.

Les limites du lot Judge restent appliquées avant appel et réconciliées ensuite,
mais ne constituent pas une garantie de plafond monétaire fournisseur.
Pour ce transport, `max_output_tokens` est une provision de réservation locale,
pas un paramètre transmis à l'API Jev pour limiter sa sortie.

## Recette et Luma

La recette locale utilise un transport simulé : schémas natifs, erreurs et
masquage, absence de retries, accès aux clés, catalogue, refus en chat, refus des
contrats de citation incompatibles, persistance du Judge, usage et réutilisation
idempotente. Elle ne prouve pas la qualité métier, la latence ou le coût d'un
appel réel Jev.

Pour la recette distante, il faut une clé TypeSafe avec accès au modèle et le
déploiement de cette livraison. Dans un périmètre autorisant les appels sans
plafond bloquant, exécuter d'abord un cas synthétique, vérifier l'identité du
modèle, ses compteurs, son tarif et les traces, puis comparer sur un corpus revu.

Cette livraison ne change aucun Flow, brouillon, publication, modèle ou budget de
Luma. Son juge actuel exige des citations et continue d'utiliser GPT-5. Un nœud
Jev peut compléter un futur brouillon pour du triage ou du scoring typé, avec ses
propres questions. Remplacer le juge actuel nécessite une décision explicite sur
le contrat de preuves ; le plafond Showcase de 2 000 EUR reste inchangé.

Sources officielles : [API](https://docs.typesafe.ai/api/system-one),
[démarrage](https://docs.typesafe.ai/introduction/quickstart),
[Noul](https://docs.typesafe.ai/primitives/noul),
[Choice](https://docs.typesafe.ai/primitives/choice),
[Score](https://docs.typesafe.ai/primitives/score).
