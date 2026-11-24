# CodeTeamMem 框架

当前统一冻结口径为`unified-48k-50steps-300k-v1`，以harness/config.yaml及config.freeze.json哈希为准，取代下面临时600万排错轮的执行限制。QA/Coding单请求输入保守上界48000（真实usage另记）；Coding最多50步，独立Coding试次最多300000 Token，Memory配对试次QA+Coding共用同一个300000子预算并同时受批总预算约束。首次新文件/新页不计连续同错，不设80次发现额度；仍占总步数和无有效编辑轮数。15轮无新有效AST编辑提醒，25轮强停；公共测试通过不重置无编辑计数。连续6次同失败/相同无改善写入/重复同页停机，错误指纹随代码状态、工具/页与公开测试通过集合区分。非法协议/基础设施错误仍按原分类立即停止，不假装成需重试六次的业务错误。旧配置、模型结果及其原始参数不回写，不宣称旧锚点与新限制同条件。

本轮没有C01模型/Docker重跑。C02草案见 [seeds/C02_promo_shipping_refund.yaml](seeds/C02_promo_shipping_refund.yaml)，维度unwritten_business_constraint，独占refunds.promo_shipping.shipping_clawback_cents，与C01槽位分离；未加入数据集的可运行冻结seeds，须审批后才注册/启动Stage 1。公开默认采用全部保留商品实付额；拟议历史约定采用STORE结算商品原标价，两项必要私有事实分属不同角色。旧合同追收责任冻结，新合同不再追收时新单回退为0。给定五单，A/B追回800/0/0/800/0分，C为0/0/0/800/0分。金额均是拟议业务约定，不是现实商家规则，区分度未实测。

C02静态实体隔离用entity_partition声明order_id/line_id字段，T0历史HIST_C02_*与全部评测EVAL_C02_*集合不得相交；validate_seed仅对显式声明该约束的新题检查，不改C01。历史样例金额也区别于评测金额。公开默认不暴露专门的标价/结算范围选择；其单角色不足与B0/B1/B2分化仍需后续QA实证。基础测试计划只检查数据/API不变量并明确提示不能证明任务完成，不把默认业务政策写成掩盖缺失功能的验收标准。业务底座、Gold、公开政策、隐藏测试及C01锁定原件不改。

Stage 3复杂流现状：事实按角色/幕隔离和每幕min/max已支持；可用数据配置分幕，但没有强制“候选推进与最终否决分幕”语义检查；没有独立噪声/O5幕类型或配额，没有相似度去重锁，没有生成成稿级的历史/评测实体扫描，也没有统一≥24条对话验收门禁。C02的四幕min_turns=6只表示配方计划24条，不代表已有全局门禁；这些缺口已列入construction_notes，走到C02 Stage 3前再讨论补齐，本轮不实现。

最新600万预算重测已完成并停Gate4B，见 [0002报告](datasets/refund_pilot/cases/C01_refund_display_contract/stage4_runs/0002/SUMMARY.md)。213项离线测试先通过；六组QA全对，Coding FullHistory 2/3、RAG 0/3。实际443006 Token，无额度/轮数早停或解析/环境错；四个错误例都收到无语义修改提醒后明确解释无需修改，再提交原基线并隐藏测试0/3。不能继续将这些错误归因为预算太小。相较旧试跑多122931 Token（38.41%）；n=1且反馈/呈现一起变更，不能做额度单变量因果结论。

分开评分已显示差异：两方法全库存储支持仍为规则2/2、前提2/2、边界3/4；RAG实际检索支持降为1/2、1/2、2/4，其中缺的是商家对账动机，受理后分配回执前提仍召回。废案污染0/3必须同时看极性覆盖（全库2/3、检索1/3），unknown不能解读为已证明无污染。两基线无结构化抽取，明确not_applicable。425个锁定业务/历史文件和0001原件均未改，框架修改已获用户授权，旧锚点只作历史参考。

当前执行器已按用户批准就地放宽：横评预算6000000，输入保守上界240000，Coding最多500轮，新发现额度80，连续无进展50轮。默认值统一由config.yaml及limits.py读取；输出512/2048、工具分页4KB、模型及温度不变。UTF-8字节数用于请求前保守预留，不冒充真实token数；实际输入/输出/缓存以provider usage记录。官方模型列表确认deepseek-v4-1-flash-260910最大输入1024K：https://docs.volcengine.com/docs/ark/model-list?redirect=1&lang=zh 。

工具关联结果新增剩余轮数/探索/停滞/预算、重复观察、重复写入、非语义改动及公共测试失败反馈；不公开隐藏测试。首次finish若与初始AST相同，会中性要求修改或提供无需修改理由；再次finish仍提交隐藏判卷，不强迫假修改。原TF-IDF排名与分块不变，仅给选中片段附完整事件来源、字符范围、片段不完整提示。

