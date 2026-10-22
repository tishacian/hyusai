# Luma — conducteur COMEX prêt à jouer

**Format : 20 minutes + 5 minutes de questions.** Trois casquettes : utilisateur
SAV, builder, dirigeant. Version préparée le 22 octobre 2026 sur la révision
en service `a2be58d1`.

## Avant d'entrer en salle — deux minutes

Choisir **Agentium Showcase**, langue française. Préouvrir les liens ci-dessous
dans cet ordre. Garder le zoom lisible sur l'écran projeté. Les pages de résultat
conservent la date et l'identité de leur exécution : on montre un résultat
exécuté, sans prétendre qu'il vient d'être recalculé.

| Onglet | Lien |
| --- | --- |
| 1. Application du conseiller | [Work — Réclamations](https://agentium.papai.ai/work/reclamations/studio) |
| 2. Enquête qualifiée RC-5003 | [Résultat du pilote](https://agentium.papai.ai/runs/3ec3dc31-dd94-4574-8f3c-a3b3207333b9) |
| 3. Charge | [Charge et capacité](https://agentium.papai.ai/work/reclamations/charge) |
| 4. Application d'équipe | [Pilotage SAV — équipe](https://agentium.papai.ai/work/pilotage-sav-equipe/home) |
| 5. Éditeur de cette application | [Studio de l'application](https://agentium.papai.ai/create/apps/20e33fa4-1653-46e5-b92e-ace7c10fe96d) |
| 6. Construction du traitement | [Flow Luma](https://agentium.papai.ai/systems/f3ea83de-df89-45ec-8a85-c00d676b2713/flow) |
| 7. Pilotage | [Impact](https://agentium.papai.ai/hypervisor?facet=synthese) |
| 8. Coûts et enveloppe | [Usage et coûts](https://agentium.papai.ai/observability?facet=usage&systemId=f3ea83de-df89-45ec-8a85-c00d676b2713) |

**État de séance à connaître :** le pilote RC-5003 a atteint la revue humaine,
avec cinq critères Judge satisfaits et onze appels tracés. Le plafond de
2 000 EUR/mois est actif. La campagne de 48 essais a démarré ; son premier essai
est passé, puis un scoring DataOps a été bloqué par une transaction du Judge.
L'opérateur l'a débloqué ; la campagne a repris en conservant ses échecs et
résultats non évalués. Le correctif de transaction reste à déployer.
Ne pas annoncer la qualification des 48 essais. Avant cette livraison, utiliser
les résultats conservés ci-dessous ; éviter les boutons Enquêter, recalcul de
file et Actualiser la prévision. Une lecture ou l'ouverture d'une carte de
résultat ne constitue pas un nouveau calcul.

Si une page attend sa source, passer au Run conservé correspondant et dire
qu'il s'agit de la dernière exécution vérifiée. La lecture de ces écrans doit
elle aussi être contrôlée avant projection ; ne pas masquer une indisponibilité.

## Ouverture — 30 secondes

**À l'écran :** l'application Réclamations, pas le Flow.

**Dire :**

> « Luma est un commerçant qui veut traiter davantage de réclamations, plus
> vite, sans perdre le contrôle de ses décisions. Je vais vous montrer ce que
> le conseiller utilise, comment on construit cette application, puis comment
> la direction suit le service rendu et son coût. Les données sont fictives ;
> les traitements et les appels d'IA montrés ont réellement été exécutés.
> Les remboursements sont simulés et les gains financiers restent des projections. »

## Acte 1 — ce que l'on vend au métier, 6 minutes

### 1. Un dossier de travail, pas une conversation isolée — 1 minute

**Aller :** Work → Réclamations → **Dossier**, dans le studio.
**Cliquer :** sélectionner **RC-1042** dans la file.
**Montrer :** dossier, commande, montant, livraison, justificatifs.

> « Le conseiller retrouve les faits de commande et les justificatifs au même
> endroit. Il n'a plus à ouvrir la base de commandes, le suivi transporteur et
> plusieurs documents pour reconstituer son dossier. »

**Démonstration concrète :** comparer le code postal de la commande, **75011**,
et celui du bordereau, **75012**. Ouvrir la pièce de livraison depuis les
justificatifs, puis revenir au dossier.

> « Ici, le statut dit “livré”, mais la pièce ne correspond pas à l'adresse de
> commande. Ce croisement empêche de clore trop vite la réclamation. »

**Ce que cela vend :** une application de traitement SAV raccordée aux données
et aux documents du client. Lecture réelle ; dossier et transporteur fictifs.
L'état courant et les reçus affichés priment sur les fixtures d'origine.

**État constaté à 14:00 UTC :** la validation de l'ancienne enquête RC-1042,
ouverte le 19 octobre, a expiré après 72 heures. Le rejet automatique a été suivi
d'une tentative d'action refusée faute d'approbation. Son message rouge actuel
ne signifie pas que le Judge a rejeté les preuves. Montrer ici les faits et les
documents ; utiliser ensuite le pilote RC-5003 pour le parcours d'enquête vérifié.
Ne pas présenter le reçu ancien comme le résultat de cette tentative.

### 2. L'agent mène une enquête dans un mandat précis — 1 minute 30

**Transition :**

> « Le même traitement sait aussi instruire une perte confirmée. Voici le
> dossier RC-5003, que nous avons réellement rejoué et contrôlé aujourd'hui. »

**Aller :** onglet préouvert du [pilote RC-5003](https://agentium.papai.ai/runs/3ec3dc31-dd94-4574-8f3c-a3b3207333b9).
**Cliquer :** **Résultat**, puis **Exécution** pour montrer les étapes et les
choix de l'assistant. Revenir au résultat avant de poursuivre.
**Montrer :** faits de commande → règles documentaires → preuve de perte →
proposition de remboursement **49,90 EUR**, avec validation humaine requise.

> « L'agent choisit les recherches utiles dans une liste d'outils autorisés,
> rassemble les preuves et prépare une proposition motivée. Les règles
> contrôlent le montant et les doublons ; le responsable conserve la décision. »

**Distinction utile si l'on demande “où est l'agentique ?” :**

> « La préparation des données et le calcul de priorité sont des traitements
> déterministes. L'agent choisit ensuite quelles informations rechercher pour
> instruire le dossier. Cette combinaison rend l'automatisation utile et contrôlable. »

Ne pas présenter RC-1042 et RC-5003 comme un seul dossier. RC-5003 n'est pas un
raccourci fiable du studio à trois cas : utiliser son Run, pas `?record=RC-5003`.

### 3. Montrer le contrôle, puis la limite de l'automatisation — 1 minute

**Cliquer :** même Run → **Qualité** → contrôle **claims-resolution-review**.
**Montrer :** cinq réponses Oui, **Critères satisfaits**, puis une preuve citée.
Faire lire une justification, pas les cinq questions en entier.

> « Un contrôle distinct vérifie que la proposition est justifiée, respecte la
> politique, ne rembourse pas deux fois et garde les incertitudes visibles.
> Sur ce dossier, les cinq critères sont satisfaits. Le contrôle qualité
> n'autorise pas le remboursement à la place du responsable. »

**État réel :** Judge a répondu et ses citations exactes ont été vérifiées.
Le Run attend toujours la validation humaine. Ne pas cliquer sur l'approbation
pendant cette séquence ; elle dépasse le pilote qualifié. Une action financière
Luma, si montrée sur un autre reçu daté, reste explicitement simulée.

### 4. Passer du conseiller au responsable d'équipe — 1 minute 30

**Aller :** [Pilotage SAV — équipe](https://agentium.papai.ai/work/pilotage-sav-equipe/home).
**Montrer :** résultat conservé du recalcul de file, **23 dossiers scorés**,
**0 exclu**, modèle SLA v5. Ne pas relancer le calcul pendant l'incident.

> « Le responsable ne traite pas les dossiers au hasard : il voit ceux qui
> risquent de dépasser son délai de service et organise le travail de l'équipe. »

**Puis :** [Charge et capacité](https://agentium.papai.ai/work/reclamations/charge).
**Montrer :** courbe, séparation observations/prévisions et intervalle ; ouvrir
les valeurs si utile. Ne pas cliquer sur **Actualiser la prévision**.

> « Il peut aussi anticiper la charge et adapter sa capacité. Ici, on voit
> l'historique, la prévision et son incertitude, pas une seule valeur présentée
> comme certaine. »

**Preuve de secours :** [Run de prévision 145c1584](https://agentium.papai.ai/runs/145c1584-b122-456e-993d-7fc119ebae0c).
70 lignes, dont 28 prévisions ; intervalle à 80 %. Historique synthétique arrêté
au 8 octobre, horizon du 9 octobre au 5 novembre. Le calcul conservé date du
22 octobre ; il n'a pas déplacé cet horizon synthétique.

## Acte 2 — comment on construit et gouverne l'application, 9 minutes

### 5. Ce qu'un auteur métier peut assembler — 2 minutes

**Transition :**

> « Nous venons de voir ce que l'équipe utilise. Changeons de casquette :
> comment un responsable adapte-t-il cet outil à son organisation ? »

**Aller :** depuis Pilotage SAV — équipe, **Modifier l'application**, ou
[ouvrir son Studio](https://agentium.papai.ai/create/apps/20e33fa4-1653-46e5-b92e-ace7c10fe96d).
**Cliquer :** **Pages**, puis **Composants** ; sélectionner l'action de recalcul
de file, montrer son libellé métier et le traitement publié auquel elle se
raccorde. Ouvrir **Aperçu de l'application** et **Prévisualiser comme** pour
expliquer l'audience. Revenir à l'application Work publiée.

> « Le métier assemble une page, des indicateurs et des actions à partir de
> traitements disponibles. Il choisit les personnes qui l'utilisent. Cette
> application équipe est publiée et a réellement calculé la file des 23 dossiers. »

**Option construction en direct, si deux minutes supplémentaires :**
ouvrir [Nouvelle application](https://agentium.papai.ai/create/apps/new), donner
le nom **SAV — superviseur COMEX**, choisir une page simple, sélectionner le
système Luma et l'entrée publiée de recalcul de file, choisir l'audience puis
**Enregistrer**. Montrer le brouillon et son aperçu. Ne pas publier ou exécuter
une configuration improvisée pendant le diagnostic.

**Phrase honnête sur l'autonomie :**

> « Le responsable assemble son application sans coder à partir de capacités
> préparées. Les connexions, les modèles et les contrats de données ont été
> configurés en amont. Le raccordement fin de certains indicateurs demande
> encore une intervention technique. »

L'interface spécialisée Réclamations n'a pas été entièrement fabriquée par le
wizard. L'assemblage de l'application ne prouve pas l'autonomie d'un utilisateur
sans droits data pour entraîner et raccorder tous les modèles.

### 6. Un même Flow réutilisé par les applications — 1 minute

**Aller :** [Flow Luma](https://agentium.papai.ai/systems/f3ea83de-df89-45ec-8a85-c00d676b2713/flow).
**Montrer :** publication **v10**, puis suivre visuellement les blocs : source
PostgreSQL → préparation → priorité ML → enquête agentique → Judge → revue
humaine. Montrer aussi les entrées file et prévision comme services du même
système.

> « L'application métier consomme ce traitement. Un seul système rassemble
> les données, le prédictif et l'agent, avec des contrôles explicites. Les
> applications peuvent réutiliser ses différentes entrées. »

Un Flow partagé peut avoir plusieurs entrées : cela ne signifie pas que chaque
clic exécute toutes ses branches. Prévision et enquête ont des Runs distincts.
Ne pas sauvegarder ni publier ; le brouillon utilisateur **r38** est conservé.

### 7. Connecteur et préparation utile — 1 minute 30

**Cliquer :** source PostgreSQL, ouvrir sa consultation/son lien de source.
Montrer les tables et un aperçu si la source répond. Rester loin du formulaire
des identifiants. Puis revenir au Flow et sélectionner la préparation SAV.

**Cliquer :** **Ouvrir l'atelier** sur l'étape de préparation visuelle.
**Montrer :** une transformation qui produit `evidence_gap` ou
`duplicate_refund_check`, ainsi que l'aperçu de la sortie.

> « On transforme les données brutes en informations directement utilisables :
> une pièce manque-t-elle, un remboursement existe-t-il déjà ? Ces contrôles
> sont réutilisables et leur résultat reste vérifiable. »

**Si l'accès source attend :** fermer la consultation et ouvrir le résultat
conservé de la file : [Run bca70d94](https://agentium.papai.ai/runs/bca70d94-5659-45c6-9f0e-181df24b8fc3).
Dire sa date ; ne pas laisser croire à une lecture PostgreSQL instantanée.

### 8. MLOps et résultats directement dans le Flow — 1 minute 30

**Cliquer :** Flow → **Résultats** ; sélectionner le Run de file **bca70d94**,
puis double-cliquer **Prioriser avec le modèle SLA v5**.
**Montrer :** aperçu conservé, **23 lignes et 12 colonnes**, prédiction et
probabilité. Ouvrir le modèle lié si l'on demande sa gouvernance :
[modèle SLA](https://agentium.papai.ai/models/2e71ce6f-800f-4d02-b59e-498e40fe48eb).

> « Le modèle aide à prioriser. Sa version est identifiée ; on peut suivre son
> usage et comparer un challenger sans remplacer le modèle de production. »

Champion v5 et shadow configuré à 10 % : ne pas annoncer une supériorité du
challenger sans résultats labellisés, ni TreeSHAP sur le champion linéaire.

**Geste visuel fort :** revenir au Flow → **Résultats**, sélectionner le Run
de prévision **145c1584**, double-cliquer l'étape de prévision, puis agrandir
ou épingler sa courbe. Le clic simple paramètre ; le double-clic consulte.

> « Le builder ne travaille pas à l'aveugle : il voit la sortie réelle d'une
> étape et peut la rapprocher des données qui l'ont produite. »

Nommer le changement de Run. Les cartes consultatives ne relancent pas le Flow.

### 9. Agent, modèles et instructions : montrer le mandat — 1 minute 30

**Cliquer :** nœud d'enquête agentique ; montrer objectif, modèle du
planificateur, outils autorisés, nombre maximum de tours et sortie humaine.
Puis **Résultats** → pilote **3ec3dc31** → décisions de la boucle.

> « Nous ne donnons pas carte blanche à un chatbot. Nous lui donnons un objectif,
> des outils autorisés, une limite de travail et un point de passage humain.
> Les décisions prises et les informations utilisées restent consultables. »

**Si besoin :** ouvrir [Modèles et fournisseurs](https://agentium.papai.ai/resources?facet=providers),
montrer OpenAI et GPT-5, puis revenir immédiatement au Flow.

> « Le choix du modèle et du fournisseur est administrable. Sur cette démo,
> c'est GPT-5 qui a réellement été appelé ; le catalogue n'est pas la preuve
> que tous les fournisseurs ont été qualifiés. »

Les instructions du planificateur Luma sont versionnées dans le Flow. Pour un
Skill à `prompt_template`, la fiche Skill porte son historique d'instructions ;
ne pas montrer ce mécanisme comme l'historique d'un prompt natif qui n'en relève
pas. La ControlPolicy centrale de v10 n'est pas configurée : distinguer ce point
des droits, outils autorisés, limites de boucle et budget Usage réellement actifs.

### 10. Événements et tests : une minute facultative

**Montrer :** les sources planning/webhook et leur liaison à une publication,
puis la [campagne QA](https://agentium.papai.ai/observability?facet=quality&qualityView=tests&systemId=f3ea83de-df89-45ec-8a85-c00d676b2713&campaign=5a8a9d28-e30b-4eff-9efa-56b0fe840d6d).

> « Le même traitement peut être lancé par une application, un événement ou
> un planning. Avant de faire évoluer le système, on peut rejouer des dossiers
> avec des critères relus et comparer les versions en conservant les échecs. »

Planning et webhook permanents sont en pause. La campagne comprend 12 dossiers,
deux versions et deux répétitions, soit 48 exécutions prévues. Son état courant
est une recette, pas une certification. Le Judge du pilote est réel ; aucun
rapport Giskard ni calibration statistique n'est établi par cette campagne.
Ne pas ouvrir cette annexe pour présenter le blocage comme une réussite.

## Acte 3 — comment un dirigeant décide, 4 minutes

### 11. Vue SAV : activité observée, puis projection — 1 minute 30

**Aller :** [Impact](https://agentium.papai.ai/hypervisor?facet=synthese).
**Cliquer :** **SAV — activité et scénario** ; sélectionner Luma et une période
contenant le **22 octobre**. Lire le périmètre avant les chiffres.
**Montrer :** terminées, attentes, échecs ; sélectionner le jour puis ouvrir
une preuve. Ensuite montrer le scénario financier et ses hypothèses.

> « Le manager distingue les traitements terminés, ceux qui attendent une
> décision et ceux qui ont échoué. Puis il estime la valeur possible avec des
> hypothèses visibles, au lieu d'assimiler chaque appel d'IA à une économie. »

**Dire en montrant les quatre hypothèses :**

> « Nous retenons huit minutes en manuel, deux minutes de validation assistée,
> quarante euros de coût horaire et cinquante centimes de budget d'automatisation.
> Cela représente six minutes de capacité libérable, soit quatre euros, puis
> trois euros cinquante de valeur nette projetée par dossier. »

Les **700 %** affichés rapportent cette valeur nette au budget d'automatisation
de 0,50 EUR. Ce n'est pas un ROI réalisé. Le volume mensuel n'est pas renseigné
dans la configuration vérifiée : ne pas annoncer 3 500 EUR/mois comme une mesure.
On peut citer **1 000 dossiers/mois → 3 500 EUR/mois** comme exemple hypothétique
explicitement choisi, sans l'enregistrer pendant la séance.

### 12. Direction, Opérations, Conformité — 1 minute

**Cliquer successivement :** **Direction**, **Opérations**, **Conformité**.
Garder le même périmètre et la même période ; ne pas commenter tous les blocs.

| Vue | Montrer | Dire |
| --- | --- | --- |
| Direction | Résultats, coûts et base de valorisation | « La direction décide où investir en confrontant le service rendu, le coût et les hypothèses de valeur. » |
| Opérations | Activité, attentes, échecs, accès à une exécution | « Le responsable voit ce qui bloque et retrouve le traitement à examiner. » |
| Conformité | Provenance, réserves, liens de preuve | « On peut expliquer une décision et retrouver sur quelles règles et quelles preuves elle reposait. » |

Le résumé d'alertes ML concerne le workspace ; il ne faut pas l'attribuer
automatiquement à Luma. La vue Conformité ne constitue pas une certification.

**Expliquer la vue SAV générique :** revenir à SAV → **Personnaliser**,
montrer blocs **Activité** et **Scénario financier**, périmètre et hypothèses.
Fermer sans enregistrer.

> « Cette vue n'est pas une carte Luma codée pour la présentation : l'utilisateur
> compose une vue à partir de blocs du produit, choisit son périmètre et ses
> hypothèses, puis l'enregistre. »

### 13. Finir la gouvernance financière par une preuve — 1 minute

**Aller :** [Usage et coûts](https://agentium.papai.ai/observability?facet=usage&systemId=f3ea83de-df89-45ec-8a85-c00d676b2713).
**Cliquer :** **Budgets**. Montrer **Plafond actif**, **2 000 EUR**, consommation,
réservations et révision 2. Puis ouvrir l'[Usage du premier essai QA](https://agentium.papai.ai/runs/7846e94f-2281-4840-9406-9a273059ec30?facet=usage).
**Montrer :** 11 appels, **53 134 tokens**, **0,065231 EUR** calculés, dont
planification, contrôle qualité et embeddings ; ouvrir un appel et son tarif.

> « Chaque appel est rattaché à son traitement, à son modèle et à son usage.
> L'enveloppe mensuelle est active : le coût est réservé avant l'envoi, puis
> rapproché de la consommation. Les essais qualité sont identifiés séparément
> de l'activité métier. »

Le plafond est unique pour Showcase, Luma inclus. Les tarifs EUR incluent une
conversion documentée ; les anciens appels USD restent en USD. Coût calculé ne
signifie pas facture. Le pilote métier RC-5003, antérieur aux tarifs EUR,
conserve **52 697 tokens / 0,0805584 USD** : ne pas mélanger les deux Runs.

## Conclusion — 30 secondes, retour à Work

> « Ce que nous pouvons vendre, c'est une application de traitement SAV :
> elle rassemble les données, prépare et automatise le travail, sollicite le
> responsable au bon moment et donne au dirigeant les moyens de suivre qualité,
> activité et coût. On peut commencer par un traitement utile, puis étendre
> l'application avec les mêmes briques et les mêmes contrôles. »

**Question commerciale pour conclure :**

> « Chez vous, quel traitement répétitif mobilise le plus de recherches et de
> validations aujourd'hui, et quelle équipe pourrait en être le premier pilote ? »

## Si tu n'as que dix minutes

1. Work : dossier et contradiction entre fait et document — 2 minutes.
2. Pilote RC-5003 : proposition, Judge, accord humain — 2 minutes.
3. Application équipe et éditeur : autonomie métier cadrée — 1 minute 30.
4. Flow : hybridation et résultat consultable d'un nœud — 2 minutes.
5. Impact SAV : activité, 3,50 EUR projetés ; budget actif — 2 minutes.
6. Retour Work et conclusion — 30 secondes.

Garder catalogue fournisseurs, détails ML, événements et campagne en annexe.
Ne jamais sacrifier l'application métier, sa construction et la décision
économique pour parcourir un catalogue de fonctionnalités.
