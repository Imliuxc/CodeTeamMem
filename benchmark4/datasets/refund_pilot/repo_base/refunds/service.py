import json
import os
from urllib.request import Request, urlopen
from shared.refund_schema import executions
from refunds.display_contract import select_exec_ids

def fetch_snapshot():
    request = Request(os.environ['WORLD_URL'], data=b'{}', headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=3) as response:
        return json.load(response)

def list_refunds(snapshot):
    chosen = set(select_exec_ids(snapshot))
    return [row for row in executions(snapshot) if row['exec_id'] in chosen]

def group_refunds(snapshot):
    groups = {}
    for row in list_refunds(snapshot):
        groups.setdefault(row['after_sale_id'], []).append(row)
    return groups

def get_visible_execution(snapshot, exec_id):
    return next((row for row in list_refunds(snapshot) if row['exec_id'] == exec_id), None)
