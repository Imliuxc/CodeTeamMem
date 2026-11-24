import pytest
from shared.refund_schema import executions, confirmed

def test_empty():
    assert executions({}) == []

def test_duplicate_rejected():
    with pytest.raises(ValueError):
        executions({'executions': [{'exec_id': 'X1'}, {'exec_id': 'X1'}]})

def test_evidence_fields():
    assert confirmed({'acceptance_ack': 'ACCEPTED'})
    assert confirmed({'query_acceptance': 'ACCEPTED'})
    assert not confirmed({'http_status': 200})
