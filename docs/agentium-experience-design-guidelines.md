# Agentium — guidelines de composition et d’interaction

**Référence de conception proposée · 17 octobre 2026**

Ce document traduit la critique du parcours Showcase en règles génériques pour le produit. Il complète le [chrome officiel](agentium-ui-chrome.md), les [principes de navigation](mental-model.md) et l’[audit illustré](demo-runs/showcase-ecommerce/DESIGN-AUDIT-2026-10-17.md). Il ne décrit pas une refonte déjà implémentée ou déployée. Les exemples Luma illustrent les règles ; aucune règle de rendu ne doit dépendre du nom Luma ou d’un workspace particulier.

## 1. La qualité recherchée

L’interface doit donner une impression de maîtrise : **je sais où je suis, je comprends ce qui compte, je vois ce qui va se passer et je retrouve le résultat**. Une composition maîtrisée rend les capacités plus crédibles et les actions plus faciles à utiliser.

Les défauts actuels proviennent de quatre décalages :

| Décalage | Effet perçu | Travail de design |
|---|---|---|
| Un composant technique devient automatiquement une carte | Page administrative, monotone et longue | Regrouper par tâche et unité de sens. |
| Tout reçoit presque le même poids | Hésitation, bruit, absence de point d’entrée | Faire correspondre importance, emplacement et contraste. |
| L’utilisateur doit combiner des états et retrouver son contexte | Produit exigeant, manque de fluidité et de confiance | État effectif, navigation contextualisée, résultats persistants. |
| Une fonctionnalité est rendue par ses paramètres | Formulaire expert difficile à prendre en main | Intention, choix compatibles, aperçu et configuration avancée. |

La beauté recherchée repose sur une hiérarchie claire, des proportions adaptées, un rythme régulier, une interaction prévisible et un vocabulaire lisible. Ajouter une ombre, une couleur ou une animation sans résoudre ces points apporterait peu.

## 2. Partir d’une tâche, puis choisir une composition

Avant de dessiner un écran, écrire : **« Pour [rôle], cet écran permet de [tâche], à partir de [informations], et aboutit à [résultat vérifiable]. »**

Exemple : « Pour le conseiller SAV, examiner une proposition de résolution à partir de la commande, des pièces et du contrôle qualité, puis autoriser une action explicite et retrouver son reçu. »

Si la phrase comporte plusieurs tâches sans lien immédiat, séparer les niveaux ou les vues. Un écran peut rester riche : sa progression doit être évidente.

Choisir un archétype réutilisable plutôt qu’une grille de cartes par défaut :

| Archétype | Composition principale | Applications possibles |
|---|---|---|
| Traiter une file | Sélection → détail du dossier → décision | SAV, revues, validations, exceptions. |
| Comprendre un objet | Identité et état → synthèse → facettes et preuves | Dataset, modèle, collection, connecteur. |
| Composer un processus | Parcours → sélection → inspecteur contextuel | Flow, préparation de données, règles. |
| Piloter une activité | Périmètre → résultat → évolution → preuves | Impact, charge, exploitation. |
| Configurer une capacité | Intention → choix → aperçu/test → enregistrement | Connexion, Judge, événement, publication. |

Ces archétypes partagent le chrome, les objets et les composants. Work conserve une enveloppe orientée métier ; il n’a pas à exposer la navigation d’administration du Cockpit.

## 3. Composer une page avec une hiérarchie réelle

Chaque vue comporte trois niveaux, avec des zones stables :

1. **Contexte** : objet, nom, version pertinente, état effectif, retour et périmètre.
2. **Travail** : contenu nécessaire pour comprendre, comparer ou décider.
3. **Approfondissement** : provenance détaillée, diagnostics, réglages et opérations secondaires.

Le premier écran utile doit donner accès à la situation, à son éventuelle réserve et à la prochaine action. Il n’a pas à contenir toutes les informations.

Une vue de consultation présente des faits, valeurs et états comme du contenu. Elle ne doit pas ressembler à un formulaire désactivé. Passer en modification révèle les champs, l’état de sauvegarde et l’effet de l’enregistrement. Les filtres de consultation restent utilisables sans ouvrir cet éditeur.

### Regroupement

- Réunir titre, fraîcheur, action, état et résultat d’une même tâche.
- Utiliser une carte lorsqu’un ensemble est autonome, sélectionnable ou mérite un regroupement perceptible. Une phrase d’aide ou un bouton isolé n’en justifie pas une.
- Préférer espace, alignement et séparateurs aux cadres imbriqués lorsque la relation est déjà claire.
- Relier visuellement une valeur à son unité, son effectif, sa période et sa réserve.
- Présenter côte à côte les éléments qu’il faut comparer ; éviter de les répartir dans des onglets distincts.

