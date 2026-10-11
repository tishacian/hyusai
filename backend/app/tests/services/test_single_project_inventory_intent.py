"""Tests for the vocabulary-agnostic single-project inventory parser."""

import pytest

from app.services.rag.single_project_inventory_intent import (
    SingleProjectInventoryIntent,
    parse_single_project_inventory_intent,
)


@pytest.mark.parametrize(
    ("query", "project_code", "category"),
    [
        ("Quelles sont les pompes du projet BCX200 ?", "BCX200", "pompes"),
        ("Quels sont les brûleurs du projet PRJ204", "PRJ204", "brûleurs"),
        ("quelles sont les capteurs du projet ZXQ901", "ZXQ901", "capteurs"),
        ("Liste des roulements du projet AXM310.", "AXM310", "roulements"),
        ("inventaire des joints pour le projet SEAL42", "SEAL42", "joints"),
        ("Inventory of seals for project QTZ731", "QTZ731", "seals"),
        ("List all thermal couplings in project NVP882", "NVP882", "thermal couplings"),
        ("Which acoustic dampers are in project ACD110", "ACD110", "acoustic dampers"),
        ("Please show me the ceramic liners for project CLR515", "CLR515", "ceramic liners"),
        ("Liste des équipements alpha/bêta du projet abc123", "ABC123", "équipements alpha/bêta"),
        ("List safety valves for project ABC123", "ABC123", "safety valves"),
        ("Inventory of repair kits for project ABC123", "ABC123", "repair kits"),
        ("List installation tools for project ABC123", "ABC123", "installation tools"),
        ("Liste des modules de diagnostic du projet ABC123", "ABC123", "modules de diagnostic"),
        ("Liste des lentilles objectives du projet ABC123", "ABC123", "lentilles objectives"),
        ("List status indicators for project ABC123", "ABC123", "status indicators"),
        ("Inventory of document holders for project ABC123", "ABC123", "document holders"),
        ("List API6D safety valves for project ABC123", "ABC123", "api6d safety valves"),
        ("Inventory of ISO9001 repair kits for project ABC123", "ABC123", "iso9001 repair kits"),
        ("List S7-300 diagnostic modules for project ABC123", "ABC123", "s7-300 diagnostic modules"),
        ("List IS barriers for project ABC123", "ABC123", "is barriers"),
        (
            "List modules for S7-300 and S7-400 for project ABC123",
            "ABC123",
            "modules for s7-300 and s7-400",
        ),
        (
            "List pumps for oil and gas for project ABC123",
            "ABC123",
            "pumps for oil and gas",
        ),
        ("What pumps are in project ABC123?", "ABC123", "pumps"),
        ("What IS barriers are in project ABC123?", "ABC123", "is barriers"),
        ("Peux-tu me lister les pompes du projet ABC123 ?", "ABC123", "pompes"),
        ("Inventory of pumps for project MAINTENANCE-42", "MAINTENANCE-42", "pumps"),
        ("Inventory of seals for project ALPHA", "ALPHA", "seals"),
        ("Inventory of seals for project 2026", "2026", "seals"),
        ("Inventory of seals for project X1", "X1", "seals"),
    ],
)
def test_parses_open_ended_category_and_one_project(query, project_code, category):
    assert parse_single_project_inventory_intent(query) == SingleProjectInventoryIntent(
        project_code=project_code,
        category=category,
    )


@pytest.mark.parametrize(
    "query",
    [
        "Liste des projets utilisant des pompes",
        "Liste des documents du projet BCX200",
        "Quelles sont les sources du projet BCX200 ?",
        "Inventory of files for project BCX200",
        "Inventory of knowledge base sources for project BCX200",
        "Résumé du projet BCX200",
        "Liste un résumé des équipements du projet BCX200",
        "Compare les pompes du projet BCX200",
        "List a comparison of seals for project BCX200",
        "Quelles sont les différences entre pompes du projet BCX200 ?",
        "Comment installer les capteurs du projet BCX200 ?",
        "Quelles precautions de maintenance pour les pompes du projet BCX200 ?",
        "Pourquoi les pompes du projet BCX200 tombent-elles en panne ?",
        "Quels sont les objectifs du projet BCX200 ?",
        "Quels sont les risques du projet BCX200 ?",
        "What is the status of project BCX200?",
        "What are the maintenance precautions for project BCX200?",
        "What are the safety precautions for project BCX200?",
        "List repair procedures for project BCX200",
        "Liste des procédures d'installation du projet BCX200",
        "Liste l'avancement du projet BCX200",
    ],
)
def test_rejects_non_equipment_inventory_intents(query):
    assert parse_single_project_inventory_intent(query) is None


@pytest.mark.parametrize(
    "query",
    [
        "Quelles sont les pompes des projets BCX200 et BAO100 ?",
        "Quelles sont les pompes du projet BCX200 et BAO100 ?",
        "Inventory of seals for project BCX200 and project BAO100",
        "Inventory of seals for projects BCX200 and BAO100",
        "List pumps for project ABC123 and valves for project DEF456",
        "List pumps for ABC123 and valves for project DEF456",
    ],
)
def test_rejects_multi_project_requests(query):
    assert parse_single_project_inventory_intent(query) is None


@pytest.mark.parametrize(
    "query",
    [
        "Quelles sont les pompes du projet ?",
        "Liste des pompes",
        "",
    ],
)
def test_requires_an_explicit_alphanumeric_project_code(query):
    assert parse_single_project_inventory_intent(query) is None
