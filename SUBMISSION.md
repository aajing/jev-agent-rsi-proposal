# 题目提案提交

本次提交的是 **JEV-Agent 的自进化** 题目提案，不提交测试结果或已完成的研究轨迹。

沿用上一题由贡献者确认的资料：Jing Qiu；工作邮箱：ajing@autotrust.ai；GitHub 账号：[aajing](https://github.com/aajing)。

相关研究背景和经验依据继续采用贡献者指定的 [AutoTrust 训练优化项目](https://github.com/AutoTrustAI/autoresearch-sota-strategy)、[JEV 模型](https://huggingface.co/autotrust/JEV-27B)及其 [GitHub](https://github.com/AutoTrustAI) / [Hugging Face](https://huggingface.co/autotrust) 组织主页。本题的多模态模型来源另明确为 [JEV-27B-VL](https://huggingface.co/autotrust/JEV-27B-VL)。以上是贡献者确认的资料，不表示已通过官方审核。

## 提交正文

使用 [proposal.md](proposal.md) 的完整 28 字段表格作为正式提案正文。科学问题、模型来源、基线、可修改范围、评测、满分和预算均在表格内。

题目概要：给定固定多模态 JEV 模型与视觉任务，研究者只优化提示文本，模型通过自身执行反馈进行三轮提示修订。最终同一份 prompt 覆盖界面操作、文档推理、文档驱动操作及四类困难游戏，共16类任务。验证与隐藏评测使用相同任务类型和难度分布；隐藏96题全部成功才是100分。

## 随题附件

- [TASK_SPEC.md](TASK_SPEC.md)：数据组成、动作限制、修订流程、计分和预算。
- [GAME_TASKS.md](GAME_TASKS.md)：推箱子、钥匙门迷宫、无猜测扫雷、十五数码的困难关卡规则。
- [baseline_prompts.json](baseline_prompts.json)：初始 policy、evolver 和 memory。
- `configs/model_lock.json`：选定模型版本及公开资产的来源哈希。

这些文件与正文已整理为 `dist/jev-agent-topic-submission.zip`。交付方式沿用上一题：题目正文和公开附件随提案提供，私有出题材料留待官方私有任务构建环节交付。

- 题目附件：`dist/jev-agent-topic-submission.zip`，包含正文和以上题目定义文件。
- 公开实现补充附件：`dist/jev-agent-proposal.zip`，包含正文引用的代码、公开数据、配置和已有实现证据，拟一并提供给审核方；提供这些已有材料不要求先运行模型测试。
- 私有材料：`data/private/` 不进入公开附件或 Discussion，在后续官方私有任务构建环节交付。

两个附件已发布在公开仓库 `https://github.com/aajing/jev-agent-rsi-proposal`。正文中的相对代码路径对应公开实现补充附件内的文件；官方 Discussion 正文提供固定提交版本的源代码与附件链接。

## 提交渠道

沿用上一题的官方 `proposal-agent → Task Ideas Discussion` 提交流程，本题作为独立提案提交完整 28 字段正文，并使用 GitHub 账号 `aajing`。认证凭据由本机凭据存储管理，不写入提案或附件。本地材料准备与正式发布分别记录；本题已提交官方 Discussion #147：https://github.com/OpenRSI-Foundation/OpenRSI-Index/discussions/147。修订继续更新同一记录。

## 提案中的估计项

H100 显存、运行时长和模型成功率尚未实测，按估计或待验证记录，不填写虚构成绩。1张H100、每候选Work/Judge预算和总体研究时长属于题目执行条件；它们不要求贡献者在本次提案送审前先完成运行。

提交阶段保留已选定的研究问题、修改范围、同类型评测、困难门槛和满分定义。实际环境验证、难度校准及研究轨迹属于题目获批后的流程。本次只修订和重新提交题目及公开附件，不运行模型实验。
