# Luma — activité réelle et restitution, 22 octobre 2026

## État contrôlé

Le frontend et les nouvelles exécutions annoncent la révision
`d03ce83a4daba16583f38fa0a9b4c3664929b3a8`. Les traitements ci-dessous ont
réellement tourné entre 08:24 et 08:28 UTC sur les données fictives déjà chargées
dans Showcase. Aucun historique n’a été fabriqué, aucun remboursement n’a été
approuvé et aucun reçu simulé supplémentaire n’a été créé.

Cette recette alimente **Work → Flow → Impact**, ainsi que le journal d’activités
et le suivi des jobs. Elle ne mesure ni le travail humain ni des économies réalisées.

## Exécutions nouvelles

| Fonction | Run | État vérifié | Résultat et limite |
| --- | --- | --- | --- |
| Recalcul des priorités, application **Pilotage SAV — équipe**, pilote R2 | [bca70d94](https://agentium.papai.ai/runs/bca70d94-5659-45c6-9f0e-181df24b8fc3) | Terminé | Lecture PostgreSQL, préparation visuelle, **23 dossiers scorés, 0 exclu**, champion v5. Dataset de sortie `89a66c6e-6d7e-43a9-9ff7-8dc450daede0`, version 17. |
| Charge et capacité, application **Réclamations** | [145c1584](https://agentium.papai.ai/runs/145c1584-b122-456e-993d-7fc119ebae0c) | Terminé | Modèle classique v2 : 28 prévisions, puis assemblage de **70 lignes** avec l’historique. Dataset `83e94dc6-8d43-4a40-a7c2-ff9636353b75`, version 3, visible dans Work. Historique synthétique arrêté au 8 octobre ; horizon du 9 octobre au 5 novembre, inchangé par ce recalcul. |
| Livraison contestée RC-5001 | [082748bb](https://agentium.papai.ai/runs/082748bb-f83c-4f73-895c-5efbd6287f32) | Revue humaine attendue | Faits, modèle, recherches documentaires et quatre choix de l’assistant exécutés. Proposition d’enquête transporteur. Judge **non évalué**, citation invalide (`evidence_quote`, question 0, citation 2). |
| Livraison contestée RC-5009 | [0d227034](https://agentium.papai.ai/runs/0d227034-871e-4288-92a8-6c2dfff39eee) | Échec conservé | Collision entre deux créations concurrentes du dataset PostgreSQL : contrainte `uq_tabular_datasets_workspace_slug_version`, version 19. Pas de résultat métier ni de reprise automatique revendiqués. |
| Colis perdu RC-5003 | [d4d3ece1](https://agentium.papai.ai/runs/d4d3ece1-cd9b-49aa-ae2c-2f59593c1846) | Revue humaine attendue | Enquête et proposition préparées. Judge **non évalué**, citation ambiguë (`evidence_quote_ambiguous`, question 1, citation 1). Aucun accord humain enregistré. |

Les actions ont été appelées par les routes Work et leurs bindings publiés,
avec confirmation et clés d’idempotence distinctes. Il ne s’agit pas de tests
du brouillon Flow. Les dossiers RC-5001 et RC-5003 avaient zéro reçu et aucune
enquête antérieure ; ils ont toujours zéro reçu après ce lot. Les dossiers de
présentation RC-1042, RC-1043 et RC-1044 n’ont pas été relancés.

## Ce qu’Impact et le suivi montrent

Lecture du bloc Activité SAV, fenêtre du 16 au 22 octobre à 08:29 UTC :

| Mesure | Avant | Après |
| --- | ---: | ---: |
| Tentatives | 22 | **27** |
| Exécutions terminées | 9 | **11** |
| Échecs | 6 | **7** |
| En cours ou en attente | 7 | **9** |
| Appels visibles | 148 | **180** |

Les graphiques de résultats SAV affichent **4 exécutions terminées le 22 octobre**,
dont les deux nouveaux recalculs. Le bloc Activité inclut également les enquêtes
en attente et l’échec : ces deux populations ne doivent pas être confondues.

Le journal d’activités attribue au lot **48 activités** : 5 Runs, 32 appels de
capacité, 7 préparations de données et 4 jobs du workspace. Il enregistre
42 activités réussies, 4 en échec et 2 en attente. Ces activités imbriquées
ne sont pas 48 dossiers traités. Les quatre jobs comprennent deux traitements
terminés et deux évaluations Judge en échec ; leurs liens de Run restent disponibles.

Les sous-totaux de coût d’Impact restent **partiels** : 134 appels sur 180 avec
coût documenté, 0 EUR et 0,132 USD dans des devises séparées. Les sorties Judge
conservent également leurs propres mesures fournisseur ; le sous-total affiché
par Impact n’est pas une facture exhaustive. Ne pas l’utiliser comme coût complet.

Le scénario financier reste celui enregistré par l’utilisateur : 8 minutes
manuelles, 2 minutes de validation, 40 €/h, 0,50 € de budget par dossier.
Il projette 3,50 €/dossier et un ratio de 700 % selon cette convention.
**Le volume mensuel reste non renseigné** ; aucun gain mensuel ni ROI observé
n’a été ajouté à partir des exécutions techniques.

## Activation de la vue Opérations

Le bloc produit générique **Activité des exécutions** a été ajouté en tête de la
vue Opérations enregistrée dans Showcase, par `PUT /api/v1/hypervisor/views`.
Les indicateurs activés sont états, appels, coûts et durée. La sauvegarde puis
la relecture sont confirmées ; leur contenu est identique au changement attendu.

Les autres blocs, leur ordre, les autres vues, le périmètre et le scénario SAV,
ainsi que la vue SAV par défaut ont été conservés. Ce n’est pas une carte codée
pour Luma : le même assemblage se configure dans **Impact → Personnaliser**.
La restitution navigateur confirme cette activation : Opérations affiche
63 tentatives sur 30 jours, pour **tous les systèmes**, avec 37 terminées,
16 échouées ou annulées et 10 en cours ou en attente. Ces totaux ont un périmètre
différent de la vue SAV de sept jours.

## Parcours de restitution

1. **Work → Réclamations → Charge et capacité** : la nouvelle sortie datée du
   22 octobre est restaurée à l’ouverture, avec courbe, intervalle, 70 lignes
   et possibilité de consulter les valeurs.
2. **Flow Luma → Consulter les résultats** : sélectionner explicitement le Run
   de prévision `145c1584…`, puis ouvrir le nœud de prévision. Le panneau de
   résultat et la fenêtre agrandie affichant la courbe ont été vérifiés sur ce
   Run en service (`08-live-flow-forecast-panel.png`, `09-live-flow-forecast-modal.png`).
   Le Run de file `bca70d94…` a également été sélectionné, puis le nœud
   **Prioriser avec le modèle SLA v5** ouvert : l’aperçu de sa version conservée
   affiche **23 lignes et 12 colonnes**, dont les prédictions et probabilités
   (`10-live-flow-queue-table.png`). La relecture du Flow après ces gestes reste
   strictement identique à l’état initial.
   Ne pas présenter
   les résultats de plusieurs Runs comme une unique exécution de bout en bout.
3. **Impact → SAV — activité et scénario** : montrer d’abord les tentatives et
   les états, puis la projection et ses hypothèses. Les graphiques de résultats
   portent sur les Runs terminés.
4. **Observabilité → Activités**, périmètre Luma : retrouver les événements et
   filtrer le type **Travail du workspace** pour consulter les jobs et leurs Runs.
5. **Run → contrôles** : les deux nouvelles enquêtes restent en revue humaine.
   Une invocation `evaluate_v2` terminée ne signifie pas que Judge a validé
   la proposition : lire son résultat d’évaluation et son motif.

## État préservé et preuves

Le Flow relu après la recette est strictement identique à celui lu avant :
brouillon **r38**, empreinte `3038f530…`, publication **v10**, empreinte
`77d4d521…`. Le champion demeure v5 et le shadow conserve sa configuration à
10 %. Le planning quotidien reste désactivé (`enabled: false`). Le contrôle
d’événements du système est lu en `dry_run` ; aucun réglage événementiel ni
webhook n’a été modifié dans cette recette.

Les captures, réponses avant/après, résultats d’invocations et sauvegardes des
vues sont conservés dans le dossier de travail
`/workspace/scratch/luma-impact-polish-2026-10-22/`. Les captures live proviennent
de la révision d03ce83a, avant le nouveau polish de l’hyperviseur. La vérification
navigateur utilise un relais local authentifié : la lecture des pages et des
résultats est qualifiée, pas la continuité du flux SSE à travers ce relais.

Les collisions de dataset et les deux réserves Judge restent des résultats de
recette à traiter. Elles ne doivent pas être supprimées pour embellir les graphes.
