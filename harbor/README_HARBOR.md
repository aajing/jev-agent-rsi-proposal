# Harbor integration and remaining acceptance gates

This directory provides a reviewable Harbor task **skeleton**, deployment and
verification scripts. It has not been Docker-built, GPU-run or passed the official
Harbor validator. Shell syntax/TOML/CPU checks are not substitutes for those gates.

The schema and shared-environment layout follow the pinned OpenRSI-Index example
`rsi-tasks/molmoweb-interaction-context` from commit
`57d9ea7127f91bdde94f89ae47d95cf1ad374836`; source snapshots are in
`../evidence/upstream/`. The official contribution process is recorded in
`openrsi_CONTRIBUTING.md`: proposal review precedes the generated private task
repository, real GPU validation, RSI-Harness experiments and trajectory upload.
No Discussion, repository, experiment or upload is created by these scripts.

## Stage the task without exposing hidden records

From the `jev-agent` project root:

```bash
python3 scripts/prepare_harbor.py --output /absolute/new/public-task-skeleton
```

This requires all 128 practice and 32 validation instances and pinned MiniWoB
assets. It copies only public records into `environment/bundle`, including the
frozen package, font and game/browser assets. The default output cannot run Judge.
To create the **private task-owner working tree**, explicitly include private data:

```bash
python3 scripts/prepare_harbor.py \
  --output /absolute/new/private-harbor-task --include-private
```

Never publish that private working tree. Its 96 hidden records reside solely in
`tests/private/hidden.jsonl`; private seeds and authoring banks are not copied.
Only the environment directory is the Docker build context. The hidden records
must be injected as trusted verifier assets, never copied into the base image or
exposed during Work. The public and private task trees share identical public
source and rules.

## Build on the task owner's Linux machine

```bash
bash scripts/build_harbor_image.sh \
  /absolute/private-harbor-task jev-agent:local-validation
```

The build downloads the pinned System-2 model and Chromium while network access
is available. GPU inference does not run during the build. PyTorch, Transformers,
Accelerate and Pillow use the declared versions; BrowserGym is installed from
commit `c05d7f38f4f788d6e4ee960512c3d5c8aabc6e42`. Its exact Playwright requirement
is **1.44.0**, used here rather than the newer initially considered version.
The complete resolved `pip freeze` is captured for review. Availability and
compatibility of this exact GPU dependency set still require an actual build.

After building, the host copies the build's runtime/model SHA-256 manifest and
image ID into trusted `tests/`. This happens before an agent receives Work access.
Do not regenerate the lock from an agent-modified environment. Docker image
identity, host driver compatibility and the one-H100-at-least-80GB requirement
must be checked by the task owner/official validator; the CUDA base-image tag
alone does not prove compatibility with the installed PyTorch wheel.

A network-disabled GPU preflight can use the built image without acquiring any
new cloud resource. Create an empty host evidence directory first:

```bash
docker run --rm --gpus '"device=0"' --network none \
  -e JEV_PYTHON=/opt/jev-env/bin/python \
  -v /absolute/empty-evidence:/evidence \
  jev-agent:local-validation bash /opt/jev-task/scripts/run_gpu_validation.sh \
  /opt/jev-model /evidence/run-001
```

This runs an actual GPU smoke, public B0 validation and the fixed three-round B1
Work loop, preserving evidence and exporting the complete final Work envelope.
The output directory must be new. This is public validation, not a hidden Judge
run or a completed RSI-Harness trajectory. Do not substitute a reference solver,
mock model or synthetic scores for these results.

## Shared-snapshot verifier contract

