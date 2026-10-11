# Spec - Chat Deep Search Output Contract

Date: 2026-06-04
Surface cible: Chat / Quick Ask / Deep Search
Hors perimetre: System Knowledge Capture
Composants principaux:
- `frontend-ng/src/app/features/chat/chat-panel.component.ts`
- `backend/app/api/v1/endpoints/chat.py`
- `backend/app/services/worker_deep_retrieval.py`
- `backend/app/core/config.py`

## Objectif

Clarifier le contrat produit de Deep Search dans le chat. Deep Search est un raffinement asynchrone d'une reponse de chat, pas un ecran Knowledge Capture et pas un simple visualiseur de passages.

Quand l'utilisateur demande une recherche profonde apres une reponse longue, le resultat attendu est une nouvelle reponse assistant detaillee, structuree et sourcee, dans le meme fil de conversation.

## Constat Code Actuel

- Le suivi Deep Search existe dans `ChatPanelComponent`.
- Le backend produit un champ `answer` dans `worker_deep_retrieval.py`.
- Le polling frontend peut promouvoir `deepAnswer` dans le contenu du message quand le job est termine.
- La config active deja l'auto Deep Search par defaut:
  - `rag_auto_deep_retrieval_enabled = True`;
  - `rag_auto_deep_retrieval_dense_unscoped = True`;
  - `rag_auto_deep_retrieval_min_confidence = 0.45`.
- `_should_queue_auto_deep_retrieval()` peut declencher un job si:
  - la reponse rapide recommande un deep retrieval;
  - le retrieval est degrade: deadline, worker timeout/error, dense corpus guardrail;
  - le corpus dense non scope utilise la politique `fast_scoped_dense_auto`;
  - aucun job deep n'est deja attache.
- Le declenchement auto ne se fait pas si la requete est deja explicitement `deep_retrieval` ou `latency_profile=deep`.

## Probleme UX

Le Deep Search final apparait encore trop souvent comme un panneau technique: statut, passages, sources, details. Ce n'est pas ce que l'utilisateur attend apres une demande comme "essaye une recherche profonde".

Si le message precedent etait une synthese en plusieurs points, le Deep Search doit produire une reponse finale de meme nature: plus precise, plus sourcee, potentiellement plus longue, mais lisible comme une reponse assistant normale.

## Contrat De Sortie

Pendant l'execution:
- afficher progression, stage, job id court et sources preview;
- garder le message compact;
- indiquer que le job continue cote serveur.

A completion:
- remplacer le placeholder "Deep Search en cours" par la reponse synthetisee;
- afficher la reponse dans le layout standard d'une reponse assistant:
  - paragraphes;
  - listes en plusieurs points si pertinent;
  - citations et sources visibles;
  - actions de feedback/copy/preview identiques aux autres reponses;
- conserver le bandeau de statut en version compacte;
- garder les passages bruts dans `Details` uniquement.

En fallback:
- si la synthese LLM echoue, afficher un fallback extractif clair;
- le fallback reste dans le layout de reponse, pas seulement dans le panneau details.

## Declenchement Automatique

Deep Search peut etre lance de deux facons:
- manuel: bouton "Approfondir" ou demande utilisateur explicite;
- automatique: si Quick Ask detecte une reponse degradee, peu fiable ou limitee par la politique dense.

Regles UX:
- le declenchement automatique doit etre visible mais discret;
- message: "Recherche approfondie lancee pour affiner cette reponse";
- jamais de demande de scope utilisateur;
- pas de multiplication de jobs pour la meme reponse;
- auto et manuel ont exactement le meme contrat de sortie.

## Prompt De Synthese

Le prompt de synthese Deep Search doit recevoir assez de contexte pour respecter la forme attendue:
- question utilisateur;
- reponse rapide precedente si disponible;
- sources/premiers passages;
- instruction: produire une reponse finale au moins aussi structuree que la reponse precedente quand celle-ci etait une synthese multi-points.

Le prompt ne doit pas demander une simple liste d'extraits sauf fallback explicite.

## Acceptance

- Une demande "fais une deep search" ne se termine jamais par une simple liste de passages.
- Le resultat final est lisible comme une nouvelle reponse assistant, avec sources.
- Le resultat reste lisible apres reload de session.
- Les details du job restent disponibles mais secondaires.
- Deep Search auto et manuel rendent le meme type de bloc final.
- Aucun modele/provider n'est visible en mode demo.
