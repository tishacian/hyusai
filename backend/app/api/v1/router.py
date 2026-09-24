"""API v1 router"""
from fastapi import APIRouter

from app.api.v1.endpoints import (
    action_plans,
    actions,
    admin,
    agents,
    apps,
    automation_edit,
    assistant,
    audit,
    auth,
    blueprints,
    build_info,
    calendar,
    capabilities,
    catalog,
    catalog_curation,
    chat,
    client360,
    contexts,
    control_plane,
    datasets,
    documents,
    evaluation,
    evaluation_campaigns,
    evaluation_corrections,
    flow_diffs,
    flow_ingresses,
    flow_publication,
    mandates,
    flow_runner,
    flow_workbench,
    hana,
    health,
    help_content,
    hooks,  # public HMAC webhook ingress
    hypervisor,
    iam,
    impact,
    intelligence,
    knowledge,
    knowledge_capture,
    livekit,
    maps,
    maritime,
    mcp,
    meetings,
    metrics,
    mission_room,
    ml_models,
    model_portal,
    models,
    observability,
    presets,
    reasoning,
    recipes,
    reports,
    rpa,
    runs,
    secure_deposit,
    sessions,
    settings,
    sharepoint,
    skills,
    # Canonical (mental-model) layer.
    experiences,
    system_bindings,
    systems,
    work,
    tasks,
    telemetry,
    traces,
    value_loop,
    value_contracts,
    visual_intelligence,
    voice,
    webcam_proxy,
    workspace_app_governance,
    workspace_jobs,
)

api_router = APIRouter()

# Public, secret-free deployment identity used by protected canaries before
# they authenticate. It deliberately lives at /api/v1/build-info.
api_router.include_router(build_info.router, prefix="/build-info", tags=["build-info"])

