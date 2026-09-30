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

已有数据保存在 `data/public/` 与 `data/private/`。`python -m jevbench build-data --data data` 会复核并补齐数据；隐藏种子由任务所有者保存在私有目录。不要把重新生成的数据插入已经计分的研究轨迹。

## 构建正式运行环境

```bash
python3 scripts/prepare_harbor.py --output /absolute/private-task --include-private
bash scripts/build_harbor_image.sh /absolute/private-task jev-agent:validation
```

`--include-private` 的输出是私有任务所有者工作树，不能上传到公开仓库或公开 ZIP。Docker 只以其 `environment/` 为构建上下文，隐藏记录进入 Judge-only `tests/private/`。构建联网获取固定模型与浏览器，正式 Work/Judge 断网。完整说明见 `harbor/README_HARBOR.md`。

## H100 基线与公开难度校准

在已配置的 GPU 环境上：

```bash
bash scripts/run_gpu_validation.sh /opt/jev-model /absolute/new-gpu-evidence
python -m jevbench calibrate --model /opt/jev-model \
  --prompts /absolute/new-gpu-evidence/baseline-prompts.json \
  --data /absolute/jev-agent/data --output /absolute/new-gpu-evidence/calibration.json
```

第一条命令运行真实 smoke、公开 B0 验证和三轮 B1 Work；第二条在128个公开练习实例上测困难程度。所有输入/输出含原生视觉 tokens；加载、失败、思考、截断与重试均不成为免费计算。不得把参考控制器或测试 fake backend 的结果登记为模型成绩。

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

包内只有代码、公开实例、来源哈希、测试和文档；排除隐藏数据、种子、私有关卡库、权重、虚拟环境、平台二进制及构建产物。`dist/jev-agent-proposal.sha256` 用于核对附件。新任务独立打包，第一道题不变。
