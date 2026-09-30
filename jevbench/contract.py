"""The task-owned action, artifact and resource contract."""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
import time


FAMILIES = (
    "u_book_flight", "u_multi_layouts", "u_form_sequence", "u_read_table",
    "d_invoice", "d_contract", "d_chart", "d_version",
    "x_expense", "x_calendar", "x_alert", "x_fulfillment",
    "sokoban", "key_maze", "minesweeper", "fifteen_puzzle",
)
GROUPS = {f: (f[0].upper() if f[1] == "_" else "G") for f in FAMILIES}
DECISIONS = {"U": 12, "D": 6, "X": 20, "G": 32}
ATOMS = {"sokoban": 128, "key_maze": 128, "minesweeper": 96, "fifteen_puzzle": 96}
PROMPT_CAPS = {"policy": 2048, "evolver": 1024, "memory": 512}

ACTION_HELP = """Return exactly one JSON object: {"actions":[...],"scratchpad":"..."}.
Each action is one of:
{"tool":"click","x":integer,"y":integer};
{"tool":"type","text":"text"}; {"tool":"press","key":"up|down|left|right|Tab|Enter|Backspace|Escape"};
{"tool":"scroll","dy":integer}; {"tool":"drag","x":integer,"y":integer,"to_x":integer,"to_y":integer};
{"tool":"open_document","page":integer} (document pages start at 1; 0 returns to the workflow app);
{"tool":"crop","x":integer,"y":integer,"width":positive_integer,"height":positive_integer};
{"tool":"finish","answer":structured_answer} (answer is optional for non-document tasks).
Interface/document/workflow tasks: one action. Games: 1-4 direction presses or cell clicks;
crop and finish must be alone. No observations occur between actions in a game plan.
Coordinates refer to the full screenshot, including after a crop. No other tools, fields,
code, URLs, or expressions. Scratchpad at most 128 native tokens. Output at most 256 tokens.
"""


class ContractError(ValueError):
    pass


class BudgetExceeded(RuntimeError):
    pass


def _unique(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise ContractError("Duplicate JSON key")
        result[k] = v
    return result


def strict_json(text):
    try:
        return json.loads(text, object_pairs_hook=_unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ContractError("Nonfinite number")))
    except (ValueError, TypeError) as exc:
        raise ContractError("Expected strict JSON") from exc


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def parse_decision(text, family, token_count):
    obj = strict_json(text)
    if not isinstance(obj, dict) or set(obj) - {"actions", "scratchpad"} or "actions" not in obj:
        raise ContractError("Expected actions and optional scratchpad only")
    scratch = obj.get("scratchpad", "")
    if not isinstance(scratch, str) or token_count(scratch) > 128:
        raise ContractError("Scratchpad too long or not text")
    actions = obj["actions"]
    if not isinstance(actions, list) or not 1 <= len(actions) <= (4 if GROUPS[family] == "G" else 1):
        raise ContractError("Invalid number of actions")
    schemas = {
        "click": ({"x", "y"}, set()), "type": ({"text"}, set()),
        "press": ({"key"}, set()), "scroll": ({"dy"}, set()),
        "drag": ({"x", "y", "to_x", "to_y"}, set()),
        "open_document": ({"page"}, set()),
        "crop": ({"x", "y", "width", "height"}, set()),
        "finish": (set(), {"answer"}),
    }
    for a in actions:
        if not isinstance(a, dict) or not isinstance(a.get("tool"), str) or a["tool"] not in schemas:
            raise ContractError("Unknown action")
        required, optional = schemas[a["tool"]]
        keys = set(a) - {"tool"}
        if not required <= keys or keys - required - optional:
            raise ContractError("Unexpected action arguments")
        for k in keys & {"x", "y", "to_x", "to_y"}:
            if not integer(a[k], 0, 4095):
                raise ContractError("Invalid pixel coordinate")
        for k in keys & {"width", "height"}:
            if not integer(a[k], 1, 4096):
                raise ContractError("Invalid positive dimension/page")
        if "page" in a and not integer(a["page"], 0, 128):
            raise ContractError("Invalid document page")
        if "dy" in a and not integer(a["dy"], -2048, 2048):
            raise ContractError("Invalid scroll")
        if "text" in a and (not isinstance(a["text"], str) or len(a["text"]) > 2048):
            raise ContractError("Invalid input text")
        if a["tool"] == "press" and (not isinstance(a["key"], str) or a["key"] not in {"up", "down", "left", "right", "Tab", "Enter", "Backspace", "Escape"}):
            raise ContractError("Key not allowed")
        if GROUPS[family] == "G":
            move = "press" if family in {"sokoban", "key_maze"} else "click"
            if a["tool"] not in {move, "crop", "finish"}:
                raise ContractError("Tool not allowed in this game")
            if a["tool"] == "press" and a["key"] not in {"up", "down", "left", "right"}:
                raise ContractError("Game direction required")
        if len(actions) > 1 and a["tool"] in {"crop", "finish"}:
            raise ContractError("Observation and finish must be alone")
    return actions, scratch


