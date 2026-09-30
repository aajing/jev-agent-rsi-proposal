"""CPU protocol tests with explicit fake environments/backends.

These tests are not JEV inference, baseline scores, or difficulty calibration.
They exercise the runner's budgets, isolation boundary, and fixed revision loop.
"""
from __future__ import annotations

import copy
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from jevbench import cli, contract, data, evolution, runtime
from jevbench import model
from jevbench.contract import BudgetExceeded, ContractError, FAMILIES, GROUPS, Meter, parse_decision, score


PROMPTS = {"policy": "initial-policy", "evolver": "fixed-evolver", "memory": "static-memory"}


def output(actions, scratchpad=""):
    return json.dumps({"actions": actions, "scratchpad": scratchpad})


def press(key="right"):
    return {"tool": "press", "key": key}


class FakeEnv:
    """A deterministic test environment; it has no benchmark task semantics."""
    goal = "Reach the test terminal state."

    def __init__(self, *, win_on=None, invalid_on=None):
        self.win_on, self.invalid_on = win_on, invalid_on
        self.done = self.success = False
        self.steps = []
        self.renders = 0
        self.closed = False

    def step(self, action):
        self.steps.append(action)
        if len(self.steps) == self.invalid_on:
            return dict(valid=False, terminal=False, success=False, reason="blocked")
        self.done = self.success = len(self.steps) == self.win_on
        return dict(valid=True, terminal=self.done, success=self.success, reason="complete" if self.done else "moved")

    def render(self):
        self.renders += 1
        return Image.new("RGB", (768, 768), "white")

    def close(self):
        self.closed = True


class FakeBackend:
    """Metered fixed responses used only to test protocol bookkeeping."""
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    @staticmethod
    def token_count(text):
        return len(text.split())

    def generate(self, request, *, max_output, meter):
        self.requests.append(copy.copy(request))
        meter.begin(100, max_output)
        result = next(self.responses)
        meter.end(self.token_count(result))
        return result

    def evidence(self):
        return {"mode": "test_fake_backend_not_a_model", "calls": len(self.requests)}


def record(family="sokoban", number=0):
    return {"id": f"test-{family}-{number}", "family": family, "tier": "hard", "goal": FakeEnv.goal,
            "data": {"gold": "SECRET-GOLD-NEVER-IN-REQUEST"},
            "certificate": {"oracle": "SECRET-CERTIFICATE"},
            "reference_actions": [{"tool": "SECRET-REFERENCE"}]}


