"""The optional Hub principals cannot inherit the legacy broad writer role."""

import importlib.util
from pathlib import Path


def test_role_policies_preserve_writer_boundary_and_versioned_deletion():
    path = Path(__file__).resolve().parents[4] / "scripts/agentium_hf_storage_policies.py"
    spec = importlib.util.spec_from_file_location("hf_policy_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    policies = module.policies("agentium-artifacts")
    application = policies["application"]["Statement"]
    assert any(
        row["Effect"] == "Deny"
        and "s3:PutObject" in row["Action"]
        and "arn:aws:s3:::agentium-artifacts/hub/blobs/*" in row["Resource"]
        for row in application
    )
    assert any(
        row["Effect"] == "Deny" and "s3:DeleteObjectVersion" in row["Action"] for row in application
    )
    reader_actions = {
        action for row in policies["hub-read"]["Statement"] for action in row["Action"]
    }
    assert reader_actions == {"s3:GetBucketLocation", "s3:GetObject"}
    writer = policies["hub-fetch"]["Statement"]
    assert all(
        resource.endswith("/hub/*")
        for row in writer
        if "s3:PutObject" in row["Action"]
        for resource in row["Resource"]
    )
    assert any("s3:DeleteObjectVersion" in row["Action"] for row in writer)
    purge = policies["tabular-purge"]["Statement"]
    assert all(
        "/workspaces/*/tabular/hub-artifacts/*" in resource
        for row in purge
        if "s3:DeleteObjectVersion" in row["Action"]
        for resource in row["Resource"]
    )
