# ANDRITZ Notices Techniques transverses - Knowledge Guide

Statut : reference de gouvernance du Knowledge Guide de la collection transverse.

Target scope : `andritz-spl-knowledge-experiment`

Target collection : `andritz-notices-techniques-spl-pilot`

Objectif : aider Agentium a lire les notices techniques SPL et Needlepunch sans confondre reference projet, ligne, machine, equipement, piece et reference documentaire.

Ce guide est un contexte d'interpretation. Il ne remplace jamais les notices sources. Les reponses doivent citer le projet, l'archive, le document interne et la page ou section quand ces metadonnees sont disponibles.

```agentium-retrieval-policy
{
  "version": 1,
  "query_planning": {
    "require_project_code_match": true,
    "protected_terms": [
      "BBA120",
      "ACO140",
      "ACO150",
      "ARA200",
      "DCI110",
      "AKK200",
      "KD724",
      "URACA KD724",
      "KSB Etachrom",
      "LM300",
      "LM 300",
      "O-ring",
      "JETLACE",
      "XS1-M",
      "XS1",
      "XS2",
      "ZCT"
    ],
    "aliases": {
      "capteur": [
        "sensor",
        "sensors",
        "detector",
        "detectors",
        "proximity switch",
        "XS1",
        "XS2",
        "ZCT"
      ],
      "capteurs": [
        "sensor",
        "sensors",
        "detector",
        "detectors",
        "proximity switch",
        "XS1",
        "XS2",
        "ZCT"
      ],
      "pompe": [
        "pump",
        "pumps",
        "URACA",
        "KD724",
        "KSB",
        "Etachrom",
        "high pressure pump",
        "HP pump"
      ],
      "injecteur": [
        "injector",
        "prewetting injector",
        "autoclamped injector",
        "injector cartridge",
        "cartridge"
      ],
      "joint": [
        "seal",
        "O-ring",
        "o ring",
        "gasket",
        "oring"
      ],
      "cartouche": [
        "cartridge",
        "filtering cartridge",
        "injector cartridge",
        "LM 300",
        "LM300"
      ],
      "nettoyage": [
        "cleaning",
        "clean",
        "cleaning procedure",
        "maintenance cleaning",
        "injector cartridge cleaning"
      ],
      "nettoyer": [
        "cleaning",
        "clean",
        "cleaning procedure",
        "maintenance cleaning",
        "injector cartridge cleaning"
      ],
      "filtration": [
        "filtration",
        "filtering",
        "filter",
        "vacuum",
        "Filtration_maintenance",
        "Vacuum_maintenance"
      ],
      "vide": [
        "vacuum",
        "filtration vacuum",
        "Filtration_vacuum_maintenance"
      ],
      "strip-carrier": [
        "strip carrier",
        "strip-carrier",
        "carrier",
        "injector strip carrier"
      ],
      "armoire pneumatique": [
        "pneumatic cabinet",
        "pneumatic enclosure",
        "pneumatic board"
      ],
      "convoyeur": [
        "conveyor",
        "conveyor jetlace",
        "transport conveyor"
      ],
      "pieces detachees": [
        "spare parts",
        "spare parts list",
        "parts list",
        "part number",
        "item reference"
      ],
      "securite": [
        "safety",
        "declaration of conformity",
        "warning"
      ],
      "carde": [
        "card",
        "carding",
        "carding machine",
        "card documentation"
      ],
      "garniture": [
        "card clothing",
        "clothing",
        "spare parts",
        "spare parts list",
        "wire"
      ]
    },
    "facets": [
      {
        "key": "project",
        "label": "Projet",
        "terms": ["projet", "project", "BBA120", "ACO140", "DCI110", "AKK200"]
      },
      {
        "key": "sensor",
        "label": "Capteurs",
        "terms": ["capteur", "capteurs", "sensor", "detector", "proximity switch", "XS1", "XS2", "ZCT"],
        "clarify_when_broad": true,
        "clarification_prompt": "Voulez-vous les capteurs de proximite, pression, securite ou automatisme ?"
      },
      {
        "key": "pump",
        "label": "Pompes",
        "terms": ["pompe", "pump", "URACA", "KD724", "KSB", "Etachrom", "HP pump"]
      },
      {
        "key": "injector",
        "label": "Injecteurs",
        "terms": ["injecteur", "injector", "prewetting injector", "autoclamped injector"]
      },
      {
        "key": "spare_parts",
        "label": "Pieces detachees",
        "terms": ["piece", "pieces", "spare parts", "parts list", "part number", "LM 300", "O-ring", "seal", "garniture", "card clothing"]
      },
      {
        "key": "filtration_vacuum",
        "label": "Filtration et vacuum",
        "terms": ["filtration", "filtering", "vacuum", "filtering cartridge"]
      },
      {
        "key": "conveyor_pneumatic",
        "label": "Convoyeur et pneumatique",
        "terms": ["conveyor", "convoyeur", "pneumatic cabinet", "armoire pneumatique"]
      },
      {
        "key": "card",
        "label": "Carde",
        "terms": ["carde", "card", "carding", "carding machine", "garniture"]
      },
      {
        "key": "procedure",
        "label": "Procedures",
        "terms": ["procedure", "maintenance", "commissioning", "operating manual", "service manual"]
      },
      {
        "key": "safety",
        "label": "Securite",
        "terms": ["securite", "safety", "conformity", "declaration"]
      }
    ]
  },
  "source_quality": {
    "demote_navigation": true,
    "navigation_terms": [
      "table of contents",
      "sommaire",
      "index",
      "navigation",
      "menu",
      "previous",
      "next"
    ],
    "prefer_source_families": [
      {
        "when_terms": ["procedure", "maintenance", "reglage", "operation", "demarrage", "nettoyer", "nettoyage", "clean", "cleaning", "filtration", "vacuum"],
        "source_families": ["operating_manual", "maintenance", "commissioning", "html_manual"]
      },
      {
        "when_terms": ["piece", "pieces", "spare", "part number", "LM 300", "O-ring", "joint", "garniture", "card clothing"],
        "source_families": ["spare_parts_list"]
      },
      {
        "when_terms": ["pompe", "pump", "URACA", "KD724", "KSB", "Etachrom", "fournisseur", "vendor"],
        "source_families": ["annex", "supplier_manual", "operating_manual"]
      },
      {
        "when_terms": ["securite", "safety", "conformite", "conformity"],
        "source_families": ["safety"]
      },
      {
        "when_terms": ["annexe", "certificat", "certificate"],
        "source_families": ["annex"]
      }
    ]
  },
  "lexical_retrieval": {
    "document_types": {
      "parts_catalog": {
        "aliases": ["spare parts list", "spare part list", "parts list", "liste de pieces", "liste pieces", "catalogue pieces", "piece detachee", "pieces detachees"]
      },
      "maintenance_procedure": {
        "aliases": ["maintenance procedure", "procedure de maintenance", "maintenance", "service manual", "nettoyer", "nettoyage", "cleaning", "filtration maintenance", "vacuum maintenance", "injecteur", "injector", "cartouche injecteur", "cartouches injecteurs", "injector cleaning", "cartridge cleaning", "autoclamped"]
      },
      "conveyor_manual": {
        "aliases": ["conveyor", "convoyeur", "transport conveyor", "conveyor jetlace"]
      },
      "supplier_manual": {
        "aliases": ["supplier manual", "vendor manual", "URACA", "KSB", "Etachrom"]
      },
      "html_manual_section": {
        "aliases": ["html manual", "section html", "users manual", "operating manual"]
      }
    },
    "metadata_fields": {
      "document_filename": 6,
      "document_title": 5,
      "project_code": 8,
      "machine": 6,
      "family": 4,
      "section": 4,
      "section_path": 5,
      "chapter": 4,
      "part_number": 8,
      "source_family": 5,
      "inner_document_path": 5,
      "archive_name": 4,
      "retrieval_identifiers": 8,
      "retrieval_terms": 5
    }
  },
  "answer_policy": {
    "instructions": [
      "Traiter les codes SPL de type XXX123 et les codes Needlepunch numeriques a cinq chiffres valides comme des references projet stables, pas comme des machines.",
      "Un code Needlepunch numerique n'est un projet que s'il provient de la structure de depot autoritative ou, dans une requete, d'un contexte projet fort ou d'un code exact deja present dans la collection autoritative.",
      "Ne jamais inferer un projet Needlepunch depuis un nombre trouve dans un nom de piece, un document, un sous-dossier ou une mesure comme 10000 rpm.",
      "Si la question cite une reference projet exacte et qu'aucune source ne correspond a cette reference, dire explicitement que la base indexee ne contient pas cette reference plutot que repondre depuis un autre projet.",
      "Pour une reponse documentaire, citer projet, archive, document interne et page ou section lorsque disponibles.",
      "Ne pas generaliser une notice projet en regle gamme sans source explicite.",
      "Pour une interpretation metier, separer clairement l'interpretation des faits sources."
    ]
  }
}
```

