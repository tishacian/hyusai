from __future__ import annotations

import importlib.util
import json
import os
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
HELPER = ROOT / "scripts" / "agentium_runtime_env_bundle.py"
SHA = "a" * 40
DEPLOYMENT_ID = "env-bundle-test"


def _module():
    spec = importlib.util.spec_from_file_location("agentium_runtime_env_bundle_unit", HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sources(tmp_path: Path, *, alias_application: bool = False) -> dict[str, Path]:
    compose_dir = tmp_path / "repo" / "docker"
    env_dir = compose_dir / "env"
    backend = tmp_path / "repo" / "backend"
    env_dir.mkdir(parents=True)
    backend.mkdir(parents=True)
    application = env_dir / "application.env"
    qdrant = env_dir / "qdrant.env"
    keycloak = env_dir / "keycloak.env"
    systemd = backend / ".env"
    application.write_text(
        "APP_SECRET=customer-app-secret\n"
        "DATABASE_URL=postgresql://agentium:postgres-private@agentium-pg:5432/agentium\n"
        "CELERY_BROKER_URL=amqp://agentium:rabbit-private@agentium-rabbitmq:5672//\n"
        "FAISS_PERSIST_DIRECTORY=/data/faiss_db\n"
        "OBJECT_STORE_BACKEND=local\n"
        "OBJECT_STORE_BASE_PATH=/data/object_store\n"
        "OBJECT_STORE_S3_BUCKET=agentium-artifacts\n"
        "OBJECT_STORE_S3_ENDPOINT_URL=http://agentium-minio:9000\n"
        "QDRANT_API_KEY=qdrant-readonly-private-1234567890abcdef\n"
        "QDRANT_HOST=agentium-qdrant\n"
        "QDRANT_HTTPS=false\n"
        "QDRANT_PORT=6333\n"
        "SECURE_DEPOSIT_SFTP_HOST_KEY_PATH=/data/secure_deposit/sftp_host_key\n"
        "SECURE_DEPOSIT_SFTP_TEMP_DIR=/data/secure_deposit/_sftp_uploads\n"
        "SECURE_DEPOSIT_STORAGE_DIR=/data/secure_deposit\n"
        "OBJECT_STORE_S3_ACCESS_KEY=object-app\n"
        "OBJECT_STORE_S3_SECRET_KEY=object-app-private\n",
        encoding="utf-8",
    )
    qdrant.write_text(
        "QDRANT__SERVICE__API_KEY=qdrant-admin-private-1234567890abcdef\n"
        "QDRANT__SERVICE__READ_ONLY_API_KEY=qdrant-readonly-private-1234567890abcdef\n",
        encoding="utf-8",
    )
    keycloak.write_text(
        "KC_DB=postgres\n"
        "KC_DB_URL=jdbc:postgresql://agentium-pg:5432/agentium\n"
        "KC_DB_USERNAME=agentium\n"
        "KC_DB_PASSWORD=postgres-private\n",
        encoding="utf-8",
    )
    systemd.write_text(
        "SYSTEMD_SECRET=systemd-private\n"
        "DATABASE_URL=postgresql://agentium:postgres-private@127.0.0.1:5432/agentium\n"
        "CELERY_BROKER_URL=amqp://agentium:rabbit-private@127.0.0.1:5672//\n"
        "FAISS_PERSIST_DIRECTORY=" + str(tmp_path / "faiss-db") + "\n"
        "OBJECT_STORE_BACKEND=local\n"
        "OBJECT_STORE_BASE_PATH="
        + str(tmp_path / "agentium-data" / "object_store")
        + "\n"
        "OBJECT_STORE_S3_ACCESS_KEY=object-app\n"
        "OBJECT_STORE_S3_BUCKET=agentium-artifacts\n"
        "OBJECT_STORE_S3_ENDPOINT_URL=http://127.0.0.1:9000\n"
        "OBJECT_STORE_S3_SECRET_KEY=object-app-private\n"
        "QDRANT_API_KEY=qdrant-admin-private-1234567890abcdef\n"
        "QDRANT_HOST=127.0.0.1\n"
        "QDRANT_HTTPS=false\n"
        "QDRANT_PORT=6333\n"
        "SECURE_DEPOSIT_STORAGE_DIR=" + str(tmp_path / "secure-deposit") + "\n",
        encoding="utf-8",
    )
    main = env_dir / "agentium.vm.env"
    application_reference = main if alias_application else application
    main.write_text(
        "\n".join(
            [
                "AGENTIUM_POSTGRES_PASSWORD=postgres-private",
                "AGENTIUM_POSTGRES_DB=agentium",
                "AGENTIUM_POSTGRES_USER=agentium",
                "DATABASE_URL=postgresql://agentium:postgres-private@agentium-pg:5432/agentium",
                "CELERY_BROKER_URL=amqp://agentium:rabbit-private@agentium-rabbitmq:5672//",
                "FAISS_PERSIST_DIRECTORY=/data/faiss_db",
                "OBJECT_STORE_BACKEND=local",
                "OBJECT_STORE_BASE_PATH=/data/object_store",
                "OBJECT_STORE_S3_BUCKET=agentium-artifacts",
                "OBJECT_STORE_S3_ENDPOINT_URL=http://agentium-minio:9000",
                "QDRANT_API_KEY=qdrant-readonly-private-1234567890abcdef",
                "QDRANT_HOST=agentium-qdrant",
                "QDRANT_HTTPS=false",
                "QDRANT_PORT=6333",
                "SECURE_DEPOSIT_SFTP_HOST_KEY_PATH=/data/secure_deposit/sftp_host_key",
                "SECURE_DEPOSIT_SFTP_TEMP_DIR=/data/secure_deposit/_sftp_uploads",
                "SECURE_DEPOSIT_STORAGE_DIR=/data/secure_deposit",
                "AGENTIUM_RABBITMQ_USER=agentium",
                "AGENTIUM_RABBITMQ_PASSWORD=rabbit-private",
                "AGENTIUM_MINIO_ROOT_USER=minio-root",
                "AGENTIUM_MINIO_ROOT_PASSWORD=minio-root-private",
                "AGENTIUM_MINIO_BUCKET=agentium-artifacts",
                f"AGENTIUM_FAISS_PATH={tmp_path / 'faiss-db'}",
                f"AGENTIUM_OBJECT_STORE_PATH={tmp_path / 'agentium-data' / 'object_store'}",
                f"AGENTIUM_SECURE_DEPOSIT_PATH={tmp_path / 'secure-deposit'}",
                "OBJECT_STORE_S3_ACCESS_KEY=object-app",
                "OBJECT_STORE_S3_SECRET_KEY=object-app-private",
                f"AGENTIUM_ENV_FILE={application_reference}",
                "AGENTIUM_QDRANT_ENV_FILE=./env/qdrant.env",
                "AGENTIUM_KEYCLOAK_ENV_FILE=./env/keycloak.env",
                "LIVEKIT_API_SECRET=livekit-private",
                "LIVEKIT_API_KEY=livekit-production",
                "",
            ]
        ),
        encoding="utf-8",
    )
    for path in {main, application, qdrant, keycloak, systemd}:
        path.chmod(0o600)
    return {
        "compose_dir": compose_dir,
        "main": main,
        "application": application_reference,
        "qdrant": qdrant,
        "keycloak": keycloak,
        "systemd": systemd,
    }


def _freeze(module, sources: dict[str, Path], bundle: Path) -> str:
    return module.freeze_bundle(
        main_env=sources["main"],
        compose_dir=sources["compose_dir"],
        systemd_env=sources["systemd"],
        output_dir=bundle,
        candidate_sha=SHA,
        deployment_id=DEPLOYMENT_ID,
        source_owner_uid=os.getuid(),
    )


def _rewrite_manifest(module, bundle: Path, manifest: dict) -> None:
    path = bundle / "manifest.json"
    path.write_bytes(module._json_bytes(manifest))
    path.chmod(0o600)


def test_bundle_is_private_value_free_and_survives_source_loss(tmp_path: Path) -> None:
    module = _module()
    sources = _sources(tmp_path)
    bundle = tmp_path / "state" / "runtime-env"
    digest = _freeze(module, sources, bundle)

    manifest_bytes = (bundle / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    assert digest == module._sha256_bytes(manifest_bytes)
    assert stat.S_IMODE(bundle.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in bundle.iterdir())
    serialized = json.dumps(manifest)
    for private in (
        "postgres-private",
        "customer-app-secret",
        "qdrant-private",
        "keycloak-private",
        "systemd-private",
        "livekit-private",
        "object-app-private",
        "minio-root-private",
        str(sources["main"]),
        str(sources["systemd"]),
    ):
        assert private not in serialized

    for role, key in module.REFERENCE_KEYS.items():
        effective, _ = module._parse_dotenv(
            (bundle / "compose.effective.env").read_bytes(), label="test"
        )
        expected = bundle / manifest["roles"][role]["file"]
        assert effective[key] == str(expected)
        assert expected.is_file()

    for source in set(sources.values()) - {sources["compose_dir"]}:
        if source.is_file():
            source.unlink()
    assert (
        module.verify_bundle(
            bundle_dir=bundle,
            candidate_sha=SHA,
            deployment_id=DEPLOYMENT_ID,
            expected_manifest_sha256=digest,
        )
        == digest
    )


def test_main_and_application_same_inode_are_copied_once(tmp_path: Path) -> None:
    module = _module()
    sources = _sources(tmp_path, alias_application=True)
    bundle = tmp_path / "state" / "runtime-env"
    _freeze(module, sources, bundle)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["roles"]["compose_main"]["file"] == manifest["roles"]["application"]["file"]
    source_files = [name for name in manifest["files"] if name.startswith("source-")]
    assert len(source_files) == 4


def test_role_path_is_digest_bound_and_stays_inside_bundle(tmp_path: Path) -> None:
    module = _module()
    sources = _sources(tmp_path)
    expected_systemd = sources["systemd"].read_text(encoding="utf-8")
    bundle = tmp_path / "state" / "runtime-env"
    digest = _freeze(module, sources, bundle)

    path = module.bundle_role_path(
        bundle_dir=bundle,
        role="systemd",
        candidate_sha=SHA,
        deployment_id=DEPLOYMENT_ID,
        expected_manifest_sha256=digest,
    )
    assert path.parent == bundle
    assert path.read_text(encoding="utf-8") == (
        expected_systemd + f"AGENTIUM_IMAGE_REVISION={SHA}\n"
    )
    with pytest.raises(module.RuntimeEnvBundleError, match="digest differs"):
        module.bundle_role_path(
            bundle_dir=bundle,
            role="systemd",
            candidate_sha=SHA,
            deployment_id=DEPLOYMENT_ID,
            expected_manifest_sha256="0" * 64,
        )


def test_role_value_returns_only_the_canonical_verified_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _module()
    sources = _sources(tmp_path)
    systemd_text = sources["systemd"].read_text(encoding="utf-8")
    sources["systemd"].write_text(
        systemd_text.replace(
            "SYSTEMD_SECRET=systemd-private",
            "export SYSTEMD_SECRET='canonical private value'",
        )
        + "EMPTY_VALUE=\n",
        encoding="utf-8",
    )
    bundle = tmp_path / "state" / "runtime-env"
    digest = _freeze(module, sources, bundle)

    assert (
        module.bundle_role_value(
            bundle_dir=bundle,
            role="systemd",
            key="SYSTEMD_SECRET",
            candidate_sha=SHA,
            deployment_id=DEPLOYMENT_ID,
            expected_manifest_sha256=digest,
        )
        == "canonical private value"
    )
    assert (
        module.main(
            [
                "value",
                "--bundle-dir",
                str(bundle),
                "--sha",
                SHA,
                "--deployment-id",
                DEPLOYMENT_ID,
                "--expected-manifest-sha256",
                digest,
                "--role",
                "systemd",
                "--key",
                "EMPTY_VALUE",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert captured.out == "\n"
    assert captured.err == ""

    assert (
        module.main(
            [
                "value",
                "--bundle-dir",
                str(bundle),
                "--sha",
                SHA,
                "--deployment-id",
                DEPLOYMENT_ID,
                "--expected-manifest-sha256",
                digest,
                "--role",
                "systemd",
                "--key",
                "MISSING_KEY",
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "canonical private value" not in captured.err
    assert "MISSING_KEY" not in captured.err


@pytest.mark.parametrize("unsafe", ["symlink", "duplicate"])
def test_freeze_refuses_unsafe_or_ambiguous_sources(tmp_path: Path, unsafe: str) -> None:
    module = _module()
    sources = _sources(tmp_path)
    if unsafe == "symlink":
        target = sources["application"]
        link = target.with_name("application-link.env")
        link.symlink_to(target)
        text = sources["main"].read_text(encoding="utf-8").replace(str(target), str(link))
        sources["main"].write_text(text, encoding="utf-8")
    else:
        with sources["qdrant"].open("a", encoding="utf-8") as handle:
            handle.write("QDRANT__SERVICE__API_KEY=second-value\n")

    with pytest.raises(module.RuntimeEnvBundleError):
        _freeze(module, sources, tmp_path / "state" / "runtime-env")


def test_verify_rejects_tamper_wrong_identity_and_extra_file(tmp_path: Path) -> None:
    module = _module()
    sources = _sources(tmp_path)
    bundle = tmp_path / "state" / "runtime-env"
    digest = _freeze(module, sources, bundle)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    role_file = bundle / manifest["roles"]["qdrant"]["file"]
    role_file.write_text("QDRANT__SERVICE__API_KEY=tampered\n", encoding="utf-8")

    with pytest.raises(module.RuntimeEnvBundleError, match="differs"):
        module.verify_bundle(
            bundle_dir=bundle,
            candidate_sha=SHA,
            deployment_id=DEPLOYMENT_ID,
            expected_manifest_sha256=digest,
        )

    sources = _sources(tmp_path / "other")
    other = tmp_path / "other-state" / "runtime-env"
    _freeze(module, sources, other)
    with pytest.raises(module.RuntimeEnvBundleError, match="identity"):
        module.verify_bundle(
            bundle_dir=other,
            candidate_sha="b" * 40,
            deployment_id=DEPLOYMENT_ID,
        )
    (other / "unexpected").write_text("x", encoding="utf-8")
    os.chmod(other / "unexpected", 0o600)
    with pytest.raises(module.RuntimeEnvBundleError, match="unexpected files"):
        module.verify_bundle(
            bundle_dir=other,
            candidate_sha=SHA,
            deployment_id=DEPLOYMENT_ID,
        )


def test_alias_with_divergent_reads_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    sources = _sources(tmp_path, alias_application=True)
    original = module._read_regular_file
    main_reads = 0

    def divergent(path: Path, *, label: str, source_owner_uid: int | None = None):
        nonlocal main_reads
        content, source_stat = original(path, label=label, source_owner_uid=source_owner_uid)
        if path == sources["main"]:
            main_reads += 1
            if main_reads > 1:
                content += b"CHANGED_BETWEEN_ALIAS_READS=1\n"
        return content, source_stat

    monkeypatch.setattr(module, "_read_regular_file", divergent)
    with pytest.raises(module.RuntimeEnvBundleError, match="aliased environment"):
        _freeze(module, sources, tmp_path / "state" / "runtime-env")


def test_freeze_rejects_rotation_between_source_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    sources = _sources(tmp_path)
    original = module._read_regular_file
    rotated = False

    def rotate_between_files(path: Path, *, label: str, source_owner_uid: int | None = None):
        nonlocal rotated
        content, source_stat = original(path, label=label, source_owner_uid=source_owner_uid)
        if path == sources["qdrant"] and not rotated:
            application = sources["application"]
            application.write_text(
                application.read_text(encoding="utf-8") + "ROTATED_AFTER_FIRST_READ=1\n",
                encoding="utf-8",
            )
            rotated = True
        return content, source_stat

    monkeypatch.setattr(module, "_read_regular_file", rotate_between_files)
    with pytest.raises(module.RuntimeEnvBundleError, match="changed across the capture"):
        _freeze(module, sources, tmp_path / "state" / "runtime-env")


def test_verify_rejects_hardlinked_bundle_file(tmp_path: Path) -> None:
    module = _module()
    sources = _sources(tmp_path)
    bundle = tmp_path / "state" / "runtime-env"
    _freeze(module, sources, bundle)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    application = bundle / manifest["roles"]["application"]["file"]
    os.link(application, tmp_path / "external-hardlink.env")

    with pytest.raises(module.RuntimeEnvBundleError, match="hard-linked"):
        module.verify_bundle(
            bundle_dir=bundle,
            candidate_sha=SHA,
            deployment_id=DEPLOYMENT_ID,
        )


def test_verify_rejects_manifest_role_alias_with_distinct_source_inodes(
    tmp_path: Path,
) -> None:
    module = _module()
    sources = _sources(tmp_path)
    bundle = tmp_path / "state" / "runtime-env"
    _freeze(module, sources, bundle)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    old_application = manifest["roles"]["application"]["file"]
    compose_main = manifest["roles"]["compose_main"]["file"]
    manifest["roles"]["application"]["file"] = compose_main
    manifest["effective_references"]["AGENTIUM_ENV_FILE"] = compose_main
    del manifest["files"][old_application]
    (bundle / old_application).unlink()
    effective_path = bundle / manifest["effective_compose_file"]
    effective = effective_path.read_text(encoding="utf-8").replace(
        str(bundle / old_application), str(bundle / compose_main)
    )
    effective_path.write_text(effective, encoding="utf-8")
    effective_path.chmod(0o600)
    manifest["files"][manifest["effective_compose_file"]] = {
        "sha256": module._sha256_bytes(effective.encode()),
        "size": len(effective.encode()),
    }
    _rewrite_manifest(module, bundle, manifest)

    with pytest.raises(module.RuntimeEnvBundleError, match="inode alias is inconsistent"):
        module.verify_bundle(
            bundle_dir=bundle,
            candidate_sha=SHA,
            deployment_id=DEPLOYMENT_ID,
        )


def test_verify_recomputes_credential_separation_instead_of_trusting_check(
    tmp_path: Path,
) -> None:
    module = _module()
    sources = _sources(tmp_path)
    bundle = tmp_path / "state" / "runtime-env"
    _freeze(module, sources, bundle)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    application_name = manifest["roles"]["application"]["file"]
    application_path = bundle / application_name
    application = application_path.read_text(encoding="utf-8").replace(
        "OBJECT_STORE_S3_ACCESS_KEY=object-app",
        "OBJECT_STORE_S3_ACCESS_KEY=minio-root",
    )
    application_path.write_text(application, encoding="utf-8")
    application_path.chmod(0o600)
    manifest["files"][application_name] = {
        "sha256": module._sha256_bytes(application.encode()),
        "size": len(application.encode()),
    }
    assert manifest["checks"] == {
        "object_store_minio_credentials_separated": True,
        "placeholder_secrets_rejected": True,
        "production_credentials_explicit": True,
        "source_files_private": True,
        "storage_paths_explicit": True,
        "systemd_revision_bound": True,
    }
    _rewrite_manifest(module, bundle, manifest)

    with pytest.raises(module.RuntimeEnvBundleError, match="not separated"):
        module.verify_bundle(
            bundle_dir=bundle,
            candidate_sha=SHA,
            deployment_id=DEPLOYMENT_ID,
        )


def test_systemd_revision_is_orchestrator_owned_and_recomputed_on_verify(
    tmp_path: Path,
) -> None:
    module = _module()
    sources = _sources(tmp_path)
    systemd_text = sources["systemd"].read_text(encoding="utf-8")
    sources["systemd"].write_text(
        systemd_text + f"AGENTIUM_IMAGE_REVISION={SHA}\n",
        encoding="utf-8",
    )
    with pytest.raises(module.RuntimeEnvBundleError, match="orchestrator-owned"):
        _freeze(module, sources, tmp_path / "rejected" / "runtime-env")

    sources["systemd"].write_text(systemd_text, encoding="utf-8")
    bundle = tmp_path / "state" / "runtime-env"
    _freeze(module, sources, bundle)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    systemd_name = manifest["roles"]["systemd"]["file"]
    systemd_path = bundle / systemd_name
    tampered = systemd_path.read_text(encoding="utf-8").replace(SHA, "b" * 40)
    systemd_path.write_text(tampered, encoding="utf-8")
    systemd_path.chmod(0o600)
    manifest["files"][systemd_name] = {
        "sha256": module._sha256_bytes(tampered.encode()),
        "size": len(tampered.encode()),
    }
    _rewrite_manifest(module, bundle, manifest)

    with pytest.raises(module.RuntimeEnvBundleError, match="revision differs"):
        module.verify_bundle(
            bundle_dir=bundle,
            candidate_sha=SHA,
            deployment_id=DEPLOYMENT_ID,
        )


@pytest.mark.parametrize("failure", ["missing", "same-access", "same-secret"])
def test_freeze_requires_distinct_object_store_and_minio_credentials(
    tmp_path: Path, failure: str
) -> None:
    module = _module()
    sources = _sources(tmp_path)
    application = sources["application"]
    app_text = application.read_text(encoding="utf-8")
    if failure == "missing":
        app_text = app_text.replace("OBJECT_STORE_S3_ACCESS_KEY=object-app\n", "")
    elif failure == "same-access":
        app_text = app_text.replace(
            "OBJECT_STORE_S3_ACCESS_KEY=object-app",
            "OBJECT_STORE_S3_ACCESS_KEY=minio-root",
        )
    else:
        app_text = app_text.replace(
            "OBJECT_STORE_S3_SECRET_KEY=object-app-private",
            "OBJECT_STORE_S3_SECRET_KEY=minio-root-private",
        )
    application.write_text(app_text, encoding="utf-8")

    with pytest.raises(module.RuntimeEnvBundleError, match="not separated"):
        _freeze(module, sources, tmp_path / "state" / "runtime-env")


@pytest.mark.parametrize("key", tuple(_module().REFERENCE_KEYS.values()))
def test_freeze_refuses_missing_indirect_environment_reference(tmp_path: Path, key: str) -> None:
    module = _module()
    sources = _sources(tmp_path)
    main = sources["main"]
    main.write_text(
        "\n".join(
            line
            for line in main.read_text(encoding="utf-8").splitlines()
            if not line.startswith(f"{key}=")
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(module.RuntimeEnvBundleError, match=f"explicitly define {key}"):
        _freeze(module, sources, tmp_path / "state" / "runtime-env")


def test_source_contains_no_value_logging_and_fsyncs_publication() -> None:
    source = HELPER.read_text(encoding="utf-8")
    assert "print(digest)" in source
    assert "print(manifest)" not in source
    assert "os.fsync(handle.fileno())" in source
    assert "_fsync_directory(temporary)" in source
    assert "_fsync_directory(output_dir.parent)" in source


def test_freeze_refuses_world_readable_source(tmp_path: Path) -> None:
    module = _module()
    sources = _sources(tmp_path)
    sources["application"].chmod(0o644)

    with pytest.raises(module.RuntimeEnvBundleError, match="0400 or 0600"):
        _freeze(module, sources, tmp_path / "state" / "runtime-env")


def test_freeze_refuses_oversized_source(tmp_path: Path) -> None:
    module = _module()
    sources = _sources(tmp_path)
    sources["qdrant"].write_bytes(b"A" * (module.MAX_SOURCE_BYTES + 1))
    sources["qdrant"].chmod(0o600)

    with pytest.raises(module.RuntimeEnvBundleError, match="maximum size"):
        _freeze(module, sources, tmp_path / "state" / "runtime-env")


@pytest.mark.parametrize("placeholder", ["guest", "devkey", "change-me-secret"])
def test_freeze_refuses_placeholder_secret(tmp_path: Path, placeholder: str) -> None:
    module = _module()
    sources = _sources(tmp_path)
    sources["qdrant"].write_text(f"QDRANT__SERVICE__API_KEY={placeholder}\n", encoding="utf-8")
    sources["qdrant"].chmod(0o600)

    with pytest.raises(module.RuntimeEnvBundleError, match="placeholder secret"):
        _freeze(module, sources, tmp_path / "state" / "runtime-env")


def test_freeze_refuses_symlinked_parent(tmp_path: Path) -> None:
    module = _module()
    sources = _sources(tmp_path)
    real = sources["application"].parent
    alias = tmp_path / "env-alias"
    alias.symlink_to(real, target_is_directory=True)
    main = sources["main"]
    main.write_text(
        main.read_text(encoding="utf-8").replace(
            str(sources["application"]), str(alias / sources["application"].name)
        ),
        encoding="utf-8",
    )
    main.chmod(0o600)

    with pytest.raises(module.RuntimeEnvBundleError, match="not canonical"):
        _freeze(module, sources, tmp_path / "state" / "runtime-env")


@pytest.mark.parametrize(
    ("role", "old", "new"),
    [
        (
            "application",
            "postgresql://agentium:postgres-private@agentium-pg:5432/agentium",
            "postgresql://${DB_USER}:${DB_PASS}@agentium-pg:5432/agentium",
        ),
        (
            "application",
            "amqp://agentium:rabbit-private@agentium-rabbitmq:5672//",
            "amqp://guest:guest@agentium-rabbitmq:5672//",
        ),
    ],
)
def test_freeze_refuses_dynamic_or_default_credential_urls(
    tmp_path: Path, role: str, old: str, new: str
) -> None:
    module = _module()
    sources = _sources(tmp_path)
    path = sources[role]
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(
        module.RuntimeEnvBundleError,
        match="literal|placeholder",
    ):
        _freeze(module, sources, tmp_path / "state" / "runtime-env")


@pytest.mark.parametrize(
    ("key", "replacement"),
    [
        ("AGENTIUM_FAISS_PATH", "faiss-db"),
        ("AGENTIUM_OBJECT_STORE_PATH", "relative/object-store"),
        ("AGENTIUM_SECURE_DEPOSIT_PATH", "/srv/agentium-data/../escape"),
    ],
)
def test_freeze_requires_explicit_safe_storage_paths(
    tmp_path: Path, key: str, replacement: str
) -> None:
    module = _module()
    sources = _sources(tmp_path)
    main = sources["main"]
    lines = [
        f"{key}={replacement}" if line.startswith(f"{key}=") else line
        for line in main.read_text(encoding="utf-8").splitlines()
    ]
    main.write_text("\n".join(lines) + "\n", encoding="utf-8")
    main.chmod(0o600)

    with pytest.raises(module.RuntimeEnvBundleError, match="storage paths"):
        _freeze(module, sources, tmp_path / "state" / "runtime-env")


@pytest.mark.parametrize(
    ("role", "old", "new", "message"),
    [
        (
            "keycloak",
            "KC_DB_URL=jdbc:postgresql://agentium-pg:5432/agentium",
            "KC_DB_URL=jdbc:postgresql://foreign-pg:5432/agentium",
            "Keycloak",
        ),
        (
            "systemd",
            "@127.0.0.1:5432/agentium",
            "@foreign-pg:5432/agentium",
            "application databases",
        ),
        (
            "application",
            "@agentium-rabbitmq:5672//",
            "@foreign-rabbitmq:5672//",
            "Celery",
        ),
    ],
)
def test_freeze_binds_stateful_clients_to_the_snapshotted_runtime(
    tmp_path: Path, role: str, old: str, new: str, message: str
) -> None:
    module = _module()
    sources = _sources(tmp_path)
    path = sources[role]
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(module.RuntimeEnvBundleError, match=message):
        _freeze(module, sources, tmp_path / "state" / "runtime-env")


def test_freeze_rejects_database_url_query_override(tmp_path: Path) -> None:
    module = _module()
    sources = _sources(tmp_path)
    application = sources["application"]
    application.write_text(
        application.read_text(encoding="utf-8").replace(
            "/agentium\n", "/agentium?host=foreign-pg\n", 1
        ),
        encoding="utf-8",
    )
    application.chmod(0o600)

    with pytest.raises(module.RuntimeEnvBundleError, match="credential URL"):
        _freeze(module, sources, tmp_path / "state" / "runtime-env")


@pytest.mark.parametrize(
    "application_key",
    [
        "qdrant-admin-private-1234567890abcdef",
        "qdrant-unrelated-private-1234567890abcdef",
    ],
)
def test_freeze_requires_application_to_use_qdrant_read_only_key(
    tmp_path: Path, application_key: str
) -> None:
    module = _module()
    sources = _sources(tmp_path)
    application = sources["application"]
    application.write_text(
        application.read_text(encoding="utf-8").replace(
            "QDRANT_API_KEY=qdrant-readonly-private-1234567890abcdef",
            f"QDRANT_API_KEY={application_key}",
        ),
        encoding="utf-8",
    )
    application.chmod(0o600)

    with pytest.raises(module.RuntimeEnvBundleError, match="read-only runtime key"):
        _freeze(module, sources, tmp_path / "state" / "runtime-env")


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("QDRANT_HOST=agentium-qdrant", "QDRANT_HOST=foreign-qdrant", "Qdrant endpoint"),
        (
            "OBJECT_STORE_S3_ENDPOINT_URL=http://agentium-minio:9000",
            "OBJECT_STORE_S3_ENDPOINT_URL=https://foreign-object-store.example",
            "ObjectStore",
        ),
        (
            "SECURE_DEPOSIT_STORAGE_DIR=/data/secure_deposit",
            "SECURE_DEPOSIT_STORAGE_DIR=/tmp/secure-deposit",
            "filesystem paths",
        ),
    ],
)
def test_freeze_binds_application_stores_to_protected_runtime(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    module = _module()
    sources = _sources(tmp_path)
    application = sources["application"]
    application.write_text(
        application.read_text(encoding="utf-8").replace(old, new), encoding="utf-8"
    )
    application.chmod(0o600)

    with pytest.raises(module.RuntimeEnvBundleError, match=message):
        _freeze(module, sources, tmp_path / "state" / "runtime-env")


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            "@127.0.0.1:5672//",
            "@foreign-rabbitmq:5672//",
            "systemd Celery",
        ),
        (
            "QDRANT_API_KEY=qdrant-admin-private-1234567890abcdef",
            "QDRANT_API_KEY=qdrant-readonly-private-1234567890abcdef",
            "systemd Qdrant",
        ),
        (
            "OBJECT_STORE_S3_ENDPOINT_URL=http://127.0.0.1:9000",
            "OBJECT_STORE_S3_ENDPOINT_URL=https://foreign.example",
            "systemd stateful clients",
        ),
    ],
)
def test_freeze_binds_systemd_clients_to_protected_host_runtime(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    module = _module()
    sources = _sources(tmp_path)
    systemd = sources["systemd"]
    systemd.write_text(
        systemd.read_text(encoding="utf-8").replace(old, new), encoding="utf-8"
    )
    systemd.chmod(0o600)

    with pytest.raises(module.RuntimeEnvBundleError, match=message):
        _freeze(module, sources, tmp_path / "state" / "runtime-env")