### Densité

La densité dépend de la tâche. Une table de travail peut être compacte ; une décision exige une lecture confortable ; un canvas doit bénéficier de l’espace disponible. Un formulaire court doit conserver une largeur de lecture adaptée au lieu de s’étirer sur tout l’écran.

Éviter les deux extrêmes observés : un grand panneau presque vide et un canvas entouré de commandes qui ne laisse plus lire les nodes. Chaque zone occupée doit servir soit le travail actuel, soit l’orientation indispensable.

**Contrôle designer :** retirer mentalement bordures et fonds. Le regroupement reste-t-il compréhensible ? Si tout se confond, travailler d’abord les titres, espacements, alignements et priorités.

## 4. Donner une fonction stable à chaque action

| Type | Emplacement | Traitement et libellé |
|---|---|---|
| Navigation | Onglets, fil de contexte, liens d’objet | Une destination lisible ; ne pas la confondre avec un lancement d’action. |
| Action de page | Zone d’actions de l’en-tête, si elle concerne toute la page | Conséquence explicite : « Modifier le parcours », « Créer une version ». |
| Action locale | Près du résultat ou de l’objet concerné | « Actualiser la prévision » avec la prévision ; « Voir l’extrait » avec la citation. |
| Confirmation de décision | Après la synthèse des faits et réserves, ou dans un panneau associé | Action précise : « Autoriser l’ouverture de l’enquête ». |
| Configuration secondaire | Menu ou panneau contextualisé | Accessible sans concurrencer la tâche de consultation. |
| Action destructive | Menu distinct ou zone dédiée à l’administration | Nom de l’objet et conséquence clairs ; confirmation proportionnée à l’irréversibilité. |

Respecter la convention existante : **une action pleine dominante dans la surface active**, les autres utilisant les variantes secondaires. Une page de consultation peut n’avoir aucune action pleine. Des lignes ou cartes indépendantes peuvent avoir plusieurs actions locales sobres ; leur répétition ne justifie pas plusieurs boutons dominants en concurrence. Lorsqu’une boîte de dialogue devient la surface active, elle porte sa propre hiérarchie.

La couleur ne doit pas encourager une décision que les preuves ne soutiennent pas. Dans une revue, l’action principale peut être l’examen d’une pièce. Si une enquête reste pertinente malgré l’abstention du Judge, son autorisation doit rester possible selon les règles métier et être explicitement nommée.

Éviter « OK », « Exécuter » ou « Valider » quand l’effet n’est pas évident. Un bouton désactivé doit avoir une raison accessible à proximité ; un tooltip porté seulement par un élément désactivé est insuffisant.

Ne pas répéter une action identique en plusieurs endroits sans besoin démontré. Une barre persistante peut aider sur une longue tâche, à condition de ne pas masquer le contenu et de conserver les réserves déterminantes accessibles.

## 5. Définir ce qui doit rester visible

La divulgation progressive sert à réduire l’effort de lecture. Elle ne doit pas cacher une condition qui change la décision.

| Toujours visible dans la synthèse concernée | Accessible en approfondissement |
|---|---|
| Objet, périmètre et version qui auront un effet | UUID, chemins, paramètres internes. |
| Disponibilité réelle ou prérequis bloquant connu | Détails de diagnostic et traces. |
| Preuve manquante ou contradiction déterminante | Métadonnées de toutes les sources. |
| État simulation/réel et conséquence d’une activation | Signature, JSON, règles techniques détaillées. |
| Unité, période, effectif et nature mesurée/projetée | Méthodologie complète et paramètres secondaires. |
| Action enregistrée, échec ou résultat non confirmé | Historique technique complet. |

Ce classement dépend de la tâche : les paramètres et traces sont principaux dans une vue de diagnostic. Dans une vue métier, la synthèse doit rester suffisante lorsque toutes les sections facultatives sont fermées.

Les tooltips expliquent un terme ou ajoutent une précision ; ils ne sont pas le seul accès à une réserve, une unité, un état de disponibilité ou une preuve nécessaire. Les informations au survol doivent aussi être accessibles au clavier et au toucher.

## 6. Construire des formulaires qui aident à concevoir

### Ordre des questions

