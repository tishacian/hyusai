"""Install the self-hosted Translation Suite into a workspace.

Explicit and tenant-scoped, like the other showcase installers: it never runs
on startup and refuses to install twice. It creates three published Systems
chained by events, the pinned Skills they call, and the review app:

* **Lancement** (``deposit.promoted``): a person confirms, then the staged pack
  is prepared on the workspace's runner.
* **Enchaînement** (``remote_runner.job_finished``): routes each finished
  command to the next one (translate, export the segments to review, open one
  review set per language, audit after reinjection) and asks a person before
  packaging for delivery.
* **Retour des relecteurs** (``review_set.completed``): reads the reviewers'
  corrections and, once a person confirms, reinjects them.

The machine side is the pipeline's ``ts.runner`` entry point, reached through
the runner named by ``runner_slug``; see
docs/agentium-translation-suite-runner-contract.md.
"""

from __future__ import annotations

import copy
from typing import Any

from app.core.iam.roles import WORKSPACE_ADMIN, WORKSPACE_OWNER, normalize_role_template
from app.models.experience import Experience
from app.models.remote_runner import RemoteRunner
from app.models.skill import Skill
from app.models.system import System
from app.models.workspace import WorkspaceMember
from app.services.experience import lifecycle
from app.services.remote_runners.catalogs import translation_suite as commands
from app.services.skills_registry.binding import workspace_skill_slug
from app.services.skills_registry.executors import validate_executor_binding
from app.services.skills_registry.seed import SEED_SKILLS
from app.services.systems import flow_publication

BLUEPRINT = "translation-suite-v1"
APP_SLUG = "translation-suite"
NAMESPACE = "translation.segment"
BUILTINS = ("remote_job_submit_v1", "review_set_open_v1", "review_set_read_v1")
REQUIRED_COMMANDS = tuple(
    spec.key
    for spec in (
        commands.PREPARE,
        commands.TRANSLATE,
        commands.REVIEW_EXPORT,
        commands.AUDIT,
        commands.REINJECT,
        commands.PACKAGE,
    )
)

# SAE J2450: seven categories, minor or major. The per-category weights of the
# standard are approximated by one weight per severity in this first version.
J2450_TAXONOMY = {
    "categories": [
        {"key": "WT", "label": "Terme erroné", "severities": ["minor", "major"]},
        {"key": "SE", "label": "Erreur de syntaxe", "severities": ["minor", "major"]},
        {"key": "OM", "label": "Omission", "severities": ["minor", "major"]},
        {"key": "SA", "label": "Accord", "severities": ["minor", "major"]},
        {"key": "SP", "label": "Orthographe", "severities": ["minor", "major"]},
        {"key": "PE", "label": "Ponctuation", "severities": ["minor", "major"]},
        {"key": "ME", "label": "Erreur diverse", "severities": ["minor", "major"]},
    ],
    "comment_required_for": ["major"],
    "severity_weights": {"minor": 2, "major": 4},
    "severity_order": ["minor", "major"],
}
TIER_POLICY = {
    "tiers": [
        {"key": "P0", "label": "P0 · sécurité avec erreur"},
        {"key": "P1", "label": "P1 · sécurité"},
        {"key": "P2", "label": "P2 · erreur majeure"},
        {
            "key": "P3",
            "label": "P3 · erreur mineure",
            "unlock_after": {"tiers": ["P0", "P1", "P2"], "threshold": 1.0},
        },
        {
            "key": "P4",
            "label": "P4 · contrôle",
            "unlock_after": {"tiers": ["P0", "P1", "P2"], "threshold": 1.0},
        },
    ],
    "package_weight": 2000,
}


class InstallError(ValueError):
    pass


def _require_admin(db, workspace, actor) -> None:
    member = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == actor.id)
        .one_or_none()
    )
    if not member or normalize_role_template(member.role_template, member.role) not in {
        WORKSPACE_OWNER,
        WORKSPACE_ADMIN,
    }:
        raise InstallError("TRANSLATION_INSTALL_ADMIN_REQUIRED")


def _require_runner(db, workspace, runner_slug: str) -> RemoteRunner:
    runner = (
        db.query(RemoteRunner).filter_by(workspace_id=workspace.id, slug=runner_slug).one_or_none()
    )
    if runner is None:
        raise InstallError("TRANSLATION_INSTALL_RUNNER_MISSING")
    missing = sorted(set(REQUIRED_COMMANDS) - set(runner.allowed_commands or []))
    if missing:
        raise InstallError("TRANSLATION_INSTALL_RUNNER_COMMANDS_MISSING: " + ", ".join(missing))
    labels = set((runner.labels or {}).keys())
    if not set(commands.PATHS) <= labels:
        raise InstallError("TRANSLATION_INSTALL_RUNNER_PATHS_MISSING")
    return runner