`tests/test.sh` launches `tests/evaluate.py` from the independent trusted tests
mount. It accepts only one non-symlink, single-link `candidate.json` in the
workspace and snapshots at most 2 MiB of complete artifact bytes. Canonical B0
may be exactly three strings; all evolved candidates require the full fixed-Work
envelope. `jevbench.evolution.validate_work_artifact` checks the native prompt
caps, initial/final prompts, complete revision log/hash, three rounds, fixed
evolver, strict-improvement retention and final-version consistency. The original
envelope is then passed to Judge for the same check again. Invalid candidates are
unscored, return nonzero, and produce no `reward.txt`. It verifies the runtime/model/asset lock and trusted input
manifest, then copies source, assets and public data from `tests/trusted` into a
fresh private temporary directory. Judge imports that copy with Python isolated
mode, never a module from the candidate workspace. Hidden data is read only from
the tests mount. Per-episode output and child stderr are captured and discarded;
only approved aggregates reach `/logs/verifier`. Infrastructure failures leave
no `reward.txt`.

The existing Harness pauses Work, snapshots it and injects task-owned tests into
Judge-only `/tests` before invoking `/tests/test.sh`. Judge inherits the Work
snapshot, including its interpreter and system libraries; `/tests` is a fresh
tmpfs injection, not a read-only or root-proof mount. Python `-I`, file permissions
and hash checks do not form a security boundary against unrestricted shared-root
tampering or independently attest Work history. Integration must be validated
within this current platform model; no future isolation capability is a proposal
prerequisite.

The official pinned Harness has a persistent submission allocator. Its run must
explicitly use `--max-submissions 12`, for example:

```bash
rsi-harness run /absolute/private-harbor-task \
  --timeout 86400 --max-submissions 12 --gpus 0
```

These names are verified against the pinned CLI and submission manager, not
invented task.toml keys. The Harness's 24-hour timeout is the agent deadline; it
may drain an already-started Judge afterward, up to the verifier timeout. Do not
call that a strict 24-hour end-to-end stop. The separate task-owner trajectory
controller is optional standalone owner tooling; it is not part of the official
proposal's enforcement assumptions and does not provide a Harness attestation service.

For standalone owner-controlled Judge calls,
`tests/private/judge_ledger.jsonl` must be persisted by the task owner for
the **entire trajectory**. Do not create a fresh ledger at each Judge invocation,
container restart or 48-hour extension. The CLI has a secondary ledger check after loading the model; it cannot count
failures that occur before that point. The trusted outer allocator must reserve a
slot before any model loading and count those failures as well. A per-invocation fresh tests mount cannot supply that persistence. In the official
Harness, `--max-submissions 12` limits allocated submissions, but a retryable
infrastructure failure can be refunded. The standalone owner controller counts
every Judge start without refunds. Verify the official resume/retry behavior in
the generated private repository; do not equate these accounting policies. Raw CLI `--records` and
`--ledger` arguments are task-owner interfaces, never research-agent controls.

A score is reported on a 0–100 scale, and Harbor receives the equivalent 0–1
reward. Complete success is 96/96. Reference-controller feasibility does not
constitute a JEV result. The Work envelope establishes structural consistency
with the fixed procedure and prevents ordinary incomplete-history submissions.
It is not a cryptographic source attestation against a shared-root adversary:
retain task-owner Work/Harness logs and validate actual isolation in the official
environment. No unimplemented signed-receipt service is claimed. Directly edited
initial controls and B0 must be task-owner runs labeled accurately.

## Required before a completed contribution

1. Freeze complete public/private manifests and retain private records outside
   the base image; validate exactly 128/32/96 unique instances and all references.
2. Build the image, inspect the resolved dependencies and model pin, test offline
   startup and confirm memory/runtime/output-format feasibility on the H100.
3. Run and record real B0/B1 and prompt-improvement experiments. Calibrate game
   difficulty using public data only, then freeze all splits under the same rules.
4. Invoke the generated private repository's `$harbor-task-validator`, fix its
   findings, and retain its report. This local TOML parse is not that validator.
5. Invoke its `$rsi-task-runner` and verify shared-snapshot isolation, trusted
   tests, persistent Judge quota and safe feedback in the actual RSI-Harness.
6. Submit the proposal/experiment trajectories through the official flow when
   authorized. Proposal approval does not guarantee benchmark inclusion.

No step above has been marked successful merely because its script exists.
