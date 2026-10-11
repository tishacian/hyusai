# -*- coding: utf-8 -*-
"""Diagrammes (FR) pour le document DGE — cohérence du socle vers une marketplace."""
import pih_diagrams as dg
from matplotlib.patches import FancyBboxPatch

NAVY, BLUE, GREEN, AMBER, PURPLE = dg.NAVY, dg.BLUE, dg.GREEN, dg.AMBER, dg.PURPLE
INK, MUT, LIGHT = dg.INK, dg.MUT, dg.LIGHT


def dge_socle():
    """papAI — plateforme souveraine unifiée : suites + 3 capacités sur un socle commun."""
    fig, ax = dg._fig(13, 7.4)
    bound = FancyBboxPatch((3, 3), 124, 64, boxstyle="round,pad=0,rounding_size=3",
                           linewidth=1.8, edgecolor=NAVY, facecolor="#F4F7FB", zorder=0)
    ax.add_patch(bound)
    ax.text(65, 70.6, "papAI — une seule plateforme souveraine, des capacités activées progressivement",
            ha="center", fontsize=11, color=NAVY, fontweight="bold")
    # suites (haut)
    dg._box(ax, 65, 58, 112, 9,
            [("Suites métier — verticalisées, prêtes à l'emploi", True, 11.5, AMBER),
             ("Translation · Narration · Compliance · Maintenance prédictive · Knowledge · …",
              False, 8.6, MUT)],
            fill=LIGHT[AMBER], edge=AMBER, accent=AMBER, round_r=2.2)
    # 3 capacités (milieu)
    caps = [("Data Intelligence", "papAI — DataOps\nML · MLOps", BLUE, 28),
            ("Knowledge Intelligence", "Document Center\nOCR · RAG souverain", GREEN, 65),
            ("Decision Intelligence", "Agentium — orchestration\névaluation · gouvernance", PURPLE, 102)]
    for name, sub, c, cx in caps:
        dg._box(ax, cx, 41, 35, 13, [(name, True, 11, c), (sub, False, 8.2, MUT)],
                fill=LIGHT[c], edge=c, accent=c, round_r=2.2)
    # socle commun (bas)
    dg._box(ax, 65, 22, 112, 14,
            [("Socle souverain commun", True, 12, NAVY),
             ("même infrastructure · même gouvernance · même moteur d'orchestration", False, 8.4, MUT),
             ("même modèle de sécurité · même observabilité · même expérience utilisateur · on-prem / air-gap",
              False, 8.4, MUT)],
            fill=LIGHT[NAVY], edge=NAVY, accent=NAVY, round_r=2.2)
    # flèches socle → capacités → suites
    for cx in (28, 65, 102):
        dg._arrow(ax, cx, 29.2, cx, 34.4, color=MUT, lw=1.3)
        dg._arrow(ax, cx, 47.6, cx, 53.4, color=MUT, lw=1.3)
    ax.text(65, 7.0, "Une seule plateforme, une seule licence, un seul environnement — pas trois piles technologiques distinctes",
            ha="center", fontsize=8.8, color=MUT, style="italic")
    return dg._save(fig, "dge-socle.png")


def dge_canonical():
    """Modèle canonique Agentium : Objectif → Système → Run → Évaluation → Décision → Action."""
    fig, ax = dg._fig(13, 3.2)
    chain = [("Objectif", BLUE), ("Système", PURPLE), ("Run", NAVY),
             ("Évaluation", GREEN), ("Décision", AMBER), ("Action", NAVY)]
    w, h = 18, 12
    gap = (124 - len(chain) * w) / (len(chain) - 1)
    y = 19
    xs = []
    for i, (t, c) in enumerate(chain):
        cx = 3 + w / 2 + i * (w + gap)
        xs.append(cx)
        dg._box(ax, cx, y, w, h, [(t, True, 11.5, "#FFFFFF")], fill=c, edge=c, round_r=2.2)
        if i:
            dg._arrow(ax, xs[i - 1] + w / 2 + 0.5, y, cx - w / 2 - 0.5, y, color=NAVY, lw=1.9)
    ax.text(65, 6.0, "Du modèle IA au système intelligent gouverné — un résultat mesurable, évalué et tracé",
            ha="center", fontsize=8.8, color=MUT, style="italic")
    return dg._save(fig, "dge-canonical.png")