新白盒输出store_support（完整存储）、逐试次retrieval_support（真正送入模型的命中片段）、structured_extraction（原文存储基线为not_applicable）。兼容字段whitebox仍等于存储支持，不能再把它解释成召回质量。三个废案状态denied/active/unknown及覆盖分母保持不变，不对未匹配项补“安全”。

旧实验日志与业务/Gold/公开政策/外部世界/隐藏单测不改；用户已授权改变旧21项中的框架代码与执行配置。旧校准报告内的框架哈希及参数原样保留，不能再宣称全部21项框架哈希未变或同条件横比。当前锁定业务产物425项仍校验。新榜单anchors.execution_compatible=false并记录参数差异，只作历史参考；不自动重跑27次锚点。离线结果见reports/expanded_execution_tests.txt（213项通过）。

最新：C01首次真实Stage 4B已完成并停在Gate 4B待审阅，见 [试跑报告](datasets/refund_pilot/cases/C01_refund_display_contract/stage4_runs/0001/SUMMARY.md)。两方法每格n=1，锚点每格n=3且只复用旧账。FullHistory QA/Coding各3/3；TF-IDF RAG QA3/3、Coding0/3，三条配对错例已导出。总320075 Token，无解析/环境错，六例容器/网络/卷均0残留；锁定425项/Stage 2冻结21项哈希不变。没有追加重复或扩额。下文Stage 4A“本轮不执行”是历史准备轮的边界，真实授权与结果以0001/run_info及verification为准。

这次RAG并未漏掉“受理后才分配回执”前提，也没有把废案作为现行规则的召回证据；其A停滞、B/C隐藏测试各0/3，补丁都只改空行。不能把这三次Coding错误直接归因为漏召回前提。白盒存储匹配两方法相同，污染率0/3但极性覆盖仅2/3，未知不代表已证明无污染。所有比较仅限C01和已观察试次。

## 当前：C01已LOCKED，Stage 4A仅离线准备

用户已人工批准Gate 3及两项表达歧义，锁定记录见 [LOCKED.json](datasets/refund_pilot/cases/C01_refund_display_contract/LOCKED.json)。它选择stage3_runs/0003原始流并固定425个Stage 1–3产物哈希；21项Stage 2哈希另列。原报告中的待审阅状态是历史原件，不重写。factory_state推进到stage=3/status=LOCKED；Stage 4A不执行真实模型、不改变任何锁定产物，也不把Mock榜单当实测。

Stage 4新入口为`python3 -m benchmark4.harness.run_memory_benchmark --dataset PATH --case ID`，默认拒绝调用；Stage 4B须另行授权并显式`--execute-memory --repeats 1 --token-budget 600000`。`--all`选择同一数据集多题；各题独立榜单，不混报不同题的排名。`--adapters long_context naive_rag`选择两个本地基线。未显式执行不会创建SDK客户端或启动Docker。旧run/summarize函数只供既有技术fixture回放，其Gold整句精确相等分不是本次真实白盒分。

LongContextConcatAdapter按sequence拼接全部公开事件，不按默认limit裁去早期记录。NaiveChunkRAGAdapter以600字符块/80字符重叠保存公开流，ASCII词和中文单字/二元词进行余弦TF-IDF，默认Top-6；平分按写入顺序，命中块按历史顺序呈现。所有文本及元数据深拷贝，不向Memory系统传fact_ids、Gold、验收答案或隐藏单测。dump_memories返回完整存储，因此白盒衡量存储支持，检索缺失由黑盒另行体现。

真实链路为`evaluate_memories → LOCKED哈希校验/冻结锚点加载 → adapter.ingest/retrieve/dump_memories → QA/Coding → paired_metrics/save_leaderboard`。不重新调用B0/B1/B2，使用原27次QA和27次Coding的原始记录核对分数，各锚点每格分母3，原文件SHA256记入榜单。两轨锚点是独立试次，不能伪装成配对错误转移。只对新Memory试次做配对：同一context/repeat只检索一次，原样注入两轨；QA题面/模型/温度/输出上限/判分不变，Coding复用冻结coding_session、镜像ID、底座、隐藏测试、24k/4KB/50轮/停滞参数。

memory_coding.py用全新临时仓库和internal网络；工作容器无隐藏测试/服务源码，判卷容器只读同一候选卷；保存补丁、XML及pytest原始输出，逐例检查容器/网络/卷清理。没有新增run_cmd或模型重试。API、Docker与预算入口在离线测试中注入Mock；测试不证明当前Docker守护进程的实时健康，Stage 4B仍受环境错误停止门禁约束。

