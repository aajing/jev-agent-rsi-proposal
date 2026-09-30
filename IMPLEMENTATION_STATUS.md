# 后续任务实现与运行状态

**本次仅提交题目 proposal，按 [SUBMISSION.md](SUBMISSION.md) 整理材料，不开展测试。** 以下记录此前实现工作及题目获批后的运行事项，不是本次提案送审的前置条件。`evidence/readiness.json` 针对完整任务运行验收；参考程序的成功不会填入模型成绩。

| 项目 | 状态与证据 |
| --- | --- |
| 16 类任务引擎 | `jevbench/visual_tasks.py`、`push_maze.py`、`mines_puzzle.py` |
| 128/32/96 数据 | 同生成器、同两档难度、独立实例，全部生成并参考回放；隐藏内容仅在 `data/private/` |
| 困难游戏 | 推箱子精确搜索、迷宫状态 BFS、扫雷可见约束枚举与雷数 DP、十五数码精确 IDA*；认证会重算而非信任声明 |
| 原生网页 | 固定 MiniWoB 与 BrowserGym；本机 Chrome 的真实截图和像素操作测试通过，Linux bundled Chromium 待复核 |
| 执行与计分 | 动作 JSON、调用/原子/token/时间预算、三轮修订、完整评测与隐藏汇总；见 `tests/test_runtime.py` |
| 模型来源 | 发布版、Apache-2.0、33 个资产的不可变来源哈希已固定；55.6 GB 权重未下载到本机 |
| 原生文本长度 | policy 188、evolver 133、memory 0；四动作+满128-token scratch+EOS 为169/201 tokens，见 `evidence/tokenizer_checks.json` |
| 本地测试 | 112 tests + 4 subtests 通过；没有模型推理、没有模型成绩 |
| 可信主机控制器 | 9 项 CPU 自检通过，含真实进程超时、前端退出后监督、12 次配额、固定数据和 Work receipt |
| Harbor | TOML、Dockerfile、Solution、Judge、部署脚本及8项边界测试；尚未 Docker build 或官方 validator 运行 |
| 官方通用静态检查 | 实际执行20项，19项通过；5小时时限规则与RSI模板的24小时配置不同，保留并报告失败，不能称官方validator通过 |
| H100 实测 | 后续任务执行阶段事项；本次不需要提供连接或启动 GPU |
| 正式研究轨迹 | 尚未运行或上传；没有发布 Discussion 或公开私有数据 |

原始 B0、三轮 B1 和改进候选须在同一冻结模型上实测。公开练习中的游戏难度目标仍是 B0 总体约10%–40%；该目标不是观测成绩。若实测显示门槛不合理，先依据公开数据调整统一规则，再重新冻结所有分割；不能按隐藏失败挑关卡。

题目获批后的完整任务贡献流程包括 Linux/CUDA 环境验证、实际模型基线与研究轨迹、官方 validator/Harness 和轨迹上传。这些属于后续阶段，本次不执行，也不以缺少 GPU 连接阻塞 proposal 整理。

共享 root 的 Work/Judge 快照存在官方平台边界限制。Work envelope 检查完整三轮链及严格改善规则，但无法单凭候选自报 JSON 证明模型来源。独立 task-owner host 控制器会保留真实过程和 HMAC receipt；正式 Harbor 依赖外层可信 Harness 日志和隔离，不能宣称尚未验证的密码学或操作系统保证。