def validate_prompts(obj, token_count):
    if not isinstance(obj, dict) or set(obj) != set(PROMPT_CAPS):
        raise ContractError("Prompt artifact must contain exactly policy, evolver, memory")
    for key, cap in PROMPT_CAPS.items():
        if not isinstance(obj[key], str) or token_count(obj[key]) > cap:
            raise ContractError(f"Invalid or oversized {key}")
    if not obj["policy"].strip() or not obj["evolver"].strip():
        raise ContractError("Policy and evolver must be nonempty")
    return obj


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0


class Meter:
    def __init__(self, *, seconds=7200, calls=2700, input_tokens=16_000_000, output_tokens=750_000):
        self.limits = dict(seconds=seconds, calls=calls, input_tokens=input_tokens, output_tokens=output_tokens)
        self.usage = Usage()
        self.started = time.monotonic()
        self.pending_max_output = None

    def check_time(self):
        self.usage.seconds = time.monotonic() - self.started
        if self.usage.seconds > self.limits["seconds"]:
            raise BudgetExceeded("Global wall-clock budget exhausted")

    def begin(self, input_tokens, max_output):
        self.check_time()
        if self.pending_max_output is not None:
            raise ContractError("Previous generation has not been accounted")
        if max_output not in (256, 3072):
            raise ContractError("Unsupported generation limit")
        if not integer(input_tokens, 1, 8192):
            raise ContractError("Native input context exceeds 8192 or is uncounted")
        if self.usage.calls + 1 > self.limits["calls"]:
            raise BudgetExceeded("Call budget exhausted")
        if self.usage.input_tokens + input_tokens > self.limits["input_tokens"]:
            raise BudgetExceeded("Input token budget exhausted")
        if self.usage.output_tokens + max_output > self.limits["output_tokens"]:
            raise BudgetExceeded("Insufficient output budget for the fixed call")
        self.usage.calls += 1
        self.usage.input_tokens += input_tokens
        self.pending_max_output = max_output

    def end(self, output_tokens):
        if self.pending_max_output is None:
            raise ContractError("No pending generation")
        if not integer(output_tokens, 0, 3072):
            raise ContractError("Unaccounted output")
        self.usage.output_tokens += output_tokens
        limit, self.pending_max_output = self.pending_max_output, None
        if output_tokens > limit:
            raise ContractError("Generation exceeded its reserved output limit")
        self.check_time()

    def summary(self):
        self.usage.seconds = time.monotonic() - self.started
        return asdict(self.usage)


def score(results, per_family):
    if len(results) != per_family * len(FAMILIES):
        raise ContractError("Incomplete evaluation: no valid score")
    ids = [r["id"] for r in results]
    if len(ids) != len(set(ids)):
        raise ContractError("Duplicate episode")
    by_type = {}
    for f in FAMILIES:
        rows = [r for r in results if r["family"] == f]
        if len(rows) != per_family or any(type(r.get("success")) is not bool for r in rows):
            raise ContractError("Missing family or non-Boolean reward")
        by_type[f] = 100 * sum(r["success"] for r in rows) / per_family
    by_group = {g: sum(by_type[f] for f in FAMILIES if GROUPS[f] == g) / 4 for g in "UDXG"}
    return {"score": sum(by_type.values()) / 16, "by_type": by_type, "by_group": by_group,
            "completed": len(results), "successful": sum(r["success"] for r in results)}
