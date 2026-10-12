"""Shared Client360 PDR product contract for API payloads and system seed."""
from __future__ import annotations

from typing import Any


CLIENT360_SYSTEM_VARIANT = "client360_pdr"
CLIENT360_CAPABILITY_SLUG = "client360_pdr_opportunity_engine"

# Unified Andritz Client360 knowledge vault (Installed_base_SPL + pilot xlsx).
# Structured truth lives in Client360DataSource; this collection is the document vault.
CLIENT360_INSTALLED_BASE_COLLECTION_SLUG = "andritz-client360-installed-base"
CLIENT360_INSTALLED_BASE_COLLECTION_NAME = "Andritz Client360 Installed Base"
CLIENT360_SPL_ADAPTER_VERSION = "client360_spl_v2"
CLIENT360_PILOT_DATASET_MARKER = "andritz_client360_pdr_mvp_20260708"

# Deterministic default weights used to turn a raw quantity gap into a weighted
# addressable potential. The factor is base + bonuses (present hub, existing
# purchase history) + observed conversion rate contribution, clamped to [0, 1].
# Defaults are tuned so a fully-signalled opportunity with a 100% observed
# conversion rate reaches 1.0 (full gap considered addressable).
CLIENT360_ADDRESSABLE_WEIGHTS: dict[str, float] = {
    "base": 0.4,
    "hub_present": 0.2,
    "existing_purchase_history": 0.25,
    "observed_conversion": 0.15,
}

CLIENT360_MVP_CONTRACT: dict[str, Any] = {
    "official_name": "Client360 PDR",
    "product_mode": "assistant_commercial_ia_spare_parts",
    "promise": (
        "Detecter, expliquer et activer les opportunites PDR a partir de la base installee, "
        "des periodicites et des historiques SAP, avec validation humaine."
    ),
    "data_policy": {
        "ground_truth": "built_by_campaign_feedback",
        "prediction_policy": "explainable_potential_only",
        "internet_sources": "context_only",
        "automatic_email_send": False,
        "stock_automation": False,
    },
    "mvp_in_scope": [
        "installed_base_ledger",
        "pdr_periodicity_mapping",
        "theoretical_and_addressable_potential",
        "first_replacement_confidence",
        "delivery_lead_time_anticipation",
        "light_client360_pdr_profile",
        "prioritized_opportunities",
        "human_validated_ai_mail_drafts",
        "manual_mail_follow_up",
        "campaign_transformation_tracking",
        "impact_learning_loop",
        "hub_country_routing_context",
    ],
    "deferred_scope": [
        "full_client360_crm",
        "live_sap_crm_metris_outlook_connectors",
        "automatic_email_campaign_send",
        "outlook_open_rate_tracking",
        "supervised_replacement_prediction",
        "fine_stock_optimization",
        "supplier_price_workflow_for_rare_parts",
        "automatic_spare_part_agreements",
        "advanced_country_behavior_modeling",
        "web_price_scraping_as_truth",
    ],
    "campaign_segments": [
        {
            "id": "first_replacement",
            "label": "Premier remplacement",
            "confidence_policy": "highest_when_install_date_and_periodicity_are_known",
        },
        {
            "id": "maintenance_education",
            "label": "Pedagogie maintenance",
            "confidence_policy": "medium_or_low_when_replacement_cycle_is_old_or_unobserved",
        },
        {
            "id": "service_audit",
            "label": "Service / audit",
            "confidence_policy": "recommended_when_data_gaps_or_usage_uncertainty_need_human_inspection",
        },
        {
            "id": "annual_grouping_spa",
            "label": "Groupement annuel / SPA",
            "confidence_policy": "recommended_when_annual_volume_or_repeated_purchases_are_visible",
        },
    ],
    "learning_loop": [
        "opportunity_validated_or_rejected",
        "mail_generated",
        "mail_manually_sent",
        "client_response",
        "quote_requested",
        "order_won",
        "lost_reason",
        "attribution_direct_probable_unknown_none",
    ],
}

CLIENT360_AGENT_ROUTING_CONTRACT: dict[str, Any] = {
    "mail_draft": {
        "route_id": "client360_pdr_mail_writer",
        "kind": "llm",
        "prompt_version": "client360_pdr_mail_v2",
        "model_resolution_order": [
            "workspace.settings.client360_pdr_mail",
            "system.settings.client360_pdr_mail",
            "system.default_model",
            "agentium.resolved_system_preset",
            "agentium.resolved_capability_preset",
            "agentium.resolved_workspace_preset",
            "global_defaults",
        ],
        "human_validation_required": True,
        "manual_send_only": True,
    },
    "customer_summary": {
        "route_id": "client360_pdr_customer_summary",
        "kind": "llm",
        "prompt_version": "client360_pdr_customer_summary_v1",
        "model_resolution_order": [
            "workspace.settings.client360_pdr_mail",
            "system.settings.client360_pdr_mail",
            "system.default_model",
            "agentium.resolved_system_preset",
            "agentium.resolved_capability_preset",
            "agentium.resolved_workspace_preset",
            "global_defaults",
        ],
        "human_validation_required": False,
        "manual_send_only": False,
        "read_only": True,
    },
}