def _builtins(db) -> dict[str, Skill]:
    for definition in SEED_SKILLS:
        if (
            definition["slug"] in BUILTINS
            and not db.query(Skill).filter(Skill.slug == definition["slug"]).first()
        ):
            db.add(Skill(**definition, is_seeded="Y", workspace_id=None))
    db.flush()
    rows = {s.slug: s for s in db.query(Skill).filter(Skill.slug.in_(BUILTINS)).all()}
    if set(rows) != set(BUILTINS):
        raise InstallError("TRANSLATION_INSTALL_SKILLS_MISSING")
    return rows


def _pinned_skill(
    db, workspace, *, local: str, name: str, target: Skill, frozen: dict[str, Any]
) -> Skill:
    slug = workspace_skill_slug(workspace_id=workspace.id, local_name=local).slug
    if db.query(Skill).filter(Skill.slug == slug).first():
        raise InstallError("TRANSLATION_INSTALL_ALREADY_EXISTS_REVIEW_REQUIRED")
    row = Skill(
        workspace_id=workspace.id,
        slug=slug,
        name=name,
        description=f"{target.name}, réglé pour la Translation Suite.",
        type=target.type,
        category=target.category,
        input_schema=copy.deepcopy(target.input_schema or {}),
        output_schema=copy.deepcopy(target.output_schema or {}),
        executor=validate_executor_binding(
            {"kind": "registry_call", "params": {"skill_slug": target.slug, "frozen_input": frozen}}
        ),
        execution=copy.deepcopy(target.execution or {}),
        pricing=copy.deepcopy(target.pricing or {}),
        certification_level="basic",
        is_seeded="N",
        provider="internal",
    )
    db.add(row)
    db.flush()
    return row


def _new_system(db, workspace, actor, *, key: str, name: str, objective: str, skills) -> System:
    system = System(
        workspace_id=workspace.id,
        blueprint_key=f"{BLUEPRINT}:{key}",
        name=name,
        objective=objective,
        execution_mode="event_driven_automation",
        status="draft",
        created_by=actor.email,
        skill_ids=[s.id for s in skills],
        flow_definition={"nodes": [], "edges": []},
        settings={"event_trigger": {"mode": "live"}},
    )
    db.add(system)
    db.flush()
    flow_publication.initialize_new_system_publication_if_enabled(
        db, system=system, workspace=workspace, actor=actor.email
    )
    return system


def _publish(db, workspace, actor, system: System, flow: dict, message: str) -> str:
    draft, _ = flow_publication.save_draft(
        db,
        system_id=system.id,
        workspace=workspace,
        flow_definition=flow,
        expected_revision=1,
        actor=actor.email,
    )
    version, _, _ = flow_publication.publish_draft(
        db,
        system_id=system.id,
        workspace=workspace,
        expected_draft_revision=draft.revision,
        expected_published_version_id=system.published_flow_version_id,
        message=message,
        breaking_change_intent=None,
        actor=actor.email,
    )
    system.status = "active"
    db.flush()
    return version.id


def _event_source(node_id: str, node_type: str, label: str, properties: dict) -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "kind": "source",
        "label": label,
        "config": {
            "input_schema": {
                "type": "object",
                "additionalProperties": True,
                "properties": properties,
            }
        },
    }


def _task(node_id: str, label: str, skill: Skill, inputs_map: dict[str, Any] | None = None) -> dict:
    config: dict[str, Any] = {"skill_slug": skill.slug}
    if inputs_map:
        config["inputs_map"] = inputs_map
    return {"id": node_id, "type": "skill", "kind": "task", "label": label, "config": config}


def _hitl(node_id: str, label: str, prompt: str) -> dict:
    return {
        "id": node_id,
        "type": "hitl",
        "kind": "hitl",
        "label": label,
        "config": {"prompt": prompt, "prompt_kind": "approve_write", "expiry_action": "reject"},
    }


def _sink(node_id: str, label: str) -> dict:
    return {"id": node_id, "type": "sink", "kind": "sink", "label": label}


def _edge(src: str, dst: str, branch: str | None = None) -> dict:
    edge: dict[str, Any] = {"from": src, "to": dst, "kind": "branch" if branch else "data"}
    if branch:
        edge["branch_label"] = branch
    return edge


