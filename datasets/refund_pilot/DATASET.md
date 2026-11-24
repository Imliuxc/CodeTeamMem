# refund_pilot

最新：经用户单独授权修复tmpfs判卷XML读取，Stage 2四项零模型准备自检全部通过，状态READY_FOR_CODING_APPROVAL；历史环境错误保留，正式Coding尚未获准执行。详细证据见cases/C01_refund_display_contract/STAGE2_PREPARATION.md，以下暂停描述为历史过程。

单项目下单退款小数据集，计划五个维度各一条记忆；当前仅 C01。
Stage 1 已通过；用户随后仅授权 Stage 2 准备与零模型硬自检，不授权真实 Coding 校准。当前 Stage 2 因 Docker 内部网络地址池耗尽而处于 NEEDS_HUMAN；已构造公开默认政策底座与 T0/T1，尚无 LOCKED 历史。
C01 的 B2 仅描述一般生效前提，不提前命名 C 的新协议或回执分配方式。
各情境三个独立请求，分母固定三；预期集合均为 E01/E02/E05。
模型由本次用户指定：deepseek-v4-1-flash-260910，Ark Responses，纯文本，无工具，关闭思考模式。
Stage 1 Token 总预算150k；详细模型参数、输入哈希、原始回答与计数见 cases/C01_refund_display_contract/。
QA 初筛不证明最终代码不可解。Stage 2 准备的具体结果与未完成项见 cases/C01_refund_display_contract/STAGE2_PREPARATION.md；三次基础设施失败后已停止，不进入正式 Coding 或 Stage 3。
