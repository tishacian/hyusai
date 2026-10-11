from app.services.automation_dossiers import dossier_rows


def test_three_versions_stay_three_rows_and_a_foreign_run_is_not_proof():
    datasets = [
        {"name": "Omar", "slug": "laptop", "version": 1, "system_id": "sys", "run_id": "run-1", "status": "ready"},
        {"name": "Omar", "slug": "laptop", "version": 2, "system_id": "sys", "run_id": "run-2", "status": "ready"},
        {"name": "Maya", "slug": "desk", "version": 1, "system_id": "sys", "run_id": "run-3", "status": "ready"},
        {"name": "Dropped", "slug": "old", "version": 1, "status": "deleted", "run_id": "run-9"},
        {"name": "Lina", "slug": "chair", "version": 1, "system_id": "sys", "run_id": "other", "status": "ready"},
    ]
    runs = {
        "run-1": {"system_id": "sys", "status": "completed"},
        "run-2": {"system_id": "sys", "status": "hitl_pending"},
        "run-3": {"system_id": "sys", "status": "completed"},
        "other": {"system_id": "elsewhere", "status": "completed"},
    }
    rows = dossier_rows(datasets, runs)
    assert [(row["slug"], row["version"]) for row in rows] == [
        ("chair", 1),
        ("desk", 1),
        ("laptop", 1),
        ("laptop", 2),
    ]
    by_key = {(row["slug"], row["version"]): row for row in rows}
    assert by_key[("laptop", 1)]["proof"] == "present"
    assert by_key[("laptop", 1)]["waiting"] is False
    assert by_key[("laptop", 2)]["waiting"] is True
    assert by_key[("laptop", 2)]["run_status"] == "hitl_pending"
    assert by_key[("desk", 1)]["proof"] == "present"
    assert by_key[("chair", 1)]["proof"] == "absent"
    assert by_key[("chair", 1)]["run_status"] is None
