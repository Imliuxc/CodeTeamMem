from shared.refund_schema import executions, confirmed

def select_exec_ids(snapshot):
    latest = {}
    for row in executions(snapshot):
        if confirmed(row):
            latest[row['after_sale_id']] = row['exec_id']
    return sorted(latest.values())
