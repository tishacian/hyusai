# Luma — qualification shadow du 20 octobre 2026

Le shadow est activé sur le champion SLA **v5**, vers le challenger forêt
aléatoire **v6**, à **10 % des appels**, avec un délai maximal de **30 secondes**.
Deux traitements shadow réels sont terminés. Le champion reste v5 : aucun
modèle n'a été promu, réentraîné ou remplacé.

Recette API sur `https://agentium.papai.ai`, workspace `agentium-showcase`,
entre **11:44 et 11:50, Europe/Paris**. Le déploiement annoncé pour cette
recette est `1b36e8a1fcd22f1b61fdd656065e97edd468cc2c`. Les réponses ML
vérifient la nouvelle politique de sélection en service, mais n'exposent pas
elles-mêmes le SHA du binaire.

## Sélection vérifiée

| Rôle | Modèle | État |
| --- | --- | --- |
| Champion observé | `2e71ce6f-800f-4d02-b59e-498e40fe48eb`, v5 | Linéaire, prêt, toujours champion |
| Challenger shadow | `6d9c2eee-60b9-4995-afb5-6dc9c148de6c`, v6 | Forêt aléatoire, prête, non champion |
| Exclusion | `0c93ef17-3241-43bd-93dc-cc0d9c5524e1`, v2 | `ML_ARTIFACT_LEGACY_UNSUPPORTED` |
| Exclusion | `17331ddf-7811-42e1-8e0f-c8dc75dd3541`, v1 | `ML_ARTIFACT_LEGACY_UNSUPPORTED` |

`GET /api/v1/ml-models/{v5}/monitoring` renvoie
`selection.policy = best_callable_compatible`, le candidat v6,
`readiness.can_enable = true` et `can_configure = true`.
La sélection shadow est distincte de l'alias historique du registre.

État initial : désactivé, échantillonnage mémorisé à 10 %, délai 15 secondes,
aucun job shadow. Le lot contrôlé utilise temporairement 100 %, uniquement
pour créer cinq appels d'une ligne, explicitement épinglés à v5.

## Essais réels et échecs conservés

Les entrées sont des sondes synthétiques construites pour cette recette, avec
les six variables du modèle. Elles ne sont ni des résultats métier observés,
ni un échantillon statistique représentatif. Les trois premières utilisent une
livraison contestée en transit, avec des montants de 364,99 €, 89,90 € et
749,00 €. Les deux dernières répètent les deux premières afin de vérifier
le budget de temps du processus shadow.

Les cinq appels primaires répondent **HTTP 200**, indiquent **v5 champion**
comme version servie et conservent leur réponse indépendamment du shadow.

| Prédiction primaire | Job shadow | Délai configuré | Résultat shadow |
| --- | --- | ---: | --- |
| `dedac71d-9034-4055-918e-4a2978d762f2` | `74262e30-7446-525b-a2a8-0fab842bdaa7` | 15 s | Échec `ML_SHADOW_TIMEOUT`, 15,25 s |
| `7fe1b11d-506d-4ec2-b100-1418ff0cac03` | `844c5602-f374-5c8a-ad34-cf2c075ca5d9` | 15 s | Échec `ML_SHADOW_TIMEOUT`, 15,21 s |
| `8de3b34a-f46d-4624-9d2c-d8bd3e63bc56` | `1cdf7e5d-de1d-5eaa-a2fd-b58ff0c2667f` | 15 s | Échec `ML_SHADOW_TIMEOUT`, 15,17 s |
| `feac3708-dfd9-4938-adf3-3ad6d1e2fa8e` | `94d45ddb-cdfb-5874-a742-8ec1badf78b7` | 60 s | Terminé à 11:48:04, 15,61 s |
| `066466e3-02e7-4dc8-a606-868138a6e0ae` | `63db0518-2a17-59e0-8704-d58c9b0d8f97` | 30 s | Terminé à 11:49:34, 16,10 s |

Le premier délai de 15 secondes était trop court pour ce chemin isolé. Le
chargement du challenger prend respectivement 11,08 et 11,29 secondes sur les
deux traitements réussis ; l'inférence prend 127,94 et 130,01 millisecondes.
Le temps total indiqué inclut le processus shadow, mais pas l'attente avant
sa prise en charge par le worker. Ces durées ne constituent pas un benchmark
de débit ni une mesure du travail humain.

Le quatrième essai utilise le plafond produit de 60 secondes pour distinguer
un chargement lent d'un échec systématique. Le cinquième confirme un budget
de 30 secondes. Aucun délai global ni plafond produit n'a été modifié.

## État final observé à 11:50:07

```json
{
  "enabled": true,
  "sample_percent": 10,
  "timeout_s": 30
}
```

La fenêtre shadow contient **5 jobs : 2 terminés, 3 échoués, 0 en attente**.
Les deux paires comparées donnent la même classe, soit un accord de 2/2.
La probabilité positive est de 0,890898 pour v5 et 0,898977 pour v6 sur la
première paire, puis 0,870779 et 0,861859 sur la seconde.

Il n'y a **aucun résultat connu** associé à ces deux paires :
`labeled_pairs = 0`, `champion_accuracy = null`,
`challenger_accuracy = null`. L'accord sur deux sondes ne démontre ni une
meilleure précision de v6, ni une qualité métier, ni un ROI.
La [comparaison hors entraînement du 19 octobre](CHALLENGER-QUALIFICATION-2026-10-19.md)
reste la référence pour discuter les performances ; elle ne justifie pas
une promotion de v6.

Contrôles avant/après :

- v5 reste champion, avec le même artefact, les mêmes paramètres
  d'apprentissage et les mêmes métriques ; seuls le réglage shadow et les
  compteurs d'usage changent ;
- le compteur de prédictions primaires de v5 passe de 139 à 144 ;
- la fiche v6 est identique, compteur de prédictions inchangé à 2 ;
- politique de surveillance, historique et proposition de réentraînement
  en attente sont identiques ;
- aucun Flow, brouillon utilisateur, événement ou réglage de déploiement
  n'est modifié par cette qualification.

## Présentation et limite de la recette

Dans la fiche du modèle v5, le panneau Shadow doit permettre de montrer la
v6 sélectionnée, les deux exclusions legacy, les paramètres 10 % / 30 s,
les traitements terminés et les trois dépassements de délai conservés.
Le récit est : le champion répond, un challenger reçoit un échantillon en
arrière-plan, puis les résultats sont comparés sans changer le modèle servi.

Cette note établit une **qualification API du produit en service**, sans
substitution par des fixtures et sans nouvelle qualification visuelle du
panneau. TreeSHAP avait été vérifié dans Play le 19 octobre ; il n'a pas été
relancé dans ce lot shadow. Aucun test local n'est présenté comme un appel
réel au déploiement.

Complément de recette : le panneau **Suivi** a ensuite été contrôlé dans
le navigateur, avec les mêmes réglages et les mêmes cinq traitements.
Le Run de prévision confirme aussi la révision applicative `1b36e8a1`.
Voir le [relevé transversal du 20 octobre](../../ops/luma-four-lots-qualification-2026-10-20.md)
pour ces vérifications UI et les autres lots.

Les réponses brutes et comparaisons avant/après sont conservées hors Git dans
`/workspace/scratch/luma-acceptance-2026-10-20/shadow/`, sans identifiant de
connexion ni jeton d'authentification. Aucun changement de code n'a été
nécessaire : le délai et l'échantillonnage utilisent la configuration produit.