## Modeles projet Andritz

La collection transverse porte deux schemas de reference projet. Le schema est
determine par la source ; il ne doit jamais etre devine par une regex numerique
globale.

### SPL alphanumerique

Les references comme `BBA120`, `ACO140`, `DCI110`, `BIO100`, `BHX100` ou
`ELM001Y` sont des references projet stables.

- Les trois premieres lettres designent le premier buyer/client historique du projet.
- Le nombre indique la position ou phase dans la chaine du projet, par exemple `100`, `120`, `200`.
- Un projet correspond a un agencement de machines et equipements dans une ligne, pas a une machine unique.
- La reference projet reste stable meme si la ligne est revendue a un autre client.
- Ne pas interpreter automatiquement `BBA120` comme une machine. Les machines et equipements doivent etre identifies uniquement quand ils sont nommes dans la notice.

Metadonnees attendues :

- `project_code` conserve la reference canonique ;
- `project_reference_kind = andritz_project` ;
- `initial_buyer_code` et `project_position` restent disponibles quand ils sont
  derivables de la grammaire SPL.

### Needlepunch numerique

Une reference a cinq chiffres est un projet Needlepunch uniquement lorsqu'elle
est portee par la structure de depot autoritative :

```text
Notices_Techniques_Needlepunch/<borne-basse>-<borne-haute>/<code a 5 chiffres + libelle>/...
```

