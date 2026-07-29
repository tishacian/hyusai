"""Contract for ordered Workspace App lifecycle step receipts migration 073."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError


def _load_migration():
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "073_workspace_app_steps.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace()
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_073", path)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            sys.modules.pop("alembic", None)
    return module


MIG = _load_migration()


class _Result:
    def scalar_one(self):
        return 0


class _Connection:
    def __init__(self, calls):
        self.calls = calls

    def execute(self, statement):
        compiled = statement.compile()
        self.calls.append(("execute", str(statement), compiled.params))
        return _Result()


class _Batch:
    def __init__(self, calls, table):
        self.calls = calls
        self.table = table

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def alter_column(self, name, **kwargs):
        self.calls.append(("alter_column", self.table, name, kwargs))

    def create_unique_constraint(self, name, columns):
        self.calls.append(("create_unique_constraint", self.table, name, columns))

    def create_check_constraint(self, name, expression):
        self.calls.append(("create_check_constraint", self.table, name, expression))


class _Operations:
    def __init__(self):
        self.calls = []
        self.connection = _Connection(self.calls)

    def add_column(self, table, column):
        self.calls.append(("add_column", table, column.name, column.nullable))

    def get_bind(self):
        return self.connection

    def batch_alter_table(self, table):
        self.calls.append(("batch_alter_table", table))
        return _Batch(self.calls, table)

    def create_table(self, name, *elements):
        self.calls.append(("create_table", name, elements))

    def create_index(self, name, table, columns, *, unique):
        self.calls.append(("create_index", name, table, columns, unique))


def test_revision_extends_the_exact_value_measurement_head() -> None:
    assert MIG.revision == "073_workspace_app_steps"
    assert len(MIG.revision) <= 32
    assert MIG.down_revision == "072_value_measurement_eval"


def test_upgrade_labels_legacy_operations_and_creates_tenant_scoped_receipts(
    monkeypatch,
) -> None:
    operations = _Operations()
    monkeypatch.setattr(MIG, "op", operations)

    MIG.upgrade()

    assert {
        call[2]
        for call in operations.calls
        if call[0] == "add_column" and call[1] == "workspace_app_operations"
    } == {"lifecycle_phase", "steps_sha256", "compensation"}
    execute = next(call for call in operations.calls if call[0] == "execute")
    assert execute[2]["lifecycle_phase"] == "legacy_unorchestrated"
    assert execute[2]["steps_sha256"] == hashlib.sha256(
        json.dumps(
            {"steps": []},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    assert execute[2]["compensation"]["post_commit"] == "legacy_unorchestrated"
    assert (
        "create_unique_constraint",
        "workspace_app_operations",
        "uq_workspace_app_operations_id_workspace",
        ["id", "workspace_id"],
    ) in operations.calls

    create = next(
        call
        for call in operations.calls
        if call[:2] == ("create_table", "workspace_app_lifecycle_step_receipts")
    )
    elements = create[2]
    columns = {item.name for item in elements if isinstance(item, sa.Column)}
    assert {
        "workspace_id",
        "operation_id",
        "installation_id",
        "position",
        "manifest_role",
        "manifest_digest",
        "step_id",
        "step_sha256",
        "executor",
        "outcome",
        "reversibility",
        "compensation",
        "evidence_sha256",
    }.issubset(columns)
    foreign_keys = {
        item.name: (tuple(item.column_keys), tuple(element.target_fullname for element in item.elements))
        for item in elements
        if isinstance(item, sa.ForeignKeyConstraint)
    }
    assert foreign_keys["fk_workspace_app_step_receipts_operation_tenant"] == (
        ("operation_id", "workspace_id"),
        ("workspace_app_operations.id", "workspace_app_operations.workspace_id"),
    )
    assert foreign_keys["fk_workspace_app_step_receipts_installation_tenant"] == (
        ("installation_id", "workspace_id"),
        ("workspace_app_installations.id", "workspace_app_installations.workspace_id"),
    )
    assert any(
        isinstance(item, sa.UniqueConstraint)
        and item.name == "uq_workspace_app_step_receipts_operation_position"
        for item in elements
    )


def _legacy_schema(engine):
    metadata = sa.MetaData()
    workspaces = sa.Table(
        "workspaces",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
    )
    installations = sa.Table(
        "workspace_app_installations",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("app_id", sa.String(120), nullable=False),
        sa.Column("version", sa.String(40), nullable=True),
        sa.Column("manifest_digest", sa.String(64), nullable=True),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("installed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.UniqueConstraint(
            "id",
            "workspace_id",
            name="uq_workspace_app_installations_id_workspace",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "app_id",
            name="uq_workspace_app_installations_workspace_app",
        ),
    )
    operations = sa.Table(
        "workspace_app_operations",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("installation_id", sa.String(36), nullable=False),
        sa.Column("app_id", sa.String(120), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(24), nullable=False),
        sa.Column("from_version", sa.String(40), nullable=True),
        sa.Column("to_version", sa.String(40), nullable=True),
        sa.Column("manifest_digest", sa.String(64), nullable=False),
        sa.Column("plan_sha256", sa.String(64), nullable=False),
        sa.Column("before_state", sa.JSON(), nullable=False),
        sa.Column("after_state", sa.JSON(), nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(
            ["installation_id", "workspace_id"],
            ["workspace_app_installations.id", "workspace_app_installations.workspace_id"],
            name="fk_workspace_app_operations_installation_tenant",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_workspace_app_operations_workspace_key",
        ),
    )
    metadata.create_all(engine)
    return workspaces, installations, operations


def _expect_integrity_error(connection, statement) -> None:
    savepoint = connection.begin_nested()
    try:
        try:
            connection.execute(statement)
        except IntegrityError:
            pass
        else:
            raise AssertionError("database constraint accepted invalid lifecycle receipt")
    finally:
        savepoint.rollback()


class _RealSQLiteBatch:
    """Apply migration 073's batch changes by rebuilding the real table."""

    def __init__(self, operations, table_name: str):
        assert table_name == "workspace_app_operations"
        self.operations = operations
        self.drop_columns: set[str] = set()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is not None:
            return False
        bind = self.operations.bind
        bind.exec_driver_sql(
            'ALTER TABLE "workspace_app_operations" '
            'RENAME TO "_workspace_app_operations_073_old"'
        )
        if self.drop_columns:
            bind.exec_driver_sql(
                """
                CREATE TABLE workspace_app_operations (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    workspace_id VARCHAR(36) NOT NULL,
                    installation_id VARCHAR(36) NOT NULL,
                    app_id VARCHAR(120) NOT NULL,
                    idempotency_key VARCHAR(160) NOT NULL,
                    request_sha256 VARCHAR(64) NOT NULL,
                    operation VARCHAR(24) NOT NULL,
                    from_version VARCHAR(40),
                    to_version VARCHAR(40),
                    manifest_digest VARCHAR(64) NOT NULL,
                    plan_sha256 VARCHAR(64) NOT NULL,
                    before_state JSON NOT NULL,
                    after_state JSON NOT NULL,
                    actor VARCHAR(255) NOT NULL,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY(workspace_id) REFERENCES workspaces (id),
                    CONSTRAINT fk_workspace_app_operations_installation_tenant
                        FOREIGN KEY(installation_id, workspace_id)
                        REFERENCES workspace_app_installations (id, workspace_id),
                    CONSTRAINT uq_workspace_app_operations_workspace_key
                        UNIQUE (workspace_id, idempotency_key),
                    CONSTRAINT ck_workspace_app_operations_operation CHECK (
                        operation IN ('install', 'upgrade', 'rollback', 'uninstall')
                    )
                )
                """
            )
            columns = (
                "id, workspace_id, installation_id, app_id, idempotency_key, "
                "request_sha256, operation, from_version, to_version, "
                "manifest_digest, plan_sha256, before_state, after_state, actor, "
                "created_at"
            )
        else:
            bind.exec_driver_sql(
                """
                CREATE TABLE workspace_app_operations (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    workspace_id VARCHAR(36) NOT NULL,
                    installation_id VARCHAR(36) NOT NULL,
                    app_id VARCHAR(120) NOT NULL,
                    idempotency_key VARCHAR(160) NOT NULL,
                    request_sha256 VARCHAR(64) NOT NULL,
                    operation VARCHAR(24) NOT NULL,
                    from_version VARCHAR(40),
                    to_version VARCHAR(40),
                    manifest_digest VARCHAR(64) NOT NULL,
                    plan_sha256 VARCHAR(64) NOT NULL,
                    lifecycle_phase VARCHAR(32) NOT NULL,
                    steps_sha256 VARCHAR(64) NOT NULL,
                    compensation JSON NOT NULL,
                    before_state JSON NOT NULL,
                    after_state JSON NOT NULL,
                    actor VARCHAR(255) NOT NULL,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY(workspace_id) REFERENCES workspaces (id),
                    CONSTRAINT fk_workspace_app_operations_installation_tenant
                        FOREIGN KEY(installation_id, workspace_id)
                        REFERENCES workspace_app_installations (id, workspace_id),
                    CONSTRAINT uq_workspace_app_operations_workspace_key
                        UNIQUE (workspace_id, idempotency_key),
                    CONSTRAINT uq_workspace_app_operations_id_workspace
                        UNIQUE (id, workspace_id),
                    CONSTRAINT ck_workspace_app_operations_operation CHECK (
                        operation IN ('install', 'upgrade', 'rollback', 'uninstall')
                    ),
                    CONSTRAINT ck_workspace_app_operations_lifecycle_phase CHECK (
                        lifecycle_phase IN (
                            'normal', 'legacy_adoption', 'legacy_unorchestrated'
                        )
                    )
                )
                """
            )
            columns = (
                "id, workspace_id, installation_id, app_id, idempotency_key, "
                "request_sha256, operation, from_version, to_version, "
                "manifest_digest, plan_sha256, lifecycle_phase, steps_sha256, "
                "compensation, before_state, after_state, actor, created_at"
            )
        bind.exec_driver_sql(
            f"INSERT INTO workspace_app_operations ({columns}) "
            f"SELECT {columns} FROM _workspace_app_operations_073_old"
        )
        bind.exec_driver_sql("DROP TABLE _workspace_app_operations_073_old")
        return False

    def alter_column(self, _name, **_kwargs):
        return None

    def create_unique_constraint(self, *_args, **_kwargs):
        return None

    def create_check_constraint(self, *_args, **_kwargs):
        return None

    def drop_constraint(self, *_args, **_kwargs):
        return None

    def drop_column(self, name):
        self.drop_columns.add(name)


