# Configurer les blocs produit dans Impact

Impact utilise des vues partagées dans le workspace. Un propriétaire ou un
administrateur peut les enregistrer ; les autres utilisateurs consultent leur
configuration. Aucun bloc d’activité ou scénario financier n’est ajouté
automatiquement pour une business app, un secteur ou un workspace.

## Parcours utilisateur

1. Ouvrir **Impact → Personnaliser**.
2. Modifier une vue existante, ou saisir un nom et cliquer **Créer une vue**.
   Une nouvelle vue contient un bloc d’activité, sans hypothèses financières.
3. Choisir **Système — périmètre de la vue**, ou **Tous les systèmes**, et la
   période : 7, 30 ou 90 jours. Ce périmètre s’applique aux graphiques de
   résultats, au registre et au bloc d’activité de cette vue.
4. Dans le catalogue **Comprendre**, ajouter **Activité des exécutions** et/ou
   **Scénario financier**. Régler le titre et les indicateurs du bloc d’activité.
5. Pour une projection, renseigner les temps manuels et assistés par unité, le
   coût horaire chargé, le budget complet par unité et la devise. L’unité métier,
   la source des hypothèses et le volume mensuel peuvent être précisés.
6. Monter ou descendre les blocs. L’ordre enregistré est aussi leur ordre de
   lecture ; les indicateurs historiques de tête restent regroupés en une bande.
7. Cocher **Ouvrir cette vue par défaut dans le workspace** si souhaité, puis
   **Enregistrer la vue**. Le périmètre, les hypothèses, l’ordre et la vue par
   défaut sont conservés après rechargement.

Les actions des blocs font 32 px et utilisent les tokens du chrome. Le parcours
et les libellés existent en français et en anglais. Le mode Présenter conserve
les blocs configurés et leur ordre.

## Ce qui est compté

**Activité des exécutions** compte toutes les tentatives visibles du ou des
Systems sélectionnés, avec leurs états et leur date de démarrage. Les essais
du Flow Builder et les exécutions de brouillons sont exclus. Le graphique
journalier inclut les échecs et les reprises. Les dates des agrégats sont UTC.
Les 50 dernières exécutions donnent accès aux preuves natives.

L’agrégation est bornée aux 2 000 dernières exécutions autorisées de la période.
Lorsque cette limite est atteinte, l’interface annonce explicitement des
sous-totaux. Les lignes refusées par les droits de lecture ne consomment pas
cette limite. Les appels sont filtrés séparément par leurs droits de lecture.

Les sous-totaux de coût exigent un coût explicitement documenté, un état tarifaire
mesuré ou calculé et une devise. Un zéro documenté est conservé ; un tarif
absent reste inconnu. Les devises sont séparées. Ces montants excluent
infrastructure, licence et intégration. La durée technique cumulée ne remplace
pas le travail humain : seules les exécutions arrivées à un état final et disposant d’un registre
d’appels complet alimentent la médiane.

Les **graphiques de résultats historiques** gardent leur cohorte d’exécutions
terminées. Leur dénominateur reste explicite : heures, exécutions ou valeur. Une
absence de convention d’heures ou de valeur ne devient pas une mesure nulle.
Le nouveau bloc d’activité fournit le graphique de toutes les tentatives.

## Projection financière

Le bloc de scénario ne reçoit aucune valeur financière par défaut et ne lit
aucun temps humain dans les latences des appels. Il ne multiplie pas le gain
unitaire par le nombre de Runs ou de reprises.

```text
capacité valorisée / unité = (minutes manuelles − minutes assistées) / 60 × coût horaire
gain net / unité = capacité valorisée − budget complet / unité
ROI projeté = gain net / unité ÷ budget complet / unité
seuil de temps gagné = budget complet / unité ÷ coût horaire × 60
gain mensuel projeté = gain net / unité × volume mensuel explicitement renseigné
```

Les résultats négatifs sont conservés. Un budget nul laisse le ROI indéterminé.
Un coût horaire nul laisse le seuil indéterminé. Sans volume mensuel, la
projection unitaire reste disponible et la projection mensuelle reste inconnue.
Les valeurs non finies, négatives ou hors bornes sont refusées à l’enregistrement.
Ces projections ne modifient ni les conventions mesurées du catalogue, ni les
mesures humaines, ni les résultats ou Flows des Systems.

## Contrats API et stockage

- `GET /api/v1/hypervisor/activity/systems` : choix de Systems autorisés.
- `GET /api/v1/hypervisor/activity?window=7d&system_id=…` : activité générique.
  `system_id` est facultatif ; les fenêtres acceptées sont `7d`, `30d`, `90d`.
  Un System absent, étranger au workspace ou interdit donne le même 404.
- `GET/PUT /api/v1/hypervisor/views` : configuration persistée existante.
  Les vues peuvent contenir `system_id`. La requête et la réponse peuvent
  contenir `default_view_id`, qui doit désigner une vue enregistrée.
- `strata.comprendre` accepte les types `activity` et `financial_scenario`.
  Les titres et paramètres appartiennent aux blocs. Un bloc de chaque type
  peut être configuré dans une vue ; créer des vues distinctes pour des
  périmètres et scénarios différents.
- `activity.settings.metrics` choisit `statuses`, `calls`, `costs`, `duration`.
- `financial_scenario.settings` contient `manual_minutes`, `assisted_minutes`,
  `hourly_cost`, `unit_budget`, `currency`, `monthly_volume`, `unit_label`, `note`.

La configuration utilise `workspace.settings.hypervisor_views` et
`hypervisor_default_view_id`. Aucune migration ni activation métier spécifique
n’est nécessaire. Les anciennes formes de blocs et vues restent lisibles.
L’ancienne carte globale de réclamations et sa route de rapport d’activité sont
remplacées par ces blocs configurables ; l’application métier conserve ses
propres parcours et preuves.
