# M1 — Gouvernance ML : implémentation et activation

Référence : `agentium-mlops-papai-parity-plan.md`, lot M1. Base :
`demo/agentic` à `47e289da`. Aucune action papAI, fusion ou activation de production.
Le plan d'origine reste la référence ; ce document explicite les adaptations.

## Contrats livrés

- Les actions ML interrogent les rôles canoniques courants du workspace. Le
  contrôle couvre l'API et les wrappers de Flow. Un Run emprunte l'identité
  persistée de son initiateur, encore membre actif. Un Run historique sans
  initiateur doit recevoir une identité technique explicite : le champ
  `System.created_by` est un libellé, pas une autorité. Aucun identifiant issu des
  arguments de Skill ne donne de droits.
- La matrice M1 est exposée comme `permissions` pour les boutons de l'interface.
  Les actions sensibles émettent un audit dans leur transaction. Une panne
  d'audit empêche la mutation. Le contrôle est initialement en **mode rapport**
  (`ML_RBAC_ENFORCED=false`), conformément au §6 du plan ; ce mode ne crée
  jamais une appartenance et ne réactive pas un compte désactivé. Les nouvelles
  actions export/import restent strictes même en mode rapport.
- `GET /ml-governance`, `PUT /ml-governance/policy` et
  `POST /ml-governance/promotions/{id}` rendent la politique et les revues
  accessibles depuis Setup. Les budgets définis par un workspace sont plafonnés
  par ceux de la plateforme.
- Une promotion soumise à approbation crée une `Decision` canonique, liée à
  l'empreinte de l'artefact, de sa signature, de son runtime et au champion
  précédent. Un autre relecteur autorisé doit décider avant expiration. Une
  décision périmée, répétée ou dont l'artefact a changé est refusée. Le service
  HITL existant n'offrant pas de fonction `can_decide` indépendante d'un Run,
  cette revue de modèle réutilise `Decision` et les droits canoniques sans créer
  un Run artificiel.
- Les clés ne stockent que leur empreinte. Elles expirent, peuvent fixer une
  version et une liste de réseaux CIDR, et se renouvellent avec recouvrement
  borné. L'audit contient leur identifiant, jamais leur secret. Le filtrage
  réseau utilise l'adresse du client ASGI : les en-têtes de proxy ne doivent
  être acceptés qu'en provenance des proxys de confiance configurés par
  l'exploitant. L'application ne lit pas directement `X-Forwarded-For`.
- L'admission de `/predict` et `/forecast` réserve simultanément les compteurs
  de lignée et de clé dans PostgreSQL. Les compteurs sont communs à tous les
  processus, contrairement au limiteur mémoire existant. La réponse est 429
  avec `Retry-After`. Les prévisions réservent horizon × nombre de séries.
  Le scoring batch garde son admission de calcul existante.
- Un verrou de workspace protège le quota de lignées exposées par clé active
  ou Skill publiée. Plusieurs versions d'une lignée comptent une fois.
- `store=false` sur predict/forecast supprime l'entrée du journal, sa référence
  de dataset et le déclenchement du shadow. Le feedback est refusé ; la sortie
  et les métriques restent conservées, comme demandé par le plan. La politique
  du workspace peut imposer ce refus de stockage à tous les appels.
- La purge horaire est bornée et conserve les références des travaux shadow
  en attente. `ML_RETENTION_ENABLED=false` par défaut ; l'interface indique
  explicitement que la purge est inactive.

## Migration et exploitation

Migration `135_mlops_governance`, après `134_execution_control` : cinq champs
sur les clés, consentement sur les prédictions, compteurs et verrous SQL.
Les clés existantes disposent de 365 jours à partir de la migration ; aucune
expiration rétroactive à partir de leur ancienne date de création.
Le downgrade refuse de retirer les garanties si une clé ou un journal sans
consentement d'entrée existe. Une sauvegarde et un retour de version compatibles
restent nécessaires ; ne pas supprimer ces données pour contourner ce refus.

Aucune dépendance ou image supplémentaire. Déployer les migrations avant les
nouveaux processus. Observer les audits `ml.model.permission_report` pendant
une release puis activer `ML_RBAC_ENFORCED=true` après attribution des rôles
attendus aux comptes humains et techniques. Activer la rétention seulement
après accord sur la durée effective. Les nouveaux réglages sont déclarés dans
`backend/app/core/config.py`. Ce chantier n'active rien sur la VM.

## Vérifications

- 95 tests de gouvernance service/HTTP : rôles, refus directs, audit atomique,
  expiration/réseaux/rotation, confidentialité, rétention, revue périmée,
  réservations et `Retry-After`.
- Deux tests de concurrence sur PostgreSQL réel jetable : vingt réservations
  concurrentes pour cinq autorisées et deux expositions pour une place.
- Régressions des API et du moteur de prédiction exécutées avec de vrais
  artefacts ; les fixtures de Flow déclarent désormais un initiateur persistant.
- 35 tests de migration ciblée sur PostgreSQL et un test de grâce des anciennes
  clés/refus du downgrade passent. Le test existant admet 135 dans sa chaîne ciblée et compare les
  colonnes, contraintes et index avec l'ORM. Il ne remplace pas un rejeu de
  l'historique Alembic complet depuis une base vide.

L'audit d'acceptation/rejet du réentraînement est raccordé lors de l'assemblage
M2 ; les agrégats d'inférence et alertes sont raccordés en M3.

Interface M1 : 2 270 tests unitaires réussis, TSC, i18n et contrôle de navigation
réussis ; build de production final réussi. Les tests couvrent notamment
l'abandon des réponses après changement de workspace, le secret montré une
seule fois, la rotation et la transmission de `store=false`.
