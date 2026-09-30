#!/usr/bin/env python3
"""Task-owner host controller for one immutable 24-hour JEV trajectory.

This is an owner-side process, NOT an OS sandbox or a researcher-facing shell.
Run it outside the researcher's container/account.  The researcher supplies only
the three-string initial prompt JSON on stdin.  All model, code, dataset, result,
deadline and ledger paths are fixed by ``init`` and copied into a private run.

Owner setup (Linux/macOS; the inference environment still requires Linux/CUDA):
  python trajectory_controller.py init --state /owner/run-001 \
    --task-root /trusted/jev-agent --data /owner/data --model /opt/jev-model \
    --python /opt/jev-env/bin/python
  python trajectory_controller.py baseline --state /owner/run-001 --kind B0
  python trajectory_controller.py baseline --state /owner/run-001 --kind B1
  cat initial-prompts.json | python trajectory_controller.py submit --state /owner/run-001
  python trajectory_controller.py status --state /owner/run-001

Each submit runs trusted three-round Work, authenticates its retained artifact,
then runs Judge. B0 is the one explicit owner control without Work; B1 uses Work.
All Judge starts, including controls and failures, consume one of 12 slots.
An independent forked supervisor retains the run lock and enforces each phase's
deadline even if this front-end process is killed. Wall time, including downtime,
starts at initialization and never resets across processes. This does not claim
to survive host clock tampering or an attacker with task-owner filesystem rights.
Harbor integration/receipt injection is NOT implemented by this standalone tool.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid


SECONDS = 86_400
PHASE_SECONDS = 7_200
JUDGE_LIMIT = 12
FAMILIES = (
    "u_book_flight", "u_multi_layouts", "u_form_sequence", "u_read_table",
    "d_invoice", "d_contract", "d_chart", "d_version",
    "x_expense", "x_calendar", "x_alert", "x_fulfillment",
    "sokoban", "key_maze", "minesweeper", "fifteen_puzzle",
)
BOOTSTRAP = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('jevbench',run_name='__main__')"


class OwnerError(RuntimeError):
    """Only fixed, non-secret categories are emitted to the submitter."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_hash(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_hash(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(part)
    return value.hexdigest()


def strict_json(text):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise OwnerError("invalid_json")
            obj[key] = value
        return obj
    def nonfinite(value):
        raise OwnerError("invalid_json")
    try:
        return json.loads(text, object_pairs_hook=unique, parse_constant=nonfinite)
    except (ValueError, TypeError, RecursionError) as exc:
        raise OwnerError("invalid_json") from exc


def prompts_only(value):
    if not isinstance(value, dict) or set(value) != {"policy", "evolver", "memory"}:
        raise OwnerError("three_literal_prompts_required")
    if any(not isinstance(v, str) for v in value.values()) or not value["policy"].strip() or not value["evolver"].strip():
        raise OwnerError("invalid_prompt_strings")
    if len(canonical(value).encode()) > 131072:
        raise OwnerError("prompt_input_too_large")
    # The real processor enforces native-token limits during Work/Judge.
    return value