class ProtocolTests(unittest.TestCase):
    def test_complete_batch_validation_happens_before_any_step(self):
        env = FakeEnv()
        episode = runtime.Episode(record(), env)
        result = episode.apply(output([press(), {"tool": "solve"}]), len)
        self.assertEqual(result["attempted"], 0)
        self.assertEqual((episode.calls, episode.atoms, env.steps), (1, 0, []))

    def test_overlong_batch_costs_call_but_no_atoms(self):
        episode = runtime.Episode(record(), FakeEnv())
        episode.apply(output([press()] * 5), len)
        self.assertEqual((episode.calls, episode.atoms), (1, 0))

    def test_unhashable_key_is_normal_format_failure(self):
        for key in ([], {}, {"up": True}):
            episode = runtime.Episode(record(), FakeEnv())
            result = episode.apply(output([press(key)]), len)
            self.assertEqual(result["reason"], "invalid_format")
            self.assertEqual((episode.calls, episode.atoms), (1, 0))

    def test_strict_json_rejects_duplicate_keys_nonfinite_and_boolean_coordinates(self):
        values = ['{"actions":[],"actions":[]}',
                  '{"actions":[{"tool":"click","x":NaN,"y":2}]}',
                  '{"actions":[{"tool":"click","x":true,"y":2}]}']
        for value in values:
            with self.assertRaises(ContractError):
                parse_decision(value, "fifteen_puzzle", len)

    def test_game_helpers_must_be_alone_and_non_games_cannot_batch(self):
        with self.assertRaises(ContractError):
            parse_decision(output([press(), {"tool": "finish"}]), "sokoban", len)
        with self.assertRaises(ContractError):
            parse_decision(output([press(), press()]), "u_book_flight", len)

    def test_illegal_action_stops_batch_but_episode_can_recover(self):
        env = FakeEnv(win_on=3, invalid_on=2)
        episode = runtime.Episode(record(), env)
        result = episode.apply(output([press()] * 4), len)
        self.assertEqual((result["attempted"], len(env.steps)), (2, 2))
        self.assertFalse(episode.done)
        episode.apply(output([press()]), len)
        self.assertTrue(episode.success)

    def test_four_action_plan_gets_no_intermediate_observation(self):
        env = FakeEnv()
        episode = runtime.Episode(record(), env)
        episode.request(PROMPTS)
        renders_before = env.renders
        episode.apply(output([press()] * 4), len)
        self.assertEqual(len(env.steps), 4)
        self.assertEqual(env.renders, renders_before)

    def test_win_stops_unattempted_suffix(self):
        env = FakeEnv(win_on=2)
        episode = runtime.Episode(record(), env)
        result = episode.apply(output([press()] * 4), len)
        self.assertEqual((result["attempted"], episode.atoms, len(env.steps)), (2, 2, 2))
        self.assertTrue(result["success"])

    def test_last_allowed_atom_can_win(self):
        env = FakeEnv(win_on=5)
        episode = runtime.Episode(record(), env)
        episode.max_atoms, episode.max_calls = 5, 2
        episode.apply(output([press()] * 4), len)
        result = episode.apply(output([press()] * 4), len)
        self.assertTrue(result["success"])
        self.assertEqual((episode.atoms, episode.calls, len(env.steps)), (5, 2, 5))

    def test_atomic_budget_checked_before_every_attempt(self):
        env = FakeEnv()
        episode = runtime.Episode(record(), env)
        episode.max_atoms = 2
        result = episode.apply(output([press()] * 4), len)
        self.assertEqual((result["attempted"], len(env.steps)), (2, 2))
        self.assertTrue(episode.done)
        self.assertFalse(episode.success)

    def test_invalid_formats_exhaust_decision_budget(self):
        episode = runtime.Episode(record(), FakeEnv())
        for _ in range(32):
            episode.apply("not JSON", len)
        self.assertEqual((episode.calls, episode.atoms), (32, 0))
        self.assertTrue(episode.done)
        with self.assertRaises(ContractError):
            episode.apply(output([press()]), len)

    def test_crop_costs_atom_and_uses_only_current_screenshot(self):
        env = FakeEnv()
        episode = runtime.Episode(record(), env)
        episode.apply(output([dict(tool="crop", x=20, y=30, width=100, height=120)]), len)
        request = episode.request(PROMPTS)
        self.assertEqual((episode.calls, episode.atoms), (1, 1))
        self.assertEqual(len(request["images"]), 2)
        self.assertEqual(request["images"][1].size, (100, 120))
        self.assertFalse(env.steps)

    def test_request_excludes_record_answers_certificates_and_reference(self):
        episode = runtime.Episode(record(), FakeEnv())
        request = episode.request(PROMPTS)
        text = request["system"] + request["user"]
        self.assertNotIn("SECRET-", text)
        self.assertEqual(set(request), {"system", "user", "images"})

    def test_scratchpad_and_action_history_reset_each_episode(self):
        first = runtime.Episode(record(), FakeEnv())
        first.apply(output([press()], scratchpad="only-this-episode"), len)
        second = runtime.Episode(record(number=1), FakeEnv())
        self.assertEqual(second.scratchpad, "")
        self.assertEqual(second.history, [])
        self.assertNotIn("only-this-episode", second.request(PROMPTS)["user"])

    def test_run_episode_meter_counts_bad_outputs_and_closes_environment(self):
        env = FakeEnv(win_on=1)
        backend = FakeBackend(["invalid", output([press()])])
        meter = Meter()
        with patch.object(runtime, "environment", return_value=env):
            result = runtime.run_episode(record(), PROMPTS, backend, meter)
        self.assertEqual((result["calls"], result["atoms"], meter.usage.calls), (2, 1, 2))
        self.assertTrue(result["success"] and env.closed)

    def test_episode_closes_on_global_budget_failure(self):
        env = FakeEnv()
        with patch.object(runtime, "environment", return_value=env):
            with self.assertRaises(BudgetExceeded):
                runtime.run_episode(record(), PROMPTS, FakeBackend(["invalid"]), Meter(calls=0))
        self.assertTrue(env.closed)


