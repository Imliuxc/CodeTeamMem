def executions(snapshot):
    rows = snapshot.get('executions', [])
    ids = [r['exec_id'] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate execution identifier')
    return sorted(rows, key=lambda r: int(r['exec_id'][1:]))

def confirmed(row):
    return row.get('acceptance_ack') == 'ACCEPTED' or row.get('query_acceptance') == 'ACCEPTED'