def dge_hierarchy():
    """Hiérarchie : Skill → Capability → System → Suite."""
    fig, ax = dg._fig(13, 4.4)
    items = [
        ("Skill", "primitive cognitive", "OCR · Retrieval · Scoring\nClassification · Forecasting", GREEN),
        ("Capability", "promesse métier", "Document Understanding\nMaintenance · Compliance", BLUE),
        ("System", "assemblage de capacités", "agents · skills · workflows\nmodèles · règles · HITL", PURPLE),
        ("Suite", "verticalisée, prête à l'emploi", "Translation · Narration\nCompliance · Knowledge", AMBER),
    ]
    n = len(items); w = 27
    gap = (122 - n * w) / (n - 1)
    y = 27
    xs = []
    for i, (t, sub, ex, c) in enumerate(items):
        cx = 4 + w / 2 + i * (w + gap)
        xs.append(cx)
        dg._box(ax, cx, y, w, 16, [(t, True, 13, c), (sub, False, 8.4, MUT),
                                   ("", False, 2, MUT), (ex, False, 7.8, INK)],
                fill=LIGHT[c], edge=c, accent=c, round_r=2.2)
        if i:
            dg._arrow(ax, xs[i - 1] + w / 2 + 0.5, y, cx - w / 2 - 0.5, y, color=MUT, lw=1.9)
    ax.text(65, 8.0, "Chaque projet enrichit les catalogues de Skills, Capabilities, Systems et Suites",
            ha="center", fontsize=8.8, color=MUT, style="italic")
    return dg._save(fig, "dge-hierarchy.png")


def dge_sovereign():
    """Souveraineté de bout en bout — une propriété du système complet."""
    fig, ax = dg._fig(13, 3.4)
    bound = FancyBboxPatch((3, 9), 124, 22, boxstyle="round,pad=0,rounding_size=3",
                           linewidth=1.6, edgecolor=NAVY, facecolor="#F4F7FB",
                           linestyle=(0, (6, 4)), zorder=0)
    ax.add_patch(bound)
    ax.text(65, 27.8, "Souveraineté de bout en bout — du calcul à la décision, dans le périmètre du client",
            ha="center", fontsize=10, color=NAVY, fontweight="bold")
    layers = ["Données", "Connaissances", "Modèles", "Exécution", "Décisions", "Audit", "Gouvernance"]
    n = len(layers); w = 15.5
    gap = (118 - n * w) / (n - 1)
    y = 16
    xs = []
    for i, t in enumerate(layers):
        cx = 6 + w / 2 + i * (w + gap)
        xs.append(cx)
        dg._box(ax, cx, y, w, 8, [(t, True, 9.2, NAVY)], fill=LIGHT[NAVY], edge=NAVY,
                accent=NAVY, round_r=1.8)
        if i:
            dg._arrow(ax, xs[i - 1] + w / 2 + 0.4, y, cx - w / 2 - 0.4, y, color=MUT, lw=1.4)
    return dg._save(fig, "dge-sovereign.png")