黑盒分母为各轨已结束且outcome属于pass/model_wrong/parse_error的试次，计划分母另列；env_error/budget_stop不补零，立即停止，未完成格仅作暂定并禁止入榜。真实成本保留provider usage；缺usage则total_tokens=null且列known_tokens/保守预算扣账，不能报告0实际消耗。缓存为输入子集。配对QA−Coding只用两轨都结束的业务试次，QA=PASS且Coding业务失败导出qa_pass_coding_fail.json；QA通过/Coding环境错不当执行鸿沟错例。

榜单输出leaderboard.json/.md、逐试次retrieval/result、memories、model_calls及错例JSON；排名只纳入完整方法，按Coding宏平均、QA宏平均、方法名排序。各格同时报告对B0净增益和距B2差距。C失败按outcome分栏；负迁移只报独立B0_C均值减Memory_C均值的有符号观测差，matched_b0_harm_count=null，不声称逐例因果负迁移。当前仅1题，所有排名/差异均不能推广为总体结论。

白盒由独立 [whitebox_rubric.json](datasets/refund_pilot/cases/C01_refund_display_contract/whitebox_rubric.json) 对齐Gold原子项：规则2、前提2、边界4、废案3。前三分为支持原子项数/固定原子项数，未命中标unmatched_or_ambiguous，不等于语义错误。污染率为最后明确被肯定的否决方案数/3，另外报告assessed_coverage；unknown不伪装成已证明无污染。只从chat/memory判断现行方案，工具输出/diff不当政策断言；同一方案后续明确否决覆盖早期肯定，避免仅因历史提过就判污染。正则证据是可复查的局部近似，不能冒充完整语义/因果评审。真实跑前rubric可单独人工复核，且不会发送给被测模型。

Stage 4B建议先2方法×3情境×1次＝6组QA+Coding，零锚点重跑。按Stage 2正式Coding平均43147 Token/例估算，加长记忆上下文后预计35–50万Token，建议总硬限60万；这是外推而非保证。链路确认后另批追加2轮至每格3次；本轮不执行。用户此前提到的0004/pm_lead豁免已撤回，所有Stage 3锁定仍按原全四角色门槛。