Un formulaire doit suivre les dépendances de la décision : **intention → choix compatibles → paramètres utiles → aperçu de l’effet → test éventuel → enregistrement**.

Exemple Judge : quelle question vérifier, sur quelles sorties et preuves, quels critères appliquer, quelle revue demander si les preuves sont insuffisantes, puis tester sur un cas. Exemple événement : quelle origine ou fréquence, quelles entrées, quel parcours, quelle échéance et quel effet réel.

### Règles de saisie

- Afficher un label permanent, une unité et un exemple lorsque nécessaire. Le placeholder ne remplace pas le label.
- Préférer un sélecteur d’objet, de sortie ou de champ à un UUID, slug ou chemin JSON à recopier.
- Mettre en avant les choix usuels sans retirer l’accès expert. Le mode guidé et le mode avancé doivent représenter le même contrat.
- Présenter seulement les champs pertinents pour le choix courant. Conserver les valeurs compatibles lorsqu’on change une option.
- Utiliser une colonne par défaut ; aligner des champs côte à côte lorsqu’ils se comprennent ensemble, par exemple date et heure. Adapter à la largeur disponible.
- Distinguer valeur obligatoire, facultative et héritée. Expliquer les valeurs par défaut qui ont une conséquence importante.
- Valider à un moment utile, notamment après sortie du champ ou soumission ; préserver la saisie et placer l’erreur près du champ. Éviter de signaler une erreur dès la première frappe.
- Montrer clairement « non enregistré », « enregistré » et « appliqué/publié ». Ces états ne sont pas interchangeables.

Un formulaire court reste un formulaire court. Un assistant à plusieurs étapes est justifié par des dépendances, une forte complexité ou un besoin de test, pas par le seul désir de moderniser son apparence.

Une connexion enregistrée ne devient « vérifiée » qu’après un test concluant. Une configuration événementielle peut être enregistrée en pause, puis testée et activée explicitement. Le résumé présenté doit correspondre exactement à l’effet serveur.

## 7. Faire de l’état une information utilisable

Un statut doit préciser **ce qui est vrai pour l’utilisateur**, à quel moment, et ce qu’il peut en faire.

- Modèle : entraînement terminé, version sélectionnée et appels disponibles sont trois dimensions. La synthèse doit dire si cette version peut effectivement servir la tâche.
- Événement : « En pause », « Simulation », « Exécution réelle prévue… » ou « Bloqué par… ». L’utilisateur ne doit pas recomposer quatre switches pour connaître l’effet.
- Source : « Référence déclarée », « Lecture configurée », « Dernière lecture réussie… » et « Données périmées » selon les preuves disponibles.
- Run : « terminé » ne signifie pas automatiquement « dossier résolu » ou « qualité approuvée ».
- Décision : proposition, avis du Judge et autorisation humaine ont des mots et des états distincts.

Éviter un « Prêt » global qui contredit un blocage connu plus bas. Lorsque l’état n’est pas vérifié, annoncer cette incertitude au lieu de déduire une disponibilité d’un simple enregistrement.

### Chargement, vide et erreur

| Situation | Réponse attendue |
|---|---|
| Premier chargement | Structure stable et attente localisée ; ne pas afficher momentanément de faux zéros. |
| Actualisation | Conserver les données précédentes si utilisables, avec fraîcheur et état d’actualisation explicites. |
| Aucun objet créé | Expliquer ce qu’apporte l’objet et proposer une création si le rôle le permet. |
| Aucun résultat de filtre | Conserver le contexte et proposer d’effacer les filtres. |
| Pas d’activité dans la période | Nommer la période et proposer de l’élargir ; ne pas laisser une grande visualisation vide sans explication. |
| Dépendance indisponible | Une cause connue et sûre, le périmètre affecté, une action utile et le rôle responsable. Éviter plusieurs alertes pour la même cause. |
| Action longue | Statut durable et retrouvable, progression réelle si disponible, possibilité de quitter sans perdre la référence. |
| Écriture dont la réponse est incertaine | « Résultat non confirmé » puis vérification de l’état existant ; ne pas encourager une relance aveugle. |

Après succès, remplacer l’invitation à refaire la même action par son résultat et sa preuve. Les confirmations optimistes sont réservées aux interactions dont le résultat peut être confirmé ou annulé de façon fiable ; un reçu, une approbation ou une publication ne doit pas être inventé par le frontend.

## 8. Préserver le contexte pour créer de la fluidité

