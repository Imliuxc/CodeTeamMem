{
  "acceptance_evidence": "acceptance_ack == ACCEPTED 或 query_acceptance == ACCEPTED 表示通道明确确认受理。HTTP 200、提交完成或请求超时本身不构成受理证明。",
  "default_rule": "没有团队专门约定时，退款列表按售后申请汇总；每张售后只选最新确认受理的执行作为代表行。详情可查询全部执行。",
  "document_id": "public_policy.md#refund-list-default",
  "ordering": "exec_id 的数字部分代表创建顺序，仅用于确定最新执行。",
  "receipt_reference": "receipt_ref 是通道记录引用；其分配时点由当前协议的 receipt_assignment 描述，不能脱离协议含义判定。",
  "scope": "这里的列表粒度是无历史覆盖时的常规默认政策，不声明本项目历史上是否另有约定。"
}
