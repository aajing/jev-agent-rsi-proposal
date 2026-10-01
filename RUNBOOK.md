# 运行与提交

本文件供题目获批后的任务执行使用，不属于本次仅提交 proposal 的工作范围。当前提交材料见 [SUBMISSION.md](SUBMISSION.md)，无需执行以下测试或 GPU 命令。

所有命令从本目录执行。本地已有 `.venv` 用于 CPU 验证；GPU 运行要求 Linux、CUDA 和一张至少80GB显存的 H100，需先完成依赖与实际性能验证。

## 复核代码和数据

```bash
.venv/bin/python -m pytest tests harbor/tests/test_verifier_unit.py -q
.venv/bin/python scripts/trajectory_controller.py self-test
.venv/bin/python -m jevbench.verify --recertify --output evidence/readiness.json
```

本机浏览器验证使用 `JEV_CHROMIUM_EXECUTABLE` 指向 Chrome；正式 Linux 镜像使用 Playwright 1.44.0 对应的 Chromium。两种环境的验证记录分开，不能用前者代替后者。

128/32 个练习与验证实例位于 `data/public/`。原定 96 个评测实例、构建种子、证书和出题库现已获准公开分发，下载位置、逐文件字节哈希及规范化数据集哈希见 [EVALUATION_ASSETS.md](EVALUATION_ASSETS.md)。完整 implementation ZIP 包含原始 `data/private/*`；也可从专用 evaluation ZIP 或 `evaluation-assets/data/private/` 获取完全相同的四个文件，并在任务所有者构建目录恢复为 `data/private/*`。旧路径中的 private 表示历史命名，不再表示未公开。不要重新生成、替换或修改批准的冻结实例；`build-data` 是历史构建工具，不是取得本次评测集所需的交付步骤。

## 构建正式运行环境

```bash
python3 scripts/prepare_harbor.py --output /absolute/private-task --include-private
bash scripts/build_harbor_image.sh /absolute/private-task jev-agent:validation
```

`--include-private` 是保留兼容性的历史参数名；脚本中的禁止公开提示和 `publishable_tree` 状态来自原分发政策，本次四个冻结构建文件的公开授权及范围见 [EVALUATION_ASSETS.md](EVALUATION_ASSETS.md)。该授权不覆盖运行日志、凭据或其他无关文件。Docker 只以其 `environment/` 为构建上下文；复制白名单仅把练习/验证实例放入 Base/Work，评测记录仅进入 Judge-only `tests/private/`。`evaluation-assets/`、`data/private/`、`dist/` 和 `.git` 均不能整体复制或挂载到 Work。种子、证书和出题库用于构建审计，无需进入 Work 或推理输入。构建联网获取固定模型与浏览器，正式 Work/Judge 断网。公开分发不再提供数据保密性；计分轨迹仍禁止查看或利用评测构建资料。完整说明见 [harbor/README_HARBOR.md](harbor/README_HARBOR.md)。

## H100 基线与公开难度校准

在已配置的 GPU 环境上：

```bash
bash scripts/run_gpu_validation.sh /opt/jev-model /absolute/new-gpu-evidence
python -m jevbench calibrate --model /opt/jev-model \
  --prompts /absolute/new-gpu-evidence/baseline-prompts.json \
  --data /absolute/jev-agent/data --output /absolute/new-gpu-evidence/calibration.json
```

基线文件为 [baseline_prompts.json](baseline_prompts.json)，baseline/work 命令在 [jevbench/cli.py](jevbench/cli.py)，固定三轮调度在 [jevbench/evolution.py](jevbench/evolution.py)，执行和评分在 [jevbench/runtime.py](jevbench/runtime.py)。第一条命令运行真实 smoke、公开 B0 验证和三轮 B1 Work；第二条在128个公开练习实例上测困难程度。所有输入/输出含原生视觉 tokens；加载、失败、思考、截断与重试均不成为免费计算。不得把参考控制器或测试 fake backend 的结果登记为模型成绩。

模型使用发布版 System 2。启动会重算所有固定模型文件的 SHA256 或 Git blob 哈希，验证原生输入长度和视觉网格 token 数。原生文本 tokenizer 已验证；AutoProcessor、GPU 生成、显存和吞吐仍须实际运行确认。

## 严格的研究轨迹

在研究容器之外的 task-owner 主机运行，固定真实 Python、模型和数据路径：

```bash
python scripts/trajectory_controller.py init --state /owner/run-001 \
  --task-root /trusted/jev-agent --data /trusted/jev-agent/data \
  --model /opt/jev-model --python /opt/jev-env/bin/python
python scripts/trajectory_controller.py baseline --state /owner/run-001 --kind B0
python scripts/trajectory_controller.py baseline --state /owner/run-001 --kind B1
python scripts/trajectory_controller.py submit --state /owner/run-001 < initial-prompts.json
python scripts/trajectory_controller.py status --state /owner/run-001
```

初始化即开始24小时绝对期限；每个 Work/Judge 最多2小时，所有 Judge 启动最多12次，失败不退款。`submit` 仅接受 policy/evolver/memory 三字符串，实际执行固定三轮 Work，再核验 receipt、评测最终 Work artifact。没有单独让研究者指定隐藏数据或重置 ledger 的接口。控制器是可信主机程序，本身不是容器隔离工具；当前也不替代官方 Harness 轨迹。

当前严格控制器固定24小时，不实现48小时延长。延长应先由任务所有者明确配置并保持同一日志/配额；不要重建状态目录当作延长。

## 官方流程

按官方 OpenRSI-Index CONTRIBUTING 提交和确认 proposal，获取自动生成的私有任务仓库，然后使用仓库自带 validator 与 RSI-Harness，上传 proposal 和真实实验轨迹。官方 Harness 的 `--timeout 86400 --max-submissions 12` 控制 Agent 时间及提交配额；在途 Judge 可能继续完成，部分基础设施失败可能退款，因此不等同于上述严格主机控制器。

不能以本地 TOML 解析或 Shell 检查声称官方 validator 已通过，也不能以代码完成声称研究轨迹已上传。本文档不执行发布操作。

## 公开附件

```bash
python3 package_submission.py
```

上述历史打包脚本仍生成代码与练习/验证资料的基础包，其原排除规则没有被改写。本次发布的完整 `dist/jev-agent-proposal.zip` 另补入原始四个 `data/private/*` 文件、`EVALUATION_ASSETS.md` 和 `EVALUATION_ASSETS_MANIFEST.json`；不要仅运行旧脚本后就把缺少这些评测资产的基础包当作完整发布包。另提供 `dist/jev-agent-evaluation-assets.zip` 与逐文件下载目录，详见 [EVALUATION_ASSETS.md](EVALUATION_ASSETS.md)。权重、虚拟环境、平台二进制、凭据、运行日志和无关构建产物不在授权发布范围。`dist/jev-agent-proposal.sha256` 用于核对完整附件；公开资产与 Work 可见资产的边界按前述 staging 白名单维持。
