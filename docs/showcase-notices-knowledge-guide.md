# NorthForge Notices - Knowledge Guide

Status: synthetic showcase guide. NorthForge is an invented OEM and every
identifier below is fictional. This guide carries no customer data and no
"project" concept.

Target scope: `agentium-showcase-notices`

Target collection: `agentium-showcase-notices`

Objective: demonstrate the UNIVERSAL chat orchestration baseline. The guide
teaches retrieval to preserve invented product and part identifiers, expand
common synonyms, prefer the right document family, and ask a clarifying
question when a query is too broad - all without any project code, project
inventory or cross-project matching.

This guide is an interpretation context. It never replaces the source notices.
Answers should cite the product or part identifier, the document name and the
section when those are available.

```agentium-retrieval-policy
{
  "version": 1,
  "query_planning": {
    "protected_terms": [
      "PMP-700",
      "PMP 700",
      "BRG-22",
      "BRG 22",
      "SNS-09",
      "SNS 09",
      "VORTEX-5",
      "VORTEX 5",
      "FLT-3",
      "GSK-8",
      "LUB-40"
    ],
    "aliases": {
      "pump": [
        "pump",
        "pumps",
        "high pressure pump",
        "HP pump",
        "PMP-700"
      ],
      "bearing": [
        "bearing",
        "bearings",
        "roller bearing",
        "BRG-22"
      ],
      "sensor": [
        "sensor",
        "sensors",
        "detector",
        "proximity sensor",
        "pressure sensor",
        "temperature sensor",
        "SNS-09"
      ],
      "filter": [
        "filter",
        "filters",
        "filter cartridge",
        "filtration cartridge",
        "FLT-3"
      ],
      "seal": [
        "seal",
        "seals",
        "gasket",
        "o-ring",
        "o ring",
        "oring",
        "GSK-8"
      ],
      "lubricant": [
        "lubricant",
        "grease",
        "lubrication",
        "LUB-40"
      ],
      "line": [
        "line",
        "production line",
        "VORTEX-5",
        "vortex line"
      ],
      "spare parts": [
        "spare parts",
        "spare parts list",
        "parts list",
        "part number",
        "item reference"
      ],
      "maintenance": [
        "maintenance",
        "service",
        "servicing",
        "preventive maintenance",
        "overhaul"
      ]
    },
    "facets": [
      {
        "key": "pump",
        "label": "Pumps",
        "terms": ["pump", "high pressure pump", "HP pump", "PMP-700"]
      },
      {
        "key": "bearing",
        "label": "Bearings",
        "terms": ["bearing", "roller bearing", "BRG-22"]
      },
      {
        "key": "sensor",
        "label": "Sensors",
        "terms": ["sensor", "sensors", "detector", "proximity sensor", "pressure sensor", "temperature sensor", "SNS-09"],
        "clarify_when_broad": true,
        "clarification_prompt": "Which sensor do you mean - proximity, pressure or temperature (SNS-09)?"
      },
      {
        "key": "filter",
        "label": "Filters",
        "terms": ["filter", "filter cartridge", "filtration cartridge", "FLT-3"]
      },
      {
        "key": "spare_parts",
        "label": "Spare parts",
        "terms": ["spare parts", "parts list", "part number", "GSK-8", "FLT-3", "LUB-40", "seal", "gasket"]
      },
      {
        "key": "maintenance",
        "label": "Maintenance",
        "terms": ["maintenance", "service", "servicing", "preventive maintenance", "commissioning", "overhaul"]
      },
      {
        "key": "line",
        "label": "Production line",
        "terms": ["line", "production line", "VORTEX-5", "vortex line"]
      },
      {
        "key": "safety",
        "label": "Safety",
        "terms": ["safety", "conformity", "declaration", "warning", "lockout"]
      }
    ]
  },
  "source_quality": {
    "demote_navigation": true,
    "navigation_terms": [
      "table of contents",
      "contents",
      "index",
      "navigation",
      "menu",
      "previous",
      "next"
    ],
    "prefer_source_families": [
      {
        "when_terms": ["procedure", "maintenance", "service", "commissioning", "operation", "start-up", "clean", "cleaning", "calibration"],
        "source_families": ["operating_manual", "maintenance", "commissioning"]
      },
      {
        "when_terms": ["spare", "spare parts", "part number", "FLT-3", "GSK-8", "LUB-40", "seal", "gasket"],
        "source_families": ["spare_parts_list"]
      },
      {
        "when_terms": ["safety", "conformity", "declaration", "lockout", "warning"],
        "source_families": ["safety"]
      },
      {
        "when_terms": ["troubleshooting", "fault", "error", "alarm", "diagnose"],
        "source_families": ["troubleshooting", "operating_manual"]
      }
    ]
  },
  "lexical_retrieval": {
    "document_types": {
      "parts_catalog": {
        "aliases": ["spare parts list", "spare part list", "parts list", "parts catalog", "spare parts catalog"]
      },
      "maintenance_procedure": {
        "aliases": ["maintenance procedure", "service manual", "maintenance", "preventive maintenance", "lubrication", "calibration"]
      },
      "operating_manual": {
        "aliases": ["operating manual", "operations guide", "user manual", "operating guide"]
      },
      "troubleshooting_guide": {
        "aliases": ["troubleshooting", "troubleshooting guide", "faq", "fault finding", "diagnostics"]
      },
      "safety_notice": {
        "aliases": ["safety", "declaration of conformity", "safety notice", "warning"]
      }
    },
    "metadata_fields": {
      "document_filename": 6,
      "document_title": 5,
      "part_number": 8,
      "section": 4,
      "section_path": 5,
      "source_family": 5,
      "retrieval_identifiers": 8,
      "retrieval_terms": 5
    }
  },
  "answer_policy": {
    "instructions": [
      "Preserve invented product and part identifiers exactly (for example PMP-700, BRG-22, SNS-09, VORTEX-5) and treat them as catalog references, not as projects.",
      "If a question cites an exact identifier and no source matches it, say the indexed base does not contain that reference instead of answering from a different product.",
      "For a documentary answer, cite the document name and the section when available.",
      "Do not generalize a single product notice into a product-line rule without an explicit source.",
      "For a business interpretation, clearly separate the interpretation from the sourced facts."
    ]
  }
}
```

