# Luma — événements sur be3c7439, 20 octobre 2026

Recette API du System `f3ea83de-df89-45ec-8a85-c00d676b2713`, workspace
`agentium-showcase`, après déploiement annoncé de
`be3c7439920903a55b61beeef1067a9b85361e4a`. Le Run planifié confirme cette
révision dans `flow_evidence.runtime_revision`.

## Consentements et exécution planifiée

Les deux PATCH `execution_identity: "current_user"` réussissent avec HTTP 200 :

- hook permanent `f7f54df5-2af7-4114-bec0-af8b150126f9` ;
- planning permanent `1feaa7f7-ca60-408f-95f2-ddf4d182646c`.

Les délégations sont liées à la publication v10
`b8eb64d3-e417-41bf-898a-7b1ad232d64a`, empreinte
`77d4d521a3526fce8a25ee125ddf010976d637f2f2335d8afee98f1a4dbd09f0`.
Le défaut de verrou PostgreSQL rencontré sur la révision précédente ne bloque
plus ces consentements.

Le planning est activé pour un seul créneau de recette, le 20 octobre à
13 h 52 Europe/Paris. Le scheduler le déclenche à 13 h 52 min 27 s :
Run **`3d9cd35d-1f24-414c-897e-6a9cf2b05052`**, terminé avec succès.
Il porte `trigger: scheduler`, `initiated_by_user_id: null` et un
`execution_principal` délégué lié à v10. Les étapes terminées sont :

| Étape | Résultat |
| --- | --- |
| Lecture PostgreSQL | 23 lignes, dataset `ad025515-b350-4a5e-9093-60c37fdf67ed` |
| Préparation visuelle | 23 lignes, neuf colonnes, dataset `e94f27b6-7b95-4ab0-ac69-0ab6629e22a6` |
| Scoring | 23 lignes, champion SLA v5, dataset `40600ea2-00d5-461e-8b01-0bdc9dd32664` |

Le planning est immédiatement restauré à `0 8 * * 1-5`, Europe/Paris,
**désactivé**, `next_fire_at: null`. Aucun cron fréquent n'est laissé actif.

## Livraison signée et déduplication

La clé du hook permanent n'est pas disponible dans cette session. Aucune
rotation n'est effectuée. Un hook séparé de recette,
`eab3c429-8ed0-4584-8c3a-2ecb22e22c4f`, est créé en pause, avec délégation v10.
Sa clé reste uniquement en mémoire.

Pendant un passage borné du System en mode `live`, le hook de recette reçoit
une requête HMAC valide portant `{"claim_id":"RC-1043"}` :

1. HTTP 200, livraison `accepted`, résultat **`buffered`**, inbox
   `88d5483f-7f64-49d3-8fbf-82b8c3c1a566` ;
2. répétition identique : HTTP 200, `duplicate`, même inbox ;
3. hook remis en pause, puis supprimé par l'API produit (HTTP 204) ;
4. nouvelle livraison signée après suppression : HTTP 404 `not_found`.

La clé est effacée de la session et n'est pas enregistrée dans les preuves.
Le hook permanent conserve sa clé et reste désactivé. Le System est restauré
en `dry_run`.

Cette recette prouve l'authentification, la réception durable et la
déduplication. **Elle ne prouve pas un nouveau Run exécuté par webhook** :
le moteur déployé a rattaché la livraison au Run manuel déjà en revue humaine
`ebb99328-f345-4650-8cd6-5ddd0e465e21`. Aucun ancien Run n'est approuvé,
annulé ou repris pour permettre la recette. L'inbox et son checkpoint sont
conservés dans l'historique.

## Défaut de routage et correction produit

Le comportement antérieur choisit le dernier Run `hitl_pending` quand aucun
identifiant de corrélation n'est fourni. Même une clé inconnue retombe sur un
Run sans clé. Le contrat Luma v10 n'accepte pas de champ de corrélation ;
ajouter un champ hors contrat n'est pas une solution de recette.

La correction générique exige une corrélation explicite, exacte et unique
pour alimenter une inbox. Une nouvelle livraison sans correspondance suit
le chemin normal de création de Run. Les validations humaines restent
inchangées, le workspace et le System sont vérifiés, et une ambiguïté est
refusée. Le contrat d'entrée publié est vérifié avant toute écriture inbox.
Un Run ciblé doit porter la même version, empreinte, contrat et entrée publiés ;
une nouvelle publication ne peut pas élargir l'autorité d'un ancien Run.
La mémoire anonyme historique `_default` n'est plus injectée dans un autre
dossier ; ses enregistrements restent conservés.

Ce correctif est testé localement après cette recette ; il n'est pas inclus
dans le binaire `be3c7439` testé ici. Il ne demande aucune modification du
Flow ni du contrat Luma. Voir la
[note de compatibilité du routage](../agentium-flow-trigger-operations.md#new-work-versus-evidence-for-a-waiting-run).
Après déploiement, refaire une livraison signée bornée et vérifier un nouveau
Run délégué jusqu'à sa validation humaine, sans approuver sa proposition.

La suite locale termine avec **103 tests réussis** : corrélation absente,
différente, exacte ou ambiguë, isolation workspace/System, mémoire historique,
contrat d'entrée avant inbox, ancienne publication incompatible, déduplication,
mode simulation, garde humaine et délégations. Ces tests conservent les
fournisseurs substitués ; ils ne remplacent pas cette future recette live.

## État conservé et activation ultérieure

Comparaison JSON stricte avant/après : brouillon Flow **r37** inchangé,
publication **v10** inchangée, brouillon Work **r11** inchangé. Le planning
et le hook permanent sont en pause ; le hook temporaire est absent.
Le compte de recette conserve ses délégations explicites sur v10.
Aucune migration, option globale ou notification sortante n'est modifiée.

Pour activer ensuite le hook permanent, le producteur doit encore disposer
de sa clé d'origine. S'il la possède, cette clé reste valide et aucune rotation
n'est nécessaire. Si elle est perdue, une rotation doit être coordonnée avec
la mise à jour du producteur avant activation ; le produit ne permet pas de
relire la clé existante. Une future publication du Flow demandera aussi un
nouveau consentement des délégations.

Preuves privées :
`/workspace/scratch/luma-postdeploy-be3c7439/events/`.
La session authentifiée est fermée. Cette recette est effectuée via les API
en service ; elle ne revendique pas une nouvelle validation visuelle des panneaux.
