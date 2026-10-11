"""Add the product category column to the Skill catalog.

Revision ID: 082_skill_category
Revises: 081_flow_publication_baseline

Discovery surfaces used to re-derive a product taxonomy from slugs and
descriptions with a frontend regex, because the catalog never carried one.
The startup registry seeding writes the same values on every boot, but it is
gated behind ``startup_reconciliation_enabled`` and swallows its own errors,
so the backfill below is what guarantees a non-null taxonomy right after the
migration. The mapping is intentionally frozen at this revision: later
taxonomy changes belong to the seeder, not to a replayed migration.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "082_skill_category"
down_revision = "081_flow_publication_baseline"
branch_labels = None
depends_on = None

COLUMN = "category"
INDEX = "ix_skills_category"

CATEGORY_BY_SLUG = {
    "action_plan_cancel_v1": "Automation",
    "action_plan_create_v1": "Automation",
    "action_plan_reschedule_v1": "Automation",
    "action_plan_status_v1": "Analysis",
    "audit_log_v1": "Governance",
    "azure_llm_v1": "LLM",
    "briefing_priorities_v1": "Analysis",
    "calendar_cancel_event_v1": "Connections",
    "calendar_create_event_v1": "Connections",
    "calendar_daily_summary_v1": "Analysis",
    "calendar_read_v1": "Connections",
    "calendar_update_event_v1": "Connections",
    "capture_structuring_v1": "LLM",
    "causal_drill_v1": "Analysis",
    "chain_hybrid_v1": "Retrieval",
    "chain_mixed_hah_v1": "Retrieval",
    "chain_naive_v1": "Retrieval",
    "chat_action_resolver_v1": "Automation",
    "chat_agentic_plan_v1": "LLM",
    "chat_grounding_policy_v1": "Governance",
    "chat_self_correct_v1": "LLM",
    "chat_trivial_bypass_v1": "Governance",
    "claim_audit_v1": "Governance",
    "decision_option_rank_v1": "Decision Support",
    "document_ingestion_v1": "Ingestion",
    "draft_email_v1": "LLM",
    "draft_response_email_v1": "LLM",
    "eval_radar_v1": "Governance",
    "evidence_graph_build_v1": "Analysis",
    "expert_answer_evaluator_v1": "Analysis",
    "expert_interview_plan_v1": "LLM",
    "generate_recommendations_v1": "Decision Support",
    "instruction_draft_v1": "LLM",
    "intelligence_batch_v1": "Ingestion",
    "knowledge_gap_analysis_v1": "Analysis",
    "llm_rag_answer_v1": "Retrieval",
    "map_command_apply_v1": "Automation",
    "map_layer_read_v1": "Connections",
    "map_recommendation_generate_v1": "Decision Support",
    "map_signal_attach_v1": "Automation",
    "map_zone_score_v1": "Decision Support",
    "maritime_snapshot_read_v1": "Connections",
    "ministerial_briefing_v1": "LLM",
    "multi_hop_retrieve_v1": "Retrieval",
    "news_signal_synthesis_v1": "Analysis",
    "ollama_llm_v1": "LLM",
    "osint_signal_prioritize_v1": "Analysis",
    "project_risk_explainer_v1": "Analysis",
    "response_eval_v1": "Governance",
    "rpa_dispatch_v1": "Automation",
    "rumor_origin_trace_v1": "Analysis",
    "sap_hana_query_v1": "Connections",
    "scenario_compare_v1": "Decision Support",
    "scenario_generate_v1": "Decision Support",
    "scenario_recommend_v1": "Decision Support",
    "schedule_meeting_v1": "Connections",
    "semantic_search_v1": "Retrieval",
    "sharepoint_ingestion_v1": "Ingestion",
    "situation_posture_score_v1": "Decision Support",
    "source_registry_refresh_v1": "Ingestion",
    "summarize_long_document_v1": "LLM",
    "territorial_action_window_v1": "Decision Support",
    "territorial_signal_map_v1": "Analysis",
    "time_context_set_v1": "Governance",
    "translation_archive_ingest_v1": "Ingestion",
    "translation_cdt_gate_v1": "Governance",
    "translation_fanout_v1": "Automation",
    "translation_j2450_qa_v1": "Analysis",
    "translation_label_index_resolve_v1": "Automation",
    "translation_memory_retrieve_v1": "Retrieval",
    "translation_package_delivery_v1": "Automation",
    "translation_pivot_normalize_v1": "LLM",
    "translation_post_guard_v1": "Governance",
    "visual_observation_sync_knowledge_v1": "Ingestion",
    "visual_snapshot_analyze_v1": "Analysis",
    "visual_snapshot_capture_v1": "Ingestion",
    "visual_source_read_v1": "Connections",
    "voice_oracle_turn_v1": "Voice",
    "voice_realtime_session_v1": "Voice",
    "voice_realtime_speak_v1": "Voice",
    "voice_realtime_transcribe_v1": "Voice",
    "voice_realtime_translate_v1": "Voice",
    "voice_tandem_oracle_v1": "Voice",
    "voice_transcribe_v1": "Voice",
    "voice_tts_v1": "Voice",
}


def _skills_table() -> sa.Table:
    return sa.table(
        "skills",
        sa.column("slug", sa.String(length=160)),
        sa.column(COLUMN, sa.String(length=40)),
    )


def upgrade() -> None:
    op.add_column("skills", sa.Column(COLUMN, sa.String(length=40), nullable=True))
    op.create_index(INDEX, "skills", [COLUMN])

    bind = op.get_bind()
    skills = _skills_table()
    by_category: dict[str, list[str]] = {}
    for slug, category in CATEGORY_BY_SLUG.items():
        by_category.setdefault(category, []).append(slug)
    for category, slugs in by_category.items():
        bind.execute(
            skills.update().where(skills.c.slug.in_(sorted(slugs))).values(category=category)
        )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="skills")
    op.drop_column("skills", COLUMN)
