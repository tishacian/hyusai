from __future__ import annotations

import ast
import inspect
import textwrap

from fastapi.routing import APIRoute

from app.api.v1.endpoints import client360

EXPECTED = {
    ("GET", "/summary"): ("system", "read"),
    ("GET", "/alerts"): ("system", "read"),
    ("POST", "/chat"): ("system", "engine.run"),
    ("GET", "/scope"): ("system", "read"),
    ("GET", "/opportunities"): ("system", "read"),
    ("POST", "/engines/opportunities/run"): ("system", "engine.run"),
    ("POST", "/sources/sync-from-collection"): ("system", "admin"),
    ("PATCH", "/opportunities/{opportunity_id}"): ("decision", "approve"),
    ("GET", "/campaigns"): ("system", "read"),
    ("POST", "/campaigns"): ("action", "execute"),
    ("PATCH", "/campaigns/{campaign_id}"): ("action", "execute"),
    ("POST", "/campaigns/{campaign_id}/drafts"): ("system", "engine.run"),
    ("GET", "/campaigns/{campaign_id}/stats"): ("system", "read"),
    ("GET", "/mappings"): ("system", "read"),
    ("POST", "/mappings"): ("system", "admin"),
    ("PATCH", "/mappings/{mapping_id}"): ("system", "admin"),
    ("GET", "/customers/{customer_id}"): ("system", "engine.run"),
    ("POST", "/mail-drafts"): ("system", "engine.run"),
    ("GET", "/mail-settings"): ("system", "read"),
    ("PATCH", "/mail-settings"): ("system", "admin"),
    ("POST", "/mail-drafts/{draft_id}/send"): ("mail_draft", "mail.send"),
    ("PATCH", "/actions/{action_id}"): ("action", "execute"),
    ("POST", "/actions/{action_id}/impact"): ("action", "execute"),
}


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _authorization_call(endpoint) -> ast.Call:
    tree = ast.parse(textwrap.dedent(inspect.getsource(endpoint)))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _call_name(node) == "_enforce_client360_action"
    ]
    assert len(calls) == 1
    return calls[0]


def _constant_keyword(call: ast.Call, name: str) -> str:
    keyword = next(item for item in call.keywords if item.arg == name)
    assert isinstance(keyword.value, ast.Constant)
    assert isinstance(keyword.value.value, str)
    return keyword.value.value


def test_every_client360_route_has_one_explicit_action_boundary() -> None:
    routes = {
        (method, route.path): route
        for route in client360.router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }

    assert set(routes) == set(EXPECTED)
    for key, expected in EXPECTED.items():
        route = routes[key]
        assert "user" in inspect.signature(route.endpoint).parameters
        call = _authorization_call(route.endpoint)
        assert (
            _constant_keyword(call, "resource_kind"),
            _constant_keyword(call, "action"),
        ) == expected


def test_authorization_precedes_every_client360_business_operation() -> None:
    helper_names = {
        "alerts_payload",
        "campaign_stats",
        "client360_mail_settings_payload",
        "client360_scope",
        "create_campaign",
        "create_mail_draft",
        "customer_payload",
        "generate_campaign_drafts",
        "handle_client360_chat_query",
        "list_campaigns",
        "list_mapping_rules",
        "list_opportunities",
        "patch_action",
        "patch_campaign",
        "patch_client360_mail_settings",
        "patch_mapping_rule",
        "patch_opportunity",
        "prepare_campaign_follow_ups",
        "record_impact",
        "run_opportunity_engine",
        "send_mail_draft",
        "summary_payload",
        "sync_sources_from_collection",
        "upsert_mapping_rule",
    }
    for route in client360.router.routes:
        if not isinstance(route, APIRoute):
            continue
        tree = ast.parse(textwrap.dedent(inspect.getsource(route.endpoint)))
        authorization_line = _authorization_call(route.endpoint).lineno
        business_lines = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _call_name(node) in helper_names
        ]
        assert business_lines, route.path
        assert authorization_line < min(business_lines), route.path