Le code doit appartenir a la plage parente. Seul le dossier projet situe
immediatement sous la plage est lu : un nombre trouve plus bas dans le chemin
n'est jamais promu comme projet. Par exemple, `61035` est un projet si le chemin
respecte cette structure, tandis que `TTN17829J`, `V10234` et `10000 rpm` ne le
sont pas.

Metadonnees attendues :

- `project_code` est une chaine de cinq chiffres ;
- `project_reference_kind = andritz_project` ;
- `project_code_scheme = needlepunch_numeric5` ;
- `business_scope = needlepunch` ;
- `project_range`, `project_folder`, `source_deposit_path` et
  `source_deposit_file_id` assurent la tracabilite ;
- `initial_buyer_code` et `project_position` ne sont pas inventes.

Dans une requete, un nombre a cinq chiffres est reconnu seulement dans une
grammaire forte (`projet`, `resume`, `comparaison`, `inventaire`) ou lorsqu'il
correspond exactement a un code present dans la collection autoritative.

## Niveaux a distinguer

- Projet : reference SPL alphanumerique ou reference Needlepunch numerique
  validee par sa source.
- Ligne : ensemble industriel vendu, deplace ou revendu.
- Machine : machine nommee dans la notice.
- Equipement : injector, pump, damper, sensor, jetlace, winder, etc.
- Sous-ensemble : strip-carrier, jaw, cartridge, body, distribution chamber, O-ring seal, etc.
- Piece detachee : item de spare parts list ou annexe fournisseur.

## Familles de documents

Les depots `Notices_Techniques_SPL` et `Notices_Techniques_Needlepunch` peuvent contenir :

- operating manual ou user manual ;
- spare parts list ;
- annexes et certificats ;
- commissioning checklist ;
- maintenance ou service manual ;
- pages HTML de navigation ;
- images et schemas ;
- fichiers techniques non textuels.

Regles :

- Les PDF et documents bureautiques sont des sources documentaires primaires.
- Les pages HTML peuvent etre des menus ou tables des matieres ; ne pas les citer comme preuve procedurale si elles ne portent pas le contenu.
- Les images seules ne suffisent pas sans OCR ou texte associe.
- Les executables, bases locales, icones et fichiers systeme ne sont pas des sources de connaissance.

## Regles de reponse

- Citer la reference projet et le document source.
- Ne pas transferer une procedure d'un projet vers un autre sans source explicite.
- Ne pas generaliser une notice projet en regle gamme.
- Distinguer procedure, avertissement securite, liste de pieces et parametre machine.
- Si le proprietaire actuel de la ligne differe du premier buyer, conserver la reference projet historique.
- Quand plusieurs projets mentionnent le meme equipement, repondre par projet et par source.

## Vocabulaire utile

- project reference, buyer, first buyer, project position
- operating manual, user manual, service manual
- spare parts list, annex, declaration of conformity
- injector, prewetting injector, autoclamped injector
- strip, strip-carrier, cartridge, jaw, body
- O-ring, seal, nozzle, distribution chamber
- jetlace, pump, damper, sensor, winder

## Guidance retrieval

Pour une question sur un code SPL valide ou un code Needlepunch valide, chercher
d'abord ce code exact comme projet. Le filtre `project_code` est strict : aucun
chunk d'un autre projet ne doit etre utilise. Ensuite seulement identifier les
equipements nommes dans les chunks retournes.

Exemples positifs Needlepunch : `resume 61038`, `resume le projet 61038`,
`compare les projets 61038 et 61035`, `inventaire du projet 61038`.

Exemples negatifs : `TTN17829J`, `V10234` et `10000 rpm` ne doivent pas creer de
filtre projet. Un follow-up comme `et ses pieces ?` conserve l'ancre projet
precedemment validee, sans rescanner arbitrairement les nombres de la conversation.

Pour une question procedurale, preferer les chunks avec `source_family = operating_manual`, `maintenance` ou `commissioning`.

Pour une question pieces detachees, preferer `source_family = spare_parts_list`.

Pour une question de securite ou conformite, preferer `source_family = safety`.

Pour Knowledge Capture, les notices servent de contexte documentaire. Une connaissance issue d'un expert doit rester une proposition relue par HITL avant integration.
