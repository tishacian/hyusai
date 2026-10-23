"""Skill registry: seeded slug -> wrapper callable, and its runtime status.

See the package docstring for the tri-state status contract.
"""

from __future__ import annotations

import importlib
from typing import Any, Optional

from app.services.skills_registry.wrappers.skills import (
    SkillBindingError,
    SkillCallable,
    _action_plan_cancel_v1,
    _action_plan_create_v1,
    _action_plan_reschedule_v1,
    _action_plan_status_v1,
    _audit_log_v1,
    _azure_llm_v1,
    _azure_openai_llm_v1,
    _briefing_priorities_v1,
    _calendar_cancel_event_v1,
    _calendar_create_event_v1,
    _calendar_daily_summary_v1,
    _calendar_read_v1,
    _calendar_update_event_v1,
    _capture_structuring_v1,
    _causal_drill_v1,
    _chain_hybrid_v1,
    _chain_mixed_hah_v1,
    _chain_naive_v1,
    _chat_agentic_plan_v1,
    _chat_grounding_policy_v1,
    _chat_self_correct_v1,
    _chat_trivial_bypass_v1,
    _claim_audit_v1,
    _connector_read_v1,
    _connector_write_request_v1,
    _data_prep_v1,
    _dbt_transform_v1,
    _decide_next_v1,
    _decision_option_rank_v1,
    _document_ingestion_v1,
    _draft_email_v1,
    _draft_response_email_v1,
    _eval_radar_v1,
    _evaluate_v1,
    _evaluate_v2,
    _evidence_graph_build_v1,
    _expert_answer_evaluator_v1,
    _expert_interview_plan_v1,
    _generate_recommendations_v1,
    _grounding_check_v1,
    _hf_dataset_import_v1,
    _hikma_list_pos_by_type_v1,
    _instruction_draft_v1,
    _intelligence_batch_v1,
    _invoice_document_extract_v1,
    _knowledge_gap_analysis_v1,
    _line_items_reconcile_v1,
    _llm_label_dataset_v1,
    _llm_rag_answer_v1,
    _map_command_apply_v1,
    _map_layer_read_v1,
    _map_recommendation_generate_v1,
    _map_signal_attach_v1,
    _map_zone_score_v1,
    _maritime_snapshot_read_v1,
    _mcp_call_v1,
    _ministerial_briefing_v1,
    _ml_batch_score_v1,
    _ml_evaluation_review_v1,
    _ml_experiment_plan_v1,
    _ml_forecast_v1,
    _ml_monitor_model_v1,
    _ml_predict_v1,
    _ml_problem_frame_v1,
    _ml_retrain_model_v1,
    _ml_train_sklearn_v1,
    _multi_hop_retrieve_v1,
    _narration_run_v1,
    _news_signal_synthesis_v1,
    _ollama_llm_v1,
    _openai_llm_v1,
    _osint_signal_prioritize_v1,
    _polars_transform_v1,
    _project_risk_explainer_v1,
    _publish_email_v1,
    _python_recipe_v1,
    _reconciliation_report_v1,
    _response_eval_v1,
    _role_agent_v1,
    _remote_job_submit_v1,
    _review_set_open_v1,
    _review_set_read_v1,
    _rpa_dispatch_v1,
    _rumor_origin_trace_v1,
    _sap_check_budget_v1,
    _sap_create_po_v1,
    _sap_get_justification_v1,
    _sap_hana_query_v1,
    _sap_handle_rejection_v1,
    _sap_list_approved_prs_v1,
    _sap_reject_pr_v1,
    _scenario_compare_v1,
    _scenario_generate_v1,
    _scenario_recommend_v1,
    _schedule_meeting_v1,
    _semantic_search_v1,
    _sharepoint_ingestion_v1,
    _situation_posture_score_v1,
    _skill_search_v1,
    _source_registry_refresh_v1,
    _spreadsheet_table_extract_v1,
    _sql_transform_v1,
    _stub,
    _summarize_long_document_v1,
    _system_run_read_v1,
    _territorial_action_window_v1,
    _territorial_signal_map_v1,
    _time_context_set_v1,
    _translation_showcase_stub,
    _visual_observation_sync_knowledge_v1,
    _visual_snapshot_analyze_v1,
    _visual_snapshot_capture_v1,
    _visual_source_read_v1,
    _voice_oracle_turn_v1,
    _voice_realtime_session_v1,
    _voice_realtime_speak_v1,
    _voice_realtime_transcribe_v1,
    _voice_realtime_translate_v1,
    _voice_tandem_oracle_v1,
    _voice_transcribe_v1,
    _voice_tts_v1,
    _workspace_llm_v1,
    is_workspace_skill_slug,
    logger,
)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
# (slug -> (callable, expected_module_path|None, status_hint))
# ``expected_module_path`` is the module whose import must succeed for
# the wrapper to be considered `bound`. A ``None`` path means the
# wrapper is self-contained (loggers, stubs, in-process helpers).
_REGISTRY: dict[str, tuple[SkillCallable, Optional[str], str]] = {
    "llm_rag_answer_v1": (_llm_rag_answer_v1, "app.services.rag.rag_service", "bound"),
    "semantic_search_v1": (_semantic_search_v1, "app.services.rag.context", "bound"),
    "multi_hop_retrieve_v1": (
        _multi_hop_retrieve_v1,
        "app.services.rag.comparative_retrieval",
        "bound",
    ),
    "chat_trivial_bypass_v1": (_chat_trivial_bypass_v1, None, "bound"),
    "chat_grounding_policy_v1": (
        _chat_grounding_policy_v1,
        "app.services.chat_grounding",
        "bound",
    ),
    "chat_action_resolver_v1": (_stub, None, "stub"),
    "document_ingestion_v1": (_document_ingestion_v1, "app.services.rag.document_service", "bound"),
    "eval_radar_v1": (_eval_radar_v1, "app.services.evaluation.judge", "bound"),
    "claim_audit_v1": (_claim_audit_v1, "app.services.evaluation.judge", "bound"),
    "intelligence_batch_v1": (_intelligence_batch_v1, "app.services.intelligence.batch", "bound"),
    "ministerial_briefing_v1": (_ministerial_briefing_v1, "app.services.mission_room", "bound"),
    "news_signal_synthesis_v1": (_news_signal_synthesis_v1, "app.services.mission_room", "bound"),
    "project_risk_explainer_v1": (_project_risk_explainer_v1, "app.services.mission_room", "bound"),
    "territorial_signal_map_v1": (_territorial_signal_map_v1, "app.services.mission_room", "bound"),
    "instruction_draft_v1": (_instruction_draft_v1, "app.services.mission_room", "bound"),
    "scenario_generate_v1": (_scenario_generate_v1, "app.services.scenario_engine", "bound"),
    "scenario_compare_v1": (_scenario_compare_v1, "app.services.scenario_engine", "bound"),
    "scenario_recommend_v1": (_scenario_recommend_v1, "app.services.scenario_engine", "bound"),
    "calendar_read_v1": (_calendar_read_v1, "app.services.workspace_calendar", "bound"),
    "sap_hana_query_v1": (
        _sap_hana_query_v1,
        "app.services.connectors.hana.service",
        "bound",
    ),
    "rpa_dispatch_v1": (
        _rpa_dispatch_v1,
        "app.services.connectors.rpa.service",
        "bound",
    ),
    "remote_job_submit_v1": (
        _remote_job_submit_v1,
        "app.services.remote_runners.service",
        "bound",
    ),
    "review_set_open_v1": (_review_set_open_v1, "app.services.review_sets", "bound"),
    "review_set_read_v1": (_review_set_read_v1, "app.services.review_sets", "bound"),
    "mcp_call_v1": (
        _mcp_call_v1,
        "app.services.connectors.mcp.client",
        "bound",
    ),
    "sap_list_approved_prs_v1": (
        _sap_list_approved_prs_v1,
        "app.services.connectors.mcp.client",
        "bound",
    ),
    "sap_check_budget_v1": (
        _sap_check_budget_v1,
        "app.services.connectors.mcp.client",
        "bound",
    ),
    "sap_get_justification_v1": (
        _sap_get_justification_v1,
        "app.services.connectors.mcp.client",
        "bound",
    ),
    "sap_reject_pr_v1": (
        _sap_reject_pr_v1,
        "app.services.connectors.mcp.client",
        "bound",
    ),
    "hikma_list_pos_by_type_v1": (
        _hikma_list_pos_by_type_v1,
        "app.services.connectors.mcp.client",
        "bound",
    ),
    "sap_create_po_v1": (
        _sap_create_po_v1,
        "app.services.connectors.mcp.client",
        "bound",
    ),
    "sap_handle_rejection_v1": (
        _sap_handle_rejection_v1,
        "app.services.connectors.mcp.client",
        "bound",
    ),
    "python_recipe_v1": (
        _python_recipe_v1,
        "app.services.recipe_executions",
        "bound",
    ),
    "system_run_read_v1": (
        _system_run_read_v1,
        "app.services.system_runs",
        "bound",
    ),
    "sql_transform_v1": (
        _sql_transform_v1,
        "app.services.tabular_transforms",
        "bound",
    ),
    "polars_transform_v1": (
        _polars_transform_v1,
        "app.services.tabular_polars",
        "bound",
    ),
    "dbt_transform_v1": (
        _dbt_transform_v1,
        "app.services.tabular_dbt",
        "bound",
    ),
    "hf_dataset_import_v1": (
        _hf_dataset_import_v1,
        "app.services.huggingface.datasets",
        "bound",
    ),
    "llm_label_dataset_v1": (
        _llm_label_dataset_v1,
        "app.services.llm_dataset_labeling",
        "bound",
    ),
    "ml_train_sklearn_v1": (
        _ml_train_sklearn_v1,
        "app.services.tabular_ml",
        "bound",
    ),
    "ml_monitor_model_v1": (_ml_monitor_model_v1, "app.services.ml_retraining", "bound"),
    "ml_evaluation_review_v1": (
        _ml_evaluation_review_v1,
        "app.services.ml_evaluation_review",
        "bound",
    ),
    "ml_problem_frame_v1": (_ml_problem_frame_v1, "app.services.ml_methodology", "bound"),
    "ml_experiment_plan_v1": (_ml_experiment_plan_v1, "app.services.ml_methodology", "bound"),
    "ml_retrain_model_v1": (_ml_retrain_model_v1, "app.services.ml_retraining", "bound"),
    "ml_predict_v1": (
        _ml_predict_v1,
        "app.services.tabular_predict",
        "bound",
    ),
    "ml_batch_score_v1": (
        _ml_batch_score_v1,
        "app.services.tabular_predict",
        "bound",
    ),
    "ml_forecast_v1": (
        _ml_forecast_v1,
        "app.services.ml.forecast_serving",
        "bound",
    ),
    "calendar_create_event_v1": (
        _calendar_create_event_v1,
        "app.services.workspace_calendar",
        "bound",
    ),
    "calendar_update_event_v1": (
        _calendar_update_event_v1,
        "app.services.workspace_calendar",
        "bound",
    ),
    "calendar_cancel_event_v1": (
        _calendar_cancel_event_v1,
        "app.services.workspace_calendar",
        "bound",
    ),
    "calendar_daily_summary_v1": (
        _calendar_daily_summary_v1,
        "app.services.workspace_calendar",
        "bound",
    ),
    "action_plan_create_v1": (_action_plan_create_v1, "app.services.action_plans", "bound"),
    "action_plan_reschedule_v1": (_action_plan_reschedule_v1, "app.services.action_plans", "bound"),
    "action_plan_status_v1": (_action_plan_status_v1, "app.services.action_plans", "bound"),
    "action_plan_cancel_v1": (_action_plan_cancel_v1, "app.services.action_plans", "bound"),
    "time_context_set_v1": (_time_context_set_v1, "app.services.demo_time_context", "bound"),
    "briefing_priorities_v1": (_briefing_priorities_v1, "app.services.mission_room", "bound"),
    "summarize_long_document_v1": (
        _summarize_long_document_v1,
        "app.services.mission_room",
        "bound",
    ),
    "generate_recommendations_v1": (
        _generate_recommendations_v1,
        "app.services.mission_room",
        "bound",
    ),
    "draft_email_v1": (_draft_email_v1, "app.services.mission_room", "bound"),
    "causal_drill_v1": (_causal_drill_v1, "app.services.mission_room", "bound"),
    "schedule_meeting_v1": (_schedule_meeting_v1, "app.services.workspace_calendar", "bound"),
    "territorial_action_window_v1": (
        _territorial_action_window_v1,
        "app.services.mission_room",
        "bound",
    ),
    "map_layer_read_v1": (_map_layer_read_v1, "app.services.workspace_maps", "bound"),
    "map_zone_score_v1": (_map_zone_score_v1, "app.services.workspace_maps", "bound"),
    "map_signal_attach_v1": (_map_signal_attach_v1, "app.services.workspace_maps", "bound"),
    "map_recommendation_generate_v1": (
        _map_recommendation_generate_v1,
        "app.services.workspace_maps",
        "bound",
    ),
    "map_command_apply_v1": (_map_command_apply_v1, "app.services.workspace_maps", "bound"),
    "source_registry_refresh_v1": (
        _source_registry_refresh_v1,
        "app.services.mission_room",
        "bound",
    ),
    "osint_signal_prioritize_v1": (
        _osint_signal_prioritize_v1,
        "app.services.mission_room",
        "bound",
    ),
    "rumor_origin_trace_v1": (_rumor_origin_trace_v1, "app.services.mission_room", "bound"),
    "evidence_graph_build_v1": (_evidence_graph_build_v1, "app.services.mission_room", "bound"),
    "situation_posture_score_v1": (
        _situation_posture_score_v1,
        "app.services.mission_room",
        "bound",
    ),
    "maritime_snapshot_read_v1": (
        _maritime_snapshot_read_v1,
        "app.services.workspace_maps",
        "bound",
    ),
    "decision_option_rank_v1": (_decision_option_rank_v1, "app.services.mission_room", "bound"),
    "draft_response_email_v1": (_draft_response_email_v1, "app.services.mission_room", "bound"),
    "visual_source_read_v1": (_visual_source_read_v1, "app.services.visual_intelligence", "bound"),
    "visual_snapshot_capture_v1": (
        _visual_snapshot_capture_v1,
        "app.services.visual_intelligence",
        "bound",
    ),
    "visual_snapshot_analyze_v1": (
        _visual_snapshot_analyze_v1,
        "app.services.visual_intelligence",
        "bound",
    ),
    "visual_observation_sync_knowledge_v1": (
        _visual_observation_sync_knowledge_v1,
        "app.services.visual_intelligence",
        "bound",
    ),
    "sharepoint_ingestion_v1": (_sharepoint_ingestion_v1, None, "stub"),
    "translation_archive_ingest_v1": (_translation_showcase_stub, None, "stub"),
    "translation_memory_retrieve_v1": (_translation_showcase_stub, None, "stub"),
    "translation_label_index_resolve_v1": (_translation_showcase_stub, None, "stub"),
    "translation_pivot_normalize_v1": (_translation_showcase_stub, None, "stub"),
    "translation_fanout_v1": (_translation_showcase_stub, None, "stub"),
    "translation_j2450_qa_v1": (_translation_showcase_stub, None, "stub"),
    "translation_post_guard_v1": (_translation_showcase_stub, None, "stub"),
    "translation_cdt_gate_v1": (_translation_showcase_stub, None, "stub"),
    "translation_package_delivery_v1": (_translation_showcase_stub, None, "stub"),
    "voice_transcribe_v1": (_voice_transcribe_v1, "app.services.voice_runtime", "bound"),
    "voice_tts_v1": (_voice_tts_v1, "app.services.voice_runtime", "bound"),
    "voice_realtime_session_v1": (
        _voice_realtime_session_v1,
        "app.services.voice_runtime",
        "bound",
    ),
    "voice_realtime_transcribe_v1": (
        _voice_realtime_transcribe_v1,
        "app.services.voice_runtime",
        "bound",
    ),
    "voice_realtime_speak_v1": (_voice_realtime_speak_v1, "app.services.voice_runtime", "bound"),
    "voice_realtime_translate_v1": (
        _voice_realtime_translate_v1,
        "app.services.voice_runtime",
        "bound",
    ),
    "voice_oracle_turn_v1": (_voice_oracle_turn_v1, "app.services.knowledge_capture", "bound"),
    "voice_tandem_oracle_v1": (
        _voice_tandem_oracle_v1,
        "app.services.voice_tandem_oracle",
        "bound",
    ),
    "knowledge_gap_analysis_v1": (
        _knowledge_gap_analysis_v1,
        "app.services.knowledge_capture",
        "bound",
    ),
    "expert_interview_plan_v1": (
        _expert_interview_plan_v1,
        "app.services.knowledge_capture",
        "bound",
    ),
    "expert_answer_evaluator_v1": (
        _expert_answer_evaluator_v1,
        "app.services.knowledge_capture",
        "bound",
    ),
    "capture_structuring_v1": (_capture_structuring_v1, "app.services.knowledge_capture", "bound"),
    "audit_log_v1": (_audit_log_v1, None, "bound"),
    "ollama_llm_v1": (_ollama_llm_v1, "app.services.model_clients.ollama_client", "bound"),
    "azure_llm_v1": (_azure_llm_v1, "app.services.model_clients.openai_client", "bound"),
    "openai_llm_v1": (_openai_llm_v1, "app.services.model_clients.openai_client", "bound"),
    "azure_openai_llm_v1": (
        _azure_openai_llm_v1,
        "app.services.model_clients.azure_openai_client",
        "bound",
    ),
    "workspace_llm_v1": (_workspace_llm_v1, "app.services.model_plane.execution", "bound"),
    "chain_naive_v1": (_chain_naive_v1, "app.services.rag.chains.naive", "bound"),
    "chain_hybrid_v1": (_chain_hybrid_v1, "app.services.rag.chains.hybrid", "bound"),
    "chain_mixed_hah_v1": (_chain_mixed_hah_v1, "app.services.rag.chains.mixed_hah", "bound"),
    "decide_next_v1": (_decide_next_v1, "app.services.model_router", "bound"),
    "skill_search_v1": (_skill_search_v1, None, "bound"),
    "chat_agentic_plan_v1": (_chat_agentic_plan_v1, "app.services.model_router", "bound"),
    "chat_self_correct_v1": (_chat_self_correct_v1, "app.services.model_router", "bound"),
    "response_eval_v1": (_response_eval_v1, "app.services.metrics.evaluator", "bound"),
    "grounding_check_v1": (_grounding_check_v1, None, "bound"),
    "connector_read_v1": (_connector_read_v1, "app.services.connectors.skill_reads", "bound"),
    "connector_write_request_v1": (_connector_write_request_v1, "app.services.connectors.skill_writes", "bound"),
    "data_prep_v1": (_data_prep_v1, "app.services.dataops.preparation", "bound"),
    "evaluate_v2": (_evaluate_v2, "app.services.evaluation.typed_judge", "bound"),
    "narration_run_v1": (_narration_run_v1, "app.services.dataops.narration", "bound"),
    "evaluate_v1": (_evaluate_v1, "app.services.evaluation.judge", "bound"),
    "publish_email_v1": (_publish_email_v1, "app.services.email", "bound"),
    "role_agent_v1": (_role_agent_v1, "app.services.model_plane.execution", "bound"),
    "spreadsheet_table_extract_v1": (
        _spreadsheet_table_extract_v1,
        "app.services.reconciliation",
        "bound",
    ),
    "invoice_document_extract_v1": (
        _invoice_document_extract_v1,
        "app.services.reconciliation",
        "bound",
    ),
    "line_items_reconcile_v1": (
        _line_items_reconcile_v1,
        "app.services.reconciliation",
        "bound",
    ),
    "reconciliation_report_v1": (
        _reconciliation_report_v1,
        "app.services.reconciliation",
        "bound",
    ),
}


