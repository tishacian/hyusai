from __future__ import annotations

import sys
from types import SimpleNamespace


class _FakePlan:
    dry_run = True
    archives: list[object] = []
    total_documents = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "dry_run": self.dry_run,
            "archives": [],
            "total_documents": self.total_documents,
        }


class _FakeQuery:
    def __init__(self, value: object):
        self._value = value

    def filter(self, *_args: object, **_kwargs: object) -> "_FakeQuery":
        return self

    def order_by(self, *_args: object, **_kwargs: object) -> "_FakeQuery":
        return self

    def first(self) -> object:
        return self._value


class _FakeSession:
    def __init__(self) -> None:
        self.workspace = SimpleNamespace(id="ws-andritz", slug="andritz")
        self.user = SimpleNamespace(id="user-1", email="operator@example.test")
        self.closed = False

    def query(self, model: object) -> _FakeQuery:
        name = getattr(model, "__name__", "")
        if name == "User":
            return _FakeQuery(self.user)
        return _FakeQuery(self.workspace)

    def close(self) -> None:
        self.closed = True


def test_promote_spl_wave_v1_defaults_to_dry_run_without_execute(
    monkeypatch,
    capsys,
) -> None:
    import scripts.promote_spl_wave_v1 as script

    fake_db = _FakeSession()
    build_calls: list[dict[str, object]] = []
    mutating_calls: list[str] = []

    def _build_wave_plan(*_args: object, **kwargs: object) -> _FakePlan:
        build_calls.append(kwargs)
        return _FakePlan()

    def _mutating_call(*_args: object, **_kwargs: object) -> None:
        mutating_calls.append("called")
        raise AssertionError("dry-run invocation must not mutate SPL collections")

    monkeypatch.setattr(script, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(script, "build_wave_plan", _build_wave_plan)
    monkeypatch.setattr(script, "copy_collection_documents", _mutating_call)
    monkeypatch.setattr(script, "execute_wave_plan", _mutating_call)
    monkeypatch.setattr(sys, "argv", ["promote_spl_wave_v1.py", "--workspace", "andritz"])

    script.main()

    assert build_calls and build_calls[0]["dry_run"] is True
    assert mutating_calls == []
    assert fake_db.closed is True
    assert '"dry_run": true' in capsys.readouterr().out


def test_promote_spl_wave_v2_defaults_to_dry_run_without_execute(
    monkeypatch,
    capsys,
) -> None:
    import scripts.promote_spl_wave_v2 as script

    fake_db = _FakeSession()
    build_calls: list[dict[str, object]] = []
    execute_calls: list[str] = []

    def _build_v2_wave_plans(*_args: object, **kwargs: object) -> list[_FakePlan]:
        build_calls.append(kwargs)
        return [_FakePlan()]

    def _execute_v2_wave_plans(*_args: object, **_kwargs: object) -> None:
        execute_calls.append("called")
        raise AssertionError("dry-run invocation must not execute SPL waves")

    monkeypatch.setattr(script, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(script, "build_v2_wave_plans", _build_v2_wave_plans)
    monkeypatch.setattr(script, "execute_v2_wave_plans", _execute_v2_wave_plans)
    monkeypatch.setattr(sys, "argv", ["promote_spl_wave_v2.py", "--workspace", "andritz"])

    script.main()

    assert build_calls and build_calls[0]["dry_run"] is True
    assert execute_calls == []
    assert fake_db.closed is True
    assert '"dry_run": true' in capsys.readouterr().out


def test_promote_spl_wave_v3_defaults_to_dry_run_without_execute(
    monkeypatch,
    capsys,
) -> None:
    import scripts.promote_spl_wave_v3 as script

    fake_db = _FakeSession()
    build_calls: list[dict[str, object]] = []
    execute_calls: list[str] = []

    def _build_v3_wave_plans(*_args: object, **kwargs: object) -> list[_FakePlan]:
        build_calls.append(kwargs)
        return [_FakePlan()]

    def _execute_v3_wave_plans(*_args: object, **_kwargs: object) -> None:
        execute_calls.append("called")
        raise AssertionError("dry-run invocation must not execute SPL waves")

    monkeypatch.setattr(script, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(script, "build_v3_wave_plans", _build_v3_wave_plans)
    monkeypatch.setattr(script, "execute_v3_wave_plans", _execute_v3_wave_plans)
    monkeypatch.setattr(script, "execute_v3_archive_wave_plan", _execute_v3_wave_plans)
    monkeypatch.setattr(sys, "argv", ["promote_spl_wave_v3.py", "--workspace", "andritz"])

    script.main()

    assert build_calls and build_calls[0]["dry_run"] is True
    assert execute_calls == []
    assert fake_db.closed is True
    assert '"dry_run": true' in capsys.readouterr().out