class BudgetAndScoringTests(unittest.TestCase):
    def test_meter_blocks_before_call_when_any_reserved_budget_is_exceeded(self):
        for meter in (Meter(calls=0), Meter(input_tokens=9), Meter(output_tokens=255)):
            with self.assertRaises(BudgetExceeded):
                meter.begin(10, 256)
            self.assertEqual(meter.usage.calls, 0)

    def test_meter_rejects_unpaired_or_oversized_completion(self):
        meter = Meter(output_tokens=256)
        with self.assertRaises(ContractError):
            meter.end(1)
        meter.begin(1, 256)
        with self.assertRaises(ContractError):
            meter.end(257)

    def test_global_clock_failure_never_produces_score(self):
        with patch.object(contract.time, "monotonic", side_effect=[0.0, 3.0]):
            meter = Meter(seconds=2)
            with self.assertRaises(BudgetExceeded):
                meter.begin(10, 256)

    def test_full_score_and_partial_score_are_exact(self):
        rows = [{"id": f"{family}-{i}", "family": family, "success": True}
                for family in FAMILIES for i in range(6)]
        self.assertEqual(score(rows, 6)["score"], 100.0)
        for row in rows[:24]:
            row["success"] = False
        self.assertEqual(score(rows, 6)["score"], 75.0)
        with self.assertRaises(ContractError):
            score(rows[:-1], 6)
        rows[-1]["id"] = rows[0]["id"]
        with self.assertRaises(ContractError):
            score(rows, 6)

    def test_family_quota_is_checked_before_any_model_call(self):
        invalid = [record("sokoban", i) for i in range(32)]
        with patch.object(runtime, "run_episode") as run:
            with self.assertRaises(ContractError):
                runtime.evaluate(invalid, PROMPTS, FakeBackend([]), Meter(), per_family=2)
            run.assert_not_called()


