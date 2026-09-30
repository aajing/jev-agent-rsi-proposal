"""Screenshot-only execution, with all budgets enforced outside candidate text."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

from .contract import ACTION_HELP, ATOMS, DECISIONS, GROUPS, ContractError, parse_decision, score


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def environment(record):
    family = record["family"]
    if family in {"sokoban", "key_maze"}:
        from .push_maze import Env
    elif family in {"minesweeper", "fifteen_puzzle"}:
        from .mines_puzzle import Env
    else:
        from .visual_tasks import Env
    return Env(record)


class Episode:
    def __init__(self, record, env=None):
        self.record = record
        self.family = record["family"]
        self.env = env if env is not None else environment(record)
        self.max_calls = DECISIONS[GROUPS[self.family]]
        self.max_atoms = ATOMS.get(self.family, self.max_calls)
        self.calls = self.atoms = 0
        self.scratchpad = ""
        self.history = []
        self.crop = None
        self.done = self.success = False
        self.reason = "started"

    def observations(self):
        full = self.env.render().convert("RGB")
        images = [full]
        if self.crop is not None:
            x, y, w, h = self.crop
            detail = full.crop((x, y, x+w, y+h))
            detail.thumbnail((768, 768))
            images.append(detail)
        return images

    def request(self, prompts):
        # Never serialize the task record, gold answer, reference plan, DOM or environment.
        return {
            "system": ACTION_HELP + "\nPOLICY:\n" + prompts["policy"] + "\nMEMORY:\n" + prompts["memory"],
            "user": canonical({"goal": self.env.goal, "family": self.family,
                "remaining_calls": self.max_calls-self.calls,
                "remaining_atoms": self.max_atoms-self.atoms,
                "recent_actions": self.history[-4:], "scratchpad": self.scratchpad,
                "last_status": self.reason}),
            "images": self.observations(),
        }

    def _failed_format(self, reason):
        self.reason = reason
        if self.calls >= self.max_calls:
            self.done = True
            self.reason = "decision_budget"
        return {"attempted": 0, "reason": self.reason, "terminal": self.done, "success": False}

    def apply(self, output, token_count):
        if self.done:
            raise ContractError("Episode already ended")
        self.calls += 1
        try:
            actions, scratchpad = parse_decision(output, self.family, token_count)
        except ContractError:
            return self._failed_format("invalid_format")
        self.scratchpad = scratchpad
        self.crop = None
        attempted = 0
        for a in actions:
            if self.atoms >= self.max_atoms:
                self.done, self.reason = True, "atomic_budget"
                break
            self.atoms += 1
            attempted += 1
            if a["tool"] == "crop":
                width, height = self.env.render().size
                valid = a["x"]+a["width"] <= width and a["y"]+a["height"] <= height
                if valid:
                    self.crop = a["x"], a["y"], a["width"], a["height"]
                status = {"valid": valid, "terminal": False, "success": False, "reason": "crop" if valid else "invalid_crop"}
            elif a["tool"] == "finish" and GROUPS[self.family] == "G":
                status = {"valid": True, "terminal": True, "success": bool(self.env.success), "reason": "finished"}
            else:
                status = self.env.step(a)
            if not isinstance(status, dict) or any(type(status.get(k)) is not bool for k in ("valid", "terminal", "success")):
                raise RuntimeError("Environment violated the status contract")
            # Only short, task-owned status categories can reach the actor.
            self.reason = str(status["reason"])[:100]
            self.history.append({"action": a, "valid": status["valid"]})
            if status["terminal"]:
                self.done, self.success = True, status["success"]
                break
            if not status["valid"]:
                break
        # Test terminal success before exhaustion: a final legal move can still win.
        if not self.done and (self.calls >= self.max_calls or self.atoms >= self.max_atoms):
            self.done, self.reason = True, "episode_budget"
        return {"attempted": attempted, "reason": self.reason, "terminal": self.done,
                "success": self.success, "remaining_calls": self.max_calls-self.calls,
                "remaining_atoms": self.max_atoms-self.atoms}

    def close(self):
        close = getattr(self.env, "close", None)
        if close:
            close()


def run_episode(record, prompts, backend, meter, *, trace_dir=None):
    episode = Episode(record)
    trace = []
    first = episode.observations()[0]
    try:
        while not episode.done:
            output = backend.generate(episode.request(prompts), max_output=256, meter=meter)
            status = episode.apply(output, backend.token_count)
            trace.append({"call": episode.calls, "output": output, "status": status})
        result = {"id": record["id"], "family": record["family"], "tier": record["tier"],
            "success": bool(episode.success), "calls": episode.calls, "atoms": episode.atoms,
            "reason": episode.reason}
        if trace_dir is not None:
            folder = Path(trace_dir) / record["id"]
            folder.mkdir(parents=True, exist_ok=True)
            first.save(folder / "first.png")
            episode.observations()[0].save(folder / "last.png")
            (folder / "trace.json").write_text(canonical({"result": result, "trace": trace})+"\n")
        return result
    finally:
        episode.close()


def evaluate(records, prompts, backend, meter, *, per_family, trace_dir=None):
    # Validate the whole workload before running anything, and never fill missing results.
    if len(records) != 16 * per_family:
        raise ContractError("Wrong evaluation size")
    if len({r["id"] for r in records}) != len(records):
        raise ContractError("Duplicate evaluation record")
    # Reuse the score contract with dummy false outcomes to validate exact quotas
    # before a single GPU call is spent. This is validation, never a reported score.
    score([dict(id=r["id"], family=r["family"], success=False) for r in records], per_family)
    result = [run_episode(r, prompts, backend, meter, trace_dir=trace_dir) for r in records]
    summary = score(result, per_family)
    summary["errors"] = dict(Counter(r["reason"] for r in result if not r["success"]))
    summary["usage"] = meter.summary()
    return summary, result
