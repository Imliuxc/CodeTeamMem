# CodeTeamMem 固定总纲

本文件为只读规范；框架、种子与后续任务均须遵守。当前仅建设框架，不构造业务题、不执行真实模型调用。

## 1. 核心立意与论文锚定
代码库只记录“做什么（What）”，不记录跨角色沟通形成的“为什么这么写、隐性约束、踩坑规矩与生效前提（Why / Premise / Unwritten Contract）”。
团队记忆按功能定义为：**只能通过队友历史知识解锁的、可验证的下游工程任务净增益**。
三大挑战：①代码与记忆纠缠，用反事实过滤剥离；②角色不对称与演化共识，防止 Stale-Consensus Trap（过时共识变毒药）；③问答-执行鸿沟（Paired QA & Executable Coding）与失败归因。

## 2. 维度、场景与角色
五类 scenario：`fe_be_coordination`（S1）、`feature_evolution`（S2）、`cross_role_debugging`（S3）、`task_handoff`（S4，默认 mode_2）、`agent_onboarding`（S5，默认 mode_1）。
五大 dimension：`cross_role_contract`、`unwritten_business_constraint`、`architectural_rationale`、`procedural_debugging_reuse`、`dynamic_knowledge_supersession`。
防饱和铁律：不得考通用编程常识，选定做法必须有至少一个通用工程上同样合理的替代方案，满足 $H(Y \mid R,Q,P_{\mathrm{LLM}}) \gg 0$。
互斥边界：前四维的动态变化主要在接手后的 C 情境触发；第五维专指历史协作流内部已发生多次覆写/推翻的记忆。
五类角色：`pm_lead`（最终拍板权，防 unknown 僵局）、`dev_backend`、`dev_frontend`、`dev_infra_ops`、`qa_engineer`。
单角色信息不足定律：任意单角色发言单独取出，均不足以推出完整答案。

## 3. 记忆、演化与障碍
Gold 四要素：`rule` 现行规则、`key_premise` 关键前提、`scope_boundary` 适用范围与新旧边界、`dead_end` 明确否决的废案/旧值。
轴一 E1–E4：E1 参数/数值链式覆写（如 1000→500→200）；E2 关键前提失效；E3 生效特例补丁；E4 无关扰动对照（检验条件独立性）。E2/E3 必须在公开文档或新环境提供明确的常规默认回退规则。
轴二 O1–O5，与 E 轴严格正交：O1 跨人跨轮拼图；O2 从未生效的脑暴废案与无关噪声；O3 隐含因果/日志前提；O4 代码剥离 Why 注释；O5 旁路无关相似概念干扰。
难度上限：easy 为 1 主演化 + E4 + 3 障碍；medium 为 1 主演化 + E4 + 4 障碍；hard 才允许复合演化与全 5 障碍。单段协作流竞争规则/候选值总数 ≤3。
代码关系：mode_1 遗留逻辑在代码、原因在历史，防 A/B 抄代码，防与历史 E1 冲突泄题；mode_2 基线只有干净骨架与常规政策，隐性约束全在历史。
同一数据集每题独占 target_slot，禁止跨 Case 修改同一策略槽位。

## 4. 代码与对话协作
独立 external_world_service 由 world_profile（T0_history / A_static / B_irrelevant / C_changed）驱动，按金额/日期/渠道/协议返回真实响应。服务源码对业务与接手容器不可见。只返回当下客观状态 What，不泄露历史规矩或老单边界。QA 直接拉取同 profile 快照，与 Coding 同源。
代码关键帧与状态机交织：上半场由单兵顺序产出真实 T0→T1 代码关键帧，在 Docker 实采 tool_log、git_diff、pytest 输出；随后 FactLedger(unlock_act) 物理隔离与 ActStateMachine(min/max turns + exit_condition) 同步推进分幕对话，将真实 tool_log、git_diff、pr_review 按时间线织入 raw_stream.jsonl。
每轮硬校验：1–3 句短句、0 条列总结、0 禁用元词、符号 100% 命中 AST symbol_manifest.json。
成稿放行：符号对齐 100%、单角色盲测低分（信息真散开）、整段原文高分（信息完整无歧义）。

## 5. 流水线与治理
harness/factory.py 确定性四阶段：
1. 配方校验 + QA 三锚点快筛。
2. Docker 代码底座/关键帧 + 单测正反自检 + Coding 三锚点校准。
3. 状态机生成混合协作流 + 自动算分入库 LOCKED。
4. 单题/多题交错 merged_stream.jsonl + 统一 MemoryAdapter 白盒与黑盒榜单。
模式：--mode supervised 每步停在 Gate，输出 ≤15 行摘要等待确认；--mode auto 从 seeds/ 批量生产过滤。
统一 budget_guard.py 预算闸门；Docker Coding 输入硬限 24k Token，工具回显按 4KB 分页，40–60 轮上限与准确进展检测。同一 Stage 失败两次战略熔断，停止补丁并上报简化提议。
反事实门槛：B0 ≤1/3、B2 ≥2/3、B1_C < B2_C。
论文指标四组：黑盒效用、QA-Coding 问答执行鸿沟、过时共识负迁移、Token/通信开销；另附白盒四项抽取分。