class EvolutionTests(unittest.TestCase):
    def test_work_artifact_rejects_final_text_edits_and_broken_revision_chain(self):
        revisions = [json.dumps({"policy": p, "memory": "new"}) for p in ("worse", "tie", "better")]
        artifact, *_ = self._run(revisions, {"initial-policy": 50, "worse": 25, "tie": 50, "better": 75})
        self.assertEqual(evolution.validate_work_artifact(artifact, FakeBackend.token_count), artifact["prompts"])
        bad = copy.deepcopy(artifact)
        bad["prompts"]["policy"] = "edited after Work"
        with self.assertRaises(ContractError):
            evolution.validate_work_artifact(bad, FakeBackend.token_count)
        bad = copy.deepcopy(artifact)
        bad["revision_log"][1]["accepted"] = True
        bad["revision_log_sha256"] = runtime.digest(bad["revision_log"])
        with self.assertRaises(ContractError):
            evolution.validate_work_artifact(bad, FakeBackend.token_count)
        bad["revision_log"][1] = []
        with self.assertRaises(ContractError):
            evolution.validate_work_artifact(bad, FakeBackend.token_count)

    def test_plain_final_prompts_require_the_exact_canonical_b0(self):
        self.assertEqual(evolution.validate_work_artifact(PROMPTS, FakeBackend.token_count, baseline=PROMPTS), PROMPTS)
        with self.assertRaises(ContractError):
            evolution.validate_work_artifact(dict(PROMPTS, policy="different"), FakeBackend.token_count, baseline=PROMPTS)

    def _run(self, revisions, scores):
        practice = [record(family, i) for family in FAMILIES for i in range(8)]
        validation = [record(family, 100 + i) for family in FAMILIES for i in range(2)]
        backend, meter = FakeBackend(revisions), Meter()
        evaluations, panels = [], []

        def fake_evaluate(records, prompts, backend, meter, *, per_family, trace_dir=None):
            self.assertEqual((len(records), per_family), (32, 2))
            evaluations.append(dict(prompts))
            return {"score": scores[prompts["policy"]]}, []

        def fake_episode(record, prompts, backend, meter, *, trace_dir):
            panels.append((record["family"], dict(prompts)))
            folder = Path(trace_dir) / record["id"]
            folder.mkdir(parents=True)
            for name in ("first.png", "last.png"):
                Image.new("RGB", (8, 8), "white").save(folder / name)
            (folder / "trace.json").write_text(json.dumps({"trace": [{"output": "test-only"}]}))
            return {"id": record["id"], "family": record["family"], "success": False, "reason": "test-failure"}

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(evolution, "evaluate", side_effect=fake_evaluate), patch.object(evolution, "run_episode", side_effect=fake_episode):
                artifact = evolution.run_work(PROMPTS, practice, validation, backend, meter, Path(tmp) / "work")
            log = json.loads((Path(tmp) / "work/revisions.json").read_text())
        return artifact, log, evaluations, panels, backend

    def test_three_rounds_reject_regression_and_tie_then_accept_strict_improvement(self):
        revisions = [json.dumps({"policy": p, "memory": "new"}) for p in ("worse", "tie", "better")]
        artifact, log, evaluations, panels, backend = self._run(revisions,
            {"initial-policy": 50, "worse": 40, "tie": 50, "better": 51})
        self.assertEqual(artifact["completed_rounds"], 3)
        self.assertEqual(artifact["accepted_version"], 3)
        self.assertEqual(artifact["prompts"], dict(policy="better", memory="new", evolver="fixed-evolver"))
        self.assertEqual([r["accepted"] for r in log], [True, False, False, True])
        self.assertEqual(len(evaluations), 4)
        self.assertEqual(len(backend.requests), 3)
        self.assertEqual(len(panels), 24)
        self.assertTrue(all(p[1]["policy"] == "initial-policy" for p in panels))
        for offset in (0, 8, 16):
            self.assertEqual({g: sum(GROUPS[f] == g for f, _ in panels[offset:offset+8]) for g in "UDXG"},
                             {g: 2 for g in "UDXG"})

    def test_invalid_revision_costs_round_without_retry_or_changing_evolver(self):
        artifact, log, evaluations, panels, backend = self._run(
            ['{"policy":"bad","memory":"","evolver":"changed"}',
             '{"policy":"tie","memory":""}', '{"policy":"tie","memory":""}'],
            {"initial-policy": 50, "tie": 50})
        self.assertEqual(len(backend.requests), 3)
        self.assertEqual(len(evaluations), 3)
        self.assertEqual(artifact["prompts"], PROMPTS)
        self.assertEqual(log[1]["reason"], "invalid_revision")


