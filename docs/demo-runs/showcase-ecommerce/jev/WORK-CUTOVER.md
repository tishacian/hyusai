# Bascule Work vers le Flow avec Jev

Ce document décrit une **bascule préparée, non effectuée**. Il complète la
[publication candidate du Flow](MAIN-FLOW.md) après déploiement du code et
qualification réelle du transport Jev. Les brouillons utilisateur restent
inchangés pendant toute la séquence.

## État constaté le 22 octobre 2026 à 21:13 UTC

Le système `f3ea83de-df89-45ec-8a85-c00d676b2713` publie encore la v10
`b8eb64d3-e417-41bf-898a-7b1ad232d64a`, empreinte `77d4d521…`.
Les trois bindings pointent sur cette version :

| Binding | Entrée conservée |
| --- | --- |
| `showcase.claims.investigate` | `source.request` |
| `showcase.claims.refresh_queue` | `source.queue` |
| `showcase.claims.forecast` | `source.forecast` |

Leur politique reste `confirm`, avec `on_unavailable: unavailable`.

| Application | Canal | Release déployée | Brouillon à préserver |
| --- | --- | --- | --- |
| Réclamations — `4c93ae4b-f2de-438d-b781-bb69a4cb962c` | `live` | 9 — `a82202e4-6116-4267-9bc3-e14923684ba7` | r11, `c3fc5787…` |
| Pilotage SAV — équipe — `20e33fa4-1653-46e5-b92e-ace7c10fe96d` | `pilot` | 2 — `28f1857d-5e8e-453d-a5a4-fefe57436739` | r13, `cf278e49…` |

Le brouillon Réclamations correspond au contenu déployé. Le brouillon Pilotage
**diffère** du contenu déployé (`07824e27…`). Créer une release depuis ce dernier
brouillon publierait donc aussi des changements utilisateur sans rapport avec
Jev. Utiliser la fonction générique de renouvellement des bindings d'une release
existante, pour les deux applications.

Les anciennes releases restent exécutables sur leurs instantanés historiques :
elles ne sont pas réécrites lorsque le système publie une nouvelle version.
La seule publication du Flow ne suffit donc pas à faire utiliser Jev dans Work.

## Lectures préalables

Toutes les routes ci-dessous commencent par `/api/v1`. Relire, avant toute
mutation, `/systems/{system_id}/flow-state`, `/system-bindings`, les détails
`/experiences/{id}`, leurs `/releases`, leurs déploiements et le sous-objet
`settings.ecommerce_claims.triage` du workspace Showcase. Comparer au relevé
préparé et conserver les preuves avant/après sans jeton ni réglages secrets.

Vérifier la nouvelle publication candidate, les essais Jev, le budget, la
révision Usage attestée et l'absence d'une édition concurrente pendant la
bascule. La grille Jev reste exploratoire. Ne pas démarrer de nouveau traitement
depuis Work avant la fin des vérifications. Les délégations webhook/planning
restent en pause ; ne pas les réactiver pour cette bascule.

## Ordre de bascule

1. Après publication du candidat, récupérer **l'ID et l'empreinte retournés par
   le serveur**, sans supposer un numéro de version. Vérifier que le Flow
   brouillon r38 reste identique, y compris sa base et ses métadonnées.
2. Pour chacun des trois bindings, comparer une nouvelle lecture au relevé,
   puis `PATCH /system-bindings/{key}` avec seulement
   `{"published_flow_version_id":"<nouvelle version>"}`. Relire les bindings
   et leur résolution : même système, même entrée, mêmes schémas et politiques,
   nouvelle version/empreinte, état `ok`. Ces patches n'ont pas de CAS atomique ;
   interrompre la bascule si un autre éditeur intervient.
3. Modifier uniquement `settings.ecommerce_claims.triage.scoring_version_id`
   et `scoring_flow_sha256`. Conserver `scoring_system_id`, `model_id`,
   `model_version`, `prediction_contract` et tout le reste. L'API actuelle est
   `PATCH /auth/workspaces/agentium-showcase` et remplace les réglages publics :
   relire ces réglages complets **en mémoire**, comparer le triage juste avant
   écriture, copier l'objet puis ne changer que les deux champs. Ne pas envoyer
   un fragment qui supprimerait les autres réglages. Le serveur garde les
   secrets masqués ; ne pas les exporter. Cette étape n'a pas non plus de CAS.
4. Pour chaque application, prendre l'ID de la release réellement déployée sur
   son canal et appeler :

   `GET /experiences/{id}/releases/{source_release_id}/rebind-ready-check`

   Exiger `ready: true`, aucune erreur et les nouveaux bindings attendus.
   Examiner les avertissements. La validation porte sur **le contenu publié
   choisi**, sa langue, son audience et ses contrats, pas sur le brouillon.
5. Appeler `POST /experiences/{id}/releases/{source_release_id}/rebind` avec :

   ```json
   {
     "notes": "Actualiser les bindings vers le Flow Jev qualifié ; conserver le contenu publié et le brouillon utilisateur.",
     "expected_source_release_sha256": "<source_release_sha256 de la revue>",
     "expected_content_sha256": "<source_content_sha256 de la revue>",
     "expected_experience_updated_at": "<experience_updated_at de la revue>",
     "expected_bindings_sha256": "<bindings_sha256 de la revue>"
   }
   ```

   Cette fonction conserve pages, empreinte de contenu, identité, audience,
   langues, thème et version de rendu de la release source. Elle crée une
   nouvelle release immutable avec les bindings revus ; elle ne déploie rien
   et ne lit ni n'écrit le brouillon. Toute différence de précondition exige
   une nouvelle revue. Une répétition strictement identique retourne la même
   release, sans doublon.
6. Comparer la nouvelle release à sa source : seuls l'identifiant, le numéro,
   les métadonnées de création et les bindings doivent différer. Relire le
   déploiement et vérifier qu'il est toujours celui attendu, puis
   `POST /experiences/{id}/deployments` :

   ```json
   {
     "channel": "<live ou pilot, inchangé>",
     "release_id": "<nouvelle release>",
     "expected_current_release_id": "<release source encore déployée>",
     "expected_deployment_updated_at": "<horodatage frais du déploiement>",
     "audience": {"roles": ["<audience actuelle exacte>"]}
   }
   ```

   L'audience ci-dessus est illustrative : recopier l'objet réel complet, y
   compris ses groupes. Pour `live`, il doit correspondre à l'audience figée
   de la release ; pour `pilot`, il peut être plus restreint. Ne jamais élargir
   cette audience au cours de la bascule.

## Vérifications et reprise

Comparer les deux brouillons **champ par champ**, y compris auteurs, révisions,
horodatages et listes de bindings. Les déploiements doivent viser leurs nouvelles
releases, sans changement de canal/audience. Les champions et le shadow ne
changent pas. Vérifier Réclamations, l'actualisation de file et Charge et capacité,
puis effectuer la recette métier Jev décrite dans [MAIN-FLOW.md](MAIN-FLOW.md).

Les écritures Flow, bindings, triage et déploiements ne forment pas une transaction
unique. En cas d'échec, arrêter les nouveaux essais et conserver le dernier état
connu ; ne pas restaurer des brouillons ni rejouer des préconditions inventées.
Les anciennes releases sont immuables et peuvent être redéployées avec les CAS
de déploiement existants. Le retour global du Flow et du triage demande sa propre
revue des références courantes. Les anciens Runs gardent leurs traces et leurs
versions ; ne pas les présenter comme des exécutions Jev.
