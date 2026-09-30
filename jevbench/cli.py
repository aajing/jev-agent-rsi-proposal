"""All user-facing commands. Hidden evaluation emits aggregate results only."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .contract import FAMILIES, Meter, ContractError, strict_json, validate_prompts
from .data import build_data, read_records, replay_reference
from .runtime import canonical, digest, evaluate


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m jevbench")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build-data")
    b.add_argument("--data", default="data")
    b.add_argument("--families", nargs="+", choices=FAMILIES)
    r = sub.add_parser("reference-check")
    r.add_argument("--records", required=True)
    r.add_argument("--output", required=True)
    s = sub.add_parser("materialize-baseline")
    s.add_argument("--source", default="baseline_prompts.json")
    s.add_argument("--output", required=True)
    d = sub.add_parser("download-model")
    d.add_argument("--destination", required=True)
    for command in ("work", "judge", "baseline", "calibrate", "gpu-smoke"):
        p = sub.add_parser(command)
        p.add_argument("--model", required=True)
        p.add_argument("--prompts", required=True)
        p.add_argument("--data", default="data")
        p.add_argument("--output", required=True)
        if command == "judge":
            p.add_argument("--records", required=True)
            p.add_argument("--ledger", required=True, help="Task-owner path tracking all full Judge runs")
    args = parser.parse_args(argv)
    if args.command == "build-data":
        result = build_data(args.data, selected_families=args.families)
        print(canonical({s: {k:v for k,v in row.items() if k != "records"} for s,row in result["splits"].items()}))
        return 0
    if args.command == "reference-check":
        results = [dict(id=r["id"], family=r["family"], **replay_reference(r)) for r in read_records(args.records)]
        Path(args.output).write_text(canonical({"mode":"reference_controller_not_model", "results":results})+"\n")
        print(canonical({"passed":len(results),"model_inference":False}))
        return 0
    if args.command == "materialize-baseline":
        source = strict_json(Path(args.source).read_text())
        output = {k: source[k] for k in ("policy", "evolver", "memory")}
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise ContractError("Refusing to overwrite an existing baseline artifact")
        path.write_text(canonical(output)+"\n")
        print(canonical({"status":"materialized_without_inference", "sha256":digest(output)}))
        return 0
    if args.command == "download-model":
        from huggingface_hub import snapshot_download
        from .model import MODEL_REPO, MODEL_REVISION
        path = Path(snapshot_download(MODEL_REPO, revision=MODEL_REVISION, local_dir=args.destination,
            ignore_patterns=["videos/*", "blog/*", "*.png", "adapter_vllm/*"]))
        (path / "jevbench_model_pin.json").write_text(canonical({"repo":MODEL_REPO,"revision":MODEL_REVISION,
            "active_mode":"System 2", "decision_adapter":False})+"\n")
        print(canonical({"status":"downloaded", "revision":MODEL_REVISION}))
        return 0

    # The meter starts before model loading: loading belongs to end-to-end wall time.
    meter = Meter()
    from .model import TransformersBackend
    backend = TransformersBackend(args.model)
    artifact = strict_json(Path(args.prompts).read_text())
    prompts = artifact.get("prompts", artifact)
    validate_prompts(prompts, backend.token_count)
    if args.command == "judge":
        from .evolution import validate_work_artifact
        baseline_source = strict_json((Path(__file__).resolve().parents[1]/"baseline_prompts.json").read_text())
        baseline = {k:baseline_source[k] for k in ("policy", "evolver", "memory")}
        prompts = validate_work_artifact(artifact, backend.token_count, baseline=baseline)
    base = Path(args.data)
    if args.command == "work":
        from .evolution import run_work
        artifact = run_work(prompts, read_records(base/"public/practice.jsonl"),
            read_records(base/"public/validation.jsonl"), backend, meter, args.output)
        print(canonical({"status":artifact["status"],"accepted_version":artifact["accepted_version"],"usage":meter.summary()}))
        return 0
    if args.command == "gpu-smoke":
        from .runtime import Episode
        record = read_records(base/"public/practice.jsonl")[0]
        episode = Episode(record)
        try:
            response = backend.generate(episode.request(prompts), max_output=256, meter=meter)
            status = episode.apply(response, backend.token_count)
            result = {"status":"inference_completed","valid_action":status["reason"]!="invalid_format",
                "model":backend.evidence(),"usage":meter.summary()}
        finally:
            episode.close()
    else:
        if args.command == "judge":
            records = read_records(args.records)
            per_family = 6
            # Linux/macOS advisory file lock prevents concurrent quota races.
            import fcntl
            ledger_path = Path(args.ledger)
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with ledger_path.open("a+") as ledger:
                fcntl.flock(ledger, fcntl.LOCK_EX)
                ledger.seek(0)
                entries = [json.loads(line) for line in ledger if line.strip()]
                if sum(r.get("event") == "started" for r in entries) >= 12:
                    raise ContractError("Judge quota exhausted, including failed attempts")
                ledger.write(canonical({"event":"started","prompt_sha256":digest(prompts)})+"\n")
                ledger.flush()
            result, _ = evaluate(records, prompts, backend, meter, per_family=per_family)
        else:
            calibration = args.command == "calibrate"
            records = read_records(base/"public"/("practice.jsonl" if calibration else "validation.jsonl"))
            result, _ = evaluate(records, prompts, backend, meter, per_family=8 if calibration else 2, trace_dir=Path(args.output).with_suffix("") / "traces")
            if calibration:
                games = {f:result["by_type"][f] for f in FAMILIES if not f.startswith(("u_", "d_", "x_"))}
                result["difficulty_calibration"] = {"game_scores":games,"games_overall":result["by_group"]["G"],
                    "target_range":[10,40],"requires_author_review":not 10<=result["by_group"]["G"]<=40 or any(v>50 for v in games.values())}
        result.update(status="complete", model=backend.evidence(aggregate_only=args.command == "judge"))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(canonical(result)+"\n")
    print(canonical({k:v for k,v in result.items() if k != "model"}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(canonical({"status":"unscored", "error_type":type(exc).__name__, "message":str(exc)}), file=sys.stderr)
        sys.exit(1)