def launch_flow(prepare: Skill) -> dict:
    return {
        "schema_version": 3,
        "nodes": [
            _event_source(
                "source.deposit",
                "source.deposit_promoted",
                "Pack source promu",
                {"collection_slug": {"type": "string"}, "file_ids": {"type": "array"}},
            ),
            _hitl(
                "hitl.launch",
                "Lancer la préparation",
                "Vérifiez le pack promu et le nom du lot (la collection de promotion). "
                "Acceptez pour préparer le lot sur la machine de traduction.",
            ),
            _task(
                "task.prepare",
                "Préparer le lot",
                prepare,
                {"lot": "run.collection_slug", "file_ids": "run.file_ids"},
            ),
            _sink("sink.queued", "Préparation lancée"),
        ],
        "edges": [
            _edge("source.deposit", "hitl.launch"),
            _edge("hitl.launch", "task.prepare"),
            _edge("task.prepare", "sink.queued"),
        ],
    }


def chain_flow(skills: dict[str, Skill]) -> dict:
    lot = {"lot": "run.params.lot"}
    route = {
        "id": "decision.route",
        "type": "decision",
        "kind": "decision",
        "label": "Étape suivante",
        "config": {
            "passthrough_inputs": ["command", "status", "job_id", "params", "result"],
            "branches": [
                {
                    "label": "prepared",
                    "condition": "command == 'translation_suite.prepare' and status == 'succeeded'",
                },
                {
                    "label": "translated",
                    "condition": "command == 'translation_suite.translate' and status == 'succeeded'",
                },
                {
                    "label": "exported",
                    "condition": "command == 'translation_suite.review_export' and status == 'succeeded'",
                },
                {
                    "label": "reinjected",
                    "condition": "command == 'translation_suite.reinject' and status == 'succeeded'",
                },
                {
                    "label": "audited",
                    "condition": "command == 'translation_suite.audit' and status == 'succeeded'",
                },
                {"label": "other", "condition": "True"},
            ],
            "default_branch": "other",
        },
    }
    return {
        "schema_version": 3,
        "nodes": [
            _event_source(
                "source.job",
                "source.remote_job_finished",
                "Commande terminée sur la machine",
                {
                    "job_id": {"type": "string"},
                    "command": {"type": "string"},
                    "status": {"type": "string"},
                    "params": {"type": "object"},
                    "result": {"type": ["object", "null"]},
                },
            ),
            route,
            _task("task.translate", "Traduire et contrôler", skills["translate"], lot),
            _task("task.export", "Exporter les segments à relire", skills["export"], lot),
            _task(
                "task.review",
                "Ouvrir la revue par langue",
                skills["review_open"],
                {"job_id": "run.job_id", "lot": "run.params.lot"},
            ),
            _task("task.audit", "Auditer le lot", skills["audit"], lot),
            _hitl(
                "hitl.deliver",
                "Valider la livraison",
                "Vérifiez le verdict d'audit du lot. Acceptez pour construire le paquet de livraison.",
            ),
            _task("task.package", "Empaqueter le lot", skills["package"], lot),
            _sink("sink.next", "Étape suivante lancée"),
            _sink("sink.review", "Revue ouverte"),
            _sink("sink.packaged", "Paquet demandé"),
            _sink("sink.stopped", "Aucune suite automatique"),
        ],
        "edges": [
            _edge("source.job", "decision.route"),
            _edge("decision.route", "task.translate", "prepared"),
            _edge("decision.route", "task.export", "translated"),
            _edge("decision.route", "task.review", "exported"),
            _edge("decision.route", "task.audit", "reinjected"),
            _edge("decision.route", "hitl.deliver", "audited"),
            _edge("decision.route", "sink.stopped", "other"),
            _edge("task.translate", "sink.next"),
            _edge("task.export", "sink.next"),
            _edge("task.audit", "sink.next"),
            _edge("task.review", "sink.review"),
            _edge("hitl.deliver", "task.package"),
            _edge("task.package", "sink.packaged"),
        ],
    }


