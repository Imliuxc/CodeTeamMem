import json
import os
from urllib.request import Request, urlopen
import pytest
from refunds.service import list_refunds, group_refunds, get_visible_execution


@pytest.fixture
def snapshot():
    with urlopen(Request(os.environ["WORLD_URL"], data=b"{}", headers={"Content-Type": "application/json"}), timeout=3) as r:
        return json.load(r)


def test_exact_selected_set(snapshot):
    assert sorted(r["exec_id"] for r in list_refunds(snapshot)) == ["E01", "E02", "E05"]


def test_failed_execution_remains_queryable(snapshot):
    row = get_visible_execution(snapshot, "E01")
    assert row is not None and row["execution_result"] == "FAILED"


def test_same_application_keeps_distinct_executions(snapshot):
    assert [r["exec_id"] for r in group_refunds(snapshot)["S01"]] == ["E01", "E02"]