def write_json(path, value):
    path = Path(path)
    temp = path.with_name(path.name + "." + secrets.token_hex(6) + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(canonical(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def append_event(state, event):
    event = dict(event, at=time.time())
    payload = (canonical(event) + "\n").encode()
    fd = os.open(Path(state) / "events.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        written = os.write(fd, payload)
        if written != len(payload):
            raise OwnerError("ledger_write_incomplete")
        os.fsync(fd)
    finally:
        os.close(fd)


def read_events(state):
    path = Path(state) / "events.jsonl"
    payload = path.read_bytes() if path.exists() else b""
    if payload and not payload.endswith(b"\n"):
        raise OwnerError("ledger_incomplete_requires_owner_recovery")
    return [strict_json(line) for line in payload.decode().splitlines() if line]


def judge_starts(events):
    return sum(row.get("event") == "phase_started" and row.get("phase") == "judge" for row in events)


def private_state(path):
    path = Path(path)
    if path.is_symlink():
        raise OwnerError("state_must_not_be_symlink")
    path = path.resolve(strict=True)
    info = path.stat()
    if not path.is_dir() or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise OwnerError("state_must_be_owner_private")
    return path


@contextmanager
def locked(state):
    state = private_state(state)
    fd = os.open(state / "lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise OwnerError("trajectory_is_busy") from exc
        yield state, fd
    finally:
        # Closing without LOCK_UN is deliberate: an orphaned supervisor retains
        # the same open-file-description lock until its bounded child exits.
        os.close(fd)


def checked_config(state, *, check_deadline=True):
    config = strict_json((state / "config.json").read_text())
    if config.get("schema_version") != 1 or config.get("judge_limit") != JUDGE_LIMIT:
        raise OwnerError("invalid_owner_configuration")
    events = read_events(state)
    now = time.time()
    if events and now < max(row["at"] for row in events):
        raise OwnerError("host_clock_moved_backwards")
    if check_deadline and now >= config["deadline_utc"]:
        raise OwnerError("trajectory_deadline_exhausted")
    return config


def copy_tree(source, destination):
    source, destination = Path(source), Path(destination)
    if source.is_symlink() or not source.is_dir():
        raise OwnerError("trusted_source_directory_missing_or_symlink")
    destination.mkdir(parents=True)
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if "__pycache__" in relative.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise OwnerError("trusted_source_contains_symlink")
        target = destination / relative
        if path.is_dir():
            target.mkdir(exist_ok=True)
        elif path.is_file():
            shutil.copyfile(path, target)
        else:
            raise OwnerError("trusted_source_contains_special_file")


def verify_records(path, per_family, split):
    rows = [strict_json(line) for line in Path(path).read_text().splitlines() if line.strip()]
    if len(rows) != 16 * per_family or len({r.get("id") for r in rows}) != len(rows):
        raise OwnerError("invalid_dataset_count_or_ids")
    for family in FAMILIES:
        records = [r for r in rows if r.get("family") == family]
        if len(records) != per_family or any(r.get("split") != split for r in records):
            raise OwnerError("invalid_dataset_family_or_split")
        if any(sum(r.get("tier") == tier for r in records) != per_family // 2 for tier in ("hard", "harder")):
            raise OwnerError("invalid_dataset_tier_balance")
    return rows


def freeze_manifest(state):
    manifest = {}
    for root in (state / "trusted", state / "data"):
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise OwnerError("frozen_snapshot_contains_symlink")
            if path.is_file():
                manifest[str(path.relative_to(state))] = {"bytes": path.stat().st_size, "sha256": file_hash(path)}
    write_json(state / "frozen_files.json", manifest)
    return file_hash(state / "frozen_files.json")


def verify_frozen(state, config):
    if file_hash(state / "frozen_files.json") != config["frozen_manifest_sha256"]:
        raise OwnerError("frozen_manifest_changed")
    manifest = strict_json((state / "frozen_files.json").read_text())
    seen = set()
    for root in (state / "trusted", state / "data"):
        for path in root.rglob("*"):
            if path.is_symlink():
                raise OwnerError("frozen_snapshot_changed")
            if path.is_file():
                relative = str(path.relative_to(state))
                expected = manifest.get(relative)
                if expected is None or path.stat().st_size != expected["bytes"] or file_hash(path) != expected["sha256"]:
                    raise OwnerError("frozen_snapshot_changed")
                seen.add(relative)
    if seen != set(manifest):
        raise OwnerError("frozen_snapshot_changed")
    if file_hash(config["python"]) != config["python_sha256"]:
        raise OwnerError("owner_interpreter_changed")


def initialize(args):
    start = time.time()
    state = Path(args.state)
    state.mkdir(mode=0o700, parents=False, exist_ok=False)
    state = private_state(state)
    try:
        task, data = Path(args.task_root).resolve(strict=True), Path(args.data).resolve(strict=True)
        python = Path(args.python).absolute()
        if not python.is_file() or not os.access(python, os.X_OK):
            raise OwnerError("owner_python_missing")
        model = Path(args.model).resolve(strict=True)
        if not model.is_dir():
            raise OwnerError("owner_model_missing")
        for name in ("jevbench", "assets", "configs"):
            copy_tree(task / name, state / "trusted" / name)
        baseline = strict_json((task / "baseline_prompts.json").read_text())
        write_json(state / "trusted/baseline_prompts.json", baseline)
        baseline = prompts_only({key: baseline[key] for key in ("policy", "evolver", "memory")})
        write_json(state / "trusted/baseline.json", baseline)
        for split, count in (("practice", 8), ("validation", 2), ("hidden", 6)):
            parent = "private" if split == "hidden" else "public"
            source = data / parent / (split + ".jsonl")
            verify_records(source, count, split)
            target = state / "data" / parent / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        config = {"schema_version": 1, "run_id": str(uuid.uuid4()), "started_utc": start,
                  "deadline_utc": start + SECONDS, "judge_limit": JUDGE_LIMIT,
                  "python": str(python), "python_sha256": file_hash(python), "model": str(model),
                  "playwright_browsers_path": str(Path(args.playwright_browsers).absolute()),
                  "frozen_manifest_sha256": freeze_manifest(state)}
        write_json(state / "config.json", config)
        (state / "receipt_key").write_bytes(secrets.token_bytes(32))
        os.chmod(state / "receipt_key", 0o600)
        (state / "submissions").mkdir(mode=0o700)
        (state / "judge_ledger.jsonl").touch(mode=0o600)
        append_event(state, {"event": "initialized", "run_id": config["run_id"],
                             "deadline_utc": config["deadline_utc"], "judge_limit": JUDGE_LIMIT})
        verify_frozen(state, config)
        return {"status": "initialized", "run_id": config["run_id"],
                "deadline_utc": config["deadline_utc"], "judge_limit": JUDGE_LIMIT}
    except BaseException:
        # Preserve a failed setup privately for owner diagnosis; do not start it.
        if (state / "config.json").exists():
            (state / "config.json").rename(state / "failed_config.json")
        raise


def safe_environment(config, run_dir):
    return {"PATH": str(Path(config["python"]).parent) + ":/usr/bin:/bin",
            "HOME": str(run_dir), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
            "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1", "TOKENIZERS_PARALLELISM": "false",
            "PLAYWRIGHT_BROWSERS_PATH": config["playwright_browsers_path"]}


def supervise(command, *, cwd, env, deadline, outcome_path, stdout_path, stderr_path):
    """One bounded process group. Called in an independent lock-owning fork."""
    start = time.time()
    process = None
    result = {"status": "failed", "returncode": None, "started_utc": start}
    def interrupted(signum, frame):
        raise OwnerError("supervisor_interrupted")
    old_handlers = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        remaining = deadline - time.time()
        if remaining <= 0:
            result["status"] = "deadline_exhausted"
        else:
            with Path(stdout_path).open("wb") as stdout, Path(stderr_path).open("wb") as stderr:
                process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                           stdout=stdout, stderr=stderr, start_new_session=True, close_fds=True)
                result["process_group"] = process.pid
                try:
                    process.wait(timeout=max(0.001, deadline - time.time()))
                    result["returncode"] = process.returncode
                    result["status"] = "complete" if process.returncode == 0 else "failed"
                    if time.time() >= deadline:
                        result["status"] = "deadline_exhausted"
                except subprocess.TimeoutExpired:
                    result["status"] = "deadline_exhausted"
    except BaseException:
        result["status"] = "supervisor_interrupted_or_failed"
    finally:
        if process is not None:
            # Also remove descendants left running after a successful leader.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                result["status"] = "process_group_cleanup_failed"
        result["finished_utc"] = time.time()
        result["elapsed_seconds"] = result["finished_utc"] - start
        write_json(outcome_path, result)
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
    return result


def run_phase(state, config, *, phase, submission, command, folder):
    events = read_events(state)
    if phase == "judge" and judge_starts(events) >= JUDGE_LIMIT:
        raise OwnerError("judge_quota_exhausted")
    now = time.time()
    if now >= config["deadline_utc"]:
        raise OwnerError("trajectory_deadline_exhausted")
    deadline = min(config["deadline_utc"], now + PHASE_SECONDS)
    folder.mkdir(mode=0o700, parents=True, exist_ok=False)
    phase_id = str(uuid.uuid4())
    # This fsynced reservation survives every later error; no Judge refunds.
    append_event(state, {"event": "phase_started", "phase": phase, "phase_id": phase_id,
                         "submission": submission, "deadline_utc": deadline})
    pid = os.fork()
    if pid == 0:
        try:
            result = supervise(command, cwd=state / "trusted", env=safe_environment(config, folder),
                               deadline=deadline, outcome_path=folder / "supervisor.json",
                               stdout_path=folder / "stdout.private.log", stderr_path=folder / "stderr.private.log")
            append_event(state, {"event": "phase_finished", "phase": phase, "phase_id": phase_id,
                                 "submission": submission, **result})
            os._exit(0)
        except BaseException:
            os._exit(1)
    _, wait_status = os.waitpid(pid, 0)
    if wait_status or not (folder / "supervisor.json").is_file():
        raise OwnerError("owner_supervisor_failed")
    result = strict_json((folder / "supervisor.json").read_text())
    if result["status"] != "complete":
        raise OwnerError("phase_failed_or_timed_out")
    verify_frozen(state, config)
    checked_config(state)
    return result


def make_receipt(state, payload):
    signature = hmac.new((state / "receipt_key").read_bytes(), canonical(payload).encode(), hashlib.sha256).hexdigest()
    return {"payload": payload, "hmac_sha256": signature}


def verify_receipt(state, receipt, prompts, work_dir=None):
    expected = make_receipt(state, receipt["payload"])
    if not hmac.compare_digest(receipt.get("hmac_sha256", ""), expected["hmac_sha256"]):
        raise OwnerError("invalid_owner_work_receipt")
    payload = receipt["payload"]
    if payload["final_prompt_sha256"] != json_hash(prompts):
        raise OwnerError("retained_prompts_changed")
    if payload["kind"] == "B0":
        baseline = strict_json((state / "trusted/baseline.json").read_text())
        if prompts != baseline:
            raise OwnerError("baseline_control_changed")
    else:
        if work_dir is None or payload["completed_rounds"] != 3:
            raise OwnerError("three_round_work_receipt_required")
        if file_hash(work_dir / "candidate.json") != payload["work_artifact_sha256"] or file_hash(work_dir / "revisions.json") != payload["work_log_sha256"]:
            raise OwnerError("trusted_work_artifact_changed")


def submit(state_path, prompts, *, kind="candidate"):
    with locked(state_path) as (state, _lock_fd):
        config = checked_config(state)
        if judge_starts(read_events(state)) >= JUDGE_LIMIT:
            raise OwnerError("judge_quota_exhausted")
        verify_frozen(state, config)
        initial = prompts_only(prompts)
        if kind in {"B0", "B1"}:
            if initial != strict_json((state / "trusted/baseline.json").read_text()):
                raise OwnerError("baseline_control_changed")
        elif kind != "candidate":
            raise OwnerError("unknown_submission_kind")
        submission = str(uuid.uuid4())
        root = state / "submissions" / submission
        root.mkdir(mode=0o700)
        write_json(root / "initial.json", initial)
        append_event(state, {"event": "submission_started", "submission": submission,
                             "kind": kind, "initial_prompt_sha256": json_hash(initial)})
        base_command = [config["python"], "-I", "-B", "-c", BOOTSTRAP, str(state / "trusted")]
        shared = ["--model", config["model"], "--data", str(state / "data")]
        work_dir, work_summary = None, None
        try:
            if kind == "B0":
                retained = initial
                receipt_payload = {"kind": kind, "run_id": config["run_id"], "submission": submission,
                                   "final_prompt_sha256": json_hash(retained), "completed_rounds": 0}
            else:
                work_dir = root / "work-artifact"
                run_phase(state, config, phase="work", submission=submission,
                          command=base_command + ["work"] + shared + ["--prompts", str(root / "initial.json"), "--output", str(work_dir)],
                          folder=root / "work-process")
                artifact = strict_json((work_dir / "candidate.json").read_text())
                log = strict_json((work_dir / "revisions.json").read_text())
                if artifact.get("status") != "work_complete" or artifact.get("completed_rounds") != 3 or artifact.get("initial") != initial or artifact.get("revision_log_sha256") != json_hash(log):
                    raise OwnerError("incomplete_or_changed_trusted_work")
                retained = prompts_only(artifact["prompts"])
                receipt_payload = {"kind": kind, "run_id": config["run_id"], "submission": submission,
                                   "final_prompt_sha256": json_hash(retained), "completed_rounds": 3,
                                   "work_artifact_sha256": file_hash(work_dir / "candidate.json"),
                                   "work_log_sha256": file_hash(work_dir / "revisions.json")}
                work_summary = {"completed_rounds": 3, "accepted_version": artifact["accepted_version"],
                                "initial_validation": artifact["initial_validation"],
                                "final_validation": artifact["final_validation"], "usage": artifact["work_usage"]}
            receipt = make_receipt(state, receipt_payload)
            write_json(root / "owner_receipt.json", receipt)
            write_json(root / "retained.json", retained)
            verify_receipt(state, receipt, retained, work_dir)
            judge_prompts = root / "retained.json" if kind == "B0" else work_dir / "candidate.json"
            judge_output = root / "judge-result.private.json"
            run_phase(state, config, phase="judge", submission=submission,
                      command=base_command + ["judge"] + shared + ["--prompts", str(judge_prompts),
                          "--records", str(state / "data/private/hidden.jsonl"),
                          "--ledger", str(state / "judge_ledger.jsonl"), "--output", str(judge_output)],
                      folder=root / "judge-process")
            result = strict_json(judge_output.read_text())
            value = result.get("score")
            if result.get("status") != "complete" or result.get("completed") != 96 or type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 100:
                raise OwnerError("incomplete_or_invalid_judge")
            safe = {key: result[key] for key in ("score", "by_type", "by_group", "completed", "successful", "usage", "errors") if key in result}
            safe.update(status="complete", submission=submission, kind=kind,
                        judge_calls_used=judge_starts(read_events(state)),
                        elapsed_trajectory_seconds=time.time() - config["started_utc"])
            if work_summary is not None:
                safe["work"] = work_summary
            # Retained prompts are public Work output, never hidden observations.
            safe["retained_prompts"] = retained
            write_json(root / "public-result.json", safe)
            append_event(state, {"event": "submission_finished", "submission": submission,
                                 "status": "complete", "score": value, "final_prompt_sha256": json_hash(retained)})
            return safe
        except BaseException:
            append_event(state, {"event": "submission_finished", "submission": submission, "status": "unscored"})
            raise


def status(state_path):
    state = private_state(state_path)
    config = checked_config(state, check_deadline=False)
    events = read_events(state)
    started = {r["phase_id"] for r in events if r.get("event") == "phase_started"}
    finished = {r["phase_id"] for r in events if r.get("event") == "phase_finished"}
    return {"run_id": config["run_id"], "deadline_utc": config["deadline_utc"],
            "remaining_seconds": max(0, config["deadline_utc"] - time.time()),
            "judge_calls_used": judge_starts(events), "judge_limit": JUDGE_LIMIT,
            "unfinished_phases": len(started - finished),
            "completed_submissions": sum(r.get("event") == "submission_finished" and r.get("status") == "complete" for r in events)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("init")
    setup.add_argument("--state", required=True)
    setup.add_argument("--task-root", required=True)
    setup.add_argument("--data", required=True)
    setup.add_argument("--model", required=True)
    setup.add_argument("--python", required=True)
    setup.add_argument("--playwright-browsers", default="/opt/playwright")
    for command in ("submit", "status", "baseline"):
        child = sub.add_parser(command)
        child.add_argument("--state", required=True)
        if command == "baseline":
            child.add_argument("--kind", choices=("B0", "B1"), required=True)
    sub.add_parser("self-test", help="CPU-only controller tests; no inference or baseline score")
    args = parser.parse_args(argv)
    if args.command == "self-test":
        return self_test()
    if args.command == "init":
        result = initialize(args)
    elif args.command == "status":
        result = status(args.state)
    elif args.command == "baseline":
        state = private_state(args.state)
        result = submit(state, strict_json((state / "trusted/baseline.json").read_text()), kind=args.kind)
    else:
        raw = sys.stdin.buffer.read(131073)
        if len(raw) > 131072:
            raise OwnerError("prompt_input_too_large")
        result = submit(args.state, prompts_only(strict_json(raw.decode("utf-8"))))
    print(canonical(result))
    return 0


def self_test():
    """Exercise real process groups/files, not model or task performance."""
    import unittest
    from unittest.mock import patch

    class ControllerTests(unittest.TestCase):
        def test_process_group_deadline_kills_leader_and_descendant(self):
            with tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                marker = folder / "escaped-marker"
                script = ("import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',"
                          + repr("import time,pathlib;time.sleep(0.7);pathlib.Path(" + repr(str(marker)) + ").write_text('escaped')")
                          + "]);time.sleep(30)")
                result = supervise([sys.executable, "-c", script], cwd=folder, env=dict(os.environ),
                                   deadline=time.time()+0.15, outcome_path=folder/"result.json",
                                   stdout_path=folder/"stdout", stderr_path=folder/"stderr")
                self.assertEqual(result["status"], "deadline_exhausted")
                time.sleep(0.75)
                self.assertFalse(marker.exists())

        def test_persistent_judge_slots_count_failures_and_never_refund(self):
            with tempfile.TemporaryDirectory() as tmp:
                state = Path(tmp)
                for i in range(12):
                    append_event(state, dict(event="phase_started", phase="judge", phase_id=str(i)))
                    append_event(state, dict(event="phase_finished", phase="judge", phase_id=str(i), status="failed"))
                self.assertEqual(judge_starts(read_events(state)), 12)
                with self.assertRaisesRegex(OwnerError, "judge_quota_exhausted"):
                    run_phase(state, {"deadline_utc":time.time()+60}, phase="judge", submission="test",
                              command=[sys.executable,"-c","raise Exception('must not run')"], folder=state/"blocked")
                self.assertFalse((state/"blocked").exists())

        def test_expired_deadline_blocks_work_and_judge_before_spawn(self):
            with tempfile.TemporaryDirectory() as tmp:
                for phase in ("work", "judge"):
                    with self.assertRaisesRegex(OwnerError, "trajectory_deadline_exhausted"):
                        run_phase(Path(tmp), {"deadline_utc":time.time()-1}, phase=phase, submission="test",
                                  command=[], folder=Path(tmp)/phase)
                self.assertFalse((Path(tmp)/"events.jsonl").exists())

        def test_frozen_hidden_content_cannot_be_hot_changed(self):
            with tempfile.TemporaryDirectory() as tmp:
                state=Path(tmp)
                (state/"trusted").mkdir();(state/"data/private").mkdir(parents=True)
                hidden=state/"data/private/hidden.jsonl";hidden.write_text("private fixture A\n")
                config={"frozen_manifest_sha256":freeze_manifest(state),"python":sys.executable,"python_sha256":file_hash(sys.executable)}
                verify_frozen(state,config)
                hidden.write_text("private fixture B\n")
                with self.assertRaisesRegex(OwnerError,"frozen_snapshot_changed"):
                    verify_frozen(state,config)

        def test_unsigned_or_changed_retained_prompt_cannot_bypass_work(self):
            with tempfile.TemporaryDirectory() as tmp:
                state=Path(tmp);(state/"receipt_key").write_bytes(b"x"*32)
                prompts={"policy":"test","evolver":"test","memory":""}
                receipt=make_receipt(state,{"kind":"candidate","final_prompt_sha256":json_hash(prompts),"completed_rounds":3})
                receipt["payload"]["completed_rounds"]=0
                with self.assertRaisesRegex(OwnerError,"invalid_owner_work_receipt"):
                    verify_receipt(state,receipt,prompts)
                receipt=make_receipt(state,{"kind":"candidate","final_prompt_sha256":json_hash(prompts),"completed_rounds":3})
                with self.assertRaisesRegex(OwnerError,"retained_prompts_changed"):
                    verify_receipt(state,receipt,dict(prompts,policy="forged"))

        def test_researcher_prompt_cannot_override_paths_or_add_artifact_fields(self):
            prompts={"policy":"literal instruction","evolver":"literal instruction","memory":""}
            self.assertEqual(prompts_only(prompts),prompts)
            for key in ("dataset", "ledger", "completed_rounds", "model", "command"):
                with self.assertRaises(OwnerError):
                    prompts_only(dict(prompts,**{key:"override"}))

        def test_cross_process_lock_rejects_parallel_submit(self):
            with tempfile.TemporaryDirectory() as tmp:
                state=Path(tmp);os.chmod(state,0o700)
                with locked(state):
                    script=("import runpy;from pathlib import Path;m=runpy.run_path("+repr(str(Path(__file__).resolve()))+");\n"
                            "try:\n with m['locked'](Path("+repr(str(state))+")):pass\n"
                            "except m['OwnerError'] as exc:print(str(exc))\n")
                    child=subprocess.run([sys.executable,"-c",script],capture_output=True,text=True,timeout=5)
                    self.assertEqual(child.returncode,0)
                    self.assertEqual(child.stdout.strip(),"trajectory_is_busy")

        def test_supervisor_keeps_lock_and_deadline_after_frontend_is_killed(self):
            with tempfile.TemporaryDirectory() as tmp:
                state=Path(tmp);os.chmod(state,0o700)
                (state/"trusted").mkdir();(state/"submissions").mkdir()
                marker, ready = state/"escaped", state/"worker-started"
                command=[sys.executable,"-c", "import pathlib,time;pathlib.Path("+repr(str(ready))+").write_text('ready');time.sleep(2);pathlib.Path("+repr(str(marker))+").write_text('escaped')"]
                config={"deadline_utc":time.time()+0.7,"python":sys.executable,"playwright_browsers_path":"/tmp/unused"}
                script=("import runpy;from pathlib import Path;m=runpy.run_path("+repr(str(Path(__file__).resolve()))+");\n"
                        "with m['locked'](Path("+repr(str(state))+")):\n"
                        " m['run_phase'](Path("+repr(str(state))+"),"+repr(config)+",phase='work',submission='test',command="+repr(command)+",folder=Path("+repr(str(state/"phase"))+"))\n")
                frontend=subprocess.Popen([sys.executable,"-c",script],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                try:
                    until=time.monotonic()+3
                    while not ready.exists() and time.monotonic()<until:
                        time.sleep(0.01)
                    self.assertTrue(ready.exists(),"bounded worker never launched")
                    frontend.kill();frontend.wait(timeout=2)
                    with self.assertRaisesRegex(OwnerError,"trajectory_is_busy"):
                        with locked(state):pass
                    until=time.monotonic()+3
                    while not (state/"phase/supervisor.json").exists() and time.monotonic()<until:
                        time.sleep(0.01)
                    result=strict_json((state/"phase/supervisor.json").read_text())
                    self.assertEqual(result["status"],"deadline_exhausted")
                    self.assertFalse(marker.exists())
                    # Wait for the supervisor's fsynced completion event and exit.
                    until=time.monotonic()+2
                    while True:
                        try:
                            with locked(state):pass
                            break
                        except OwnerError:
                            if time.monotonic()>=until:raise
                            time.sleep(0.01)
                    self.assertTrue(any(r.get('event')=='phase_finished' for r in read_events(state)))
                finally:
                    if frontend.poll() is None:frontend.kill();frontend.wait(timeout=2)

        def test_complete_owner_pipeline_passes_work_envelope_and_fixed_private_paths(self):
            # A subprocess fixture validates orchestration only. It neither
            # imports a model nor claims these fake values as a task baseline.
            stub = '''import argparse,json,hashlib
from pathlib import Path
def canon(x):return json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'))
p=argparse.ArgumentParser();p.add_argument('command')
for name in ('model','data','prompts','output','records','ledger'):p.add_argument('--'+name)
a=p.parse_args();value=json.loads(Path(a.prompts).read_text());out=Path(a.output)
if a.command=='work':
 out.mkdir();log=[{'version':i,'test_only':True} for i in range(4)]
 retained=dict(value,policy=value['policy']+' test-revision')
 artifact={'status':'work_complete','completed_rounds':3,'initial':value,'prompts':retained,
  'revision_log':log,'revision_log_sha256':hashlib.sha256(canon(log).encode()).hexdigest(),
  'accepted_version':3,'initial_validation':{'score':0},'final_validation':{'score':0},
  'work_usage':{'calls':0,'test_only':True}}
 (out/'candidate.json').write_text(canon(artifact));(out/'revisions.json').write_text(canon(log))
elif a.command=='judge':
 assert value['completed_rounds']==3 and len(value['revision_log'])==4
 assert Path(a.records)==Path(a.data)/'private/hidden.jsonl'
 assert len(Path(a.records).read_text().splitlines())==96
 with Path(a.ledger).open('a') as f:f.write(canon({'event':'started'})+'\\n')
 out.write_text(canon({'status':'complete','completed':96,'successful':0,'score':0,
  'usage':{'calls':0,'test_only':True},'model':{'calls':['PRIVATE-TRACE']}}))
else:raise AssertionError('unexpected command')
'''
            with tempfile.TemporaryDirectory() as tmp:
                folder=Path(tmp);task=folder/"task";dataset=folder/"dataset";model=folder/"model"
                for name in ('jevbench','configs','assets'):(task/name).mkdir(parents=True)
                (task/'jevbench/__init__.py').write_text('')
                (task/'jevbench/__main__.py').write_text(stub)
                prompts={'policy':'test-public-initial','evolver':'test-fixed-evolver','memory':''}
                write_json(task/'baseline_prompts.json',dict(prompts,policy='test-baseline'))
                model.mkdir()
                for split,count in (('practice',8),('validation',2),('hidden',6)):
                    dest=dataset/('private' if split=='hidden' else 'public');dest.mkdir(parents=True,exist_ok=True)
                    rows=[{'id':f'{split}-{family}-{tier}-{i}','family':family,'tier':tier,'split':split}
                          for family in FAMILIES for tier in ('hard','harder') for i in range(count//2)]
                    (dest/(split+'.jsonl')).write_text(''.join(canonical(row)+'\n' for row in rows))
                state=folder/'state'
                initialize(argparse.Namespace(state=str(state),task_root=str(task),data=str(dataset),model=str(model),
                                               python=sys.executable,playwright_browsers='/tmp/test-unused'))
                result=submit(state,prompts)
                self.assertEqual(result['judge_calls_used'],1)
                self.assertEqual(result['work']['completed_rounds'],3)
                self.assertEqual(result['retained_prompts']['policy'],'test-public-initial test-revision')
                self.assertNotIn('PRIVATE-TRACE',canonical(result))
                events=read_events(state)
                self.assertEqual([r['phase'] for r in events if r['event']=='phase_started'],['work','judge'])
                self.assertEqual([r['status'] for r in events if r['event']=='phase_finished'],['complete','complete'])
                self.assertEqual(status(state)['judge_calls_used'],1)
                self.assertTrue((state/'trusted/baseline_prompts.json').is_file())

    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ControllerTests))
    print(canonical({"mode":"controller_cpu_tests_not_model_inference", "tests":result.testsRun,
                     "passed":result.wasSuccessful(), "model_calls":0}))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except OwnerError as exc:
        print(canonical({"status":"unscored", "reason":str(exc)}), file=sys.stderr)
        sys.exit(1)
    except BaseException as exc:
        if isinstance(exc, SystemExit):
            raise
        # Tracebacks/paths/model errors can contain private evidence.
        print(canonical({"status":"unscored", "reason":"task_owner_controller_failure",
                         "error_type":type(exc).__name__}), file=sys.stderr)
        sys.exit(1)
