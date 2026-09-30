"""The fixed three-round Work procedure; no evolution runs in Judge."""
from __future__ import annotations

import json
import math
from pathlib import Path
from PIL import Image

from .contract import FAMILIES, GROUPS, ContractError, strict_json, validate_prompts
from .runtime import canonical, digest, evaluate, run_episode


def validate_work_artifact(artifact, token_count, baseline=None):
    """Check a recorded Work chain; authenticity relies on owner/harness logs.

    This rejects direct arbitrary final-prompt submission. It does not claim
    that a root-controlled snapshot can cryptographically attest model calls.
    """
    if isinstance(artifact, dict) and set(artifact) == {"policy", "evolver", "memory"}:
        validate_prompts(artifact, token_count)
        if baseline is None or artifact != baseline:
            raise ContractError("Only canonical B0 may omit the three-round Work record")
        return artifact
    if not isinstance(artifact, dict) or artifact.get("schema_version") != 1 or artifact.get("status") != "work_complete" or artifact.get("completed_rounds") != 3:
        raise ContractError("A completed three-round Work artifact is required")
    initial = validate_prompts(artifact.get("initial"), token_count)
    final = validate_prompts(artifact.get("prompts"), token_count)
    log = artifact.get("revision_log")
    if not isinstance(log, list) or len(log) != 4 or any(not isinstance(row, dict) for row in log) or digest(log) != artifact.get("revision_log_sha256"):
        raise ContractError("Missing or changed revision log")
    def valid_score(value):
        return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 100 and abs(value*32/100-round(value*32/100)) < 1e-8
    current = dict(initial)
    old_score = log[0].get("score")
    if log[0].get("version") != 0 or log[0].get("accepted") is not True or log[0].get("prompt_sha256") != digest(initial) or not valid_score(old_score):
        raise ContractError("Invalid initial Work record")
    accepted_version = 0
    for version, row in enumerate(log[1:], 1):
        if row.get("version") != version or row.get("previous_prompt_sha256") != digest(current) or type(row.get("accepted")) is not bool:
            raise ContractError("Broken revision chain")
        raw = row.get("revision_raw")
        if not isinstance(raw, str) or token_count(raw) > 3072:
            raise ContractError("Invalid recorded revision output")
        proposed = None
        try:
            revision = strict_json(raw)
            if not isinstance(revision, dict) or set(revision) != {"policy", "memory"}:
                raise ContractError("Malformed revision")
            proposed = validate_prompts(dict(revision, evolver=initial["evolver"]), token_count)
        except ContractError:
            if row["accepted"] or row.get("reason") != "invalid_revision":
                raise ContractError("Invalid revision cannot be accepted")
        if proposed is not None:
            new_score = row.get("score")
            if not valid_score(new_score) or row.get("prompt_sha256") != digest(proposed):
                raise ContractError("Missing scored proposed version")
            improves = new_score > old_score
            if row["accepted"] != improves:
                raise ContractError("Work acceptance must use strict full-panel improvement")
            if improves:
                current, old_score, accepted_version = proposed, new_score, version
    if final != current or artifact.get("accepted_version") != accepted_version:
        raise ContractError("Final prompts do not match the retained Work version")
    if not isinstance(artifact.get("initial_validation"), dict) or not isinstance(artifact.get("final_validation"), dict):
        raise ContractError("Missing Work validation summaries")
    if artifact["initial_validation"].get("score") != log[0]["score"] or artifact["final_validation"].get("score") != old_score:
        raise ContractError("Work summary differs from revision log")
    return final


def schedule(practice, round_index):
    selected = []
    for group in "UDXG":
        families = [f for f in FAMILIES if GROUPS[f] == group]
        for j in range(2):
            family = families[(2*round_index+j) % 4]
            rows = sorted((r for r in practice if r["family"] == family), key=lambda r: r["id"])
            if len(rows) != 8:
                raise ContractError("Practice panel must contain eight records per family")
            selected.append(rows[round_index])
    return selected


def run_work(initial, practice, validation, backend, meter, outdir):
    validate_prompts(initial, backend.token_count)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=False)
    current = dict(initial)
    initial_summary, _ = evaluate(validation, current, backend, meter, per_family=2,
        trace_dir=outdir / "validation-0")
    retained = initial_summary
    log = [{"version": 0, "prompt_sha256": digest(current), "score": retained["score"], "accepted": True}]
    (outdir / "initial.json").write_text(canonical(initial)+"\n")
    for round_index in range(3):
        panel = schedule(practice, round_index)
        trace_dir = outdir / f"practice-{round_index+1}"
        outcomes = [run_episode(r, current, backend, meter, trace_dir=trace_dir) for r in panel]
        chosen = next((r for r in outcomes if not r["success"]), outcomes[0])
        folder = trace_dir / chosen["id"]
        trace = json.loads((folder / "trace.json").read_text())["trace"]
        example = next(r for r in panel if r["id"] == chosen["id"])
        evidence = {"goal": example["goal"], "family": chosen["family"],
            "result": chosen, "recent_trace": trace[-2:],
            "panel": [{"family": r["family"], "success": r["success"], "reason": r["reason"]} for r in outcomes]}
        request = {"system": current["evolver"] +
            '\nReturn exactly {"policy":"...","memory":"..."}. Policy <=2048 native tokens; memory <=512. No code.',
            "user": canonical({"policy": current["policy"], "memory": current["memory"], "evidence": evidence}),
            "images": [Image.open(folder / "first.png").convert("RGB"), Image.open(folder / "last.png").convert("RGB")]}
        raw = backend.generate(request, max_output=3072, meter=meter)
        row = {"version": round_index+1, "previous_prompt_sha256": digest(current),
            "revision_raw": raw, "accepted": False, "reason": "invalid_revision"}
        try:
            revision = strict_json(raw)
            if not isinstance(revision, dict) or set(revision) != {"policy", "memory"}:
                raise ContractError("Wrong revision fields")
            proposed = dict(revision, evolver=initial["evolver"])
            validate_prompts(proposed, backend.token_count)
        except ContractError:
            pass
        else:
            summary, _ = evaluate(validation, proposed, backend, meter, per_family=2,
                trace_dir=outdir / f"validation-{round_index+1}")
            row.update(prompt_sha256=digest(proposed), score=summary["score"], reason="no_improvement")
            if summary["score"] > retained["score"]:
                current, retained = proposed, summary
                row.update(accepted=True, reason="strict_improvement")
        log.append(row)
        (outdir / "revisions.json").write_text(canonical(log)+"\n")
        (outdir / "progress.json").write_text(canonical({"completed_rounds": round_index+1, "usage": meter.summary()})+"\n")
    artifact = {"schema_version": 1, "initial": initial, "prompts": current,
        "completed_rounds": 3, "revision_log": log, "revision_log_sha256": digest(log), "initial_validation": initial_summary,
        "final_validation": retained, "accepted_version": max(r["version"] for r in log if r["accepted"]),
        "work_usage": meter.summary(), "model": {k:v for k,v in backend.evidence().items() if k != "calls"}, "status": "work_complete"}
    (outdir / "model_usage.json").write_text(canonical(backend.evidence())+"\n")
    (outdir / "candidate.json").write_text(canonical(artifact)+"\n")
    return artifact
