import copy
import hashlib
import json
from pathlib import Path

import pytest

from jevbench import visual_tasks as vt


@pytest.mark.parametrize("family", vt.D_FAMILIES + vt.X_FAMILIES)
@pytest.mark.parametrize("tier", ("hard", "harder"))
def test_documents_reference_and_unique_instance_content(family, tier):
    hashes = set()
    for seed in range(8):
        record = vt.generate(family, seed, tier)
        assert vt.certify(record)["success"]
        env = vt.Env(record)
        assert env.render().size == (768, 768)
        hashes.add(vt._digest(record["data"]["facts"]))
        for page in range(1, len(record["data"]["pages"]) + 1):
            assert env.step({"tool": "open_document", "page": page})["valid"]
            assert env.render().size == (768, 768)
    assert len(hashes) == 8


def test_gold_money_rounding_and_exclusion_independent_example():
    facts = {"currency":"USD", "project":"ORION", "lines":[
        {"id":"L1","invoice":"I1","project":"ORION","approved":True,"qty":3,"unit_cents":101,"discount_pct":10,"tax_pct":5},
        {"id":"L2","invoice":"I2","project":"ORION","approved":False,"qty":99,"unit_cents":999,"discount_pct":0,"tax_pct":10},
        {"id":"L3","invoice":"I2","project":"LYRA","approved":True,"qty":99,"unit_cents":999,"discount_pct":0,"tax_pct":10},
    ]}
    # 303 * 90% = 272.7 -> 273; 273 * 5% = 13.65 -> 14; 287 cents.
    assert vt._gold("invoice",facts) == {"project":"ORION","invoice_ids":["I1"],"line_ids":["L1"],"amount_cents":287,"currency":"USD"}


def test_gold_contract_weekend_unsigned_and_future_rules():
    facts={"contract_id":"C1","payee":"V1","accepted":"2028-01-07","as_of":"2028-01-08","notice_before":2,"amendments":[
        {"id":"A1","signed":True,"effective":"2028-01-01","days":2,"amount":100},
        {"id":"A2","signed":False,"effective":"2028-01-08","days":1,"amount":200},
        {"id":"A3","signed":True,"effective":"2028-01-09","days":1,"amount":300}]}
    # Friday acceptance -> Monday day 1, Tuesday day 2. Notice uses calendar days.
    assert vt._gold("contract",facts) == {"contract_id":"C1","payment_date":"2028-01-11","notice_date":"2028-01-09","amount_cents":100,"payee":"V1"}


def test_gold_chart_audit_net_and_tie_break():
    facts={"period":"2028-01","critical_gap":80,"values":[
        {"region":"Z","audited":False,"sales":1,"returns":0,"target":999},
        {"region":"B","audited":True,"sales":100,"returns":10,"target":190},
        {"region":"A","audited":True,"sales":200,"returns":20,"target":280}]}
    assert vt._gold("chart",facts) == {"period":"2028-01","region":"A","net_units":180,"gap_units":100,"priority":"critical"}


def test_answers_vary_across_instances_not_constant_labels():
    for family,key in (("d_chart","region"),("d_contract","amount_cents"),("d_version","warehouse"),("d_invoice","amount_cents")):
        answers={vt.generate(family,s,"hard")["data"]["answer"][key] for s in range(32)}
        assert len(answers)>=3


@pytest.mark.parametrize("family",vt.D_FAMILIES)
def test_document_wrong_final_answer_and_type_are_terminal_failures(family):
    record=vt.generate(family,127,"harder")
    for transform in (lambda a: {}, lambda a: {**a,"extra":"field"}, lambda a: {**a,next(k for k,v in a.items() if type(v) is int): True}):
        env=vt.Env(record)
        result=env.step({"tool":"finish","answer":transform(copy.deepcopy(record["data"]["answer"]))})
        assert result["terminal"] and not result["success"]
        assert not env.step({"tool":"finish","answer":record["data"]["answer"]})["valid"]


