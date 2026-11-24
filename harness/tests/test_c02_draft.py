from copy import deepcopy
from pathlib import Path
from benchmark4.harness.common import read
from benchmark4.harness.validate_seed import validate,validate_dataset

def test_c02_static_slots_entity_partition_and_examples():
 root=Path(__file__).resolve().parents[2]
 s=read(root/'seeds/C02_promo_shipping_refund.yaml')
 c01=read(root/'datasets/refund_pilot/seeds/C01_refund_display_contract.yaml')
 assert validate_dataset([c01,s])==[]
 assert s['target_slot']!=c01['target_slot'] and s['status']=='DRAFT_AWAITING_APPROVAL'
 for context,c in [('A_static','A'),('B_irrelevant','B'),('C_changed','C')]:
  state=s['external_profiles'][context]['default'];charges=[]
  for order in state['orders']:
   retained=sum(l['retained_list_cents'] for l in order['retained_lines'] if l['settlement_owner']=='STORE')
   liability=order['checkout_recovery'] if order['checkout_recovery'] is not None else state['carrier_recovery_required']
   amount=order['shipping_subsidy_cents'] if order['promo_waived'] and liability and retained<state['promo_threshold_cents'] else 0
   charges.append(order['order_id']+':'+str(amount))
  assert charges==s['qa']['expected'][c]['charges']
 broken=deepcopy(s)
 broken['external_profiles']['A_static']['default']['orders'][0]['order_id']=s['external_profiles']['T0_history']['default']['orders'][0]['order_id']
 assert any('entity overlap' in e for e in validate(broken))
