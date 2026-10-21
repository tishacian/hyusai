# Lots 8b et 8c — état de livraison au 21 octobre 2026

Ce bilan distingue les modifications livrées dans le checkout, les contrôles effectivement exécutés et la recette encore nécessaire. Il ne vaut ni déploiement ni validation utilisateur du lot 9.

## Lot 8b — usages quotidiens

| Critère du plan | Implémentation et preuve disponible |
| --- | --- |
| Inscription : e-mail envoyé, non envoyé ou état inconnu | La branche reconstruite fournit les textes FR/EN, les états explicites, la sortie administrateur et le renvoi sans création d'un deuxième compte. L'absence du champ `verification_email_sent` ne confirme pas l'envoi. L'API `/auth/signup/resend-verification` sélectionne un compte activé non vérifié. Les tests du renvoi existent dans `backend/app/tests/api/test_auth_signup.py` ; ils n'ont pas été exécutés avec succès par cet agent pendant cette passe. |
| Aide sans perte de tâche | Les points d'entrée de la barre de titre, de Work et des liens contextuels ouvrent le panneau sur place, y compris à 320 px. Le panneau expose la source sous forme d'un lien vers le guide complet ; celui-ci s'ouvre séparément. Les tests de fermeture, restitution du focus et ouverture sur écran étroit passent. Aucune recette humaine de conservation d'une saisie sur tous les objets n'a été effectuée. |
| Conversation : import partiel explicite | Chaque fichier refusé reste visible avec son nom et le motif fourni. Les fichiers en file d'attente sont séparés des sources effectivement indexées. Les résultats agrégés seuls ne créent plus de fausses sources. L'API conserve le nom d'origine des fichiers refusés et n'expose pas leur chemin temporaire comme identifiant de document. Le texte du composeur reste en place. Les écritures du contexte propagent les erreurs au composant. Tests de classification et de composant réussis. |
| Capture : relecture et sources avant publication | La publication est désactivée tant que la proposition n'est pas acceptée. Le moteur existant conserve les sources et impose déjà l'acceptation ; ses tests passent. Le contexte du chat publié utilise une écriture stricte. Les préférences de présentation utilisent une issue explicite avec vérification par relecture en cas de résultat inconnu. La persistance complète des preuves et la reprise d'une capture réelle restent à recetter sur la pile de recette. |
| Veille : échec distinct du vide | La liste conserve l'enveloppe des droits même quand elle ne contient aucun système. Un échec laisse le droit de créer inconnu. News Lab affiche les états de lecture avant ses données ; une erreur ne produit plus un tableau vide. Les réponses tardives d'un autre workspace sont ignorées. Tests du modèle de vue réussis ; scénarios Playwright d'erreurs ajoutés mais non exécutés ici. |
| Veille : source, cible et cadence séparées | La cadence est une propriété de chaque source, modifiée via une route dédiée validant les bornes et le workspace. Cette modification ne lance pas la veille. Le planificateur respecte cette cadence ; un lancement manuel reste explicite. Les résultats montrent la source et la pertinence, ou leur indisponibilité. Tests de frontière de cadence, isolation et absence de collecte lors de la modification réussis. |

## Lot 8c — applications spécialisées

Les écrans Client 360, ITSD et Achats embarquent une fiche FR/EN : objectif, audience, sources, fonctions, configuration, extensions nécessitant du code et limites. La fiche Client 360 annonce la dépendance spécifique à ANDRITZ ; une seconde configuration nécessite de revoir les contrats de données, les règles métier et les droits. Les écrans ITSD annoncent la simulation de l'annuaire et des notifications avant l'action, ou l'absence d'exécution depuis le catalogue. Les décisions existantes des lots 2a restent régies par leurs droits et leurs reçus.

**Version : configuration publiée et service technique sont distincts.** La fiche lit le catalogue autorisé `/api/v1/work` pour le workspace courant. Le champ « Configuration publiée de l’application » affiche le `release_number` et le canal réellement renvoyés pour l’application : `client360`, `nawa` ou `pr-to-po`. L’identité immutable de release est conservée dans le composant. Un résultat absent, ambigu, incomplet, refusé ou indisponible affiche explicitement « Version de l’application inconnue ». Une réponse d’un ancien workspace ne peut pas attribuer sa version au nouveau.