def _claim_tool(mode: str):
    async def call(payload, ctx=None):
        from app.services.ecommerce.claims import invoke

        return await invoke(mode, payload, ctx)

    return call


async def _ecommerce_sla_features_v1(payload, ctx=None):
    from app.services.ecommerce.triage import invoke

    return await invoke(payload, ctx)


async def _ecommerce_sla_dataset_v1(payload, ctx=None):
    from app.services.ecommerce.triage import invoke

    return await invoke(payload, ctx, batch=True)


_REGISTRY["ecommerce_sla_features_v1"] = (
    _ecommerce_sla_features_v1,
    "app.services.ecommerce.triage",
    "bound",
)
_REGISTRY["ecommerce_sla_dataset_v1"] = (
    _ecommerce_sla_dataset_v1,
    "app.services.ecommerce.triage",
    "bound",
)


async def _ecommerce_sav_dataset_v1(payload, ctx=None):
    from app.services.ecommerce.composition import invoke_dataset

    return await invoke_dataset(payload, ctx)


async def _ecommerce_sav_context_v1(payload, ctx=None):
    from app.services.ecommerce.composition import invoke_context

    return await invoke_context(payload, ctx)


_REGISTRY["ecommerce_sav_dataset_v1"] = (
    _ecommerce_sav_dataset_v1,
    "app.services.ecommerce.composition",
    "bound",
)
_REGISTRY["ecommerce_sav_context_v1"] = (
    _ecommerce_sav_context_v1,
    "app.services.ecommerce.composition",
    "bound",
)