class _RealSQLiteOperations:
    def __init__(self, bind):
        self.bind = bind

    def get_bind(self):
        return self.bind

    def add_column(self, table_name: str, column: sa.Column) -> None:
        type_sql = column.type.compile(dialect=self.bind.dialect)
        self.bind.exec_driver_sql(
            f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" {type_sql}'
        )

    def batch_alter_table(self, table_name: str):
        return _RealSQLiteBatch(self, table_name)

    def create_table(self, name, *elements):
        metadata = sa.MetaData()
        metadata.reflect(self.bind)
        table = sa.Table(name, metadata, *elements)
        table.create(self.bind)
        return table

    def create_index(self, name, table_name, columns, *, unique):
        unique_sql = "UNIQUE " if unique else ""
        column_sql = ", ".join(f'"{column}"' for column in columns)
        self.bind.exec_driver_sql(
            f'CREATE {unique_sql}INDEX "{name}" '
            f'ON "{table_name}" ({column_sql})'
        )

    def drop_table(self, name):
        table = sa.Table(name, sa.MetaData(), autoload_with=self.bind)
        table.drop(self.bind)


def test_real_sqlite_upgrade_enforces_receipts_and_safe_downgrade(monkeypatch) -> None:
    engine = sa.create_engine("sqlite://")
    workspaces, installations, operations = _legacy_schema(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.execute(
            workspaces.insert(),
            [{"id": "workspace-a"}, {"id": "workspace-b"}],
        )
        now = datetime.now(UTC).replace(tzinfo=None)
        connection.execute(
            installations.insert(),
            [
                {
                    "id": "installation-a",
                    "workspace_id": "workspace-a",
                    "app_id": "mission-room.extension",
                    "version": "1.0.0",
                    "manifest_digest": "a" * 64,
                    "state": "installed",
                    "configuration": {},
                    "revision": 1,
                    "installed_at": now,
                    "updated_at": now,
                    "updated_by": "legacy-test",
                },
                {
                    "id": "installation-b",
                    "workspace_id": "workspace-b",
                    "app_id": "mission-room.extension",
                    "version": "1.0.0",
                    "manifest_digest": "b" * 64,
                    "state": "installed",
                    "configuration": {},
                    "revision": 1,
                    "installed_at": now,
                    "updated_at": now,
                    "updated_by": "legacy-test",
                },
            ],
        )
        connection.execute(
            operations.insert().values(
                id="operation-a",
                workspace_id="workspace-a",
                installation_id="installation-a",
                app_id="mission-room.extension",
                idempotency_key="legacy-key",
                request_sha256="c" * 64,
                operation="install",
                from_version=None,
                to_version="1.0.0",
                manifest_digest="a" * 64,
                plan_sha256="d" * 64,
                before_state={"state": "absent"},
                after_state={"state": "installed"},
                actor="legacy-test",
                created_at=now,
            )
        )

        monkeypatch.setattr(MIG, "op", _RealSQLiteOperations(connection))
        MIG.upgrade()

        inspector = sa.inspect(connection)
        assert "workspace_app_lifecycle_step_receipts" in inspector.get_table_names()
        operations_v73 = sa.Table(
            "workspace_app_operations",
            sa.MetaData(),
            autoload_with=connection,
        )
        legacy = connection.execute(
            sa.select(operations_v73).where(operations_v73.c.id == "operation-a")
        ).mappings().one()
        assert legacy["lifecycle_phase"] == "legacy_unorchestrated"
        assert legacy["steps_sha256"] == MIG._sha256({"steps": []})
        assert legacy["compensation"]["post_commit"] == "legacy_unorchestrated"

        receipts = sa.Table(
            "workspace_app_lifecycle_step_receipts",
            sa.MetaData(),
            autoload_with=connection,
        )
        valid = {
            "id": "receipt-a",
            "workspace_id": "workspace-a",
            "operation_id": "operation-a",
            "installation_id": "installation-a",
            "app_id": "mission-room.extension",
            "position": 0,
            "manifest_role": "target",
            "manifest_digest": "a" * 64,
            "step_id": "workspace_app_platform.schema.069",
            "step_sha256": "e" * 64,
            "phase": "precondition",
            "executor": "platform_schema_contract_v1",
            "outcome": "verified",
            "reversibility": "persistent_additive_schema",
            "compensation": {},
            "evidence_sha256": "f" * 64,
            "created_at": now,
        }
        connection.execute(receipts.insert().values(**valid))
        _expect_integrity_error(
            connection,
            receipts.insert().values(**{**valid, "id": "receipt-duplicate-position"}),
        )
        _expect_integrity_error(
            connection,
            receipts.insert().values(
                **{
                    **valid,
                    "id": "receipt-cross-tenant",
                    "workspace_id": "workspace-b",
                    "installation_id": "installation-b",
                    "position": 1,
                }
            ),
        )
        _expect_integrity_error(
            connection,
            receipts.insert().values(
                **{
                    **valid,
                    "id": "receipt-invalid-check",
                    "position": 1,
                    "manifest_role": "ambient",
                }
            ),
        )

        try:
            MIG.downgrade()
        except RuntimeError as exc:
            assert "Refusing to downgrade" in str(exc)
        else:
            raise AssertionError("downgrade destroyed non-empty lifecycle receipts")

        connection.execute(receipts.delete())
        MIG.downgrade()
        inspector = sa.inspect(connection)
        assert "workspace_app_lifecycle_step_receipts" not in inspector.get_table_names()
        assert {
            "lifecycle_phase",
            "steps_sha256",
            "compensation",
        }.isdisjoint(
            {column["name"] for column in inspector.get_columns("workspace_app_operations")}
        )
        operations_legacy = sa.Table(
            "workspace_app_operations",
            sa.MetaData(),
            autoload_with=connection,
        )
        preserved = connection.execute(
            sa.select(operations_legacy.c.id, operations_legacy.c.plan_sha256)
        ).mappings().one()
        assert dict(preserved) == {"id": "operation-a", "plan_sha256": "d" * 64}
