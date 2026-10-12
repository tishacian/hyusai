---
title: "papAI"
subtitle: "PRS - Plan de reprise après sinistre"
author: ["Datategy"]
date: "2022-01-30"
subject: "Markdown"
keywords: [papAI, ML, AI, MLOPS]
lang: "fr"
titlepage: true
titlepage-color: "03A9F4"
titlepage-text-color: "FFFAFA"
titlepage-rule-color: "FFFAFA"
titlepage-rule-height: 2
book: true
classoption: oneside
code-block-font-size: \scriptsize
titlepage-background: "background.pdf"
---


# Finalité

Des interruptions de service peuvent survenir à tout moment. Vous pouvez rencontrer une panne de réseau, votre dernier déploiement d'application peut entraîner un bug critique ou vous pouvez être victime d'une catastrophe naturelle. En cas de problème, il est important de disposer d'un plan de reprise après sinistre robuste, ciblé et testé.

La récupération d’urgence correspond à un ensemble de stratégies, d’outils et de procédures qui permettent la récupération ou la poursuite de l’infrastructure à la suite d’une défaillance majeure. 

Il convient de différencier la récupération après sinistre (DR) et la haute disponibilité (HA).
La haute disponibilité est une caractéristique de résilience du système, garantissant un niveau minimal de temps d’activité.

**Récupération d’urgence et corruption des données**

Une solution de récupération d’urgence n’atténue **pas** l’endommagement des données. Les données endommagées dans une instance principale de la solution sont répliquées de l’instance principale vers une instance secondaire et sont endommagées dans les deux instances.


# Sauvegarde

Il est de votre responsabilité de sauvegarder vos données afin de de garantir la récupération de votre instance papAI.

## Base de données

papAI utilise une base de données interne PostgreSQL. La base de données est persistée dans un *Persistent Volume* (PV). Nous recommandons de mettre en place des automatismes de sauvegarde de type CRON ou à l’aide d’autres utilitaires.

Alternatives :

- (Recommandé) Sauvegardez le PV
- Utilisez votre base de données d’entreprise PostgreSQL si elle existe, plutôt que la base de données PostgreSQL provisionnée par papAI.

## Stockage d’objets

papAI utilise un serveur de stockage d’objets interne minIO. Le serveur de stockage d’objets est persisté dans un Persistent Volume (PV). Nous recommandons de mettre en place des automatismes de sauvegarde de type CRON ou à l’aide d’autres utilitaires.

Alternatives :

- (Recommandé) Sauvegardez le PV
- Utilisez votre serveur de stockage d’objets internes minIO ou AWS S3 s’ils existent, plutôt que le serveur de stockage d’objets minIO provisionnée par papAI.


# Récupération

Pour récupérer papAI :

- Provisionnez une machine virtuelle
- Récupérer les PV de la base de données et du serveur de stockage d’objets
- Installez papAI en suivant le guide d’installation. Si nécessaire, modifiez les configurations de sorte à récupérer les PV de la base de données et du serveur de stockage d’objets