Le champ séparé « Révision du service » / « Service revision » provient de `/api/v1/build-info` et n’affiche un SHA court que si le serveur fournit une révision vérifiée ; sinon il indique « Révision non confirmée ». Ni ce SHA ni la version du renderer ne remplacent une version applicative manquante. La version affichée décrit la configuration Experience publiée, pas une nouvelle certification du code natif ou de la version de chaque Flow exécuté. Les workspaces utilisant les écrans natifs sans entrée Work publiée gardent honnêtement une version d’application inconnue.

Pour Client 360 :

- La confirmation de relecture porte sur le destinataire, l'objet et le corps exacts. Une modification invalide la confirmation. Le serveur refuse un envoi sans `reviewed: true` avant tout effet externe.
- Le serveur et le fil distinguent « accepté pour envoi » de « envoi déclaré ». Aucun de ces résultats n'atteste la réception. Les réponses portent `receipt_confirmed: false`.
- Une acceptation SMTP déjà enregistrée ne provoque pas de second envoi lors d'un nouvel appel ; le brouillon est verrouillé pendant l'opération.
- En cas d'issue inconnue, l'interface bloque la répétition et propose une lecture de vérification. Cela ne constitue pas une preuve de réception ni une garantie transactionnelle entre le serveur SMTP et la base.

## Contrôles effectivement exécutés

| Commande / périmètre | Résultat constaté |
| --- | --- |
| `FLOW_UNIT_FILTER=chat-upload-outcome,chat-workspace.component,client360-page.component,help-panel.component,capture-published-chat,capture-engine,intelligence.vm npm run test:unit` depuis `frontend-ng` | 7 fichiers de tests réussis, 0 échec. Journal local : `/tmp/agentium-daily-unit2.log`. Le compteur du runner est un nombre de fichiers, pas un nombre d'assertions. |
| `../.venv/bin/python -m pytest app/tests/services/test_intelligence_cadence.py app/tests/services/test_client360_pdr.py app/tests/api/test_intelligence_api.py app/tests/api/test_client360_authorization_inventory.py -q -k 'cadence or timeline or send_mail_draft or authorization'` depuis `backend` | 8 tests réussis, 56 non sélectionnés. Journal local : `/tmp/agentium-daily-pytest3.log`. |
| `../.venv/bin/python -m pytest app/tests/api/test_daily_usage_contracts.py -q` depuis `backend` | 2 tests réussis : refus d'envoi sans relecture et identification d'un fichier rejeté. Journal local : `/tmp/agentium-daily-contracts.log`. |
| Test direct local `specialized-app-version.spec.ts`, compilé avec esbuild puis exécuté par `node --test` | 1 fichier de tests réussi : sélection de la release propre à chacune des trois applications, refus des preuves incomplètes/ambiguës et absence de substitution par le SHA technique. Exécuté après le contrôle TypeScript ciblé ci-dessous ; intégration du fichier au runner global demandée à l’agent principal. |
| `npx tsc --noEmit -p tsconfig.app.json` depuis `frontend-ng` | Réussi au moment du contrôle ciblé ; journal local vide `/tmp/agentium-daily-tsc2.log`. La compilation Angular finale du checkout partagé est centralisée par l'agent principal. |

Les tests unitaires et les appels directs de fonctions d'API utilisent des doubles pour les systèmes externes. Ils ne prouvent pas le comportement réel de Keycloak, SMTP, du stockage documentaire ou du navigateur.

## Recette et limites non masquées

Le navigateur **n'a pas été testé** par cet agent. Le démarrage local Angular sur `127.0.0.1:4381` a échoué avec `listen EPERM`. Une nouvelle tentative avec permission réseau est restée en attente puis a été interrompue ; elle n'a produit aucun résultat Playwright. Aucun serveur 4381 ne tournait lors du bilan. Les cas de `32-intelligence-watch-mocked.spec.ts` sont prêts mais ne sont pas comptés comme réussis.

Restent à constater sur une pile déployée : le cycle inscription avec e-mail coupé puis rétabli sans second compte ; l'aide avec saisie en cours ; une capture complète et ses sources après reprise ; les trois parcours spécialisés avec leurs droits réels ; les simulations clairement comprises par les utilisateurs ; la distinction acceptation/déclaration/réception du mail. Les seuils de trois collaborateurs du plan, les observations à 320 px, au clavier et avec lecteur d'écran ne sont pas revendiqués ici. Le bilan global de recette et de compilation doit être lu séparément.