def dge_pluralite():
    """Pluralité des cas d'usage → socle commun → marketplace réutilisable."""
    fig, ax = dg._fig(13, 5.6)
    domains = ["Transport & mobilité", "Énergie", "Santé publique",
               "Secteur public & justice", "Industrie", "Finance & assurance"]
    top, bot = 48, 8
    ys = [top - i * (top - bot) / (len(domains) - 1) for i in range(len(domains))]
    for d, y in zip(domains, ys):
        dg._box(ax, 22, y, 34, 5.6, [(d, True, 9.6, INK)], fill=dg.PANEL, edge=dg.LINE,
                accent=BLUE, round_r=1.8)
        dg._arrow(ax, 39.2, y, 56, 28, color=MUT, lw=1.1, rad=0.0)
    dg._box(ax, 73, 28, 30, 16, [("Socle papAI", True, 13, NAVY), ("commun & souverain", False, 9, MUT)],
            fill=LIGHT[NAVY], edge=NAVY, accent=NAVY, round_r=2.4)
    dg._arrow(ax, 88.2, 28, 99, 28, color=NAVY, lw=2.0)
    dg._box(ax, 114, 28, 22, 18, [("Marketplace", True, 12, AMBER), ("de Suites", True, 11, AMBER),
                                  ("& Systems", True, 11, AMBER), ("", False, 2, MUT),
                                  ("réutilisables", False, 8.6, MUT)],
            fill=LIGHT[AMBER], edge=AMBER, accent=AMBER, round_r=2.4)
    ax.text(65, 3.4, "La pluralité des cas d'usage repose sur un même socle souverain — réutilisable, gouverné, scalable",
            ha="center", fontsize=9, color=MUT, style="italic")
    return dg._save(fig, "dge-pluralite.png")


def dge_papai():
    """papAI 7 — plateforme tout-en-un (4 couches)."""
    fig, ax = dg._fig(13, 3.6)
    layers = [("Collecte de données", "intégration · nettoyage · ingestion", GREEN),
              ("Orchestration des\ninfrastructures", "sur site · cloud · hybride", BLUE),
              ("Entraînement des modèles", "MLOps · AutoML · fine-tuning", PURPLE),
              ("Déploiement de l'IA", "API · apps · edge", AMBER)]
    n = len(layers); w = 27
    gap = (122 - n * w) / (n - 1)
    y = 20
    xs = []
    for i, (t, sub, c) in enumerate(layers):
        cx = 4 + w / 2 + i * (w + gap)
        xs.append(cx)
        dg._box(ax, cx, y, w, 15, [(t, True, 10.5, c), (sub, False, 8.4, MUT)],
                fill=LIGHT[c], edge=c, accent=c, round_r=2.2)
        if i:
            dg._arrow(ax, xs[i - 1] + w / 2 + 0.5, y, cx - w / 2 - 0.5, y, color=MUT, lw=1.7)
    ax.text(65, 6.0, "Une plateforme IA tout-en-un, de la donnée au déploiement — souveraine (SaaS ou on-premise)",
            ha="center", fontsize=8.8, color=MUT, style="italic")
    return dg._save(fig, "dge-papai.png")


def dge_edge():
    """Edge AI & apprentissage fédéré souverain (HyperOpenX / OpenSVC)."""
    fig, ax = dg._fig(13, 5.6)
    bound = FancyBboxPatch((3, 3), 124, 48, boxstyle="round,pad=0,rounding_size=3",
                           linewidth=1.6, edgecolor=NAVY, facecolor="#F4F7FB",
                           linestyle=(0, (6, 4)), zorder=0)
    ax.add_patch(bound)
    ax.text(65, 54.4, "Edge AI & apprentissage fédéré souverain",
            ha="center", fontsize=10.5, color=NAVY, fontweight="bold")
    # agrégation fédérée (haut)
    dg._box(ax, 65, 41, 58, 11, [("Agrégation fédérée — FedAvg / FedProx", True, 11, PURPLE),
                                 ("modèle global redistribué aux sites", False, 8.6, MUT)],
            fill=LIGHT[PURPLE], edge=PURPLE, accent=PURPLE, round_r=2.2)
    # sites (bas)
    sites = [("Site 1", BLUE, 24), ("Site 2", GREEN, 65), ("Site 3", AMBER, 106)]
    for name, c, cx in sites:
        dg._box(ax, cx, 14, 34, 12, [(name, True, 11, c), ("données locales (restent sur site)", False, 8.2, MUT),
                                     ("· modèle local", False, 8.2, MUT)],
                fill=LIGHT[c], edge=c, accent=c, round_r=2.0)
        dg._arrow(ax, cx, 20.2, 65 + (cx - 65) * 0.32, 35.4, color=MUT, lw=1.4, rad=0.0)
    ax.text(65, 29.5, "deltas de modèles chiffrés & signés  (aucune donnée brute ne quitte les sites)",
            ha="center", fontsize=8.6, color=PURPLE, style="italic")
    ax.text(65, 6.0, "Orchestration souveraine portable (OpenSVC) · inférence edge multi-sites · montée en charge automatique",
            ha="center", fontsize=8.6, color=MUT, style="italic")
    return dg._save(fig, "dge-edge.png")


