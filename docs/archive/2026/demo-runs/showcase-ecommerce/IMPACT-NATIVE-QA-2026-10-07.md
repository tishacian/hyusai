# Activation et QA native d’Impact — 7 octobre 2026

La vue **SAV — activité et scénario** est enregistrée dans **Agentium Showcase**
et s’ouvre par défaut dans Impact. L’assemblage a été réalisé en navigateur avec
**Personnaliser → Créer une vue**, le choix du système et les blocs du catalogue,
puis **Enregistrer la vue**. Le rechargement conserve le périmètre, les titres,
l’ordre, les hypothèses et la vue par défaut.

Les [preuves structurées](IMPACT-NATIVE-QA-2026-10-07.json) contiennent la vue
enregistrée et les réponses d’activité constatées. Il s’agit de données de
configuration du produit : aucune condition Luma n’est ajoutée à l’interface.

## Vue enregistrée

- Identifiant : `view-64b80cfd-85ca-40f2-b566-9bbc5cc19128`.
- Système : **Luma Maison — Réclamations**, `f3ea83de-df89-45ec-8a85-c00d676b2713`.
- Période : **7 jours**, dénominateur des graphiques de résultats : **Exécutions**.
- Ordre : activité, scénario financier, Monument, Provenance, Cadran,
  Détail par automatisation.
- Les trois vues précédentes Direction, Operations et Conformite ont été
  comparées avant/après : leur configuration est conservée.

La position des blocs dépend de l’assemblage enregistré. L’ouverture sur cette
vue dépend de **Ouvrir cette vue par défaut dans le workspace**. On retrouve
ces réglages dans **Impact → Personnaliser**, sans modifier le Flow ou la
business app.

## Activité retrouvée

| Observation native | Valeur |
| --- | --- |
| Tentatives, tous états | 23 |
| Terminées | 15 |
| Échouées | 8 |
| Annulées / en attente | 0 / 0 |
| Appels visibles | 231 |
| Appels avec coût documenté / coût inconnu | 181 / 50 |
| Sous-totaux documentés, devises séparées | 0,00 EUR / 0,330 USD |
| Médiane du temps technique cumulé | 48,3 s, échantillon de 23 exécutions |

Le graphique d’activité montre 3 tentatives le **2 octobre UTC** et 20 le
**6 octobre UTC**. Un clic sur le 6 octobre restitue **20 tentatives, 12 terminées,
8 échouées**. Ces dernières exécutions commencent après minuit le 7 octobre en
Europe/Paris ; les dates du graphique sont explicitement UTC.

Le cadran et le graphique par automatisation utilisent les exécutions terminées :
**3 + 12 = 15**. Ils montrent Luma, avec un pic de 12, tandis que le bloc d’activité
inclut aussi les échecs. La vue Direction reste disponible avec son agrégat en
heures ; aucune durée humaine n’a été inventée pour y faire entrer Luma.

**Dernières exécutions et preuves → Voir l’exécution** ouvre la page native de
l’exécution `52fd23dc-5660-4077-8e6a-5f22622a7bf8`. Son erreur
`CLAIM_ACTION_ALREADY_RECORDED` et son registre de skills restent consultables.
Aucune nouvelle exécution ni aucun nouveau reçu n’ont été créés pour cette QA.

## Scénario enregistré

Les conventions validées sont enregistrées dans le bloc produit : **8 min**
manuelles, **2 min** assistées, **40 EUR/h** et **0,50 EUR/dossier** de budget
complet. Le bloc calcule **3,50 EUR/dossier**, **700 % de ROI projeté** et
**0,75 minute** pour atteindre l’équilibre.

Le volume mensuel reste vide et le gain mensuel reste inconnu. Les temps humains
et le ROI observé ne sont pas mesurés. Les coûts partiels des appels ne sont pas
assimilés au budget complet ni à une économie réalisée.

## QA de l’interface

Vérifications natives effectuées à 1 440 × 1 000 en thèmes clair et sombre et
à 390 × 950 en thème sombre : blocs, graphiques, sélection du jour, preuves,
navigation vers l’exécution et panneau Personnaliser. Pas de débordement
horizontal du document ; les actions Configurer et Actualiser mesurent 32 px.
Les audits Axe des blocs, du panneau et des blocs en présentation ont retourné
zéro violation. Le mode Présenter conserve l’activité et le scénario et masque
leurs boutons de configuration.

Trois écarts génériques constatés sont corrigés dans la contribution de QA :

1. L’en-tête d’une vue filtrée sans capability associée reprenait le nombre de
   capabilities du workspace. Il compte maintenant celles du périmètre affiché.
2. L’agrégat des exécutions terminées était décrit comme des exécutions
   « lancées ». Le libellé français et anglais précise qu’elles sont terminées.
3. Un nom de vue long créait un onglet de plusieurs lignes sur mobile. Les
   onglets gardent une ligne, se répartissent sur plusieurs rangées si nécessaire
   et conservent leur nom complet accessible et dans l’infobulle.

Ces corrections d’affichage nécessitent le déploiement de la contribution de QA.
La configuration native et les graphiques d’activité sont déjà actifs.

La contribution est vérifiée localement par **1 942 tests unitaires frontend**,
**10 parcours navigateur** (dont les graphiques historiques, les droits et la
persistance), le build de production, le contrôle i18n et les hooks de conformité.
L’inlining des polices externes est désactivé uniquement pendant le build de QA ;
la configuration Angular du dépôt est restaurée après la commande. Les parcours
isolés utilisent Inventory et GBP pour vérifier le comportement générique.
