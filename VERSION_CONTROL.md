# CodeTeamMem 版本管理说明

`benchmark4/` 是 Git 仓库根目录，后续在此目录执行 Git 操作。项目说明见 `README.md`，规范见 `SPEC.md`，原外层立意文档已移入 `introduction.md`。初始提交历史保留，目录迁移单独提交。

本仓库保存框架与可视化源码、配置、配方、业务底座、隐藏测试和离线测试。首次提交是当前开发状态的代码检查点，不代表工作流质量审查已完成。

实验原始记录与生成报告保留在本地，`datasets/*/cases/`、`datasets/*/artifacts/` 和 `reports/` 不纳入代码提交；Git 提交不能替代这些证据的独立备份。

本地离线测试命令：

```sh
python3 -m pytest harness/tests visualization/tests -v
```

部分 Stage 3/4 测试仍依赖上述本地 C01 产物及其冻结路径。仅克隆代码并不足以复现完整测试套件；将这些依赖改为可移植测试夹具属于后续工作。本次提交不改写历史产物或冻结哈希。

现有模块使用 `benchmark4` 包名。需要运行 `python3 -m benchmark4.harness.<模块>` 时，可在仓库根目录设置 `PYTHONPATH=..`；历史文档中的外层相对路径命令应结合这一目录调整使用。