@pytest.mark.parametrize("family",vt.X_FAMILIES)
def test_workflow_requires_actual_app_state_and_all_fields(family):
    record=vt.generate(family,127,"harder")
    env=vt.Env(record)
    assert not env.step({"tool":"finish","answer":record["data"]["answer"]})["success"]
    env=vt.Env(record)
    actions=record["reference_actions"]
    # Skip filling one field, retaining all other correct fields: no partial credit.
    skipped=False
    for action in actions:
        if action["tool"]=="type" and not skipped:
            skipped=True
            continue
        result=env.step(action)
    assert result["terminal"] and not result["success"]


@pytest.mark.parametrize("family",vt.D_FAMILIES+vt.X_FAMILIES)
def test_canonical_json_roundtrip_does_not_change_form_layout_or_reference(family):
    record=vt.generate(family,317,"harder")
    reloaded=json.loads(json.dumps(record,sort_keys=True))
    reloaded.update(id="test-roundtrip",split="practice")
    assert vt.certify(reloaded)["success"]


def test_invalid_action_recoverable_and_gold_tampering_rejected():
    record=vt.generate("d_invoice",42,"hard")
    env=vt.Env(record)
    assert not env.step({"tool":"open_document","page":999})["valid"]
    assert not env.done
    assert env.step({"tool":"finish","answer":record["data"]["answer"]})["success"]
    record["data"]["answer"]["amount_cents"]+=1
    with pytest.raises(ValueError):
        vt.certify(record)


def test_all_rendered_document_lines_fit_without_truncation():
    for family in vt.D_FAMILIES:
        for tier in ("hard","harder"):
            for seed in range(8):
                for page in vt.generate(family,seed,tier)["data"]["pages"]:
                    assert vt._font(25).getlength(page["title"]) <= 698
                    assert len(page["lines"]) <= 15
                    for line in page["lines"]:
                        assert vt._font(17).getlength(line) <= 698, line


def test_vendored_native_assets_match_unmodified_upstream_manifest():
    manifest=json.loads((vt.VENDOR/"SOURCE_MANIFEST.json").read_text())
    assert manifest["revision"]==vt.MINIWOB_PIN
    for name, info in manifest["files"].items():
        value=(vt.VENDOR/name).read_bytes()
        assert hashlib.sha256(value).hexdigest()==info["sha256"]
        assert len(value)==info["bytes"]


@pytest.mark.parametrize("family",vt.U_FAMILIES)
@pytest.mark.parametrize("tier",("hard","harder"))
def test_native_miniwob_browser_reference_and_replay(family,tier):
    pytest.importorskip("browsergym.miniwob")
    record=vt.generate(family,71,tier)
    assert record["certificate"]["raw_reward"]==1
    assert vt.certify(record)["success"]
    env=vt.Env(record)
    try:
        assert env.render().size==(768,768)
        # Pixel reproducibility is tested on this same browser/OS only; it is not
        # a portable semantic identity requirement for the submitted fixtures.
        assert hashlib.sha256(env.render().tobytes()).hexdigest()==record["certificate"]["initial_pixels_sha256"]
        assert env.observable_fingerprint()==record["certificate"]["observable_sha256"]
        if family=="u_read_table":
            env.page.evaluate("document.querySelector('#tab td').textContent = 'CHANGED VISIBLE LABEL'")
            assert env.observable_fingerprint()!=record["certificate"]["observable_sha256"]
        assert not env.step({"tool":"finish"})["success"]
    finally:
        env.close()


def test_native_partial_positive_reward_is_not_full_success():
    pytest.importorskip("browsergym.miniwob")
    record=vt.generate("u_multi_layouts",71,"hard")
    env=vt.Env(record)
    try:
        # Task-owner adversarial verifier test, not an actor-visible operation.
        env.page.evaluate("core.endEpisode(0.5, false)")
        assert env.task.validate(env.page, [])[0] == 1.0
        result=env._check()
        assert result["terminal"] and not result["success"]
    finally:
        env.close()
