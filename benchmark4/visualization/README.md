# CodeTeamMem 状态观测台

独立的本地可视化目录：`server.py` 提供页面/API，`control.py` 提供会话控制 CLI 与串行控制器，`store.py` 保存状态与有序事件，`demo.py` 是无业务含义的技术夹具，`static/` 是原生网页，`tests/` 是服务专属测试。
Python 3.9+，复用框架的 PyYAML；测试使用 pytest。无前端构建、CDN、模型或 Docker 服务依赖。

## 启动与控制

从工作空间根目录执行：

```sh
python3 -m benchmark4.visualization.server
```

浏览器打开 [本地看板](http://127.0.0.1:8764)。页面仅查询状态，无执行按钮。默认只监听 loopback；端口可用 `--port` 修改。运行数据默认位于 `benchmark4/reports/status_service/`，用 `--data-dir` 可指定其他独立目录，同一目录只允许一个服务持有锁。

另一个终端（或当前会话）创建 Mock：

```sh
python3 -m benchmark4.visualization.control create --demo
python3 -m benchmark4.visualization.control status
python3 -m benchmark4.visualization.control step --run RUN_ID
python3 -m benchmark4.visualization.control approve --run RUN_ID
python3 -m benchmark4.visualization.control step --run RUN_ID
```

将 RUN_ID 替换为 create 返回的 id。命令选项 `--url http://127.0.0.1:其他端口` 写在子命令前。`step` 不自动批准 Gate；`approve` 不执行下一阶段。完成 Stage 2 并确认 Gate 后，每个 `step` 仅执行 Stage 3 的一轮，最后一轮附带整段验真。

接入已有产物（这些命令不会生成数据或启动模型）：

```sh
python3 -m benchmark4.visualization.control create --dataset /absolute/dataset --case CASE_ID
python3 -m benchmark4.visualization.control create --dataset /absolute/dataset --all
python3 -m benchmark4.visualization.control step --run RUN_ID --case CASE_ID
```

多 Case 运行每次控制必须明确选一题；无自动批量调度。首次失败后，先 `retry --run RUN_ID` 准备重试，再 `step`；第二次同阶段失败即熔断，CLI 无重置或继续入口。Mock 可用 `create --demo --fail-stage 1` 演示失败路径（阶段可选 1–4），不会混入正式数据集。

## 状态和证据口径

- `completed_stage` 只记录已完成阶段，`active_stage` 记录正在执行/等待下一轮/失败/中断的阶段；阶段内不虚构完成百分比。
- `READY → RUNNING → GATE` 为普通阶段；Stage 3 中间轮次为 `WAITING_STEP`，最后一轮验真通过为 `LOCKED + gate=true`；Stage 4 后为 `COMPLETE`。Gate 确认与执行分离。
- 同阶段失败按阶段尝试计数；轮次完成不算阶段完成。首次 `FAILED` 可准备重试，再次失败为 `CIRCUIT_OPEN`；必须先讨论简化，服务不提供清零绕过。
- SQLite 事务同时保存快照与事件，事件 seq 全局单调递增；UI 通过每秒轮询按运行补齐事件（每页最多 100 条）。断线保留已有显示并明确提示；刷新从日志重建。
- 正常 `WAITING_STEP` 重启后从下一轮继续；`RUNNING` 时服务退出，重启后为 `INTERRUPTED`。中断不当成校验失败，显式 `retry` 清理当前阶段游标后从阶段开头重新执行；保留历史事件和失败次数。无自动重试。
- 查询接口不会返回私有完整 seed、gold、尚未到达的对话和事实。页面“本轮可见事实”对应最后执行轮次的 ledger view；进入下一幕但尚未执行首轮时，不提前解锁。退出条件栏同时考虑事实覆盖和最小轮次，最小/最大轮次在旁显示。
- `mock` 的通过结果和盲测分数来自技术夹具，不是模型实测。`artifact` 使用输入文件的既有分数做门槛/结构校验及回放，不证明来源真实性或复现实验。页面始终显示来源，不将 artifact 回放称为实时生成。
- Stage 1 按整个数据集 seed 检查槽位与组合，读取所选题 QA scores；Stage 2 校验 coding_evidence 与 Coding scores；Stage 3 按幕逐轮重放 raw_stream，并在末尾校验完整时间线与既有盲测分数；Stage 4 按框架既有分母规则汇总 benchmark_records。
- 缺失文件/结果不补零，阶段失败；只有已通过阶段才有结果。指标计算与纳入/排除口径沿用框架 README，不将分数差异自动当作因果归因。
- 输入 seed 在创建时形成私有快照；Stage 3 的原文、manifest、verification 在首轮形成内容指纹，中途修改即失败，必须显式重试从阶段开头读取。其他阶段的 artifacts 在执行时读取，首败后允许修正材料再重试；输入目录从不回写。
- 已有产物的派生输出保存于 `reports/status_service/runs/<run>/<case>/`。Stage 4 使用已验真的冻结协作流，避免源文件变化造成结果错配。运行事件及快照保存于 `status.sqlite3`。

## 接口与测试

只读接口：`GET /api/runs`、`GET /api/runs/<run>`、`GET /api/runs/<run>/events?after=<seq>`。返回快照的 cursor 是参考值；客户端只用实际收到的事件推进游标，避免并发快照导致漏事件。
控制接口：CLI 调用本机 `POST /control`，请求含 action 与参数。控制前读取 revision，过期 revision 或执行中重复命令返回 409，不排队。带浏览器 Origin/Sec-Fetch-Site 的控制请求返回 403。页面脚本不调用控制接口。

```sh
python3 -m pytest benchmark4/harness/tests benchmark4/visualization/tests -v
```

服务测试仅允许 loopback HTTP 并阻断外部连接和子进程；夹具文件只写临时目录。浏览器验收同样只操作 Mock，不消耗模型预算。

## 查看实际 QA 运行的 Prompt 和回答

打开 [调用详情 / Prompt](http://127.0.0.1:8764/records)。该入口自动读取 `benchmark4/datasets/**/qa_calibration_runs/*.json`，独立于 Mock 的运行数据库；外部数据集可在启动服务时指定 `--datasets-dir /absolute/path`。

左栏选择一次已保存的 QA 运行，在“选择一次调用”中按 B0/B1/B2、A/B/C 或判分筛选，点击记录或使用下拉选择器，查看该次保存的 Prompt 原文、模型原始回答、预期答案、解析结果、响应 ID 与 Token 用量。链接中的 `recording` 和 `call` 可固定选中记录；call 为从 0 开始的文件记录下标。

数据与判断口径：只纳入上述目录中的 JSON 原始运行文件，不将 Mock、汇总 qa_calibration.json 或当前 seed 当作实际调用证据。各格分子是文件 records 中 outcome=pass 的记录数，分母是该格已保存的全部记录数（不剔除错误/环境错误），同时展示文件声明的计划分母和保存分数；不完整记录不冒充完整试验。保存分数与记录计数冲突时显示警告，不覆写原分数或重新判分。文件无法读取时保留异常条目，缺字段显示“未记录”，不从当前代码或 seed 重建。预期答案仅是评分侧证据，不表示已发送给模型；Prompt 的结构化视图只格式化 JSON，原文始终保留。

当前 Case 状态与该次运行的完成/通过标记分开显示，因为 Case 可能已继续推进。页面不推断错误的心理/因果原因，不补写完整 HTTP 报文、系统提示或内部推理。配置与调用元数据采用字段白名单，不展示凭据或原始请求 headers。已执行调用的 Prompt 和评分信息在此专门的只读证据入口显示；流水线页面仍保持未来事实隔离。