La fluidité se juge à la continuité de la tâche : l’utilisateur n’a pas à se réorienter ou à ressaisir une sélection après chaque approfondissement.

- Le même objet conserve son nom, son état et son en-tête quand on change de facette.
- Les liens portent le contexte précis : dossier, version, table, source, extrait ou exécution. Une provenance PostgreSQL doit ouvrir sa table, pas un explorateur vierge.
- Les filtres et sélections partageables utilisent les mécanismes de route existants. Respecter la navigation canonique du produit ; ne pas inventer un historique incompatible à chaque écran.
- Le retour restaure sélection, filtres et position utile. Une preuve doit rester vérifiable sans faire disparaître la décision.
- Un volet convient à une inspection ponctuelle ; une page convient à un travail autonome. Éviter une cascade de panneaux imbriqués et de modales pour traverser plusieurs objets.
- Les commandes d’édition, d’administration et de publication apparaissent selon le rôle et le contexte. Leur visibilité ne remplace jamais les autorisations serveur.

L’identité stable ne signifie pas tout rendre identique : Work sert une tâche métier, le Cockpit permet son approfondissement. Le passage doit nommer clairement ce que l’on va examiner et comment revenir.

## 9. Calibrer typographie, espace, couleur et mouvement

Conserver les primitives et variables `--ck-*`. Les valeurs suivantes sont des repères de conception à confronter aux vrais contenus et aux deux thèmes, pas des corrections CSS globales à appliquer sans revue.

| Élément | Repère | Intention |
|---|---|---|
| Titre de page | Base existante 24 px / 32 px, poids 600 | Une identité visible, sans répéter le titre dans plusieurs cartes. |
| Titre de section | Environ 18–20 px selon le contexte | Différencier les unités de travail. |
| Contenu de décision et aide nécessaire | Généralement 14–16 px, interligne confortable | Lire les réserves aussi facilement que la proposition. |
| Données denses et métadonnées | 12–13 px lorsque la tâche le permet | Ne pas y reléguer une condition critique. |
| Bouton desktop | Primitives existantes : 32 px ; variante compacte 28 px | Dimension proportionnée au libellé, cohérente avec le chrome. |
| Usage tactile | Viser une cible d’environ 44 px, par taille ou espace de frappe suffisant | Confort de manipulation ; ce repère n’est pas une certification d’accessibilité. |
| Espacements | Échelle existante de 4 px : 8/12 à l’intérieur, 16/24 entre groupes, 24/32 entre sections selon le contenu | Faire voir les relations, pas remplir une grille mécanique. |
| Rayons et surfaces | Tokens existants ; surfaces plates, ombres réservées aux couches flottantes | Éviter des variantes inventées à chaque fonctionnalité. |
| Mouvement | Tokens existants 120/200 ms lorsque pertinent | Expliquer une ouverture, une sélection ou un changement d’état ; respecter la réduction des animations. |

Utiliser le texte principal pour les faits utiles, le secondaire pour les métadonnées. Le gris discret ne doit pas porter seul une réserve déterminante. La couleur accompagne un libellé et, si nécessaire, un symbole ; elle ne suffit pas à communiquer un état.

Les nombres comparables s’alignent et utilisent des chiffres tabulaires. Le monospace sert les identifiants et le code. Les capitales et micro-labels restent exceptionnels. Les icônes seules conviennent aux actions familières et non ambiguës, avec un nom accessible ; une action essentielle mérite généralement un libellé.

La hiérarchie doit rester perceptible en niveaux de gris : taille, graisse, emplacement et espacement portent d’abord la structure. La couleur renforce une information précise. Cette vérification évite que le cyan, un badge ou une bordure soient les seuls moyens de trouver la prochaine étape.

Vérifier contraste, focus visible et lisibilité en clair/sombre sur les surfaces réellement utilisées. Une animation ne doit pas retarder l’action ni simuler un progrès que le système ne mesure pas. Réserver la place du contenu asynchrone évite les sauts de mise en page.

## 10. Donner une grammaire aux données et graphiques

Partir de la question : comparer, suivre une évolution, localiser une exception ou inspecter une preuve. Choisir ensuite la représentation.

