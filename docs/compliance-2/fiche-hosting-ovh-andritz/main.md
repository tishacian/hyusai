# Conformité, sécurité et protection des données
## Hébergement papAI / Agentium sur OVHcloud — Dossier ANDRITZ

**Émetteur** : Datategy SAS
**Destinataire** : ANDRITZ (équipes Sécurité / Conformité / DPO)
**Sous-traitant d'hébergement** : OVHcloud (OVH SAS)
**Référentiel structurant** : ISO/IEC 27001:2022 (Annexe A — 4 thèmes, 93 mesures)
**Version** : 1.0
**Date** : avril 2026

---

## 1. Synthèse exécutive

Datategy hébergera la plateforme papAI/Agentium destinée à ANDRITZ sur l'infrastructure **OVHcloud** (datacenters européens, France), via le service **OVH Managed Kubernetes Service (MKS)**. La présente note recense, autour du référentiel **ISO/IEC 27001:2022**, l'ensemble des mesures techniques et organisationnelles applicables, et identifie les pièces à transmettre à ANDRITZ pour son évaluation de conformité interne.

Datategy n'est pas elle-même certifiée ISO/IEC 27001 ; en revanche :

- Datategy opère un **SMSI** (Système de Management de la Sécurité de l'Information) aligné sur les exigences ISO/IEC 27001 et formalisé dans sa **PSSI** interne (cf. *Plan d'Assurance Sécurité* — `fiche-pas/`).
- Le **sous-traitant d'hébergement OVHcloud** est certifié ISO/IEC 27001, ISO/IEC 27017, ISO/IEC 27018, ISO/IEC 27701, qualifié **HDS** et **SecNumCloud** (selon offres), et publie son référentiel de conformité sur [ovhcloud.com/fr/compliance/](https://www.ovhcloud.com/fr/compliance/).
- Le cumul de ces deux niveaux (Datategy + OVHcloud) couvre les exigences de sécurité et de protection des données attendues d'un hébergement professionnel européen.