固定规范见 [SPEC.md](SPEC.md)。C01 已完成 Stage 2 正式27次 Coding 校准并满足冻结门槛，状态 CODE_CALIBRATED，停在 Gate 2，未进入 Stage 3/4。当前结果见 [Stage 2 摘要](datasets/refund_pilot/cases/C01_refund_display_contract/CODING_CALIBRATION.md)，此前 [Stage 1 摘要](datasets/refund_pilot/cases/C01_refund_display_contract/SUMMARY.md) 与 [Repeat #1 摘要](datasets/refund_pilot/cases/C01_refund_display_contract/CODING_REPEAT1.md) 独立保留。可视化演示运行记录独立保存在 reports/status_service/。

## Stage 3：0003自动验真通过，待Gate 3人工审阅

最新实际0003见 [复核汇总](datasets/refund_pilot/cases/C01_refund_display_contract/stage3_runs/0003/review_summary.json) 与 [全部聊天候选原文](datasets/refund_pilot/cases/C01_refund_display_contract/stage3_runs/0003/CHAT.md)：6条接受消息、1条事实表达检查失败后重生成的候选；原全四角色盲测每格≤1/3，完整流A/B/C各3/3。没有采用C01拍板角色豁免。45次QA均有精确判分，pass=10、model_wrong=35、parse_error/env_error均0；盲测低分是门槛要求，不是阶段失败。

普通文本代码形态引用的词法复查为23/23，按每条消息不同引用累计；原验真报告symbol_reference_count仍是仅反引号计数0，复核汇总明确分开记录，未覆盖或重写原始报告。6条接受消息条列/禁词0。否决三项均获模型二元语义判true，这不是确定性证明：原文“先不采用”及未直说跨协议禁止的表达需人工重点审阅，不能把自动分数当最终自然度/歧义验收。

0003真实生成13406、验真59593、合计72999 Token，低于本轮独立200000；0001/0002历史9572保留，累计生成22978、验真59593、总82571。70次API均有usage且响应ID互异，无未知消耗；21项冻结哈希及0001/0002文件哈希均未变。状态GATE_3_REVIEW、待确认阶段3，最后正式完成阶段仍为2；未LOCKED、未进入Stage 4。以下保留修复与历史故障口径。

0003前统一规则（用户批准，替代下面0002时的两套引用限制）：普通文本与反引号使用同一个动态集合。集合来自冻结AST及真实文件路径、公开data_schema/public_policy标识、当前speaker已解锁的私有事实标识、已验证公开事实标识、已注入T0载荷的所有JSON键和标量、已注入T0→T1 diff的标识/路径、常见基础字面量。数据ID与代码名不再按反引号分两套会员规则。T0/diff词随事件注入，私有事实词按speaker隔离，不提前公布未来幕或队友私事。

控制侧用C_changed与T0的键/标量差集保留未来专属值硬拦截，且优先于白名单；这个差集不进入生成器提示。识别范围为反引号引用及普通文本中的snake_case、大写/混合大小写标识、样例ID、函数调用和常见源码/数据文件路径；自然语言别名不能仅靠词法证明。每轮错误以具体rule、hits、previous_output、next_attempt传入重试提示，不承诺temperature=0必然改写成功，仍最多两次重生成。测试见 [196项离线结果](reports/stage3b_unified_vocabulary_pytest.txt)。

用户已明确解除此前CIRCUIT_OPEN并批准一次0003，历史失败次数和0001/0002原件不重写。新运行独立200000 Token，历史9572分列。此处没有采用基于不存在的0003结果提出的C01盲测例外：仍执行全部四角色每格≤1/3和整段每格≥2/3，完成前不预判结果，不LOCKED、不进Stage 4。

以下为0002结束时的历史记录：

最新0002在166项离线测试通过后执行，见 [0002失败复核](datasets/refund_pilot/cases/C01_refund_display_contract/stage3_runs/0002/failure_review.json) 与 [全部候选原文](datasets/refund_pilot/cases/C01_refund_display_contract/stage3_runs/0002/CHAT.md)。字段/协议白名单已生效，但后端三次都把已公开的E01/E02/E03加反引号；当前实现只允许这些样例ID作为普通数据文本，带反引号即按代码符号校验而拦截。这是本次实现的引用形式遗漏，不是捏造ID，也不是QA答错。未执行盲测、清晰度或否决核验，不能填0分或宣称验真通过。

0002独立预算200000，实际生成4985、验真0；0001历史生成4587，合计9572 Token，无未知消耗。0001全部文件哈希原样保留，21项Stage 2哈希未变。最后完成阶段仍为2/CODE_CALIBRATED，Stage 3失败计数2、CIRCUIT_OPEN；没有LOCKED或Stage 4，也没有0003。已停止进一步补丁。建议后续审阅“已观测数据值的反引号引用”与“代码符号引用”分类边界，再另行授权修复/重启；这只是提议，尚未实施。

0002前的框架修复：单轮及成稿复核共用随时间线变化的白名单，来源仅为冻结AST、公开data_schema字段名、已注入T0响应的JSON键与协议/枚举。`t0_vocabulary`只遍历T0响应：收集所有JSON键、protocol子树及`*_values`声明的字符串、观测到的纯大写枚举；不遍历C或其他profile、不从公开说明正文抽取值。实际样例标识E03/CH01等仅允许作为T0已公开的数据引用，不当作代码符号加入allowed_symbols；未知REG03即使未加反引号也拒绝。T0新增词在日志注入前不进入生成器白名单；公开schema字段本来公开，可提前使用。验证阶段按事件顺序重建相同集合，不用最终并集倒灌早期幕。

修复没有修改46项AST清单或其他21项冻结文件；0001全部证据保留，原失败判定不回写。离线测试见 [166项测试记录](reports/stage3b_symbol_fix_pytest.txt)。后续0002获单次真实调用授权，独立总预算200000 Token；0001的4587 Token另列累计，不冲抵本次额度。尚未生成的分数不补0，符号对齐以实际引用数为分母。

历史0001真实Stage 3B，见 [失败复核](datasets/refund_pilot/cases/C01_refund_display_contract/stage3_runs/0001/failure_review.json) 和 [全部聊天候选原文](datasets/refund_pilot/cases/C01_refund_display_contract/stage3_runs/0001/CHAT.md)。Act 1接受2条；Act 2后端连续3条（含2次重生成）因引用receipt_ref而被符号门禁拦截，故停止。该字段真实存在于T0响应，但不在冻结46项AST清单，不能把此次失败归因为捏造字段或业务理解错误。当轮未改白名单、未重跑；后续0002的修复与结果见上文，旧判定不回写。

本次生成阶段4587 Token（输入4223、输出364；缓存1920已含在输入中，含事实语义检查），验真0；7次API都有真实usage，无缺失。接受的2条未引用代码符号，分母0，符号对齐率记null，不报100%。36次盲测、9次清晰度及否决核验均未执行，不能填0分或声称完整验真。T0日志已在Act 2前注入，未到Act 3所以diff未注入。stage3_last_run记录FAILED、阶段失败次数1；最后完成阶段仍为2/CODE_CALIBRATED，未到Gate 3、未LOCKED、未进入Stage 4。21项冻结哈希均不变。

以下为Stage 3A验收时的接口及规则说明；“尚未授权/仅Mock”描述仅适用于该历史验收轮：

入口为 [run_stage3.py](harness/run_stage3.py)，默认拒绝调用；只有显式 `--execute-stage3 --dataset PATH (--case ID | --all)` 才连接注入的provider，`--token-budget` 覆盖本次预算。当前只执行离线Mock，无真实raw_stream、盲测分数或LOCKED结论。Stage 2的21项冻结文件和参数不改；时间线配置另存 [stage3_plan.json](datasets/refund_pilot/cases/C01_refund_display_contract/stage3_plan.json)。本轮自证见 [stage3a_selfcheck.json](reports/stage3a_selfcheck.json)，不属于业务历史或模型实测。

生成沿 `run_stage3.generate_stream → ActStreamSession.view/step → BudgetedCalls → provider` 流转。FactLedger只给当前speaker的 `owner/role == speaker && unlock_act <= act` 私有事实；完整ledger仅控制侧可见。已公开的聊天允许其他角色引用，但公共上下文剥除fact_ids等控制字段。`owner`兼容原配方`role`，冲突拒绝。发言人按当前幕尚未覆盖事实的owner确定；不把其他人的事实、未来幕或完整gold交给生成器。单次请求重试不会扩展可见事实。

真实事件经文件SHA256校验后先注入公共上下文再发言：C01 Act 2开始注入Stage 2的T0 HTTP原始记录，Act 3开始注入T0→T1真实diff；后续幕保留已发布事件。没有重建容器或伪造工具证据。旧`interleave`只供已有产物/演示格式回放，真实生成使用session内事件注入。

每轮检查1–3句、每句≤160字符、条列/归纳禁词、种子禁词及中文“团队记忆/关键前提/适用边界/废案/反事实/锚点”。代码引用须命中原46项AST清单并加反引号；额外拦截未标注的已知符号、snake_case和函数调用形态。符号100%只针对该机器可识别引用集合，报告同时给引用数；无法仅凭AST证明所有自然语言别名都被识别。格式违规默认最多重生成2次；耗尽即失败，不污染已接受轮数。到max_turns仍未满足退出条件直接ActExhausted，不重生成该轮或跳幕。

真实退出覆盖不信任模型自报fact_ids：每个声明必须由消息文本支持，优先配置正则、未命中再做单条发言的二元语义判断（非纯确定性）。C01未配人工正则，使用语义判断。明确否决检查也按这一规则逐条确认，不能把“提到候选”当“已否决”；没有证据或判定不可解析不放行。语义判断是模型评审，仍须之后人工抽读；Mock通过不证明真实对话质量。

成稿沿 `verify_stream → qa_stream_prompt → Stage 1 make_prompt/parse_exact` 验真：公开政策、结构、A/B/C同源快照、中性题面与精确集合判分保持Stage 1口径，只替换team_record。Gold/预期答案只在判分侧。单角色只拿本人chat，不附公共事件或他人chat；完整组拿全部聊天和真实事件。C01盲测分母为每角色每情境3次（4×3×3=36），每格≤1/3；完整组3×3=9次，每格≥2/3。可选完整组每情境只跑1次时，要求三情境全部正确（3/3），不是平均2/3。parse_error单列且纳入分母；env_error/预算中断停止，不补零、不虚构完整分数。

生成、事实语义检查、否决核验、45次QA共用同一BudgetGuard，禁止截断固定证据，保留原始prompt/响应/usage与未确认消耗标记；预算预留与实际usage分别记录。语义事实检查计入生成；否决核验和QA计入验真。Stage 3B建议本次总限200000 Token（估计，不保证足够）；全局config中100000默认值仍冻结不改。成功仅产出GATE_3_REVIEW/locked=false，必须人工抽读后另行批准LOCKED；不推进factory或执行Stage 4。

下单退款小数据集正在共同设计，已确认的首条契约、受理证据口径、纳入/排除规则与待定项见 [DESIGN.md](DESIGN.md)。该文档不是可执行 seed，业务约定不等于已校准的 benchmark 结论。

**新批准口径及 Stage 1 使用方式以 [STAGE1.md](STAGE1.md) 为准**，C01 配方见 [seeds/C01_refund_display_contract.yaml](seeds/C01_refund_display_contract.yaml)，实际运行使用 [数据集内冻结副本](datasets/refund_pilot/seeds/C01_refund_display_contract.yaml)。Stage 1 每格 3 次、共 27 次独立请求；严格采用 B0≤1/3、B2≥2/3、B1_A/B≥2/3、B1_C≤B2_C−1/3。model_wrong 与 parse_error 分栏并计入固定分母；env_error 不补零、不计业务失败，初次失败后最多重试 2 次，仍失败 NEEDS_HUMAN。业务失败按 (case_id, stage) 两次熔断；默认不调用模型，真实调用必须显式 --execute-stage1，首次真实调用已获用户授权并执行，后续调用仍需遵守当前任务授权。新配方使用新入口，旧技术 fixture 的 artifact 回放不能充当真实校准。

运行：`python3 -m pytest benchmark4/harness/tests -v`（从工作空间根目录）。依赖 Python 3.9+、PyYAML、pytest（本机以 Python 3.9.6 验证）；Dockerfile 是未构建的 python:3.11-slim 候选基础镜像，不表示已验证本机镜像。
所有 CLI 可用 `python3 -m benchmark4.harness.<module> --help`；选择器为 `--dataset PATH (--case ID | --all)`。数据集约定为 PATH/seeds/*.yaml；模板刻意不合法，待共同设计首题。CLI 不内置业务题。

## 校验与证据口径
静态校验只证明结构与组合合法，不能证明非通用性、角色信息不足或因果关系。alternatives、facts 和回退来源是待实证的声明，不当作已证实事实。
难度解释为上限：easy/medium 恰有一主演化和 E4，障碍分别最多 3/4；hard 可复合、最多 5。S4 强制 mode_2；S5 默认 mode_1（显式 mode_2 允许）。mode_1 禁止历史 E1。第五维历史覆写次数至少 2；前四维不允许该计数 ≥2。竞争规则按候选列表长度（含废案）计，最多 3；槽位按同一数据集所有 seed 查重。
E2/E3 的 fallback 必须含 rule、source（public_document 或 new_environment）、reference。四个 world profile 必须齐备。服务按 exact match 选择首个路由；重复 match 拒绝，不匹配返回客观默认响应。文本键过滤只是基础检查，不能证明响应不泄密，后续任务需审查 profile 内容。
Stage 1/2 产物同时记录真实 usage 和保守预算预留，不把预留值冒充实测 Token。Stage 2 每格三次正式校准沿用 Stage 1 的冻结门槛；九格各一次只作为 Repeat #1 预检，screen_passed 不代表正式 passed。每个 Coding 会话的隐藏测试必须全部通过才记该次成功；部分通过仍记 model_wrong。parse_error 分栏且计入分母，env_error 不补零，缺失证据不得判通过。缺格、空题、缺失或非有限分数拒绝，不把预填分数当作模型实测。
白盒采用 gold 四字段的精确匹配比例，每项分母为已验证记录数；黑盒为同一完整记录集的 B2 coding 平均分。QA-Coding 为 B2 QA 减 B2 coding；负迁移为 C 上 B0 coding 减 B1 coding（保留符号，正数表示伤害）。Token/通信开销为全部记录求和。空集、缺字段、越界分数均拒绝，不能补零。指标是观测差异，不自动宣称因果归因；因果结论还需受控反事实。
对话短句默认每句最多 160 字符；禁用词按模板配置。代码符号须用反引号显式标注，代码符号不允许在未标注文本出现；自然语言中未标注的新标识符无法仅靠 AST 可靠识别，需后续语义审查。低分 ≤1/3、高分 ≥2/3 为当前框架阈值。单角色盲测须覆盖参与角色及 pm_lead，并至少两人。
FactLedger 只把当前及已解锁事实的深拷贝交给生成器；完整 ledger 属于可信控制侧，不能交给生成器或放入其提示。每幕 max_turns 到达仍未满足退出条件即失败。

## 阶段与接入边界
Factory 保存每题状态：四阶段顺序执行，Stage 3 成功才 LOCKED，Stage 4 后 COMPLETE。supervised 每个成功阶段停 Gate，下次必须显式 --approve；连续两次同阶段失败进入 CIRCUIT_OPEN，CLI 无自动重试或自动解锁。--all 为每题独立状态。
Stage 1 显式执行可生成 qa_calibration.json、逐次原始运行记录和 factory_state.json；不显式执行则只校验已有报告。Stage 2 已接通隔离 Docker 实测并产出 coding_calibration.json 和 coding_evidence.json；Stage 3 新入口可生成/验真，但本轮仅Mock，真实运行按独立stage3_runs编号保留，人工审批前不回填正式LOCKED状态；factory原入口仍消费已有raw_stream.jsonl与stream_verification.json。Stage 4仍只消费benchmark_records.json，未动其代码。
预算调用默认禁用，必须显式启用且注入 provider、精确 tokenizer；总预算按预留上限扣账，异常也扣账以防重试绕过，按使用量结算；provider 使用量超过预留则熔断。工作空间镜像不 COPY 服务源码；独立服务不得把配置挂入接手容器。无 Docker socket 挂载。

## Stage 2 准备状态

**最新：正式27次校准通过，CODE_CALIBRATED，停在 Gate 2。** 本轮仅补18例，原9例逐条复用且未改写。Coding B0 A/B/C均0/3；B1 A/B为2/3、C为0/3；B2均3/3。pass=13、model_wrong=12、parse_error=2、env_error=0；其中10次隐藏测试失败、2次停滞未提交、2次非法分页，后二类不能描述成隐藏测试失败。缺少finish/隐藏判卷不判通过，不事后补判或替换独立样本。负对照答错不逐例计为整阶段失败。

正式记录见 [coding_calibration.json](datasets/refund_pilot/cases/C01_refund_display_contract/coding_calibration.json) 与 [0002.json](datasets/refund_pilot/cases/C01_refund_display_contract/coding_calibration_runs/0002.json)；原Repeat #1的 [0001.json](datasets/refund_pilot/cases/C01_refund_display_contract/coding_calibration_runs/0001.json) 保留9例预检时的状态，不能当作最新完整报告。逐例原始调用、补丁和判卷在 coding_trials/repeat_1/、repeat_2/、repeat_3/。全部21项冻结哈希、初始请求、模型参数、镜像ID与判卷口径均保持一致；旧探路不纳入正式通过率，但计入累计Token预算。缺失用量/环境故障暂停处理，不伪装为模型错误或0消耗。

本轮18例实际753876 Token（输入741330、输出12546）；正式27例1164981 Token（输入1145854、输出19127）；含此前两次探路47148，Stage 2累计1212129，低于1.5M。缓存分别712192与1096064，均为输入子集。388次请求均有真实usage，无缺失；会话10–18轮，最大单次输入5780。全部27例逐例及批后复核容器/专用网络/卷均0残留，详见 [最终复核](datasets/refund_pilot/cases/C01_refund_display_contract/stage2_final_verification.json)。

每格分母固定3，包含model_wrong/parse_error；QA与Coding为独立试次，仅报告观察比例差，不作配对因果归因。B1 A/B/C的Coding通过率均比QA低1/3，B0/B2无差值；B1 A/B少通过的两例为停滞早停，不能据此归因为知识缺失。CODE_CALIBRATED只表示代码底座及校准已过门槛，不等于Stage 3的历史流LOCKED；下一阶段需用户单独授权。

历史Repeat #1：九格各一次共411105 Token，5次通过、4次model_wrong、无解析/环境错误。该轮21项哈希及原始9例已完整复用于正式27例，不重跑替换；其单轮报告保留当时complete=false的事实。

以下为历史探路及准备记录，日期先后以各原始报告为准：

修复后第二次B2×A探路通过基础测试6/6、隐藏A测试3/3。全部128项离线测试先通过后才进行真实调用；原模型/thinking/温度未变。14轮，总42029 Token。[第二次探路证据](datasets/refund_pilot/cases/C01_refund_display_contract/coding_pilots/B2_A_002/SUMMARY.md)。该探路不纳入上述正式 Repeat #1。

Coding使用原生Responses的function_call与function_call_output按call_id关联并完整重放，裁剪历史时成对移除，QA接口保持原格式。任务明确工作区根目录、write全文覆盖和finish触发判卷；示例仅用src/example.py等占位路径，各锚点操作说明完全相同，不新增run_cmd。真实原生函数名/参数另存provider_output，不把包装后的JSON动作冒充模型原始文本。

停滞判断区分工程进展和有限探索：新AST状态或新增通过的基础测试为工程进展；新文件、新分页、首次目录/快照等至多获得8次探索额度，耗尽后不再重置停滞。未变化文件/已看分页重复读取不计进展，即使输出id变化也不重置。仍保留连续5次无上述进展停止和50轮硬上限。此规则与旧规则的结果分版本保留，旧试跑不能与新协议结果混算正式通过率。

后续首次真实Coding探路已仅执行B2×A一次，因5轮只读无语义代码/测试进展而停止：5次调用、5119 Token、无补丁、隐藏测试未执行。全部本次容器/网络/卷清理为空，未启动其余26次。见[探路报告](datasets/refund_pilot/cases/C01_refund_display_contract/coding_pilots/B2_A_001/SUMMARY.md)。准备自检通过与真实代理执行成功是两件事，当前不能按成功链路进入全量。

模型Token统计使用provider真实usage；cached_input_tokens是input_tokens的子集，不重复计入total_tokens。未返回缓存细项时记unknown/null，不补0。输入上限报告采用实际input_tokens最大值，并与请求前保守预算界限区分。仅按失败早停样本线性外推的费用必须明确标注局限，不能冒充27次完成运行的预算预测。

**最新：四项真实Docker自检全部通过，READY_FOR_CODING_APPROVAL。** 正检隐藏测试9/9通过、未改基线9/9失败；清洗后基础测试6/6；A/C协议切换和既定源码隔离探针通过；公开政策/schema哈希未变。见[当前准备报告](datasets/refund_pilot/cases/C01_refund_display_contract/STAGE2_PREPARATION.md)。实验模型调用0；factory completed stage仍为1，等待stage2_coding审批，不自动运行Coding或Stage 3。

判卷XML位于tmpfs，改用docker exec在容器内读取并回传，不能用docker cp导出；pytest原始输出先落盘为同名.pytest.json，XML缺失/截断/不可解析不得伪装成反检成功。历史env_error=6保留，最新单独授权的局部修复窗口错误0，临时参考已删除。

以下保留此前故障及准备入口说明，旧NEEDS_HUMAN描述属于历史：

用户已批准 Gate 1，仅授权 Stage 2 零模型准备与四项硬自检。当前结果为 **NEEDS_HUMAN**，见 [准备报告](datasets/refund_pilot/cases/C01_refund_display_contract/STAGE2_PREPARATION.md)：TSD 挂载字节和 Git 目录归属问题已定位处理，第三次基础设施运行因 Docker 默认地址池耗尽而停止；env_error=3、业务失败=0、实验模型调用=0。源码隔离和隐藏测试正反自检尚未完成，不得据此运行 Coding 校准或进入 Stage 3。

Stage 2 新入口为 `python3 -m benchmark4.harness.prepare_stage2 --dataset PATH --case ID --reference TEMP_FILE`；从 `PATH/recipes/ID.yaml` 读取业务代码/测试配方，脚本不硬编码具体题目。已有构造目录禁止覆盖，恢复需明确复用或归档策略。`run_coding_calibration` 默认只检查准备结果，真实评测必须显式 `--execute-coding --approve`，本轮未执行。临时参考已删除，不能在未完成自检时标为 READY。

隔离采用 `--internal` 网络、独立 service/worker/judge、只读根文件系统、无 Docker socket/API 密钥传入 worker；隐藏测试仅进入独立 judge。TSD 环境使用 [run-tsd-with-authbash 技能](/Users/liuxc/.codex/skills/run-tsd-with-authbash/SKILL.md) 的授权 `authbash docker cp` 传输至容器存储，不改写宿主包装文件；直接 bind mount 在当前环境不可用。网络地址池问题尚待恢复后处理。

拟定参数见 harness/config.yaml：单题总预算1.5M Token，每格3次（27个全新会话），单会话50轮、24k输入上限、4KB逐页工具回显、单次工具输出最多64KB、5轮无新语义代码状态/基础测试进展即停止。工具历史按完整交换移除以适配输入上限，不截断固定任务与记忆；隐藏测试只在 finish 后判卷，不向模型回传其内容。代码写入限制在任务声明的策略槽位，注释/空白变化不算进展。预算不足、环境故障和模型答错分开；Stage 2 的 attempts 按 (case_id, stage) 记录，环境上限为初次失败加两次重试，已达到上限必须等用户恢复。

公开政策/结构说明与 Stage 1 的对象及哈希一致，当前无需付费重跑 QA。参考正检、基线反检以每情境隐藏测试的实际收集数为分母，未收集/基础设施错误不得冒充反检通过；最终四项自检报告通过前，Coding 接口接通不等于底座已验收。

## 实时状态看板（原有独立演示）

可视化服务、会话控制 CLI、静态页面与专属测试全部在 [visualization/](visualization/README.md)。页面只读，默认 http://127.0.0.1:8764；通过会话执行 CLI 推进阶段或单轮。
Mock 演示与已有产物校验/回放严格区分；Stage 3 的 LOCKED 只表示本次来源对应的校验通过，不代表独立实测。Gate 确认不执行下一阶段。阶段失败按整阶段计数，不按轮计数；同阶段两次失败熔断。中断不计为验证失败，需显式重试该阶段；未来事实不进入当前页面或生成输入。运行记录不回写输入 Case，缺失结果显示“未产生”，具体证据与状态口径见可视化 README。

实际 QA 运行可通过 [调用详情 / Prompt](http://127.0.0.1:8764/records) 查看：自动索引 datasets 下的 qa_calibration_runs/*.json，按调用展示已保存的 Prompt、原始回答、预期答案、判分与用量；仅只读展示，不重跑模型。计数分母、缺失证据和分数冲突处理见 [可视化说明](visualization/README.md)。

最近恢复状态：显式internal子网已可用，T0/T1重放为3/3和6/6基础测试通过，T0 HTTP已留档；仍在NEEDS_HUMAN，当前卡在tmpfs判卷XML导出。历史env_error=3与本恢复窗口3次均保留，累计6，业务失败0、实验模型调用0；完整结果见上述Stage 2准备报告，不把局部恢复当作四项全通过。