- Des comptages journaliers utilisent des marques datées et une échelle entière. Des barres empilées peuvent distinguer terminé, échec et en cours.
- Une prévision montre historique, frontière du futur, unité, horizon et incertitude. Ne pas lisser une activité discrète jusqu’à suggérer des événements inexistants entre les jours.
- Une comparaison de modèles montre la même population, la référence, la version et l’effectif utilisable. Attacher le dénominateur à la mesure : « 1/1 cas revu », avec une réserve de couverture.
- Un gain projeté montre sa formule, ses hypothèses et son unité. Dans l’exemple SAV : `(8 − 2) / 60 × 40 − 0,50 = 3,50 €/dossier`. Le pourcentage vient après la compréhension du calcul.
- Distinguer zéro, inconnu, non mesuré et hors périmètre. Une absence de donnée ne devient pas zéro.
- Garder période, System et unité accessibles en consultation. Personnaliser sert à enregistrer une composition ; un filtre temporaire ne doit pas modifier silencieusement la vue commune.
- Un clic sur une date ou un segment doit avoir une conséquence explicite : sélection et filtre des preuves, avec moyen de réinitialiser. Si cette interaction n’existe pas, ne pas la suggérer visuellement.
- Une ligne de preuve doit être reconnaissable : heure, nom du traitement, référence métier si disponible, état et System lorsque le périmètre est pluriel.

Les limites restent près du chiffre concerné. La méthode complète peut être repliée. Une représentation décorative n’a pas de priorité sur la capacité à identifier le dernier événement et à vérifier son résultat.

## 11. Réorganiser le travail sur mobile

Préserver la progression de lecture plutôt que l’ordre des colonnes desktop.

- Work : sélecteur de dossier → situation → faits critiques et réserves → proposition et décision → preuve et historique détaillés.
- Flow : lecture du parcours puis inspection d’une étape. L’édition complexe peut rester mieux adaptée au desktop ; annoncer les limites au lieu de comprimer toutes les commandes.
- Model Center : nom/version, disponibilité et synthèse utile avant l’inventaire des métriques et actions administratives.
- Personnalisation : une colonne, choix du bloc puis ses propriétés ; le catalogue s’ouvre à la demande.

Les barres fixes ne doivent pas recouvrir une erreur, le focus ou la fin d’un formulaire. Éviter les défilements imbriqués sans nécessité. Pour une table intrinsèquement large, un défilement local identifié peut rester préférable à des cellules illisibles ; proposer une lecture par ligne lorsque la tâche s’y prête.

Tester petits écrans, tablette, zoom 200 %, clavier, libellés longs et traduction. L’absence d’overflow document est un contrôle technique utile, pas une preuve suffisante de bonne expérience.

## 12. Application aux surfaces existantes

| Surface | Composition actuelle à reprendre | Cible générique |
|---|---|---|
| Accueil Work | Arriéré technique dominant, application sous le premier écran | Applications récentes/épinglées et tâches du rôle ; file filtrable ; accompagnement contextuel. |
| Dossier | Bandeaux avant le travail ; décision parfois avant faits en mobile | Contexte compact ; faits et preuves rapprochés ; proposition et revue associées ; reçu après action. |
| Document Center | Infrastructure et statistiques avant les contenus | Documents utiles, fraîcheur, usages ; diagnostics dans leur facette. |
| PostgreSQL / DataOps | Source accessible mais contexte parfois perdu ; reprise à qualifier | Étapes guidées, table adressable, aperçu et provenance ; préparation nommée et reprise explicite. |
| Model Center | Métriques nombreuses et disponibilité ambiguë | État effectif, rôle du modèle, qualité et limite ; détails experts accessibles. |
| Flow | Palette et bandeaux permanents, graphe réduit | Lecture publiée cadrée ; phases ; sélection et inspection ; édition explicite. |
| Judge / événements | Paramètres techniques et états dispersés | Intention guidée, sélection d’objets, aperçu/test, effet réel synthétisé. |
| Prévision | Six panneaux pour une tâche | Un bloc avec fraîcheur, action, prévision et conclusion ; capacité seulement si déclarée. |
| Amélioration | Inventaire de sept modèles | Version utilisée, candidat, couverture, puis revoir les retours / comparer / décider. |
| Impact | Consultation mêlée à édition et grandes visualisations vides | Périmètre visible, activité et preuves liées, projection expliquée, personnalisation séparée. |

La vue de lecture, la vue de configuration et la vue d’exploitation concernent le même objet et ses versions. Elles ne doivent pas recréer plusieurs Systems pour raconter un seul parcours.

## 13. Construire une généricité utile

Une fonctionnalité générique peut avoir une composition spécialisée dans un type de travail. Une liste de champs arbitraires ne suffit pas à devenir un bon composant de décision.

