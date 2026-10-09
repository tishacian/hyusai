"""OpenAI-compatible HF Inference with a fresh workspace/license gate per call."""

from __future__ import annotations

import asyncio

from app.services.huggingface.connection import DEFAULT_ENDPOINT, INFERENCE_ENDPOINT, Connection
from app.services.huggingface.errors import HFError
from app.services.model_clients.openai_client import OpenAIClient


class HFInferenceClient(OpenAIClient):
    def __init__(self, workspace_id: str, *, max_retries=None):
        # No environment/API-key fallback. The current connection is read for
        # every actual call, including calls made directly through ModelRouter.
        super().__init__(
            api_key="pending-workspace-authorization",
            base_url=INFERENCE_ENDPOINT,
            max_retries=max_retries,
        )
        self.workspace_id = workspace_id
        self._prepared_model = None
        self.license_provenance = None

    def _authorization(self, model: str) -> tuple[str, dict]:
        from app.db.base import SessionLocal
        from app.models.workspace import Workspace
        from app.services.huggingface.client import HFClient, validate_repo
        from app.services.huggingface.policy import require_acceptance

        # HF router suffix selects an inference provider (e.g. :fastest); the
        # repository before it owns the license.
        repo_id = model.split(":", 1)[0]
        validate_repo("model", repo_id)
        with SessionLocal() as db:
            workspace = db.query(Workspace).filter(Workspace.id == self.workspace_id).first()
            if workspace is None:
                raise HFError(
                    "HF_WORKSPACE_REQUIRED", "The inference workspace is unavailable.", 403
                )
            connection = Connection.resolve(db, workspace)
            if connection.endpoint != DEFAULT_ENDPOINT:
                raise HFError(
                    "HF_INFERENCE_ENDPOINT_UNSUPPORTED",
                    "HF Inference requires a connection to huggingface.co.",
                    422,
                )
            if not connection.token:
                raise HFError("HF_TOKEN_REQUIRED", "Configure a Hub token for HF Inference.", 403)
            hub = HFClient(connection)
            metadata = hub.repo_info("model", repo_id)
            hub.check_access(metadata)
            evidence = hub.license_evidence(metadata)
            db.refresh(workspace)
            if Connection.resolve(db, workspace) != connection:
                raise HFError(
                    "HF_CONNECTION_CHANGED",
                    "The Hub connection changed before inference dispatch.",
                    409,
                )
            try:
                decision = require_acceptance(db, workspace, metadata, evidence["license_text"])
            except HFError:
                db.commit()  # retain the refusal audit before ending this read
                raise
            return connection.token, {
                "repo_id": repo_id,
                "revision": metadata["revision"],
                "hub_endpoint": metadata["hub_endpoint"],
                "license": decision["license"],
                "license_digest": decision["license_digest"],
                "policy_version": decision["policy_version"],
                "remote_revision_pinned": False,
            }

    async def prepare(self, model: str) -> dict:
        self.api_key, self.license_provenance = await asyncio.to_thread(self._authorization, model)
        self._prepared_model = model
        return dict(self.license_provenance)

    async def _authorize(self, model: str):
        if self._prepared_model != model:
            await self.prepare(model)
        self._prepared_model = None

    async def generate(self, model: str, prompt: str, **kwargs):
        await self._authorize(model)
        result = await super().generate(model, prompt, **kwargs)
        return {**result, "huggingface": self.license_provenance}

    async def stream(self, model: str, prompt: str, **kwargs):
        await self._authorize(model)
        async for chunk in super().stream(model, prompt, **kwargs):
            yield {**chunk, "huggingface": self.license_provenance}

    async def complete_with_tools(self, model: str, messages: list, **kwargs):
        await self._authorize(model)
        result = await super().complete_with_tools(model, messages, **kwargs)
        return {**result, "huggingface": self.license_provenance}


class ArtifactInferenceClient(HFInferenceClient):
    """Revalidate a registered node's artifact grant before each remote call."""

    def __init__(self, workspace_id: str, provider_key: str, provenance: dict, *, max_retries=None):
        super().__init__(workspace_id, max_retries=max_retries)
        self.provider_key = provider_key
        self.provenance = dict(provenance)

    def _authorization(self, model: str) -> tuple[str, dict]:
        from app.db.base import SessionLocal
        from app.models.workspace import Workspace
        from app.services.huggingface.registry import require_artifact
        from app.services.model_plane.registration import get_routable_provider, route_base_url
        from app.services.model_plane.serving_nodes import get_node

        with SessionLocal() as db:
            workspace = db.query(Workspace).filter(Workspace.id == self.workspace_id).first()
            metadata = get_routable_provider(self.provider_key)
            if (
                workspace is None
                or not metadata
                or metadata.get("workspace_id") != self.workspace_id
                or metadata.get("status") != "active"
                or metadata.get("model") != model
                or any(metadata.get(key) != value for key, value in self.provenance.items())
            ):
                raise HFError(
                    "HF_DEPLOYMENT_UNAVAILABLE",
                    "This artifact deployment is unavailable or has changed.",
                    403,
                )
            node = get_node(metadata["node"], workspace=workspace)
            if node is None or not node.token:
                raise HFError(
                    "HF_NODE_UNAVAILABLE", "The serving node is no longer configured.", 403
                )
            expected = route_base_url(node.base_url, metadata)
            if expected != metadata.get("openai_base_url"):
                raise HFError("HF_NODE_UNAVAILABLE", "The serving node endpoint has changed.", 403)
            try:
                artifact = require_artifact(
                    db, self.workspace_id, metadata["artifact_id"], usage="llm"
                )
            except HFError:
                db.commit()
                raise
            if artifact.revision != metadata.get("revision") or artifact.variant != metadata.get(
                "variant"
            ):
                raise HFError(
                    "HF_DEPLOYMENT_MISMATCH",
                    "The node reports a different artifact revision or variant.",
                    403,
                )
            self.base_url = expected
            # The node relay authenticates with its control token, read fresh per call.
            return node.token, dict(self.provenance)
