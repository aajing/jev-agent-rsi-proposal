# JEV-Agent 的自进化

给定冻结的多模态 JEV 发布版，以截图完成界面、文档、文档驱动操作和四类困难游戏；模型在固定三轮 Work 中根据自身执行反馈修订 prompt，Judge 只评测最终保留版本。

**本次交付范围是题目提案送审，不包含测试或研究轨迹运行。** 实际模型成绩、显存和耗时如实标为待验证，作为题目获批后的执行事项，不作为当前整理和提交 proposal 的前置条件。

- [SUBMISSION.md](SUBMISSION.md)：本次题目提交说明。
- [题目提案附件包](dist/jev-agent-topic-submission.zip)：正式 proposal、题目细则、四类游戏规则和初始 prompt。

- [proposal.md](proposal.md)：官方 28 字段提案，填写 Jing Qiu / ajing@autotrust.ai。
- [TASK_SPEC.md](TASK_SPEC.md)：科学问题、允许修改范围、三轮流程和计分。
- [GAME_TASKS.md](GAME_TASKS.md)：四类困难游戏与精确认证规则。
- [RUNBOOK.md](RUNBOOK.md)：本地复核、GPU 运行和正式提交步骤。
- [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)：完成项和剩余验收条件。
- [evidence/readiness.json](evidence/readiness.json)：后续完整任务运行的验收记录，不是 proposal 送审门槛。
- [evidence/official_static_checks.json](evidence/official_static_checks.json)：20项通用静态检查的实际结果及适用范围。
- [harbor/README_HARBOR.md](harbor/README_HARBOR.md)：Harbor 外壳与共享快照限制。
- [公开实现补充附件](dist/jev-agent-proposal.zip)：正文引用的代码、公开数据与脚本，按上一题的交付方式拟随提案提供给审核方。

贡献者资料沿用上一题：Jing Qiu，工作邮箱 ajing@autotrust.ai，GitHub 账号 [aajing](https://github.com/aajing)；相关经验依据继续采用贡献者指定的 AutoTrust 公开项目。附件已在本地准备，当前尚未发布本题 Discussion。

16 类任务各有 8 个练习、2 个验证、6 个隐藏实例，共 128 / 32 / 96。验证和隐藏使用同一类型集合、生成规则和两档难度；16 类等权，隐藏全部 96 题成功才是 100 分。参考求解器成功只证明任务可解，不是 JEV 成绩。

模型固定为 `autotrust/JEV-27B-VL@3ea6d7a3a140d2d08e6a64174195967013168d5b`，Apache-2.0。按自由生成动作的要求使用其 System 2；该路径是未改动的 Qwen3.8-27B，不激活 JEV System 1 决策适配器。代码、提案和日志均明确这一点，不把结果归因于决策头。

本目录独立于第一道 Qwen 合成数据训练题；原题文件和 ZIP 未改动。