Enrichir les composants partagés autour de fonctions sémantiques : **identité et état**, **synthèse de décision**, **preuve vérifiable**, **résultat et reçu**, **activité filtrable**, **configuration avec aperçu**. Ces fonctions reçoivent des données, des permissions, des versions et des actions configurées. Elles ne contiennent pas de branche conditionnelle dédiée à Luma.

Faire porter aux configurations la bonne information : objet visé, importance d’une réserve, effet d’une action, état effectif, lien vers la preuve. Le frontend ne doit ni inférer une autorisation ni fabriquer un statut métier à partir d’un libellé.

Réutiliser et faire évoluer les primitives existantes après comparaison avec les autres usages. Une primitive commune peut être mal utilisée, voire comporter un défaut ; sa présence ne dispense pas de revue visuelle. Éviter un second design system local qui divergerait à la prochaine fonctionnalité.

## 14. Méthode de correction et critères de livraison

### Séquence recommandée

1. **Inventorier l’information et les actions.** Pour chaque élément : rôle, tâche, importance, fréquence et conséquence. Identifier doublons et informations déterminantes masquées.
2. **Recomposer trois parcours représentatifs.** Une décision Work, une lecture/inspection Flow et une consultation Impact. Inclure les cas d’erreur dès cette étape.
3. **Éprouver les compositions sur les vrais contenus.** Dossiers longs, graphe réel, références variées, faibles/grands volumes, absence de preuve, indisponibilité et traduction.
4. **Extraire les patterns réutilisables.** Appliquer aux données, modèles, événements et autres applications. Conserver les tokens et la navigation canonique.
5. **Mesurer puis ajuster.** Observer compréhension et accomplissement ; vérifier ensuite rendu, clavier, accessibilité, performances et non-régression.

### Critères designer

Une revue doit chercher des preuves concrètes, plutôt qu’une note esthétique globale :

- Au premier regard, le testeur peut nommer l’objet, son état et la tâche proposée.
- Le poids visuel principal correspond à l’information ou l’action la plus importante.
- La prochaine action annonce correctement son effet ; les alternatives sont reconnaissables.
- Toutes les sections facultatives fermées, les conditions de décision restent compréhensibles.
- Les éléments comparés et les preuves déterminantes sont accessibles sans reconstituer un puzzle.
- Après un approfondissement, le dossier, le périmètre et la sélection restent retrouvables.
- La confirmation d’une action apparaît au bon endroit et empêche la répétition accidentelle.
- Un lecteur distingue mesure, projection et donnée inconnue, y compris avec un seul événement.
- Les erreurs donnent une prochaine étape utile ; la mise en page ne s’effondre pas sans données.
- Sur mobile et au clavier, la progression reste logique et le focus demeure visible.

Une exposition brève de l’écran peut aider à vérifier la hiérarchie, mais ne remplace pas une tâche complète. Les seuils de temps doivent être définis après une mesure de référence et selon le rôle ; ne pas inventer une exigence universelle « tout en trois clics ».

### Contrôles produit

Pour chaque surface modifiée, recetter : nominal, vide réel, filtre sans résultat, chargement, donnée périmée, erreur, permission limitée, action en cours et résultat incertain. Couvrir desktop, mobile, FR/EN et clair/sombre selon les usages supportés. Lancer les contrôles de chrome et de navigation du dépôt et les tests pertinents du composant ; compléter par une inspection visuelle humaine.

Les actions dont les conséquences métier comptent doivent être testées avec leurs vrais contrats et états. Les captures avec données simulées servent à vérifier la composition ; elles ne prouvent pas qu’un modèle, une connexion ou un parcours déployé est disponible.

## Références d’implémentation

- [Chrome officiel](agentium-ui-chrome.md) : conventions et contrôle `check:ui-chrome`.
- [Modèle mental et navigation](mental-model.md) : Work orienté tâche, invariance de l’objet, facettes et couches de détail ; les statuts d’implémentation y restent à respecter.
- [Tokens Cockpit](../frontend-ng/src/styles/cockpit-tokens.scss) : couleurs, espacements, typographie, mouvements et rôles.
- [Utilitaires Cockpit](../frontend-ng/src/styles/cockpit-utilities.scss) : boutons, variantes et focus.
- [Audit designer du parcours](demo-runs/showcase-ecommerce/DESIGN-AUDIT-2026-10-17.md) : constats et captures datés, avec distinction site/QA/code.

**Objectif d’acceptation : la qualité visuelle rend la tâche plus facile à comprendre, et chaque interaction confirme ce que l’utilisateur avait compris.**