def feedback_flow(read: Skill, reinject: Skill) -> dict:
    return {
        "schema_version": 3,
        "nodes": [
            _event_source(
                "source.review",
                "source.review_set_completed",
                "Revue terminée",
                {"set_id": {"type": "string"}, "group_labels": {"type": "object"}},
            ),
            {
                "id": "task.read",
                "type": "skill",
                "kind": "task",
                "label": "Lire les corrections",
                "config": {"skill_slug": read.slug, "inputs_map": {"set_id": "run.set_id"}},
            },
            _hitl(
                "hitl.reinject",
                "Valider la réinjection",
                "Vérifiez les corrections des relecteurs. Acceptez pour les réinjecter dans le lot.",
            ),
            _task(
                "task.reinject",
                "Réinjecter les corrections",
                reinject,
                {
                    "lot": "run.group_labels.lot",
                    "decisions": {"node_id": "task.read", "path": ["decisions"]},
                },
            ),
            _sink("sink.reinjected", "Réinjection lancée"),
        ],
        "edges": [
            _edge("source.review", "task.read"),
            _edge("task.read", "hitl.reinject"),
            _edge("hitl.reinject", "task.reinject"),
            _edge("task.reinject", "sink.reinjected"),
        ],
    }


_APP_COPY = {
    "ts.page.review": ("Revue", "Review"),
    "ts.page.steering": ("Pilotage", "Steering"),
    "ts.review.title": ("Segments à relire", "Segments to review"),
    "ts.review.description": (
        "Un lot de revue par langue. Les niveaux P3 et P4 s'ouvrent quand P0 à P2 sont relus.",
        "One review set per language. Tiers P3 and P4 open once P0 to P2 are reviewed.",
    ),
    "ts.matrix.title": ("Avancement par lot et par langue", "Progress by lot and language"),
}


def _t(key: str) -> dict[str, str]:
    return {"$i18n": key, "fallback": _APP_COPY[key][0]}


APP_PAGES = {
    "pages": [
        {
            "id": "revue",
            "title": _t("ts.page.review"),
            "components": [
                {
                    "type": "review_workbench",
                    "id": "review",
                    "props": {
                        "title": _t("ts.review.title"),
                        "description": _t("ts.review.description"),
                        "namespace": NAMESPACE,
                    },
                }
            ],
        },
        {
            "id": "pilotage",
            "title": _t("ts.page.steering"),
            "components": [
                {
                    "type": "review_matrix",
                    "id": "matrix",
                    "props": {
                        "title": _t("ts.matrix.title"),
                        "namespace": NAMESPACE,
                        "rowLabel": "lot",
                        "columnLabel": "language",
                        "extendDays": 2,
                    },
                }
            ],
        },
    ],
    "i18n": {
        "fr": {key: fr for key, (fr, _en) in _APP_COPY.items()},
        "en": {key: en for key, (_fr, en) in _APP_COPY.items()},
    },
}