def dge_method():
    """Méthode de mise en œuvre : boucle opérationnelle avec HITL & qualification."""
    fig, ax = dg._fig(13, 4.6)
    bound = FancyBboxPatch((3, 9), 124, 33, boxstyle="round,pad=0,rounding_size=3",
                           linewidth=1.4, edgecolor=NAVY, facecolor="#F4F7FB",
                           linestyle=(0, (6, 4)), zorder=0)
    ax.add_patch(bound)
    steps = [("Données &", "connecteurs", GREEN),
             ("Traitement IA", "ML · RAG · vision · agents", BLUE),
             ("Qualification &", "évaluation (golden · équité · dérive)", PURPLE),
             ("Revue humaine", "HITL", AMBER),
             ("Décision /", "action", NAVY)]
    n = len(steps); w = 21
    gap = (118 - n * w) / (n - 1)
    y = 30
    xs = []
    for i, (t, sub, c) in enumerate(steps):
        cx = 6 + w / 2 + i * (w + gap)
        xs.append(cx)
        dg._box(ax, cx, y, w, 13, [(t, True, 10, c), (sub, False, 8.0, MUT)],
                fill=LIGHT[c], edge=c, accent=c, round_r=2.0)
        if i:
            dg._arrow(ax, xs[i - 1] + w / 2 + 0.5, y, cx - w / 2 - 0.5, y, color=MUT, lw=1.7)
    dg._arrow(ax, xs[-1], y - 6.6, xs[0], y - 6.6, color=AMBER, lw=1.6, rad=-0.18)
    ax.text((xs[0] + xs[-1]) / 2, 17.5, "boucle de feedback · amélioration continue",
            ha="center", fontsize=8.6, color=AMBER, style="italic")
    ax.text(65, 5.4, "Déploiement par étapes : POC timeboxé (~1 mois) → MVP → industrialisation · gouvernance & piste d'audit",
            ha="center", fontsize=8.6, color=MUT, style="italic")
    return dg._save(fig, "dge-method.png")


