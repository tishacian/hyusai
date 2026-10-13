"""Version-pinned hash salts never enter SQL, manifests, logs, or API outputs."""

from app.services.secrets import registry


def hash_parameters(spec, db=None, *, workspace_id=None, run_id=None, node_id=None):
    result = {}
    for i, step in enumerate(spec.steps):
        if step.action != "hash":
            continue
        ref = step.params.get("salt_secret_ref")
        try:
            parsed = registry.parse_ref(ref)
        except registry.SecretRegistryError as exc:
            raise ValueError(exc.code) from None
        if parsed.scope != "workspace" or parsed.version is None:
            raise ValueError("DATAPREP_HASH_PINNED_WORKSPACE_SALT_REQUIRED")
        if db is None:
            # Preview does not expose a pseudonym or resolve a secret.
            result[f"dp_salt_{i}"] = "[preview-redacted]"
        else:
            from app.models.secret import Secret

            secret = (
                db.query(Secret)
                .filter_by(scope="workspace", workspace_id=workspace_id, name=parsed.name)
                .first()
            )
            if (
                secret is None
                or secret.kind != "generic"
                or (secret.meta or {}).get("purpose") != "dataops_hash_salt"
            ):
                raise ValueError("DATAPREP_HASH_SALT_PURPOSE_REQUIRED")
            value = registry.resolve(
                db,
                ref,
                consumer=registry.SecretConsumer(
                    kind="dataops",
                    id="hash",
                    workspace_id=workspace_id,
                    run_id=run_id,
                    node_id=node_id,
                ),
            )
            if len(value.reveal().encode()) < 32:
                raise ValueError("DATAPREP_HASH_SALT_TOO_SHORT")
            result[f"dp_salt_{i}"] = value.reveal()
    return result
