# Adaptateur de narration externe

> Adaptateur bêta inactif : narration est différée à la demande de l’utilisateur. Le flag serveur/workspace `narration_enabled` reste fermé. Ce protocole ne prouve aucun raccordement au moteur réel.


`narration_run_v1` appelle `run_narration(payload, ctx)` dans le moteur de Runs.
L'adaptateur ne contient pas le moteur de narration et ne simule aucun résultat.
Sans `NARRATION_ENDPOINT`, il refuse avec `NARRATION_ENDPOINT_UNCONFIGURED`.
Le moteur, son endpoint et ses droits ObjectStore restent à fournir pour une
qualification réelle. Les tests HTTP locaux ne constituent pas cette qualification.

## Configuration et entrée

Le graphe publié fournit `_narration = {node_id, narration}`. `narration` contient
`engine_revision`, `source_ref` facultatif, `options` JSON borné à 16 Kio et
`budgets`. La source effective est `payload.asset_ref` ou `source_ref` ; deux
références différentes sont refusées. Le contexte serveur doit porter un vrai
Run dans le workspace. Les droits natifs collection/Run sont vérifiés pour
l'utilisateur ; une identité planifiée ne peut lire que la source persistée dans
l'entrée du Run ou un asset produit par ce même Run.

L'asset source A1 porte `objects` et un inventaire immuable `units` :

```json
{
  "units": [
    {"id": "page-1", "kind": "page", "object_key": "workspaces/WS/original/document.pdf", "sha256": "SHA256_DE_L_OBJET", "page_number": 1},
    {"id": "image-1", "kind": "image", "object_key": "workspaces/WS/original/image.png", "sha256": "SHA256_DE_L_OBJET"}
  ]
}
```

Chaque objet doit exister dans le manifeste et ses octets doivent correspondre à
son empreinte. Les limites par défaut sont 500 pages et 500 images, 64 Mio de
sortie, 256 Kio par unité, 2 000 requêtes et 900 secondes. Le schéma limite chaque
type à 500 unités, même si une configuration serveur supérieure existe. Les
plafonds serveur peuvent réduire ces valeurs ; un contrat de service réduit
aussi temps, tokens et coût. Le délai est persisté et ne repart pas à zéro lors
d'une reprise. Une réservation de coût non mesuré ne devient pas une facture à
zéro. Le gateway doit appliquer les plafonds transmis avant ses appels facturés.

## Protocole gateway v1

`NARRATION_ENDPOINT=https://gateway.example/v1` est une base administrée, sans
identifiants, query ou fragment. `NARRATION_ALLOWED_HOSTS` contient les hôtes
exacts séparés par des virgules. TLS vérifie le certificat, les redirections et
proxys d'environnement sont désactivés. Toutes les adresses DNS sont contrôlées,
puis l'adresse de connexion est épinglée avec le nom TLS d'origine. Une adresse
privée exige aussi sa présence explicite dans la liste ; loopback, link-local,
multicast, adresses réservées et non spécifiées sont refusées même listées.

1. `POST /jobs` avec `Idempotency-Key: <WorkspaceJob.id>` :
   `{protocol_version:1, source_ref, units, engine_revision, options, budgets}`.
   Le gateway doit retourner la même tâche pour cette clé après un timeout ou
   crash. Il reçoit des références ObjectStore, sans secret ni URL signée : ses
   propres droits de lecture sur ce stockage doivent être configurés séparément.
2. `GET /jobs/{job_id}?cursor=<next_cursor>` renvoie des pages de résultats.
3. `DELETE /jobs/{job_id}` tente une annulation, au plus une requête de deux
   secondes après un échec terminal/une annulation. Cette tentative consomme aussi
   le budget de requêtes ; une annulation distante n'est jamais déclarée confirmée
   quand elle est indisponible ou que ce budget est épuisé.

Chaque réponse POST/GET suit ce schéma fermé :

```json
{
  "protocol_version": 1,
  "job_id": "remote_job_123",
  "engine_revision": "revision_exacte_demandee",
  "source_digest": "SHA256_ASSET_SOURCE",
  "status": "running",
  "units": [{
    "id": "page-1",
    "status": "completed",
    "content_base64": "VGV4dGUgZXhwbGljaXRl",
    "sha256": "SHA256_DES_OCTETS_DECODES",
    "mime_type": "text/plain"
  }],
  "next_cursor": "page2",
  "cost_usd": null,
  "tokens": null
}
```

Les statuts sont `queued`, `running`, `completed`, `failed`, `cancelled`. Une
unité échouée ne porte que `id` et `status:failed`. Au plus 100 unités et 8 Mio
par réponse sont admis. Les compteurs coût/tokens sont cumulatifs et ne doivent
pas diminuer. `null` ou absence signifie non mesuré ; un zéro explicite est une
mesure. Un résultat final doit utiliser `completed`, sans curseur restant, avec
toutes les unités attendues disponibles. Les réponses partielles restent
`running`. Les URLs, clés de sortie et champs inconnus sont refusés.

## Checkpoints et livraison

Le WorkspaceJob est créé durablement avant POST ; chaque requête est débitée
avant son émission. `running` ne vient que d'un état retourné par le gateway.
Les octets décodés sont bornés, hachés puis écrits une seule fois sous
`workspaces/<id>/narration/<job-id>/<sha256>`. Le checkpoint d'une unité est validé
après cette écriture. Rejouer la même unité est idempotent ; une autre empreinte
pour le même identifiant échoue. Un verrou par tâche empêche deux workers actifs.

Un problème réseau conserve la tâche et le curseur pour reprise avec la même
clé. Une modification source/options/révision/gateway sous la même identité
Run+nœud est refusée. L'annulation asyncio est transmise au worker et persistée.
Les erreurs durables utilisent uniquement des codes fermés, sans traces serveur.

La couverture sépare pages et images, avec `expected`, `processed`, `failed`,
`missing`. Aucune page absente n'est comptée comme traitée. Seul le succès complet
produit un asset A1 `document_set`, lié à la source et au Run, avec preuves texte
lisibles via leurs objets. `confidence` reste `null` et la disposition est
`review`. Cette réussite technique ne constitue pas une approbation humaine ou
une qualification de qualité ; les contrats/reçus appliquent ces contrôles.

## Validation disponible

`app/tests/services/test_narration.py` utilise un transport HTTP mock, un vrai
ledger SQL et le vrai ObjectStore local. Il couvre 500 unités paginées, les
octets/empreintes, la reprise après timeout, les budgets, l'annulation, les
workers concurrents, la portée tenant, les sources modifiées et les protections
réseau. Les unités de test ne sont pas 500 pages interprétées par un moteur
externe. Aucune performance, couverture OCR, fidélité sémantique ou facture
production n'est revendiquée sans endpoint réel qualifié.