def dge_translation():
    """Translation Suite — pipeline gouverné en 5 phases (version épurée, sans libellés internes)."""
    fig, ax = dg._fig(13, 6.0)
    bound = FancyBboxPatch((3, 10), 124, 42, boxstyle="round,pad=0,rounding_size=3",
                           linewidth=1.4, edgecolor=NAVY, facecolor="#F4F7FB", zorder=0)
    ax.add_patch(bound)
    ax.text(65, 55.4, "Translation Suite — un pipeline de traduction gouverné, normé et auditable",
            ha="center", fontsize=10.5, color=NAVY, fontweight="bold")
    phases = [
        ("PHASE A", "Préparation", "terminologies &\nressources métier", BLUE),
        ("PHASE B", "Traduction agentique", "+ protection\ndes invariants", GREEN),
        ("PHASE C", "QA agentique", "norme SAE J2450\nagents + superviseur", AMBER),
        ("PHASE D", "Revue humaine", "HITL — expert sur\ncas résiduels", PURPLE),
        ("PHASE E", "Audit & livraison", "contrôles + verdict\nde livraison", NAVY),
    ]
    n = len(phases); w = 21.5
    gap = (120 - n * w) / (n - 1)
    y = 37
    xs = []
    for i, (ph, title, sub, c) in enumerate(phases):
        cx = 5 + w / 2 + i * (w + gap)
        xs.append(cx)
        dg._box(ax, cx, y, w, 16,
                [(ph, True, 7.5, c), (title, True, 9.2, c), (sub, False, 7.4, MUT)],
                fill=LIGHT[c], edge=c, accent=c, round_r=2.0)
        if i:
            dg._arrow(ax, xs[i - 1] + w / 2 + 0.4, y, cx - w / 2 - 0.4, y, color=MUT, lw=1.6)
    dg._arrow(ax, xs[4], 25.5, xs[2], 25.5, color="#C0392B", lw=1.5, rad=-0.18)
    ax.text((xs[2] + xs[4]) / 2, 21.8, "replay si défaut bloquant", ha="center",
            fontsize=8, color="#C0392B", style="italic")
    dg._arrow(ax, xs[4], 17.3, xs[0], 17.3, color=GREEN, lw=1.5, rad=-0.14)
    ax.text((xs[0] + xs[4]) / 2, 13.6, "feedback : enrichissement continu du corpus", ha="center",
            fontsize=8, color=GREEN, style="italic")
    ax.text(65, 5.6, "Qualité normée (SAE J2450) · revue humaine ciblée · audit déterministe — souverain, de bout en bout",
            ha="center", fontsize=8.6, color=MUT, style="italic")
    return dg._save(fig, "dge-translation.png")


def dge_carakai():
    """CarakAI (SGP) — chaîne de caractérisation des déblais, stylisée (maison)."""
    fig, ax = dg._fig(13, 4.8)
    bound = FancyBboxPatch((3, 11), 124, 31, boxstyle="round,pad=0,rounding_size=3",
                           linewidth=1.4, edgecolor=NAVY, facecolor="#F4F7FB", zorder=0)
    ax.add_patch(bound)
    ax.text(65, 45.4, "CarakAI — de la donnée terrain à la décision réglementaire, tracée",
            ha="center", fontsize=10.5, color=NAVY, fontweight="bold")
    steps = [
        ("ENTRÉE", "Bordereaux PDF", "déblais entrants", GREEN),
        ("OCR", "Extraction", "mesures des\ncomposés chimiques", BLUE),
        ("RÉFÉRENTIEL", "Rapprochement", "règles de contrôle\npar composé", AMBER),
        ("DÉCISION", "Validation exutoire", "score d'admissibilité\n+ revue humaine", PURPLE),
        ("SORTIE", "Résultat structuré", "XML / TXT · tracé", NAVY),
    ]
    n = len(steps); w = 21.5
    gap = (120 - n * w) / (n - 1)
    y = 28
    xs = []
    for i, (lbl, title, sub, c) in enumerate(steps):
        cx = 5 + w / 2 + i * (w + gap)
        xs.append(cx)
        dg._box(ax, cx, y, w, 15,
                [(lbl, True, 7.5, c), (title, True, 9.2, c), (sub, False, 7.4, MUT)],
                fill=LIGHT[c], edge=c, accent=c, round_r=2.0)
        if i:
            dg._arrow(ax, xs[i - 1] + w / 2 + 0.4, y, cx - w / 2 - 0.4, y, color=MUT, lw=1.6)
    ax.text(65, 6.2, "Contrôle réglementaire fiabilisé · validation humaine (HITL) · intégré à la traçabilité des déblais (T-REX)",
            ha="center", fontsize=8.6, color=MUT, style="italic")
    return dg._save(fig, "dge-carakai.png")


ALL = [dge_socle, dge_canonical, dge_hierarchy, dge_sovereign,
       dge_pluralite, dge_papai, dge_edge, dge_method, dge_translation, dge_carakai]

if __name__ == "__main__":
    for fn in ALL:
        print("rendered:", fn())