class HiddenPrivacyTests(unittest.TestCase):
    def test_public_manifest_contains_no_hidden_per_episode_certificate(self):
        class FakeAuthor:
            @staticmethod
            def generate(family, seed, tier):
                return {"family": family, "seed": seed, "tier": tier, "goal": "test", "data": {"seed": seed}}
            @staticmethod
            def certify(record):
                return True
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(data, "FAMILIES", ("sokoban",)), patch.object(data, "COUNTS", {"practice": 2, "hidden": 2}), \
                 patch.object(data, "module", return_value=FakeAuthor), \
                 patch.object(data, "replay_reference", return_value={"calls": 20, "atoms": 78, "success": True}):
                data.build_data(tmp)
            public = json.loads((Path(tmp) / "manifest.json").read_text())
            self.assertNotIn("records", public["splits"]["hidden"], "Hidden solution lengths and record hashes must stay owner-private")

    def test_judge_never_emits_per_call_model_evidence_or_episode_results(self):
        evidence_modes = []
        class JudgeBackend:
            def __init__(self, unused_path):
                pass
            token_count = staticmethod(FakeBackend.token_count)
            def evidence(self, *, aggregate_only=False):
                evidence_modes.append(aggregate_only)
                return {"call_count": 96, **({} if aggregate_only else {"calls": ["SECRET-PER-CALL-DETAIL"]})}
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            prompt_path, records_path, result_path = folder / "prompts.json", folder / "hidden.jsonl", folder / "result.json"
            source = json.loads((Path(__file__).resolve().parents[1] / "baseline_prompts.json").read_text())
            baseline = {k: source[k] for k in ("policy", "evolver", "memory")}
            prompt_path.write_text(json.dumps(baseline))
            records_path.write_text("".join(json.dumps(record(f, i)) + "\n" for f in FAMILIES for i in range(6)))
            summary = {"score": 100, "completed": 96, "successful": 96}
            private_results = [{"id": "SECRET-PER-EPISODE", "success": True}]
            console = io.StringIO()
            with patch.object(model, "TransformersBackend", JudgeBackend), \
                 patch.object(cli, "evaluate", return_value=(summary, private_results)) as evaluate, \
                 contextlib.redirect_stdout(console):
                cli.main(["judge", "--model", "unused", "--prompts", str(prompt_path),
                          "--records", str(records_path), "--ledger", str(folder / "owner_ledger.jsonl"),
                          "--output", str(result_path)])
            self.assertEqual(evidence_modes, [True])
            self.assertNotIn("SECRET-", result_path.read_text() + console.getvalue())
            self.assertNotIn("trace_dir", evaluate.call_args.kwargs)
            self.assertEqual(evaluate.call_args.kwargs["per_family"], 6)


class FrozenModelAssetTests(unittest.TestCase):
    def _fixture(self, folder):
        path = folder / "snapshot"
        path.mkdir()
        payloads = {"model.safetensors": b"test-only-fake-weight-bytes", "config.json": b'{"test_only":true}'}
        lock = {"repo": model.MODEL_REPO, "revision": model.MODEL_REVISION, "files": {}}
        for name, payload in payloads.items():
            (path / name).write_bytes(payload)
            info = {"bytes": len(payload)}
            if name.endswith("safetensors"):
                info["sha256"] = hashlib.sha256(payload).hexdigest()
            else:
                info["git_blob_sha1"] = hashlib.sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest()
            lock["files"][name] = info
        lock_path = folder / "trusted_lock.json"
        lock_path.write_text(json.dumps(lock))
        return path, lock_path

    def test_sha256_and_git_blob_assets_both_verify_without_gpu(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, lock = self._fixture(Path(tmp))
            result = model.verify_model_files(path, lock)
            self.assertEqual(result["verified_files"], 2)

    def test_same_length_weight_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, lock = self._fixture(Path(tmp))
            original = (path / "model.safetensors").read_bytes()
            (path / "model.safetensors").write_bytes(b"x" * len(original))
            with self.assertRaises(ContractError):
                model.verify_model_files(path, lock)

    def test_extra_adapter_and_missing_processor_asset_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, lock = self._fixture(Path(tmp))
            (path / "adapter.safetensors").write_bytes(b"unauthorized")
            with self.assertRaises(ContractError):
                model.verify_model_files(path, lock)
            (path / "adapter.safetensors").unlink()
            (path / "config.json").unlink()
            with self.assertRaises(ContractError):
                model.verify_model_files(path, lock)


if __name__ == "__main__":
    unittest.main()