_REGISTRY.update(
    {
        slug: (_claim_tool(mode), "app.services.ecommerce.claims", "bound")
        for mode, slug in {
            "snapshot": "postgresql_claim_snapshot_v1",
            "policy": "ecommerce_policy_evidence_v1",
            "delivery": "ecommerce_delivery_evidence_v1",
            "refund": "ecommerce_refund_evidence_v1",
            "propose": "ecommerce_resolution_propose_v1",
            "simulate": "ecommerce_resolution_simulate_v1",
        }.items()
    }
)

_RESOLVED_STATUS: dict[str, str] = {}


def resolve(slug: str) -> SkillCallable:
    """Return the runtime callable bound to a seeded skill slug.

    Fail-closed, in two different ways because the two mistakes differ.
    Resolution used to hand back a callable that raised only once awaited, so
    the failure surfaced as a node the walker had already committed to running.

    An unknown seeded slug raises ``NotImplementedError``: nothing was ever
    declared for it, which the walker records as a skipped node. A
    workspace-namespaced slug raises instead, because reaching here means a
    caller skipped executor resolution entirely — its runtime binding lives on
    the Skill row (cf. :func:`app.services.skills_registry.executors.bind_executor`)
    and treating that as "not declared" would turn a dispatch bug into a quietly
    skipped node.
    """
    if is_workspace_skill_slug(slug):
        raise SkillBindingError(
            code="workspace_skill_requires_executor",
            message=(
                f"{slug} is a workspace-defined Skill and has no registry wrapper; "
                "it must be resolved through its verified executor binding."
            ),
        )
    entry = _REGISTRY.get(slug)
    if entry is None:
        raise NotImplementedError(
            f"No runtime wrapper is bound to {slug!r}. Add it to `_REGISTRY` in "
            "`skills_registry/wrappers/registry.py` or mark it as a stub."
        )
    return entry[0]


