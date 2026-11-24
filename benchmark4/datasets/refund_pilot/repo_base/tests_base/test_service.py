from refunds.service import list_refunds, group_refunds, get_visible_execution

def test_empty_projection():
    assert list_refunds({}) == []
    assert group_refunds({}) == {}

def test_single_execution_roundtrip():
    row = {'exec_id': 'X1', 'after_sale_id': 'Y1', 'acceptance_ack': 'ACCEPTED'}
    snapshot = {'executions': [row]}
    assert list_refunds(snapshot) == [row]
    assert group_refunds(snapshot) == {'Y1': [row]}
    assert get_visible_execution(snapshot, 'X1') == row

def test_missing_lookup():
    assert get_visible_execution({}, 'X9') is None