def install(db, workspace, actor, *, runner_slug: str, activate: bool = False) -> dict[str, Any]:
    _require_admin(db, workspace, actor)
    runner = _require_runner(db, workspace, runner_slug)
    if (
        db.query(System.id)
        .filter(System.workspace_id == workspace.id, System.blueprint_key.like(f"{BLUEPRINT}:%"))
        .first()
        or db.query(Experience.id)
        .filter(Experience.workspace_id == workspace.id, Experience.slug == APP_SLUG)
        .first()
    ):
        raise InstallError("TRANSLATION_INSTALL_ALREADY_EXISTS_REVIEW_REQUIRED")

    settings = copy.deepcopy(workspace.settings or {})
    settings.setdefault("features", {}).update(
        {"experience_v1": True, "flow_publication_v1": True, "enable_event_triggers": True}
    )
    workspace.settings = settings
    db.flush()

    builtin = _builtins(db)
    launch = _new_system(
        db,
        workspace,
        actor,
        key="launch",
        name="Translation Suite · Lancement",
        objective="Préparer un lot à partir d'un pack source promu, après validation.",
        skills=[builtin["remote_job_submit_v1"]],
    )
    chain = _new_system(
        db,
        workspace,
        actor,
        key="chain",
        name="Translation Suite · Enchaînement",
        objective="Enchaîner traduction, contrôle, revue, audit et livraison du lot.",
        skills=list(builtin.values()),
    )
    feedback = _new_system(
        db,
        workspace,
        actor,
        key="feedback",
        name="Translation Suite · Retour des relecteurs",
        objective="Réinjecter les corrections des relecteurs dans le lot, après validation.",
        skills=[builtin["review_set_read_v1"], builtin["remote_job_submit_v1"]],
    )

    def job(local: str, name: str, command: str, extra: dict | None = None) -> Skill:
        frozen = {
            "runner": runner.slug,
            "command": command,
            "param_keys": ["lot"],
            "notify_system_id": chain.id,
            **(extra or {}),
        }
        return _pinned_skill(
            db,
            workspace,
            local=local,
            name=name,
            target=builtin["remote_job_submit_v1"],
            frozen=frozen,
        )

    skills = {
        "prepare": job("ts_prepare", "Préparer un lot", commands.PREPARE.key),
        "translate": job("ts_translate", "Traduire un lot", commands.TRANSLATE.key),
        "export": job("ts_review_export", "Exporter la revue", commands.REVIEW_EXPORT.key),
        "audit": job("ts_audit", "Auditer un lot", commands.AUDIT.key),
        "reinject": job(
            "ts_reinject",
            "Réinjecter les corrections",
            commands.REINJECT.key,
            {"document_keys": {"decisions.jsonl": "decisions"}},
        ),
        "package": job("ts_package", "Empaqueter un lot", commands.PACKAGE.key),
        "review_open": _pinned_skill(
            db,
            workspace,
            local="ts_review_open",
            name="Ouvrir la revue",
            target=builtin["review_set_open_v1"],
            frozen={
                "namespace": NAMESPACE,
                "title": "Revue de traduction",
                "artifact": "review.jsonl",
                "group_key_from": "lot",
                "label_from": {"lot": "lot"},
                "split_by_group": True,
                "group_label": "language",
                "taxonomy": J2450_TAXONOMY,
                "policy": TIER_POLICY,
                "deadline_days": 7,
                "notify_system_id": feedback.id,
            },
        ),
    }

    # A published flow may only call Skills bound to its System.
    launch.skill_ids = [skills["prepare"].id]
    chain.skill_ids = [
        skills[k].id for k in ("translate", "export", "review_open", "audit", "package")
    ]
    feedback.skill_ids = [builtin["review_set_read_v1"].id, skills["reinject"].id]
    db.flush()

    versions = {
        "launch": _publish(
            db,
            workspace,
            actor,
            launch,
            launch_flow(skills["prepare"]),
            "Lancement v1 : préparation après validation humaine.",
        ),
        "chain": _publish(
            db,
            workspace,
            actor,
            chain,
            chain_flow(skills),
            "Enchaînement v1 : traduction, revue, audit, livraison validée.",
        ),
        "feedback": _publish(
            db,
            workspace,
            actor,
            feedback,
            feedback_flow(builtin["review_set_read_v1"], skills["reinject"]),
            "Retour des relecteurs v1 : réinjection après validation.",
        ),
    }

    experience, draft = lifecycle.create_experience(
        db,
        workspace=workspace,
        actor=actor.email,
        name="Translation Suite",
        slug=APP_SLUG,
        pattern="queue",
        languages=["fr", "en"],
        theme={},
        access_policy={"roles": []},
        emblem="◇",
        description="Revue des segments traduits par langue et pilotage des lots.",
    )
    draft = lifecycle.save_draft(
        db,
        workspace_id=workspace.id,
        experience_id=experience.id,
        pages=copy.deepcopy(APP_PAGES),
        binding_keys=[],
        expected_revision=draft.revision,
        actor=actor.email,
    )
    check = lifecycle.ready_check(db, workspace=workspace, experience_id=experience.id)
    if check["blockers"]:
        raise InstallError(
            "TRANSLATION_INSTALL_APP_NOT_READY: "
            + ", ".join(str(b.get("code") if isinstance(b, dict) else b) for b in check["blockers"])
        )
    release = lifecycle.create_release(
        db,
        workspace=workspace,
        experience_id=experience.id,
        notes="Translation Suite v1",
        expected_draft_revision=draft.revision,
        expected_content_sha256=draft.content_sha256,
        expected_experience_updated_at=experience.updated_at,
        expected_bindings_sha256=check["bindings_sha256"],
        actor=actor.email,
    )
    deployment = lifecycle.deploy(
        db,
        workspace=workspace,
        experience_id=experience.id,
        channel="live" if activate else "pilot",
        release_id=release.id,
        expected_current_release_id=None,
        expected_deployment_updated_at=None,
        audience={"roles": []} if activate else {"roles": [WORKSPACE_OWNER, WORKSPACE_ADMIN]},
        actor=actor.email,
    )
    return {
        "workspace_id": workspace.id,
        "systems": {"launch": launch.id, "chain": chain.id, "feedback": feedback.id},
        "published_versions": versions,
        "skills": {key: skill.slug for key, skill in skills.items()},
        "experience_id": experience.id,
        "release_id": release.id,
        "deployment_id": deployment.id,
        "channel": deployment.channel,
    }
