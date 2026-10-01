# JEV-Agent 的自进化

给定冻结的多模态 JEV 发布版，以截图完成界面、文档、文档驱动操作和四类困难游戏；模型在固定三轮 Work 中根据自身执行反馈修订 prompt，Judge 只评测最终保留版本。

**本次交付范围是题目提案送审，不包含测试或研究轨迹运行。** 实际模型成绩、显存和耗时如实标为待验证，作为题目获批后的执行事项，不作为当前整理和提交 proposal 的前置条件。

- [SUBMISSION.md](SUBMISSION.md)：本次题目提交说明。
- [题目提案附件包](dist/jev-agent-topic-submission.zip)：正式 proposal、题目细则、四类游戏规则、初始 prompt 和评测资产交付说明。

- [proposal.md](proposal.md)：官方 28 字段提案，填写 Jing Qiu / ajing@autotrust.ai。
- [TASK_SPEC.md](TASK_SPEC.md)：科学问题、允许修改范围、三轮流程和计分。
- [GAME_TASKS.md](GAME_TASKS.md)：四类困难游戏与精确认证规则。
- [RUNBOOK.md](RUNBOOK.md)：本地复核、GPU 运行和正式提交步骤。
- [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)：完成项和剩余验收条件。
- [evidence/readiness.json](evidence/readiness.json)：后续完整任务运行的验收记录，不是 proposal 送审门槛。
- [evidence/official_static_checks.json](evidence/official_static_checks.json)：20项通用静态检查的实际结果及适用范围。
- [harbor/README_HARBOR.md](harbor/README_HARBOR.md)：Harbor 外壳与共享快照限制。
- [公开实现补充附件](dist/jev-agent-proposal.zip)：正文引用的代码、练习与验证数据、脚本及已有实现证据，以及原始四个 `data/private/*` 评测构建文件、`EVALUATION_ASSETS.md` 和 `EVALUATION_ASSETS_MANIFEST.json`。
- [EVALUATION_ASSETS.md](EVALUATION_ASSETS.md)：公开评测构建资产、下载方式与运行时分离要求；[评测资产附件](dist/jev-agent-evaluation-assets.zip) 提供原始冻结记录、种子和出题库。

贡献者资料沿用上一题：Jing Qiu，工作邮箱 ajing@autotrust.ai，GitHub 账号 [aajing](https://github.com/aajing)；相关经验依据继续采用贡献者指定的 AutoTrust 公开项目。本题已提交 [官方 Discussion #147](https://github.com/OpenRSI-Foundation/OpenRSI-Index/discussions/147)，修订继续更新同一记录。

16 类任务各有 8 个练习、2 个验证、6 个隐藏实例，共 128 / 32 / 96。验证和隐藏使用同一类型集合、生成规则和两档难度；16 类等权，隐藏全部 96 题成功才是 100 分。参考求解器成功只证明任务可解，不是 JEV 成绩。

本次经贡献者明确授权，将四个原始评测构建文件原样公开于 `evaluation-assets/data/private/`，并提供未加密附件；文件名中的 `private` 是兼容旧路径，不再表示未公开。“隐藏”仅指正式运行时不向 Work 提供评测明细，不承诺公开发布后的保密性或从未接触。构建 Work 时必须排除 `evaluation-assets/`、`data/private/`、`dist/` 和 `.git/`，冻结评测记录仅通过 Judge-only tests 注入。原始数据与代码字节保持不变；其中保留的历史“不公开”政策文字已由本次明确公开授权取代。

模型固定为 `autotrust/JEV-27B-VL@3ea6d7a3a140d2d08e6a64174195967013168d5b`，Apache-2.0。按自由生成动作的要求使用其 System 2；该路径是未改动的 Qwen3.8-27B，不激活 JEV System 1 决策适配器。代码、提案和日志均明确这一点，不把结果归因于决策头。

本目录是独立的第二题；第一道 Qwen 合成数据训练题使用独立仓库和附件交付。
