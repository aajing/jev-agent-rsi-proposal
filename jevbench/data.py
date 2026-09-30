"""Task-owner materialization. Private seeds and records never enter public ZIPs."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import secrets

from .contract import FAMILIES, ContractError
from .runtime import canonical, digest, Episode

COUNTS = {"practice": 8, "validation": 2, "hidden": 6}


def module(family):
    name = "push_maze" if family in {"sokoban", "key_maze"} else (
        "mines_puzzle" if family in {"minesweeper", "fifteen_puzzle"} else "visual_tasks")
    return importlib.import_module("jevbench." + name)


def read_records(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def observable_id(record):
    if record["family"].startswith("u_"):
        value = record.get("certificate", {}).get("observable_sha256")
        if not isinstance(value, str) or len(value) != 64:
            raise ContractError("Native task lacks observable-instance fingerprint")
        return digest({"family": record["family"], "observable_sha256": value})
    return digest({"family": record["family"], "goal": record["goal"], "data": record["data"]})


def replay_reference(record):
    episode = Episode(record)
    batches = record.get("reference_batches")
    if batches is None:
        actions = record["reference_actions"]
        width = 4 if record["family"] in {"sokoban", "key_maze", "fifteen_puzzle"} else 1
        batches = [actions[i:i+width] for i in range(0, len(actions), width)]
    try:
        for batch in batches:
            if episode.done:
                break
            episode.apply(canonical({"actions": batch}), lambda text: len(text))
        if not episode.done or not episode.success:
            raise ContractError("Reference failed under the actual controller")
        if record["family"] in {"sokoban", "key_maze", "minesweeper", "fifteen_puzzle"} and episode.calls > 24:
            raise ContractError("Reference exceeds 24-call feasibility gate")
        return {"calls": episode.calls, "atoms": episode.atoms, "success": True}
    finally:
        episode.close()


def build_data(base, *, selected_families=None):
    base = Path(base)
    private = base / "private"
    private.mkdir(parents=True, exist_ok=True)
    (base / "public").mkdir(parents=True, exist_ok=True)
    seed_file = private / "construction_seeds.json"
    seeds = json.loads(seed_file.read_text()) if seed_file.exists() else {}
    selected_families = selected_families or FAMILIES
    manifest = {"schema_version": 1, "families": list(FAMILIES), "splits": {}, "source_status": "generated_and_certified"}
    seen = set()
    for split, count in COUNTS.items():
        folder = private if split == "hidden" else base / "public"
        target = folder / (split + ".jsonl")
        existing = {r["id"]: r for r in read_records(target)} if target.exists() else {}
        all_records = []
        certificates = []
        for family in FAMILIES:
            for tier in ("hard", "harder"):
                for index in range(count // 2):
                    key = f"{split}:{family}:{tier}:{index}"
                    rid = f"{split}-{family}-{tier}-{index:02d}"
                    if family not in selected_families and rid not in existing:
                        continue
                    if rid in existing:
                        record = existing[rid]
                    else:
                        # Checkpoint construction seeds before expensive generation.
                        for attempt in range(100):
                            attempt_key = key + f":{attempt}"
                            if attempt_key not in seeds:
                                seeds[attempt_key] = secrets.randbits(63) if split == "hidden" else int(digest(attempt_key)[:15], 16)
                                seed_file.write_text(json.dumps(seeds, indent=2)+"\n")
                            record = module(family).generate(family, seeds[attempt_key], tier)
                            visible_id = observable_id(record)
                            if visible_id not in seen:
                                break
                        else:
                            raise ContractError("Could not produce a distinct instance")
                        record.update(id=rid, split=split)
                    visible_id = observable_id(record)
                    if visible_id in seen:
                        raise ContractError("Duplicate full instance across splits")
                    seen.add(visible_id)
                    certified = module(family).certify(record)
                    if certified is False:
                        raise ContractError("Structural certification failed")
                    reference = replay_reference(record)
                    all_records.append(record)
                    certificates.append({"id": rid, "family": family, "tier": tier,
                        "record_sha256": digest(record), "reference": reference, "certified": True})
                    # Save every finished record; resume never loses certified work.
                    existing[rid] = record
                    target.write_text("".join(canonical(v)+"\n" for v in existing.values()))
        if len(all_records) == len(FAMILIES) * count:
            target.write_text("".join(canonical(v)+"\n" for v in all_records))
        row = {"count": len(all_records), "expected": len(FAMILIES)*count,
            "complete": len(all_records) == len(FAMILIES)*count}
        if split == "hidden":
            # Per-instance solution length is a side channel. Keep it owner-only.
            (private / "certificates.json").write_text(json.dumps(certificates, indent=2)+"\n")
            row["certified_count"] = len(certificates)
            row["dataset_sha256"] = digest(all_records)
        else:
            row["records"] = certificates
        manifest["splits"][split] = row
    # Public metadata never includes hidden per-instance paths, seeds or proof details.
    (base / "manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
    return manifest