| Couche | Responsable | Référentiels |
|--------|-------------|--------------|
| Datacenter, infrastructure physique, réseau bas-niveau, hyperviseur | OVHcloud | ISO 27001, 27017, 27018, 27701, HDS, SOC 2 Type II, PCI-DSS, SecNumCloud (offres dédiées) |
| Cluster Kubernetes managé (control plane) | OVHcloud (MKS) | ISO 27001, 27017, 27018 |
| Plateforme papAI/Agentium (workloads, services d'inférence IA locaux, données applicatives, configuration sécurité) | Datategy | SMSI Datategy aligné ISO 27001 — PAS, PCA, PRS, RGPD |
| Données métier, comptes utilisateurs, paramétrage tenant, contenus soumis à l'IA | ANDRITZ | Politique sécurité ANDRITZ |

---

## 2. Périmètre et modèle de responsabilité partagée

### 2.1 Acteurs et rôles RGPD

| Rôle | Entité | Détail |
|------|--------|--------|
| **Responsable de traitement** | ANDRITZ | Détermine finalités et moyens du traitement des données ANDRITZ sur la plateforme. |
| **Sous-traitant** (art. 28 RGPD) | Datategy SAS | Édite et opère papAI/Agentium pour le compte d'ANDRITZ. |
| **Sous-traitant ultérieur** (art. 28.4 RGPD) | OVHcloud (OVH SAS) | Fournit l'infrastructure d'hébergement (IaaS/CaaS) sur datacenters européens. |
| **Utilisateurs finaux** | Collaborateurs ANDRITZ | Consomment la plateforme via interface web SSO. |

### 2.2 Architecture d'hébergement OVHcloud

La plateforme est conteneurisée et déployée via Ansible (réf. `OPS/ansible/env/prod-ovh-k8s/`) sur un **cluster OVH Managed Kubernetes** :

| Composant | Choix de production |
|-----------|--------------------|
| **Distribution Kubernetes** | OVH Managed Kubernetes Service (MKS) — control plane managé par OVHcloud |
| **Région d'hébergement** | Datacenters OVHcloud France (GRA / SBG / RBX) — données stockées en Union européenne |
| **Compute** | Worker nodes OVH (gamme `b3-128` ou supérieure selon dimensionnement) |
| **Stockage bloc** | `csi-cinder-high-speed` (CSI Cinder OVH, redondé au niveau datacenter) |
| **Stockage objet** | MinIO opéré par Datategy sur volumes Cinder OVH (alternative : Object Storage OVH compatible S3) |
| **Base de données** | PostgreSQL (déploiement managé par Datategy, possibilité de bascule vers OVH Public Cloud Databases) |
| **Réseau** | VPC privé OVH, ingress unique via Istio Gateway + Load Balancer OVH |
| **Terminaison TLS** | cert-manager + Let's Encrypt (TLS 1.2 / 1.3, RSA 2048, SHA-256) |
| **Identité** | Keycloak 26 (OIDC), fédération SAML/OIDC vers IdP ANDRITZ possible |
| **Secrets** | HashiCorp Vault (in-cluster) |
| **Domaine de production** | `<tenant>.papai.ai` (DNS Datategy) — sous-domaine dédié ANDRITZ négociable |
| **Sauvegardes** | Snapshots quotidiens chiffrés (Datategy) ; rétention chaude 7 j, hebdo 1 mois, mensuelle 12 mois (cf. PAS §Sauvegarde) |
| **Service LLM (LLMaaS)** | Moteur d'inférence **vLLM** auto-hébergé dans le cluster, endpoint OpenAI-compatible privé ; alternative **llama.cpp** pour modèles quantifiés CPU/GPU mixte |
| **Service d'embedding (EMBaaS)** | Service vectoriel auto-hébergé (vLLM-embed ou Text-Embeddings-Inference), modèles open-source (ex. `BAAI/bge-m3`) |
| **Composants IA complémentaires** | Modèles sémantiques et NLI (ex. `sentence-transformers/LaBSE`, `xlm-roberta-large-xnli`) servis localement via Transformers |

### 2.3 Schéma logique simplifié

```
                    Internet (HTTPS)
                          │
                  TLS 1.2/1.3 (Let's Encrypt)
                          │
              ┌───────────▼───────────┐
              │  OVH Load Balancer    │   ◄── Frontière OVHcloud
              └───────────┬───────────┘
                          │
              ┌───────────▼───────────┐
              │  Istio Ingress GW     │   ◄── Frontière Datategy (cluster K8s)
              │  (mTLS in-cluster)    │
              └───────────┬───────────┘
                          │
       ┌──────────────────┼──────────────────────┐
       │                  │                      │
   ┌───▼────┐       ┌─────▼─────┐          ┌─────▼─────┐
   │Frontend│       │ Keycloak  │          │  FastAPI  │
   │ (Next) │       │ (OIDC)    │          │  (core)   │
   └────────┘       └─────┬─────┘          └─────┬─────┘
                          │                      │
                          │                      │   (appels privés in-cluster)
                          │                      │
                          │                ┌─────▼──────────────────┐
                          │                │  LLMaaS  ─ vLLM        │
                          │                │  (modèles open-source  │
                          │                │   servis localement)   │
                          │                └─────┬──────────────────┘
                          │                      │
                          │                ┌─────▼──────────────────┐
                          │                │  EMBaaS  ─ vectoriel   │
                          │                │  (BAAI/bge-m3 local)   │
                          │                └─────┬──────────────────┘
                          │                      │
                          ▼                      ▼
                   ┌──────────────────────────────────┐
                   │  Couche données (PV Cinder OVH)  │
                   │  • PostgreSQL  • MinIO  • Vault  │
                   │  • RabbitMQ    • IoTDB           │
                   └──────────────────────────────────┘
                                  │
                          ┌───────▼────────┐
                          │ Snapshots chiff│
                          │ + backups froid│
                          └────────────────┘
```

### 2.4 Sécurité des composants d'intelligence artificielle

L'ensemble des modèles d'IA exploités par la plateforme papAI/Agentium est **servi à l'intérieur du périmètre Datategy/OVHcloud** : les inférences de modèles de langage (LLM) et les calculs d'embeddings vectoriels s'exécutent sur des composants conteneurisés **déployés dans le même cluster Kubernetes** que les services applicatifs.

| Composant IA | Implémentation | Conséquence sécurité |
|--------------|----------------|----------------------|
| **LLMaaS** (génération) | Moteur d'inférence **vLLM** (alternative **llama.cpp** pour modèles quantifiés). Endpoint privé OpenAI-compatible exposé exclusivement intra-cluster. | Aucun prompt ni complétion ne quitte l'infrastructure. |
| **EMBaaS** (vectorisation) | Service d'embedding auto-hébergé (vLLM-embed ou Text-Embeddings-Inference), modèles open-source de type `BAAI/bge-m3`. | Aucun contenu indexé n'est envoyé vers un service tiers. |
| **Modèles auxiliaires** | Modèles sémantiques (`LaBSE`), NLI (`xlm-roberta-large-xnli`), traduction (`opus-mt`) chargés via la bibliothèque Transformers sur GPU local. | Modèles open-source vérifiables ; pas d'API externe. |
| **Choix des modèles** | Modèles open-source (familles Llama, Mistral, Qwen, GPT-OSS, BGE, MiniLM, etc.) sélectionnés et figés par version. | Reproductibilité, audit possible, immutabilité. |
| **Isolation réseau** | NetworkPolicy : seuls les services applicatifs Datategy peuvent appeler les endpoints LLMaaS/EMBaaS ; egress par défaut bloqué. | Pas de fuite par sortie inattendue. |
| **Persistance** | Les modèles sont préchargés depuis un registre interne (MinIO/registre OCI) ; pas de téléchargement à chaud depuis Internet en production. | Chaîne d'approvisionnement maîtrisée. |
| **Journalisation** | Métriques d'inférence (latence, tokens, codes retour) collectées localement ; les contenus de prompts ne sont pas exportés. | Observabilité sans exfiltration. |
| **Données d'entraînement client** | Aucun fine-tuning n'utilise les données ANDRITZ sans accord explicite et ségrégation par tenant. | Pas de contamination inter-clients. |

**Conséquence pour ANDRITZ** : les contenus métier (documents, requêtes utilisateurs, résultats d'évaluation) traités par la couche IA restent en permanence dans le périmètre du cluster d'hébergement OVHcloud. Aucune donnée applicative n'est transmise à un fournisseur d'IA externe par défaut. Le modèle de responsabilité partagée s'applique également à cette couche : OVHcloud opère l'infrastructure GPU/CPU, Datategy opère les services d'inférence et la chaîne de modèles, ANDRITZ contrôle les contenus envoyés en entrée.

---

## 3. Conformité du sous-traitant d'hébergement OVHcloud

### 3.1 Certifications et qualifications publiques

| Référentiel | Statut OVHcloud | Source officielle |
|-------------|-----------------|-------------------|
| **ISO/IEC 27001 / 27017 / 27018** — SMSI cloud + protection des PII | Certifié sur les services hébergés | [ovhcloud.com/fr/compliance/iso-27001-27017-27018/](https://www.ovhcloud.com/fr/compliance/iso-27001-27017-27018/) |
| **ISO/IEC 27701** — PIMS (extension RGPD) | Certifié | [ovhcloud.com/fr/compliance/iso-27701/](https://www.ovhcloud.com/fr/compliance/iso-27701/) |
| **HDS** — Hébergeur de Données de Santé | Certifié (offres dédiées) | [ovhcloud.com/fr/compliance/hds/](https://www.ovhcloud.com/fr/compliance/hds/) |
| **SecNumCloud** (qualification ANSSI) | Qualifié sur l'offre Bare Metal Pod / Hosted Private Cloud Powered by VMware | [ovhcloud.com/fr/compliance/secnumcloud/](https://www.ovhcloud.com/fr/compliance/secnumcloud/) |
| **SOC 1 / SOC 2 / SOC 3** (SSAE 16 / ISAE 3402 type II) | Conforme | [ovhcloud.com/fr/compliance/soc-1-2-3/](https://www.ovhcloud.com/fr/compliance/soc-1-2-3/) |
| **PCI-DSS** | Certifié (offres concernées) | [ovhcloud.com/fr/compliance/pci-dss/](https://www.ovhcloud.com/fr/compliance/pci-dss/) |
| **C5** (BSI Allemagne) | Conforme | [ovhcloud.com/fr/compliance/c5/](https://www.ovhcloud.com/fr/compliance/c5/) |
| **HIPAA / HITECH** | Conforme (datacenters US) | [ovhcloud.com/fr/compliance/hipaa-hitech/](https://www.ovhcloud.com/fr/compliance/hipaa-hitech/) |
| **CSA STAR** | Niveau 1 (auto-évaluation) | [cloudsecurityalliance.org/star/registry](https://cloudsecurityalliance.org/star/registry) |
| **CISPE** | Membre fondateur, signataire du code de conduite | [cispe.cloud](https://cispe.cloud/) |
| **ISO 14001 / ISO 50001** — Management environnemental et énergétique | Certifié | [ovhcloud.com/fr/compliance/iso-14001/](https://www.ovhcloud.com/fr/compliance/iso-14001/) |

Vue d'ensemble : [ovhcloud.com/fr/compliance/](https://www.ovhcloud.com/fr/compliance/) — page parent listant l'ensemble des certifications et conformités OVHcloud. La PSSI publique d'OVHcloud est consultable directement sur le centre d'aide : [help.ovhcloud.com — Politique de sécurité d'OVHcloud](https://help.ovhcloud.com/csm/fr-account-issp?id=kb_article_view&sysparm_article=KB0043105).

### 3.2 Engagements contractuels et politiques publiques OVHcloud

| Document OVHcloud | Objet | Référence |
|-------------------|-------|-----------|
| **Conditions générales de service & contrats par produit** | Cadre contractuel et conditions particulières (incluant SLA Public Cloud / Managed Kubernetes) | [ovhcloud.com/fr/terms-and-conditions/contracts/](https://www.ovhcloud.com/fr/terms-and-conditions/contracts/) |
| **Politique de protection des données personnelles** | Page parent RGPD OVHcloud | [ovhcloud.com/fr/personal-data-protection/](https://www.ovhcloud.com/fr/personal-data-protection/) |
| **RGPD — engagements OVHcloud** | Conformité au Règlement (UE) 2016/679 | [ovhcloud.com/fr/personal-data-protection/gdpr/](https://www.ovhcloud.com/fr/personal-data-protection/gdpr/) |
| **Mesures de sécurité OVHcloud** | Mesures techniques et organisationnelles | [ovhcloud.com/fr/personal-data-protection/security/](https://www.ovhcloud.com/fr/personal-data-protection/security/) |
| **Sécurité juridique et confidentialité** | Cadre des transferts internationaux et clauses contractuelles types | [ovhcloud.com/fr/personal-data-protection/legal-privacy-security/](https://www.ovhcloud.com/fr/personal-data-protection/legal-privacy-security/) |
| **Politique d'utilisation des données personnelles (Privacy Policy)** | Privacy Policy OVHcloud | [ovhcloud.com/fr/terms-and-conditions/privacy-policy/](https://www.ovhcloud.com/fr/terms-and-conditions/privacy-policy/) |
| **PSSI OVHcloud** (Politique de sécurité des SI) | PSSI publique d'OVHcloud | [help.ovhcloud.com — KB0043105](https://help.ovhcloud.com/csm/fr-account-issp?id=kb_article_view&sysparm_article=KB0043105) |
| **Souveraineté des données** | Engagement de souveraineté UE | [ovhcloud.com/fr/about-us/data-sovereignty/](https://www.ovhcloud.com/fr/about-us/data-sovereignty/) |
| **Public Cloud Managed Kubernetes (MKS)** | Page produit MKS (architecture managée, SLA résumé) | [ovhcloud.com/fr/public-cloud/kubernetes/](https://www.ovhcloud.com/fr/public-cloud/kubernetes/) |
| **Centre d'aide / documentation** | Procédures, runbooks, gestion incidents | [help.ovhcloud.com](https://help.ovhcloud.com/) |

---

## 4. Référentiel ISO/IEC 27001:2022 — Mesures applicables

L'ISO/IEC 27001:2022 (Annexe A) regroupe **93 mesures** en **4 thèmes**. Les sections suivantes décrivent, pour chaque mesure significative, qui en porte la responsabilité (OVHcloud, Datategy, ANDRITZ) et comment elle est implémentée sur l'hébergement papAI/OVH.

### A.5 — Mesures organisationnelles (37 contrôles)

| Mesure clé | Implémentation | Porteur |
|-----------|----------------|---------|
| **A.5.1** Politiques de sécurité de l'information | PSSI Datategy (confidentielle) ; PAS public communicable. PSSI OVHcloud publiée dans la Déclaration d'Applicabilité (SoA) OVH. | Datategy + OVHcloud |
| **A.5.2** Rôles et responsabilités | RACI Datategy : DSI (CISO de fait), DevOps, DPO. Comité de sécurité trimestriel. | Datategy |
| **A.5.7** Renseignement sur les menaces | Veille CVE quotidienne (Snyk, Dependabot, ANSSI-CERT-FR, OVH-CERT). | Datategy |
| **A.5.8** Sécurité dans la gestion de projet | Revue sécurité intégrée au cycle développement (CI sécurité, scan IaC). | Datategy |
| **A.5.9–5.11** Inventaire, classification, manipulation des actifs | Inventaire actifs Ansible (`inventory`, `group_vars`) ; classification donnée (Public / Interne / Confidentiel / Secret). | Datategy |
| **A.5.14** Transfert d'information | TLS 1.2/1.3 obligatoire pour tout flux entrant ; mTLS Istio entre services internes. | Datategy |
| **A.5.15–5.18** Contrôle d'accès, gestion des identités | Keycloak 26 (OIDC), MFA recommandé, fédération SAML/OIDC vers IdP ANDRITZ. | Datategy |
| **A.5.19–5.23** Sécurité dans les relations fournisseurs | OVHcloud sélectionné pour ses certifications ; DPA signé ; revue annuelle des sous-traitants ; Datategy répond aux questionnaires fournisseurs des responsables de traitement. | Datategy |
| **A.5.23** Sécurité services cloud | Modèle de responsabilité partagée formalisé (cf. §2). | Datategy + OVHcloud |
| **A.5.24–5.28** Gestion des incidents | Procédure d'incident Datategy (PAS §Gestion des incidents) ; notification CNIL <72 h ; alerte client par email / canal ticket. | Datategy |
| **A.5.29–5.30** Continuité — PCA / TIC | PCA Datategy (`fiche-bcp-continuity/main.md`) ; RTO 6 h / RPO 12 h sur l'environnement applicatif. | Datategy |
| **A.5.31–5.34** Conformité légale, propriété intellectuelle, RGPD | Conformité RGPD (cf. §5) ; clauses contractuelles types pour transferts hors UE (non applicable : données stockées en UE). | Datategy |
| **A.5.35–5.37** Revue indépendante, documentation des procédures | Audit interne annuel ; pentest annuel par tiers indépendant. | Datategy |

### A.6 — Mesures liées aux personnes (8 contrôles)

| Mesure | Implémentation | Porteur |
|--------|----------------|---------|
| **A.6.1** Filtrage à l'embauche | Vérifications des références ; clause de non-divulgation dans tout contrat de travail. | Datategy |
| **A.6.2** Termes et conditions d'emploi | Charte informatique signée à l'onboarding ; clause de confidentialité (cf. PAS §RH). | Datategy |
| **A.6.3** Sensibilisation et formation | Formation sécurité à l'onboarding ; campagnes annuelles (phishing, RGPD, OWASP). | Datategy |
| **A.6.4** Processus disciplinaire | Procédure documentée RH ; cas d'incidents traités sous responsabilité Direction. | Datategy |
| **A.6.5** Responsabilités après cessation d'emploi | Procédure offboarding : révocation comptes, restitution actifs (cf. PAS §Départ). | Datategy |
| **A.6.6** Accords de confidentialité | NDA standard avec partenaires/clients ; clauses incluses dans tout contrat. | Datategy |
| **A.6.7** Travail à distance | Postes administrés (chiffrement disque), VPN d'accès, MFA obligatoire pour les accès admin. | Datategy |
| **A.6.8** Notification d'événements de sécurité | Canal interne dédié ; alertes corrélées (Slack + email DSI). | Datategy |

### A.7 — Mesures physiques (14 contrôles)

Les mesures physiques sont **intégralement portées par OVHcloud** sur les datacenters d'hébergement. Datategy ne stocke aucune donnée client en local.

| Mesure | Implémentation OVHcloud |
|--------|-------------------------|
| **A.7.1** Périmètres de sécurité physique | Datacenters OVH avec clôture, sas, contrôle d'accès biométrique 24/7 (cf. fiche datacenter OVH). |
| **A.7.2** Contrôles d'accès physique | Accès strictement nominatif, journalisé ; visites tracées. |
| **A.7.3** Sécurisation des bureaux et locaux | Salles techniques séparées, vidéosurveillance permanente. |
| **A.7.4** Surveillance physique | CCTV 24/7 ; gardiennage permanent. |
| **A.7.5** Protection contre menaces physiques | Sites en zones non inondables ; détection incendie VESDA + extinction gaz inerte ; redondance électrique N+1 ou 2N selon site. |
| **A.7.6** Travail dans les zones sécurisées | Procédure d'intervention OVH ; escortes obligatoires pour tiers. |
| **A.7.7** Politique de bureau propre / écran verrouillé | Applicable au personnel OVH. |
| **A.7.8** Emplacement et protection du matériel | Racks scellés ; salles climatisées (ASHRAE A1). |
| **A.7.9** Sécurité des biens hors locaux | Sans objet — pas de matériel client hors datacenter. |
| **A.7.10** Supports de stockage | Procédure de destruction physique des disques (broyage, certificat). |
| **A.7.11** Services support (énergie, climatisation) | Onduleurs UPS + groupes électrogènes ; refroidissement liquide watercooling. |
| **A.7.12** Câblage | Chemins de câbles ségrégués (puissance / data) ; FDDI/optique pour interconnexions inter-DC. |
| **A.7.13** Maintenance des équipements | Plans de maintenance OVH ; remplacement préventif. |
| **A.7.14** Mise au rebut | Disques broyés sur site ; certificat de destruction (sur demande client en NDA). |

> Références : [ovhcloud.com/fr/about-us/data-sovereignty/](https://www.ovhcloud.com/fr/about-us/data-sovereignty/) (engagement souveraineté UE) et [corporate.ovhcloud.com/fr/](https://corporate.ovhcloud.com/fr/) (gouvernance, RSE et liste des datacenters OVHcloud).

### A.8 — Mesures technologiques (34 contrôles)

| Mesure | Implémentation Datategy / OVHcloud |
|--------|------------------------------------|
| **A.8.1** Terminaux utilisateurs | Postes administrateurs Datategy avec chiffrement intégral (FileVault/BitLocker), MDM. |
| **A.8.2** Droits d'accès privilégiés | Accès SSH bastion sur IPs whitelistées (cf. PAS §Contrôle d'accès) ; comptes admin K8s nominatifs ; audit logs Keycloak. |
| **A.8.3** Restriction d'accès à l'information | RBAC Kubernetes ; NetworkPolicies ; isolation tenant via namespaces et politiques de garde. |
| **A.8.4** Accès au code source | GitLab privé + revue obligatoire ; protection branche `main` ; signed commits. |
| **A.8.5** Authentification sécurisée | Keycloak 26 ; politique mot de passe forte (CNIL) ; MFA obligatoire pour les admins ; SSO ANDRITZ via OIDC/SAML. |
| **A.8.6** Capacité | Surveillance ressources cluster (Kubernetes Dashboard, alertes seuils). |
| **A.8.7** Protection contre malwares | Scan d'images conteneurs (Snyk) avant déploiement ; signatures Cosign possibles ; OVH protège l'infrastructure sous-jacente. |
| **A.8.8** Vulnérabilités techniques | CVE scan continu (Snyk dépendances + conteneurs) ; CIS Benchmark Docker (Docker Bench) ; patch management mensuel. |
| **A.8.9** Configuration | Configuration en code via Ansible (`OPS/ansible/env/prod-ovh-k8s/`) ; revue MR obligatoire. |
| **A.8.10** Suppression d'information | Process de purge à fin de contrat (cf. §5) ; suppression sécurisée des PV (Reclaim Policy `Delete`). |
| **A.8.11** Masquage des données | Données sensibles chiffrées au repos ; pseudonymisation possible côté applicatif. |
| **A.8.12** Prévention de fuite (DLP) | Egress NetworkPolicy par défaut deny ; logs de flux sortants. |
| **A.8.13** Sauvegarde | Snapshot PV journalier chiffré (rétention 7 j chaud / 1 mois hebdo / 12 mois mensuel) ; tests restauration trimestriels. |
| **A.8.14** Redondance | OVH MKS : control plane redondant managé OVH ; workers ≥ 2 pour la production ; PostgreSQL réplication possible. |
| **A.8.15** Journalisation | Logs applicatifs centralisés (stdout pods + Loki/ELK selon config) ; logs Keycloak ; logs API K8s ; rétention min. 6 mois. |
| **A.8.16** Surveillance | Monitoring temps réel (CPU/RAM/IO, alertes mail) ; supervision Istio ; healthchecks K8s. |
| **A.8.17** Synchronisation horloges | NTP du cluster MKS aligné OVH NTP. |
| **A.8.18** Utilisation de programmes utilitaires privilégiés | Restreints aux opérateurs Datategy ; tracés dans Vault audit log. |
| **A.8.19** Installation logiciel sur systèmes opérationnels | Tout déploiement passe par Ansible + GitOps ; pas d'installation manuelle. |
| **A.8.20–8.22** Sécurité réseau | Istio mTLS in-cluster ; NetworkPolicies par namespace ; ségrégation ingress/egress. |
| **A.8.23** Filtrage web | Egress filtering au niveau cluster + niveau OVH (gateway). |
| **A.8.24** Cryptographie | TLS 1.2/1.3 en transit ; AES-256 sur snapshots OVH ; Vault pour secrets ; certs RSA 2048 SHA-256 (cf. PAS §Cryptographie). |
| **A.8.25–8.27** Cycle de vie développement | CI/CD GitLab : tests unitaires, qualité code, scan sécu, scan licence ; environnements dev/staging/prod isolés. |
| **A.8.28** Codage sécurisé | Bonnes pratiques OWASP Top 10 (cf. PAS §Sécurité logicielle) ; revue de code obligatoire. |
| **A.8.29** Tests sécurité | Pentest annuel tiers ; tests automatisés en CI (SAST). |
| **A.8.30** Développement externalisé | Sans objet — développement interne Datategy. |
| **A.8.31** Séparation des environnements | Cluster `prod-ovh-k8s` distinct des clusters `dev-ovh` / `demo-ovh` (cf. `prod-ovh-k8s/PREREQUISITES.md`). |
| **A.8.32** Gestion du changement | Workflow GitOps + revue MR obligatoire ; runbook de rollout (`PROD_OVH_K8S_ROLLOUT.md`). |
| **A.8.33** Données de test | Jeux de test synthétiques ou anonymisés ; pas de copie production en environnements inférieurs. |
| **A.8.34** Protection systèmes en audit | Audits planifiés ; isolation des outils d'audit. |
| **A.8.x — Sécurité des services d'IA** *(extension Datategy)* | Inférence LLM et embeddings exécutées intra-cluster (vLLM / llama.cpp / TEI). Modèles open-source figés et préchargés. Endpoints privés Kubernetes, NetworkPolicy restrictive, pas d'appel sortant vers fournisseur d'IA tiers en configuration standard. Journalisation des métadonnées d'inférence, pas des contenus. Cf. §2.4. |

---

## 5. Protection des données personnelles (RGPD)

### 5.1 Localisation et transferts

- **Stockage des données** : datacenters OVHcloud situés en **Union européenne** (France principalement — GRA, SBG, RBX). Aucun transfert par défaut vers un pays tiers.
- **Sous-traitance** : OVHcloud publie son cadre de gestion des sous-traitants ultérieurs sur [ovhcloud.com/fr/personal-data-protection/legal-privacy-security/](https://www.ovhcloud.com/fr/personal-data-protection/legal-privacy-security/).
- **Souveraineté** : OVHcloud est un acteur français (groupe coté Euronext Paris), soumis au droit européen ; pas d'exposition au CLOUD Act US sur les offres opérées depuis les datacenters européens d'OVH SAS.
- **Inférence IA** : les modèles LLM et d'embedding s'exécutent **dans le cluster d'hébergement** (cf. §2.4). En configuration standard, aucune donnée ANDRITZ n'est transmise à un fournisseur d'IA externe — les problématiques de transfert international applicables aux API d'IA tierces (CLOUD Act, *Schrems II*) sont par construction écartées.

### 5.2 Mesures techniques et organisationnelles (MTO art. 32 RGPD)

| Catégorie | Mesure |
|-----------|--------|
| Confidentialité | TLS 1.2/1.3 en transit ; chiffrement AES-256 au repos (snapshots, backups) ; secrets Vault chiffrés (transit + repos) ; isolation tenant. |
| Intégrité | Signatures de commits, checksums sur backups, journalisation immuable (logs append-only). |
| Disponibilité | Cluster K8s redondé ; MKS avec control plane managé OVH ; sauvegardes testées trimestriellement ; PCA RTO 6 h / RPO 12 h. |
| Traçabilité | Logs Keycloak (authentification), logs API K8s, audit Vault, audit applicatif papAI. |
| Pseudonymisation / anonymisation | Possible au niveau applicatif selon cas d'usage ANDRITZ. |
| Tests réguliers | Pentest annuel ; tests restauration trimestriels ; revue PSSI annuelle. |

### 5.3 Droits des personnes concernées

Datategy traite les demandes d'exercice des droits (accès, rectification, effacement, portabilité, opposition) via le DPO ANDRITZ comme guichet unique, et apporte le concours technique requis dans les 48 h ouvrées (cf. politique de confidentialité Datategy — `fiche-privacy/main.md`).

### 5.4 Notification de violation

- **Datategy → ANDRITZ** : sous 24 h ouvrées dès qualification de la violation (canal contractuel).
- **OVHcloud → Datategy** : conformément au DPA OVHcloud (sans retard injustifié, généralement <72 h).
- **ANDRITZ → CNIL/autorité compétente** : sous 72 h conformément à l'article 33 RGPD, avec appui technique de Datategy.

### 5.5 Réversibilité et fin de contrat

Conformément à la politique Datategy (cf. PAS §Réversibilité) :

- Restitution des données dans un format ouvert (dumps PostgreSQL chiffrés, exports MinIO/S3, modèles d'IA, scripts) via SFTP/FTPS sur serveur désigné par ANDRITZ.
- Suppression sécurisée des données après délai de réversibilité contractuel (typiquement 30 jours après notification de fin de contrat).
- Certificat de destruction fourni à ANDRITZ.
- Suppression OVH des volumes Cinder selon la politique OVH (zeroing logique + procédure de destruction physique des disques en fin de vie).

---

## 6. Cartographie du dossier de livraison

Le dossier de livraison ANDRITZ est organisé en trois compartiments. Chaque pièce est mise en correspondance avec les mesures de l'Annexe A de la norme ISO/IEC 27001:2022 qu'elle documente.

### 6.1 `00_synthese/` — Note de synthèse Datategy

| Fichier | Objet | Couverture ISO 27001 |
|---------|-------|---------------------|
| `fiche-hosting-ovh-andritz.docx` | Le présent document — synthèse de l'hébergement OVH/papAI structurée par mesure ISO 27001:2022 | Couverture intégrale Annexe A (A.5 à A.8) |

### 6.2 `01_datategy/` — Politiques et procédures Datategy

| Fichier | Objet | Couverture ISO 27001 |
|---------|-------|---------------------|
| `01_PAS-plan-assurance-securite.pdf` | Plan d'Assurance Sécurité (PSSI publique, gestion des risques EBIOS, RH, exploitation, cryptographie, sécurité logicielle, réversibilité) | A.5.1, A.5.7-A.5.18, A.5.24-A.5.37, A.6.1-A.6.8, A.8.2-A.8.34 |
| `02_PCA-plan-continuite-activite.pdf` | Plan de Continuité d'Activité (RTO 6 h / RPO 12 h, scénarios de sévérité, prévention, tests) | A.5.29, A.5.30 |
| `03_PRS-plan-reprise-sinistre.pdf` | Plan de Reprise après Sinistre (sauvegardes PV, procédure de récupération) | A.5.30, A.8.13, A.8.14 |
| `04_politique-confidentialite.pdf` | Politique de confidentialité Datategy (collecte, finalités, conservation, droits) | A.5.34 |
| `05_DPA-data-processing-addendum.pdf` | Data Processing Addendum (annexe RGPD art. 28) | A.5.19-A.5.23, A.5.34 |
| `06_SLA-et-conditions-support.pdf` | SLA et conditions de support (priorités d'incident, délais de prise en compte et de résolution) | A.5.30, A.8.16 |
| `07_programme-formation-papAI.pdf` | Programme de formation utilisateurs papAI | A.6.3 |

### 6.3 `02_ovhcloud/` — Documents publics OVHcloud (sous-traitant d'hébergement)

Pages publiques OVHcloud archivées en PDF au moment de la constitution du dossier.

| Fichier | Objet | Couverture ISO 27001 |
|---------|-------|---------------------|
| `01_OVH-conformite-vue-ensemble.pdf` | Référentiel global des certifications et conformités OVHcloud | A.5.19-A.5.23 |
| `02_OVH-ISO-27001-27017-27018.pdf` | Certifications SMSI cloud + protection des PII | A.5, A.7 (DC), A.8 |
| `03_OVH-ISO-27701.pdf` | Certification PIMS (extension RGPD) | A.5.34 |
| `04_OVH-HDS.pdf` | Certification Hébergeur de Données de Santé | A.5.31, A.5.34 |
| `05_OVH-SecNumCloud.pdf` | Qualification ANSSI cloud de confiance | A.5.19-A.5.23, A.7, A.8 |
| `06_OVH-SOC-1-2-3.pdf` | Attestations AICPA SSAE 16 / ISAE 3402 type II | A.5.35, A.8.34 |
| `07_OVH-PCI-DSS.pdf` | Certification PCI-DSS | A.8 (selon offres) |
| `08_OVH-protection-donnees-personnelles.pdf` | Page parent RGPD OVHcloud | A.5.34 |
| `09_OVH-RGPD.pdf` | Engagements OVHcloud au regard du Règlement (UE) 2016/679 | A.5.34 |
| `10_OVH-mesures-de-securite.pdf` | Mesures techniques et organisationnelles OVHcloud (art. 32 RGPD) | A.7, A.8 |
| `11_OVH-securite-juridique-confidentialite.pdf` | Cadre juridique des transferts internationaux et clauses contractuelles types | A.5.31, A.5.34 |
| `12_OVH-privacy-policy.pdf` | Politique d'utilisation des données à caractère personnel OVHcloud | A.5.34 |
| `13_OVH-PSSI-help-center.pdf` | Politique de Sécurité des Systèmes d'Information OVHcloud (publique) | A.5.1 |
| `14_OVH-conditions-de-service.pdf` | Conditions de service par produit, incluant SLA Public Cloud / Managed Kubernetes | A.5.20, A.5.30 |
| `15_OVH-public-cloud-managed-kubernetes.pdf` | Page produit Managed Kubernetes Service (architecture managée, périmètre opérationnel) | A.8.6, A.8.14 |
| `16_OVH-souverainete-des-donnees.pdf` | Engagement de souveraineté des données dans l'Union européenne | A.5.31, A.5.34 |

---

## 7. Annexes

### Annexe A — Mapping ISO 27001:2022 ↔ documents Datategy / OVHcloud

| Thème ISO 27001:2022 | Couverture Datategy | Couverture OVHcloud |
|----------------------|--------------------|--------------------|
| **A.5 Mesures organisationnelles** | PAS, PCA, DPA Datategy | Déclaration d'Applicabilité ISO 27001, DPA OVH, liste sous-traitants OVH |
| **A.6 Mesures liées aux personnes** | PAS §RH, programme formation | ISO 27001 SoA |
| **A.7 Mesures physiques** | Sans objet (pas de DC propre) | Fiches datacenters, ISO 27001, HDS |
| **A.8 Mesures technologiques** | PAS §Cryptographie/Réseau/Dev, PRS | ISO 27001 SoA, ISO 27017, SOC 2 |

### Annexe B — Glossaire

- **CSI** : Container Storage Interface
- **DPA** : Data Processing Agreement (Accord de sous-traitance RGPD art. 28)
- **EMBaaS** : Embeddings as a Service (service de vectorisation auto-hébergé)
- **HDS** : Hébergeur de Données de Santé (référentiel français)
- **llama.cpp** : moteur d'inférence open-source pour modèles quantifiés (alternative à vLLM)
- **LLMaaS** : Large Language Model as a Service (service d'inférence LLM auto-hébergé)
- **MKS** : Managed Kubernetes Service (OVHcloud)
- **NLI** : Natural Language Inference (inférence sémantique)
- **PAS** : Plan d'Assurance Sécurité
- **PCA** : Plan de Continuité d'Activité
- **PRS** : Plan de Reprise après Sinistre
- **PSSI** : Politique de Sécurité des Systèmes d'Information
- **RPO** : Recovery Point Objective
- **RTO** : Recovery Time Objective
- **SecNumCloud** : qualification ANSSI pour cloud de confiance
- **SMSI** : Système de Management de la Sécurité de l'Information
- **SoA** : Statement of Applicability (Déclaration d'Applicabilité ISO 27001)
- **TEI** : Text-Embeddings-Inference (serveur d'embeddings open-source)
- **vLLM** : moteur d'inférence haute performance open-source compatible API OpenAI

### Annexe C — Contacts

| Rôle | Contact Datategy |
|------|------------------|
| Direction de la sécurité (DSI / RSSI) | À renseigner — `security@datategy.net` |
| Délégué à la Protection des Données (DPO) | `dpo@datategy.net` |
| Support contractuel | `support@papai.ai` |
| Notification d'incident sécurité | Canal contractuel ANDRITZ + `security@datategy.net` |

---

*Document préparé par Datategy à l'attention des équipes ANDRITZ. Source markdown : `docs/compliance-2/fiche-hosting-ovh-andritz/main.md`. Sortie Word générée via le pipeline Pandoc/reference.docx partagé avec CarakAI/METROPOLIS.*