def runtime_status(slug: str) -> str:
    """Return ``bound`` | ``stub`` | ``unbound`` for a slug.

    Evaluates the dependency import on first call so we catch missing
    modules without forcing eager imports at startup.
    """
    if slug in _RESOLVED_STATUS:
        return _RESOLVED_STATUS[slug]
    entry = _REGISTRY.get(slug)
    if entry is None:
        _RESOLVED_STATUS[slug] = "unbound"
        return "unbound"
    _, module_path, hint = entry
    if module_path is None:
        _RESOLVED_STATUS[slug] = hint
        return hint
    try:
        importlib.import_module(module_path)
        _RESOLVED_STATUS[slug] = "bound"
        return "bound"
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "skills_registry: dependency import failed — marking stub",
            slug=slug,
            module=module_path,
            error=str(exc),
        )
        _RESOLVED_STATUS[slug] = "stub"
        return "stub"


def bound_slugs() -> dict[str, str]:
    """Return `{slug: status}` for every registered skill (tri-state)."""
    return {slug: runtime_status(slug) for slug in _REGISTRY}


def registry_snapshot() -> dict[str, dict[str, Any]]:
    """Richer report for admin / observability endpoints."""
    snap: dict[str, dict[str, Any]] = {}
    for slug, (_fn, module_path, hint) in _REGISTRY.items():
        snap[slug] = {
            "status": runtime_status(slug),
            "declared_status": hint,
            "module": module_path,
        }
    return snap