# OmniRAG engine — preserved.
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(models.router, prefix="/models", tags=["models"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(assistant.router, prefix="/assistant", tags=["assistant"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(agents.router, prefix="/agents", tags=["agents (legacy alias of /systems)"])
api_router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
api_router.include_router(metrics.router, prefix="/metrics", tags=["metrics"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings (legacy proxy over /presets default)"])
api_router.include_router(presets.router, prefix="/presets", tags=["presets"])
api_router.include_router(traces.router, prefix="/traces", tags=["traces (legacy alias of /runs)"])
api_router.include_router(audit.router, prefix="/audit", tags=["audit"])
api_router.include_router(voice.router, prefix="/voice", tags=["voice"])
api_router.include_router(livekit.router, prefix="/livekit", tags=["livekit"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(evaluation_corrections.router, prefix="/evaluation/corrections", tags=["evaluation"])
api_router.include_router(evaluation.router, prefix="/evaluation", tags=["evaluation"])
api_router.include_router(evaluation_campaigns.router, prefix="/evaluation", tags=["evaluation"])
api_router.include_router(observability.router, prefix="/observability", tags=["observability"])
api_router.include_router(intelligence.router, prefix="/intelligence", tags=["intelligence"])
api_router.include_router(sharepoint.router, prefix="/sharepoint", tags=["sharepoint"])
api_router.include_router(hana.router, prefix="/hana", tags=["hana"])
api_router.include_router(rpa.router, prefix="/rpa", tags=["rpa"])
api_router.include_router(mcp.router, prefix="/mcp", tags=["mcp"])
api_router.include_router(apps.router, prefix="/workspaces", tags=["apps"])
api_router.include_router(model_portal.router, prefix="/models", tags=["model-portal"])

# Canonical mental-model layer.
api_router.include_router(systems.router,       prefix="/systems",       tags=["systems"])
api_router.include_router(
    system_bindings.router,
    prefix="/system-bindings",
    tags=["system-bindings"],
)
api_router.include_router(
    experiences.router,
    prefix="/experiences",
    tags=["experiences"],
)
api_router.include_router(work.router, prefix="/work", tags=["work"])
api_router.include_router(flow_publication.router, prefix="/systems", tags=["flow-publication"])
api_router.include_router(automation_edit.router, prefix="/systems", tags=["automation-edit"])
api_router.include_router(mandates.router, tags=["mandates"])
api_router.include_router(flow_ingresses.router, prefix="/systems", tags=["flow-ingresses"])
api_router.include_router(flow_runner.router, prefix="/systems", tags=["flow-runner"])
api_router.include_router(flow_workbench.router, prefix="/systems", tags=["flow-workbench"])
api_router.include_router(flow_diffs.router, prefix="/systems", tags=["flow-diffs"])
api_router.include_router(value_loop.router,    prefix="/systems",       tags=["value-loop"])
api_router.include_router(value_contracts.router, prefix="/systems", tags=["value-contract"])
api_router.include_router(capabilities.router,  prefix="/capabilities",  tags=["capabilities"])
api_router.include_router(skills.router,        prefix="/skills",        tags=["skills"])
api_router.include_router(runs.router,          prefix="/runs",          tags=["runs"])
api_router.include_router(recipes.envs_router, prefix="/python-envs", tags=["python-envs"])
api_router.include_router(
    recipes.executions_router,
    prefix="/recipe-executions",
    tags=["recipe-executions"],
)
api_router.include_router(datasets.router, prefix="/datasets", tags=["datasets"])
api_router.include_router(ml_models.router, prefix="/ml-models", tags=["ml-models"])
api_router.include_router(impact.router,        prefix="/impact",        tags=["impact"])
api_router.include_router(hypervisor.router,    prefix="/hypervisor",    tags=["hypervisor"])
api_router.include_router(control_plane.router, prefix="/control-plane", tags=["control-plane"])
api_router.include_router(contexts.router,      prefix="/contexts",      tags=["contexts"])
api_router.include_router(reasoning.router,     prefix="/reasoning",     tags=["reasoning"])
api_router.include_router(help_content.router,  prefix="/help-content",  tags=["help-content"])
api_router.include_router(telemetry.router,      prefix="/telemetry",     tags=["telemetry"])
api_router.include_router(knowledge.router,      prefix="/knowledge",     tags=["knowledge"])
api_router.include_router(knowledge_capture.router, prefix="/knowledge-capture", tags=["knowledge-capture"])
api_router.include_router(iam.router, prefix="/iam", tags=["iam"])
api_router.include_router(secure_deposit.internal_router, prefix="/sftp", tags=["secure-deposit"])
api_router.include_router(secure_deposit.public_router, prefix="/deposit-links", tags=["deposit-links"])
# Public HMAC webhook ingress (no workspace JWT).
api_router.include_router(hooks.router, prefix="/hooks", tags=["hooks"])
api_router.include_router(catalog.router, prefix="/catalog", tags=["catalog"])
api_router.include_router(catalog_curation.router, prefix="/catalog", tags=["catalog"])
api_router.include_router(blueprints.router, prefix="/blueprints", tags=["blueprints"])
api_router.include_router(
    workspace_app_governance.router,
    prefix="/governance/workspace-apps",
    tags=["workspace-app-governance"],
)
api_router.include_router(mission_room.router, prefix="/mission-room", tags=["mission-room"])
api_router.include_router(calendar.router, prefix="/calendar", tags=["calendar"])
api_router.include_router(action_plans.router, prefix="/action-plans", tags=["action-plans"])
api_router.include_router(actions.router, prefix="/actions", tags=["actions"])
api_router.include_router(workspace_jobs.router, prefix="/workspace-jobs", tags=["workspace-jobs"])
api_router.include_router(maps.router, prefix="/maps", tags=["maps"])
api_router.include_router(visual_intelligence.router, prefix="/visual-intelligence", tags=["visual-intelligence"])
api_router.include_router(meetings.router, prefix="/meetings", tags=["meetings"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(maritime.router, prefix="/mission-room/maritime", tags=["mission-room", "maritime"])
api_router.include_router(webcam_proxy.router, prefix="/mission-room/webcams", tags=["mission-room", "webcam-proxy"])
api_router.include_router(client360.router, prefix="/client360", tags=["client360"])
