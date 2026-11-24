# Stage 1：已批准口径与实现边界

来源：本聊天用户正式拍板的五项口径；这些决议是固定 SPEC 的细化，本轮不修改只读 SPEC。

## 五项决议

1. 达到 max_turns 仅强停；exit_condition 未满足时本次生成失败，计阶段 attempt，不得继续放行或 LOCKED。退出判定口径为“正则优先 + 必要时单句二元语义判定”，非纯确定性；本轮不改 Stage 3。
2. Stage 1 只在公开政策与数据结构说明下做 QA 初筛，验证题面区分度、防剧透，不证明真实代码底座不可解。Stage 2 在最终冻结底座上做 Coding 校准；Stage 2 改动公开说明后须复核 QA，本轮不实现 Stage 2。
3. 每题声明 watched_files（共享文件和独占槽位文件），按文件哈希绑定。新增题未改共享文件时，旧题仅跑 0-Token pytest 回归；共享文件或公开政策变更时重验受影响旧题，范围不明才全量重验。本轮 Stage 1 产物记录 seed/policy/schema 和已存在 watched_files 的哈希；缺文件明确记 null，不视为哈希相等。Stage 2 的依赖调度与 pytest 重验以后实现。
4. Stage 1 每格独立答题 3 次：B0≤1/3、B2≥2/3、B1_A≥2/3、B1_B≥2/3、B1_C≤B2_C−1/3。Stage 3 整段验真：单轮 A/B/C 3/3；重复三次则每情境≥2/3（待对应阶段实现）。可调预算默认 Stage 1=150k、Stage 2=1.5M、Stage 3=100k，见 harness/config.yaml；本轮仅接入 Stage 1。
5. 业务失败 attempts 按 (case_id, stage) 累积，两次战略熔断。结果分栏 model_wrong、parse_error、env_error；env_error 不计业务失败。基础设施初次失败后最多重试两次，第三次仍失败标 NEEDS_HUMAN；该上限跨恢复保留，不得靠重启清零。

## 当前可运行路径

C01 已获首次真实 Stage 1 授权并完成初筛，结果为 GATE；详见 [真实运行摘要](datasets/refund_pilot/cases/C01_refund_display_contract/SUMMARY.md)。Stage 2–4 仍未接通生产运行。C01 配方见 [源配方](seeds/C01_refund_display_contract.yaml)，实际运行副本位于 datasets/refund_pilot/seeds/。静态检查：

```sh
python3 -m benchmark4.harness.validate_seed --dataset benchmark4 --case C01_refund_display_contract
python3 -m pytest benchmark4/harness/tests -v
```

模板 seed_template.yaml 是保留的空模板，选择器及数据集校验都排除它，其他不合法配方仍拒绝。
配方包含 qa 时校验公开政策/schema、三锚点上下文、A/B/C 同话术、输出 schema、精确答案格式及 watched_files。文本中性、防剧透仍需人工审查；静态关键词规则不证明语义中性。

后续获得用户对 C01 配方及真实调用的明确授权后，才允许使用执行入口。命令形式如下（本轮未执行）：

```sh
python3 -m benchmark4.harness.factory --dataset DATASET_PATH --case CASE_ID --stage 1 --mode supervised --execute-stage1
```

配方位于 DATASET_PATH/seeds/；不使用 --execute-stage1 时只校验已有产物，无真实调用。显式执行只允许 --stage 1，成功停 Gate，不自动启动 Stage 2。也可用 run_qa_calibration 同名 --execute-stage1 入口，经同一 Factory 和计数路径运行。后续阶段的代码与旧技术演示回放入口保持原状；无 qa 字段的旧技术 fixture 仍按旧 artifact 规则回放，不能作为新的 Stage 1 实测。

## 模型配置与预算

真实传输使用可选 openai SDK：默认 Chat Completions；CODETEAMMEM_API_STYLE=responses 时用 Responses（纯文本、关闭思考、store=false）。首轮按用户指定采用 Ark 的 deepseek-v4-1-flash-260910，记录在 run_info.json；未持久化密钥。环境变量为 CODETEAMMEM_MODEL、CODETEAMMEM_API_KEY（可回退 ARK_API_KEY / OPENAI_API_KEY）、CODETEAMMEM_BASE_URL（可回退 OPENAI_BASE_URL，未设则用 SDK 默认地址）。SDK 自动重试关闭，防止绕开基础设施计数。temperature 默认 0；模型不支持时可在配置设 null。
接口以单个 user 消息承载序列化的两轮任务与上下文，27 次均为独立请求，不共享会话。不是两次 API 的多轮交互；这一点对 A/B/C 完全一致。
prompt 只取 public_policy、data_schema、指定 anchor_context、当前世界快照、中性话术及输出 schema。expected、候选对照答案、Gold 字段名、轴标签、case id 不进入模型输入；B2 的团队上下文本来就是受控提供的完整规则上界。

