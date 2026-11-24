# CodeTeamMem 工作区

基础实现位于 `benchmark4/`，项目说明见 `benchmark4/README.md`，规范见 `benchmark4/SPEC.md`。

本仓库保存框架与可视化源码、配置、配方、业务底座、隐藏测试和离线测试。首次提交是当前开发状态的代码检查点，不代表工作流质量审查已完成。

实验原始记录与生成报告保留在本地，`benchmark4/datasets/*/cases/`、`benchmark4/datasets/*/artifacts/` 和 `benchmark4/reports/` 不纳入代码提交；Git 提交不能替代这些证据的独立备份。

本地离线测试命令：

```sh
python3 -m pytest benchmark4/harness/tests -v
```

部分 Stage 3/4 测试仍依赖上述本地 C01 产物及其冻结路径。仅克隆代码并不足以复现完整测试套件；将这些依赖改为可移植测试夹具属于后续工作。本次提交不改写历史产物或冻结哈希。