## What the showcase demonstrates

This is the UNIVERSAL baseline, not the industrial opt-in layer. There is no
project code, no project inventory, no cross-project rejection and it does not
require a project-code match. The same retrieval funnel (hybrid dense+sparse,
C-HAH, MMR, candidate headroom, optional Deep Search) and the same generic
answer policy (`precise_fact`, `summary`, `comparison`, `insufficient_context`)
are driven entirely by this guide plus the workspace settings.

## Identifier model (all fictional)

NorthForge product and part identifiers are stable catalog references:

- `PMP-700` - high-pressure process pump model.
- `BRG-22` - roller bearing used on the pump and the line drive.
- `SNS-09` - sensor family (proximity, pressure and temperature variants).
- `VORTEX-5` - the flagship production line / series.
- `FLT-3` - filtration cartridge.
- `GSK-8` - gasket / O-ring seal kit.
- `LUB-40` - service lubricant.

An identifier names a product, an assembly or a spare part - never a project.
Identify the named item only when it appears in the retrieved source.

## Document families

The synthetic `agentium-showcase-notices` collection contains:

- operating and operations manuals;
- maintenance and service procedures;
- a spare parts catalog;
- commissioning checklists;
- safety notices and declarations of conformity;
- troubleshooting FAQs.

Rules:

- Prefer maintenance/commissioning families for procedural questions.
- Prefer the spare parts catalog for part-number and spare questions.
- Prefer the safety family for conformity and lockout questions.
- Demote navigation-only pages (tables of contents, indexes) when richer
  content exists.

## Answer rules

- Cite the product/part identifier and the source document.
- Do not transfer a procedure from one product to another without an explicit
  source.
- Distinguish a procedure, a safety warning, a parts list entry and a setpoint.
- If a query is broad (for example just "sensor"), ask the configured
  clarification question before answering.

## Knowledge Capture

For Knowledge Capture, the notices act as documentary context. Knowledge
elicited from an expert stays a proposal reviewed by HITL before it is
published to the `agentium-showcase-expert-fiche` collection.