BudgetGuard 默认禁用。Stage 1 显式执行后启用，每次请求经过统一预算闸门；Stage 1 超长输入直接拒绝，不能截断事实后继续评分。异常请求的预留预算不退还，防止重试绕过；跨业务重跑/基础设施重跑保留累计预算。预算不足或 provider 使用量越界时 NEEDS_HUMAN，不计为业务答错，也不盲目重试。
内置 Utf8BoundTokenizer 用 UTF-8 字节数为 byte-BPE 输入提供保守上界（另预留可配置消息开销），不是实际 Token 数。实际 Token 账来自 provider usage；不兼容 byte-BPE 的模型必须通过 Python 接口注入适配 tokenizer。回包超过预留上界会记录实际越界量并熔断。没有用字符估算冒充真实 Token。服务报错且无 usage 时只能保守预留，真实消耗未知。

## 判分、证据与分母

27 次 = 3 锚点 × 3 情境 × 3 次重复；每格分母固定 3。精确解析 JSON，只接受 output_schema 声明的唯一字符串列表；不隐式转换类型，不修复输出，不剥 Markdown。列表按集合身份排序比较，重复标识、额外字段、重复 JSON 键均 parse_error。
有效 JSON 但集合不匹配记 model_wrong；不合法输出记 parse_error，并在该格固定分母中记未通过。二者始终分栏。env_error 使该轮校准不完整，不补零、不假装形成完整矩阵；基础设施重跑保存独立原始记录。
Factory 的 attempts[case_id]["1"] 记录阶段级业务失败次数及失败类别次数；每次请求级别的类别明细在校准报告。混合错误的失败轮次优先标 parse_error，明细仍保留 model_wrong；这些是观测分类，不是因果归因。

产物在 cases/CASE_ID/：qa_calibration_runs/NNNN.json 保留每次完整或中断运行；qa_calibration.json 指向最新报告内容；factory_state.json 记录计数、阶段、Gate、累计保守预算。报告包含原始 prompt/回答、每格分数、正确集合、真实 usage、未确认请求的保守记账及来源哈希。这些是可信控制侧私有材料，不能挂入接手容器。
B1 是缺失关键前提的历史压缩共识；B2 是完整结构化规则的特权上界。不能据此声称实际历史流信息完整或角色信息真分散；要等 Stage 3 独立生成和盲测。三次重复只是小样本筛选，不能当成稳定能力估计。

## 后续阶段待办（本轮不修改）

- Stage 2：真实代码关键帧、隐藏测试正反自检、外部服务容器隔离、最终底座 Coding 校准；公开说明变化时 QA 复核；按 watched_files 哈希执行受影响范围重验。
- Stage 3 act_stream_builder：先选 speaker 再按 owner+unlock_act 物理投喂；工具事件先进入公共上下文再生成；违规有界重生成；exit_condition 正则/必要语义二元判定；真实单角色盲测与整段清晰度评测，超幕失败计阶段 attempt。
- Stage 4 run_memory_benchmark：真正运行各 Memory 系统、QA 与 Coding 双轨、白盒完整度/污染率、统一分母与失败分栏、榜单导出。
- 外层仅 Stage 1 增强；后续阶段 manifest/hash/Gate 与新错误分类联动，等用到对应 Stage 再实施，不把本轮初筛 Gate 当作完整工厂已经接通。

## 首轮结果

[首次真实 Stage 1 摘要](datasets/refund_pilot/cases/C01_refund_display_contract/SUMMARY.md)：B0=0/0/0，B1=3/3/1，B2=3/3/3（各格分母3）；实际26125 Token，27次请求，无解析/环境错误，停在Gate。B2提前剧透的语句已在实际调用前移除。Responses 适配的思考参数按 [Ark 官方说明](https://docs.volcengine.com/docs/ark/responses-api-deep-thinking?lang=en) 核对。
