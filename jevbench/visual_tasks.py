"""Frozen screenshot-only document tasks and native MiniWoB adapters.

``record`` is task-owner state, never an actor observation.  In particular its
gold answer and reference actions must not be serialized into model prompts.
The actor receives only ``goal``, ``render()`` and public ``step`` results.
"""
from __future__ import annotations

import copy
import atexit
import hashlib
import io
import os
import json
import random
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

U_FAMILIES = ("u_book_flight", "u_multi_layouts", "u_form_sequence", "u_read_table")
D_FAMILIES = ("d_invoice", "d_contract", "d_chart", "d_version")
X_FAMILIES = ("x_expense", "x_calendar", "x_alert", "x_fulfillment")
FAMILIES = U_FAMILIES + D_FAMILIES + X_FAMILIES
MINIWOB_PIN = "7fd85d71a4b60325c6585396ec4f48377d049838"
BROWSERGYM_PIN = "c05d7f38f4f788d6e4ee960512c3d5c8aabc6e42"
MINIWOB_NAMES = dict(zip(U_FAMILIES, ("book-flight-nodelay", "multi-layouts", "form-sequence-3", "read-table-2")))
ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "assets" / "vendor" / "miniwob"
WIDTH = HEIGHT = 768


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _round(n: int, d: int) -> int:
    return (2 * n + d) // (2 * d)


def _business_days(start: date, n: int) -> date:
    while n:
        start += timedelta(days=1)
        if start.weekday() < 5:
            n -= 1
    return start


def _kind(family: str) -> str:
    return {"x_expense": "invoice", "x_calendar": "contract", "x_alert": "chart", "x_fulfillment": "version"}.get(family, family[2:])


def _make_facts(kind: str, seed: int, tier: str) -> dict:
    r = random.Random(f"visual-v1:{kind}:{seed}:{tier}")
    ident = f"{r.randrange(100000, 999999)}"
    base = date(2028, 1, 1) + timedelta(days=r.randrange(500))
    if kind == "invoice":
        lines = []
        for i in range(6 if tier == "hard" else 8):
            lines.append({"id": f"L{i+1}", "invoice": f"INV-{ident}-{1+i%2}",
                          "project": "ORION" if i % 3 else "LYRA", "approved": i % 4 != 0,
                          "qty": r.randrange(2, 10), "unit_cents": r.randrange(101, 6000),
                          "discount_pct": r.choice((0, 5, 10, 15)), "tax_pct": r.choice((5, 10))})
        # Vary eligibility and line order; hidden answers cannot be a fixed mask.
        for line in lines:
            line["project"] = r.choice(("ORION", "LYRA"))
            line["approved"] = r.choice((True, True, False))
        lines[0].update(project="ORION", approved=True)
        lines[1].update(project="LYRA", approved=True)
        r.shuffle(lines)
        return {"case": ident, "currency": "USD", "project": "ORION", "lines": lines}
    if kind == "contract":
        amendments = [
            {"id": "A1", "signed": True, "effective": (base - timedelta(days=2)).isoformat(), "days": 5, "amount": r.randrange(50000, 100000)},
            {"id": "A2", "signed": True, "effective": (base + timedelta(days=2)).isoformat(), "days": 7, "amount": r.randrange(100000, 150000)},
            {"id": "A3", "signed": False, "effective": (base + timedelta(days=4)).isoformat(), "days": 2, "amount": r.randrange(150000, 200000)},
        ]
        if tier == "harder":
            amendments.append({"id": "A4", "signed": True, "effective": (base + timedelta(days=30)).isoformat(), "days": 1, "amount": r.randrange(200000, 250000)})
        ids = [a["id"] for a in amendments]
        r.shuffle(ids)
        for a, aid in zip(amendments, ids):
            a["id"], a["days"] = aid, r.randrange(3, 11)
        r.shuffle(amendments)
        return {"contract_id": f"C-{ident}", "payee": f"Vendor-{r.randrange(20,99)}", "as_of": (base + timedelta(days=10)).isoformat(),
                "accepted": (base + timedelta(days=5)).isoformat(), "notice_before": 3 if tier == "hard" else 5,
                "amendments": amendments, "default_days": 10, "default_amount": 25000}
    if kind == "chart":
        regions = ["Amber", "Birch", "Cedar", "Delta"] + (["Elm", "Fir"] if tier == "harder" else [])
        values = [{"region": name, "sales": r.randrange(180, 600), "returns": r.randrange(10, 70),
                   "target": r.randrange(200, 500), "audited": i != 1} for i, name in enumerate(regions)]
        guaranteed = r.choice([v for v in values if v["audited"]])
        guaranteed["target"] = guaranteed["sales"]-guaranteed["returns"]+r.randrange(80,260)
        r.shuffle(values)
        return {"period": base.strftime("%Y-%m"), "values": values, "critical_gap": r.choice((100,150,200,250))}
    if kind == "version":
        revisions = [
            {"id": "R1", "status": "issued", "effective": (base - timedelta(days=10)).isoformat(), "sku": f"SKU-{r.randrange(100,999)}", "quantity": r.randrange(10,30)},
            {"id": "R2", "status": "issued", "effective": (base - timedelta(days=1)).isoformat(), "sku": f"SKU-{r.randrange(100,999)}", "quantity": r.randrange(30,50)},
            {"id": "R3", "status": "draft", "effective": base.isoformat(), "sku": f"SKU-{r.randrange(100,999)}", "quantity": 99},
        ]
        if tier == "harder":
            revisions.append({"id": "R4", "status": "issued", "effective": (base + timedelta(days=4)).isoformat(), "sku": f"SKU-{r.randrange(100,999)}", "quantity": 75})
        ids = [v["id"] for v in revisions]
        r.shuffle(ids)
        for v, vid in zip(revisions,ids):
            v["id"] = vid
        r.shuffle(revisions)
        warehouses = [{"name": name, "stock": r.randrange(60, 120), "reserved": r.randrange(5, 35)} for name in ("North","South","West")]
        # Ensure a feasible complete shipment independent of candidate performance.
        warehouses[r.randrange(3)]["stock"] = 125
        return {"order_id": f"O-{ident}", "as_of": base.isoformat(), "revisions": revisions,
                "warehouses": warehouses,
                "shipping_business_days": 2 if tier == "hard" else 4}
    raise ValueError(kind)


def _gold(kind: str, f: dict) -> dict:
    """Derive answers from facts; stored certificates are never trusted."""
    if kind == "invoice":
        selected = [x for x in f["lines"] if x["project"] == f["project"] and x["approved"]]
        total = 0
        for x in selected:
            net = _round(x["qty"] * x["unit_cents"] * (100-x["discount_pct"]), 100)
            total += net + _round(net * x["tax_pct"], 100)
        return {"project": f["project"], "invoice_ids": sorted({x["invoice"] for x in selected}),
                "line_ids": sorted(x["id"] for x in selected), "amount_cents": total, "currency": f["currency"]}
    if kind == "contract":
        active = [a for a in f["amendments"] if a["signed"] and a["effective"] <= f["as_of"]]
        a = max(active, key=lambda a: (a["effective"], a["id"]))
        due = _business_days(date.fromisoformat(f["accepted"]), a["days"])
        return {"contract_id": f["contract_id"], "payment_date": due.isoformat(),
                "notice_date": (due-timedelta(days=f["notice_before"])).isoformat(), "amount_cents": a["amount"], "payee": f["payee"]}
    if kind == "chart":
        rows = [v for v in f["values"] if v["audited"] and v["target"] > v["sales"]-v["returns"]]
        v = sorted(rows, key=lambda v: (-(v["target"]-v["sales"]+v["returns"]), v["region"]))[0]
        net = v["sales"] - v["returns"]
        gap = v["target"] - net
        return {"period": f["period"], "region": v["region"], "net_units": net, "gap_units": gap,
                "priority": "critical" if gap >= f["critical_gap"] else "high"}
    if kind == "version":
        v = max((v for v in f["revisions"] if v["status"] == "issued" and v["effective"] <= f["as_of"]), key=lambda v: (v["effective"], v["id"]))
        w = sorted((w for w in f["warehouses"] if w["stock"]-w["reserved"] >= v["quantity"]), key=lambda w: (-(w["stock"]-w["reserved"]), w["name"]))[0]
        return {"order_id": f["order_id"], "revision": v["id"], "sku": v["sku"], "quantity": v["quantity"], "warehouse": w["name"],
                "ship_date": _business_days(date.fromisoformat(f["as_of"]), f["shipping_business_days"]).isoformat()}
    raise ValueError(kind)


def _pages(kind: str, f: dict) -> list[dict]:
    if kind == "invoice":
        pages = [{"title": "Expense review policy", "lines": [f"Case {f['case']} / currency {f['currency']}",
            "Include only APPROVED lines for project ORION.", "Other projects and unapproved lines are excluded.",
            "For EACH line: quantity x unit cents, apply discount,", "round half up to the nearest integer cent; then apply tax",
            "to that discounted amount and round half up again.", "Total = sum of eligible discounted amounts plus their tax.",
            "Return sorted unique invoice_ids and sorted line_ids.", "All values in invoice tables are exact."]}]
        for invoice in sorted({x["invoice"] for x in f["lines"]}):
            rows = [x for x in f["lines"] if x["invoice"] == invoice]
            pages.append({"title": invoice, "lines": ["Line / Project / Approved / Qty / Unit cents / Disc% / Tax%"] +
                [f"{x['id']}  {x['project']}  {'YES' if x['approved'] else 'NO'}  {x['qty']}  {x['unit_cents']}  {x['discount_pct']}%  {x['tax_pct']}%" for x in rows]})
        return pages
    if kind == "contract":
        return [
            {"title": "Contract and interpretation rules", "lines": [f"Contract {f['contract_id']} / payee {f['payee']}", f"Evaluate as of {f['as_of']}.",
                "Use the latest SIGNED amendment effective by that date.", "Future and unsigned amendments do not apply.",
                "Payment due: N BUSINESS days after acceptance.", "Exclude acceptance day. Mon-Fri are business days; no holidays.",
                f"Send notice {f['notice_before']} CALENDAR days before payment.", "Amounts are integer USD cents."]},
            {"title": "Amendment register", "lines": ["ID / Signed / Effective / Business days / Amount cents"] +
                [f"{a['id']} / {'YES' if a['signed'] else 'NO'} / {a['effective']} / {a['days']} / {a['amount']}" for a in f["amendments"]]},
            {"title": "Delivery evidence", "lines": [f"Contract: {f['contract_id']}", f"Accepted by customer: {f['accepted']}",
                f"Invoice received: {(date.fromisoformat(f['accepted'])+timedelta(days=1)).isoformat()}", "Acceptance controls the due-date calculation, not invoice receipt.", "Dates must be returned as YYYY-MM-DD."]},
        ]
    if kind == "chart":
        return [
            {"title": "Monthly performance chart", "lines": [f"Period {f['period']}; exact units are labeled.", "Blue = gross sales; orange = returns. Net = gross - returns."], "chart": f["values"]},
            {"title": "Targets and alert policy", "lines": ["Region / Target units / Audited"] +
                [f"{v['region']} / {v['target']} / {'YES' if v['audited'] else 'NO'}" for v in f["values"]] +
                ["Only AUDITED regions below target qualify.", "Choose the largest absolute shortfall; tie: region A-Z.",
                 f"Priority is critical for gap >= {f['critical_gap']}, otherwise high.", "Return period, region, net_units, gap_units and priority."]},
        ]
    return [
        {"title": "Order revisions", "lines": [f"Order {f['order_id']} / as of {f['as_of']}", "Revision / Status / Effective / SKU / Quantity"] +
            [f"{v['id']} / {v['status']} / {v['effective']} / {v['sku']} / {v['quantity']}" for v in f["revisions"]]},
        {"title": "Warehouse stock ledger", "lines": ["Stock below applies to every SKU in this order.", "Warehouse / Physical stock / Reserved"] +
            [f"{w['name']} / {w['stock']} / {w['reserved']}" for w in f["warehouses"]] + ["Available quantity = physical stock minus reserved."]},
        {"title": "Fulfillment policy", "lines": ["Use latest ISSUED revision effective by the as-of date.", "Drafts and future revisions are not authoritative.",
            "Select a warehouse able to supply the ENTIRE quantity.", "Among eligible warehouses choose largest available stock.", "If tied, select warehouse name alphabetically.",
            f"Ship {f['shipping_business_days']} BUSINESS days after the as-of date.", "Exclude the as-of day; Mon-Fri, no holidays.", "Return revision ID as well as all fulfillment fields."]},
    ]


def expected_goal(record: dict) -> str:
    """Rebuild only the D/X instruction text from existing immutable facts.

    Task-owner migration helper: never changes facts, golds or reference actions.
    """
    family=record["family"]
    if family not in D_FAMILIES+X_FAMILIES:
        raise ValueError("expected_goal is only for document/workflow records")
    gold=_gold(_kind(family),record["data"]["facts"])
    schema = {k: "integer" if type(v) is int else "array of strings (sorted)" if isinstance(v, list) else "string" for k, v in gold.items()}
    task = "Read the documents and submit one JSON object using finish(answer)." if family in D_FAMILIES else "Read the documents, then create the correct record in the local workflow app and click Submit record."
    goal = task + " Required fields and types: " + json.dumps(schema) + ". Exact field set required; case-sensitive strings, integer cents, ISO dates. Use open_document(page) with 1-based pages."
    if family in X_FAMILIES:
        goal += " open_document(0) returns to the workflow app. In app inputs, type array fields as JSON arrays, number fields as decimal integers, and string fields without JSON quotes."
    return goal


def generate(family: str, seed: int, tier: str = "hard") -> dict:
    if family not in FAMILIES or tier not in ("hard", "harder") or type(seed) is not int:
        raise ValueError("Invalid family, integer seed or tier")
    if family in U_FAMILIES:
        return _generate_miniwob(family, seed, tier)
    kind = _kind(family)
    facts = _make_facts(kind, seed, tier)
    gold = _gold(kind, facts)
    goal = expected_goal({"family":family,"data":{"facts":facts}})
    record = {"family": family, "seed": seed, "tier": tier, "goal": goal,
              "data": {"facts": facts, "pages": _pages(kind, facts), "answer": gold},
              "certificate": {"method": "facts_recompute_and_reference_replay", "facts_sha256": _digest(facts), "gold_sha256": _digest(gold)}}
    if family in D_FAMILIES:
        record["reference_actions"] = [{"tool": "open_document", "page": n+1} for n in range(1, len(record["data"]["pages"]))] + [{"tool": "finish", "answer": gold}]
    else:
        actions = [{"tool": "open_document", "page": n+1} for n in range(1, len(record["data"]["pages"]))]
        actions.append({"tool": "open_document", "page": 0})
        for i, (k, v) in enumerate(gold.items()):
            actions += [{"tool": "click", "x": 360, "y": 178+i*68}, {"tool": "type", "text": json.dumps(v) if isinstance(v, list) else str(v)}]
        actions.append({"tool": "click", "x": 380, "y": 650})
        record["reference_actions"] = actions
    return record


def _font(size: int) -> ImageFont.ImageFont:
    # Bundled DejaVu font is part of the asset lock, not an OS-dependent fallback.
    font = ROOT / "assets" / "DejaVuSans.ttf"
    if not font.exists():
        raise RuntimeError("Missing frozen assets/DejaVuSans.ttf")
    return ImageFont.truetype(str(font), size)


def _strict_equal(a: Any, b: Any) -> bool:
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_strict_equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_strict_equal(x, y) for x, y in zip(a, b))
    return a == b


class Env:
    """Facade; coordinates refer to the unscaled 768x768 actor screenshot."""
    def __new__(cls, record: dict):
        if cls is Env and record["family"] in U_FAMILIES:
            return MiniwobEnv(record)
        return super().__new__(cls)

    def __init__(self, record: dict):
        self.record = copy.deepcopy(record)
        self.family = record["family"]
        self.goal = record["goal"]
        self.done = self.success = False
        self.page = 0
        self.focus: str | None = None
        # JSON canonicalization sorts dictionary keys; form layout must not depend
        # on the serialized answer object's incidental key order.
        self.values = {k: "" for k in _gold(_kind(self.family), record["data"]["facts"])}
        self.crop_box = None
        self.reason = "ready"

    def close(self):
        pass

    def _result(self, valid: bool, reason: str) -> dict:
        self.reason = reason
        return {"valid": valid, "terminal": self.done, "success": self.success, "reason": reason}

    def step(self, action: dict) -> dict:
        if self.done:
            return self._result(False, "episode_already_terminal")
        self.crop_box = None
        if not isinstance(action, dict):
            return self._result(False, "invalid_action")
        tool = action.get("tool", action.get("action"))
        if tool == "open_document":
            page = action.get("page")
            if type(page) is not int or not (0 if self.family in X_FAMILIES else 1) <= page <= len(self.record["data"]["pages"]):
                return self._result(False, "invalid_document_page")
            self.page, self.focus = page-1, None
            return self._result(True, "document_opened" if page >= 1 else "app_opened")
        if tool == "crop":
            vals = [action.get(k) for k in ("x", "y", "width", "height")]
            if any(type(v) is not int for v in vals):
                return self._result(False, "invalid_crop")
            x, y, w, h = vals
            if not (0 <= x < WIDTH and 0 <= y < HEIGHT and w > 0 and h > 0 and x+w <= WIDTH and y+h <= HEIGHT):
                return self._result(False, "invalid_crop")
            self.crop_box = (x,y,x+w,y+h)
            return self._result(True, "cropped_observation_coordinates_remain_original")
        if tool == "finish":
            self.done = True
            self.success = self.family in D_FAMILIES and _strict_equal(action.get("answer"), _gold(_kind(self.family), self.record["data"]["facts"]))
            return self._result(True, "success" if self.success else "wrong_final_answer_or_unsubmitted_app")
        if tool == "click":
            x, y = action.get("x"), action.get("y")
            if type(x) not in (int, float) or type(y) not in (int, float) or not (0 <= x < WIDTH and 0 <= y < HEIGHT):
                return self._result(False, "invalid_coordinates")
            if 18 <= y <= 65:
                n = int((x-20)//180)
                if 0 <= n < len(self.record["data"]["pages"]) and 20+n*180 <= x <= 185+n*180:
                    self.page, self.focus = n, None
                    return self._result(True, "document_opened")
                if self.family in X_FAMILIES and 590 <= x <= 748:
                    self.page, self.focus = -1, None
                    return self._result(True, "app_opened")
            if self.page == -1:
                for i, key in enumerate(self.values):
                    if 240 <= x <= 720 and 154+i*68 <= y <= 202+i*68:
                        self.focus = key
                        return self._result(True, "input_focused")
                if 240 <= x <= 520 and 625 <= y <= 680:
                    answer = {}
                    gold = _gold(_kind(self.family), self.record["data"]["facts"])
                    try:
                        for k, v in gold.items():
                            value = self.values[k]
                            answer[k] = json.loads(value) if isinstance(v, list) else int(value) if type(v) is int and re.fullmatch(r"-?(0|[1-9][0-9]*)", value) else value
                    except (ValueError, TypeError):
                        answer = {}
                    self.done = True
                    self.success = _strict_equal(answer, gold)
                    return self._result(True, "success" if self.success else "incorrect_submitted_record")
            self.focus = None
            return self._result(True, "click_no_effect")
        if tool == "type":
            if self.page != -1 or self.focus is None or not isinstance(action.get("text"), str) or len(action["text"]) > 2048:
                return self._result(False, "no_focused_input_or_invalid_text")
            self.values[self.focus] += action["text"]
            return self._result(True, "text_inserted")
        if tool == "press" and self.page == -1 and self.focus:
            key = action.get("key")
            if key in ("CTRL+A", "Control+A", "Meta+A"):
                self.values[self.focus] = ""
            elif key == "Backspace":
                self.values[self.focus] = self.values[self.focus][:-1]
            elif key == "Tab":
                keys = list(self.values)
                self.focus = keys[(keys.index(self.focus)+1) % len(keys)]
            else:
                return self._result(False, "unsupported_key")
            return self._result(True, "key_pressed")
        return self._result(False, "unsupported_action_in_current_view")

    def render(self) -> Image.Image:
        image = Image.new("RGB", (WIDTH, HEIGHT), "#edf1f7")
        draw = ImageDraw.Draw(image)
        f, small, bold = _font(20), _font(17), _font(25)
        for n in range(len(self.record["data"]["pages"])):
            box = (20+n*180,18,185+n*180,65)
            draw.rounded_rectangle(box, 8, fill="#234976" if self.page == n else "#d6e2f2")
            draw.text((32+n*180,30), f"Document {n+1}", font=small, fill="white" if self.page == n else "#163453")
        if self.family in X_FAMILIES:
            draw.rounded_rectangle((590,18,748,65),8,fill="#16765a" if self.page == -1 else "#d5eadf")
            draw.text((610,30), "Workflow app", font=small, fill="white" if self.page == -1 else "#174832")
        if self.page == -1:
            draw.rounded_rectangle((18,82,750,708),12,fill="white")
            draw.text((35,100), "Create record - all fields required", font=bold, fill="#192e49")
            for i, (k, v) in enumerate(self.values.items()):
                y = 154+i*68
                draw.text((34,y+12), k, font=small, fill="#233c53")
                draw.rounded_rectangle((240,y,720,y+48),5,fill="#f9fbfe",outline="#1662b8" if self.focus == k else "#a6b2c2",width=2)
                # Input text clipped to its own rectangle rather than leaking outside UI.
                text_img = Image.new("RGB", (464,40), "#f9fbfe")
                ImageDraw.Draw(text_img).text((0,9), v, font=small, fill="#162d48")
                image.paste(text_img,(248,y+4))
            draw.rounded_rectangle((240,625,520,680),8,fill="#16765a")
            draw.text((275,640), "Submit record", font=f, fill="white")
        else:
            page = self.record["data"]["pages"][self.page]
            draw.rounded_rectangle((18,82,750,708),12,fill="white")
            draw.text((35,102), page["title"],font=bold,fill="#192e49")
            for i, line in enumerate(page["lines"]):
                draw.text((35,155+i*35),line,font=small,fill="#273c51")
            if "chart" in page:
                for i, row in enumerate(page["chart"]):
                    y=250+i*65
                    draw.text((35,y+8),row["region"],font=small,fill="#273c51")
                    for offset,key,color in ((0,"sales","#397cc3"),(25,"returns","#dc8c35")):
                        length=int(row[key]*0.7)
                        draw.rectangle((135,y+offset,135+length,y+offset+19),fill=color)
                        draw.text((145+length,y+offset-1),str(row[key]),font=small,fill="#273c51")
        draw.text((25,727), "Status: "+("SUCCESS" if self.success else "FAILED" if self.done else "in progress"),font=small,fill="#233c53")
        if self.crop_box:
            image = image.crop(self.crop_box).resize((WIDTH, HEIGHT), Image.Resampling.NEAREST)
        return image


def certify(record: dict) -> dict:
    """Owner-side deterministic checks plus exact reference action replay."""
    if record["family"] in U_FAMILIES:
        return _certify_miniwob(record)
    regenerated = generate(record["family"], record["seed"], record["tier"])
    payload = {k:v for k,v in record.items() if k not in ("id","split")}
    if not _strict_equal(payload, regenerated):
        raise ValueError("Document record differs from deterministic generator")
    env = Env(record)
    for a in record["reference_actions"]:
        result = env.step(a)
        if not result["valid"]:
            raise ValueError(f"Reference action invalid: {result['reason']}")
    if not env.done or not env.success:
        raise ValueError("Reference failed")
    limit = 6 if record["family"] in D_FAMILIES else 20
    if len(record["reference_actions"]) > limit:
        raise ValueError("Reference exceeds actor decision budget")
    return {"valid": True, "success": True, "reference_calls": len(record["reference_actions"]), "certificate_sha256": _digest(record["certificate"])}


# MiniWoB implementation is below. BrowserGym owns generation and termination;
# this wrapper exposes only screenshot observations and literal mouse/keyboard.
_PLAYWRIGHT = None
_BROWSER = None
_SOURCE_VERIFIED = False


def _browser():
    global _PLAYWRIGHT, _BROWSER
    if _BROWSER is None:
        from playwright.sync_api import sync_playwright
        _PLAYWRIGHT = sync_playwright().start()
        _BROWSER = _PLAYWRIGHT.chromium.launch(headless=True, executable_path=os.environ.get("JEV_CHROMIUM_EXECUTABLE") or None)
    return _BROWSER


def close_browser():
    global _PLAYWRIGHT, _BROWSER
    if _BROWSER:
        _BROWSER.close()
        _BROWSER = None
    if _PLAYWRIGHT:
        _PLAYWRIGHT.stop()
        _PLAYWRIGHT = None


atexit.register(close_browser)


class MiniwobEnv:
    """Native pinned BrowserGym task with an intentionally pixel-only actor API.

    BrowserGym's generic validate reward maps ANY positive raw reward to 1.
    We instead require its native DONE_GLOBAL and exactly RAW_REWARD_GLOBAL=1.
    The sole task mutation is frozen, visible CSS layout; raster scaling is DPR 3; no event handlers,
    task predicates, goal strings, readonly flags or native inputs are replaced.
    """
    def __init__(self, record: dict):
        global _SOURCE_VERIFIED
        import browsergym.miniwob.base as native_base
        from browsergym.miniwob.base import AbstractMiniwobTask
        if not _SOURCE_VERIFIED:
            base_hash=hashlib.sha256(Path(native_base.__file__).read_bytes()).hexdigest()
            if base_hash != "4d7b82b7b63403a9774969f4166ab858243bef381335ae1af3ced345e66552ab":
                raise RuntimeError("BrowserGym MiniWoB wrapper differs from the pinned source")
            manifest=json.loads((VENDOR/"SOURCE_MANIFEST.json").read_text())
            if manifest["revision"] != MINIWOB_PIN:
                raise RuntimeError("MiniWoB source revision drift")
            for name,meta in manifest["files"].items():
                if hashlib.sha256((VENDOR/name).read_bytes()).hexdigest()!=meta["sha256"]:
                    raise RuntimeError("MiniWoB source asset drift: "+name)
            _SOURCE_VERIFIED=True
        if not (VENDOR / "miniwob" / (MINIWOB_NAMES[record["family"]]+".html")).exists():
            raise RuntimeError("Pinned native MiniWoB assets missing")
        self.record = copy.deepcopy(record)
        self.family = record["family"]
        self.done = self.success = False
        self.crop_box = None
        self.context = _browser().new_context(viewport={"width": WIDTH//3,"height": HEIGHT//3}, locale="en-US", timezone_id="UTC", device_scale_factor=3)
        # Never allow task pages to use the network or access arbitrary local files.
        prefix = VENDOR.resolve().as_uri()+"/"
        self.context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(prefix) else route.abort())
        self.page = self.context.new_page()
        task_class = type("FrozenNativeMiniwob", (AbstractMiniwobTask,), {"subdomain": MINIWOB_NAMES[self.family]})
        self.task = task_class(seed=record["data"]["native_seed"], base_url=(VENDOR/"miniwob").resolve().as_uri()+"/", episode_max_time=86400000, remove_human_display=True)
        try:
            native_goal, _ = self.task.setup(self.page)
            self.page.set_viewport_size({"width": WIDTH//3,"height": HEIGHT//3})
            self.page.add_style_tag(content="#query { background: #eef2f7; } #wrap { background: white; }")
            if record["tier"] == "harder":
                # Visible instance stratum shared by every split; native semantics unchanged.
                self.page.add_style_tag(content="#wrap { margin-left: 45px; } #buttons { display: flex; flex-direction: row-reverse; justify-content: center; } #dropdown-container { padding-top: 12px; }")
            self.goal = native_goal + " Use screenshot coordinates and literal keyboard input. Complete the native task; finish is not a substitute for its submit/book button."
            if record.get("goal") and record["goal"] != self.goal:
                raise ValueError("Native goal drifted from frozen record")
            self.page.wait_for_timeout(40)
        except Exception:
            self.context.close()
            raise

    def close(self):
        self.task.teardown()
        self.context.close()

    def render(self) -> Image.Image:
        image = Image.open(io.BytesIO(self.page.screenshot())).convert("RGB")
        if self.crop_box:
            image = image.crop(self.crop_box).resize((WIDTH, HEIGHT), Image.Resampling.NEAREST)
        return image

    def observable_fingerprint(self) -> str:
        """Owner-only semantic digest of what is initially visible, not raster AA.

        It excludes the native seed, reference IDs, hidden DOM nodes, answers,
        browser version and font metrics. Native template structure distinguishes
        layouts, while text/control state catches visible task-content drift.
        """
        visible = self.page.evaluate("""() => {
          const area = document.querySelector('#area');
          const normalized = x => (x || '').replace(/\\s+/g, ' ').trim();
          const nodes = Array.from(area.querySelectorAll('*')).filter(e => {
            const style = getComputedStyle(e);
            return e.getClientRects().length && style.display !== 'none' && style.visibility !== 'hidden';
          }).map(e => ({tag:e.tagName.toLowerCase(), id: e.id.startsWith('ui-id-') ? '' : e.id,
            classes: Array.from(e.classList).filter(x => !/^(focus|hover|active)$/.test(x)).sort(),
            text: normalized(e.children.length ? '' : e.innerText),
            value: 'value' in e ? String(e.value) : null,
            placeholder: e.getAttribute('placeholder'), readonly: !!e.readOnly,
            checked: 'checked' in e ? !!e.checked : null}));
          return {text: normalized(area.innerText), nodes};
        }""")
        return _digest({"goal":self.goal,"family":self.family,"layout_tier":self.record["tier"],"visible":visible})

    def _check(self) -> dict:
        _, _, _, info = self.task.validate(self.page, [])
        if not {"DONE_GLOBAL", "RAW_REWARD_GLOBAL"} <= set(info):
            raise RuntimeError("Native verifier unavailable; no candidate score")
        self.done = bool(info.get("DONE_GLOBAL"))
        self.success = self.done and info.get("RAW_REWARD_GLOBAL") == 1
        return {"valid": True,"terminal": self.done,"success": self.success,
                "reason": "success" if self.success else "native_task_failed" if self.done else "action_applied"}

    def step(self, action: dict) -> dict:
        invalid = {"valid": False,"terminal": self.done,"success": self.success,"reason": "invalid_native_action"}
        if self.done or not isinstance(action, dict):
            return invalid
        self.crop_box = None
        tool = action.get("tool", action.get("action"))
        try:
            if tool == "scroll":
                dy=action.get("dy")
                if type(dy) is not int or abs(dy)>2048:
                    return invalid
                self.page.mouse.move(WIDTH/6, HEIGHT/6)
                self.page.mouse.wheel(0,dy/3)
                # Fixed settle interval applies to every actor and reference call.
                self.page.wait_for_timeout(150)
            elif tool in ("click", "drag"):
                x, y = action.get("x"), action.get("y")
                if type(x) not in (int,float) or type(y) not in (int,float) or not (0 <= x < WIDTH and 0 <= y < HEIGHT):
                    return invalid
                if tool == "click":
                    self.page.mouse.click(x/3,y/3)
                else:
                    x2,y2=action.get("to_x"),action.get("to_y")
                    if type(x2) not in (int,float) or type(y2) not in (int,float) or not (0 <= x2 < WIDTH and 0 <= y2 < HEIGHT):
                        return invalid
                    self.page.mouse.move(x/3,y/3)
                    self.page.mouse.down()
                    self.page.mouse.move(x2/3,y2/3,steps=5)
                    self.page.mouse.up()
            elif tool == "type":
                if not isinstance(action.get("text"),str) or len(action["text"])>2048:
                    return invalid
                # Literal keyboard insertion, never eval, HTML, selector, or fill via DOM.
                self.page.keyboard.insert_text(action["text"])
            elif tool == "press":
                key = action.get("key")
                mapping={"up":"ArrowUp","down":"ArrowDown","left":"ArrowLeft","right":"ArrowRight"}
                if key not in ("up","down","left","right","Enter","Escape","Tab","Backspace"):
                    return invalid
                self.page.keyboard.press(mapping.get(key,key))
            elif tool == "crop":
                vals = [action.get(k) for k in ("x","y","width","height")]
                if any(type(v) is not int for v in vals):
                    return invalid
                x,y,w,h=vals
                if not (0<=x<WIDTH and 0<=y<HEIGHT and w>0 and h>0 and x+w<=WIDTH and y+h<=HEIGHT):
                    return invalid
                self.crop_box=(x,y,x+w,y+h)
            elif tool == "finish":
                # A completed native episode already terminates automatically.
                self.done, self.success = True, False
                return {"valid":True,"terminal":True,"success":False,"reason":"finished_before_native_success"}
            else:
                return invalid
            self.page.wait_for_timeout(40)
        except Exception as exc:
            # Infrastructure errors must not be reported as candidate failures.
            if self.page.is_closed() or not _BROWSER.is_connected():
                raise RuntimeError("Browser infrastructure failed") from exc
            return {**invalid,"reason":"native_action_error"}
        # Verifier failures are infrastructure failures, never candidate zeros.
        return self._check()


def _reference_native(env: MiniwobEnv) -> list[dict]:
    """Task-owner controller. DOM inspection is ONLY for fixture certification.

    Every state-changing operation is replayable through the actor's literal
    coordinate/keyboard interface. No DOM mutation, element.click/fill, hidden
    reward hack, or free scroll_into_view is used to solve an instance.
    """
    p=env.page
    actions=[]
    def do(a):
        result=env.step(a)
        actions.append(a)
        if not result["valid"]:
            raise ValueError("Reference native action failed (details remain task-owner state)")
    def click(selector, index=0):
        box=p.locator(selector).nth(index).bounding_box()
        if not box:
            raise ValueError(f"No visible reference target {selector}")
        do({"tool":"click","x":round(3*(box["x"]+box["width"]/2)),"y":round(3*(box["y"]+box["height"]/2))})
    def enter(selector,text,index=0):
        click(selector,index)
        do({"tool":"type","text":text})
    if env.family=="u_multi_layouts":
        m=re.search(r"Search for (.+) movies directed by (.+) from year (\d+)\.", env.goal)
        if not m: raise ValueError("Native multi-layout goal schema drift")
        values={"genre":m[1],"director":m[2],"year":m[3]}
        inputs=p.locator('#area input[type="text"]')
        for i in range(inputs.count()):
            label=inputs.nth(i).evaluate("e => (e.closest('tr') || e.parentElement.parentElement?.classList.contains('field') && e.parentElement.parentElement || e.parentElement).innerText.toLowerCase()")
            key="genre" if "genre" in label else "director" if "director" in label else "year"
            enter('#area input[type="text"]',values[key],i)
        click("#area button, #area .final, #area .ui-submit")
    elif env.family=="u_read_table":
        rows=p.locator("#tab tr").evaluate_all("es => Object.fromEntries(es.map(e=>Array.from(e.querySelectorAll('td')).map(x=>x.innerText)))")
        for i in (1,2):
            label=p.locator(f"#ll{i}").inner_text().removesuffix(":")
            enter(f"#tt{i}",rows[label])
        click("#subbtn")
    elif env.family=="u_form_sequence":
        m=re.search(r'Choose (.+) from the dropdown, then click the button labeled "(.+)"',env.goal)
        if not m: raise ValueError("Native sequence goal schema drift")
        click(".selectric")
        options=p.locator("#dropdown option").all_text_contents()
        for _ in range(options.index(m[1])):
            do({"tool":"press","key":"down"})
        do({"tool":"press","key":"Enter"})
        click("#"+m[2].lower())
    else:
        m=re.search(r"Book the (cheapest|shortest) one-way flight from: (.+) to: (.+) on (\d+/\d+/\d+)\.",env.goal)
        if not m: raise ValueError("Native flight goal schema drift")
        cities=p.evaluate("DOMESTIC_FLIGHTS")
        enter("#flight-from",next(c for c in cities if m[2] in c))
        # Native autocomplete can cover the next input; keyboard Tab closes it
        # and focuses the next control without a hidden DOM-assisted click.
        do({"tool":"press","key":"Tab"})
        do({"tool":"type","text":next(c for c in cities if m[3] in c)})
        do({"tool":"press","key":"Tab"})
        month,day,year=map(int,m[4].split("/"))
        months="January February March April May June July August September October November December".split()
        for _ in range(3):
            current=months.index(p.locator(".ui-datepicker-month").inner_text())+1
            if current==month: break
            click(".ui-datepicker-prev" if current>month else ".ui-datepicker-next")
        dates=p.locator(".ui-datepicker-calendar a")
        idx=dates.all_text_contents().index(str(day))
        click(".ui-datepicker-calendar a",idx)
        click("#search")
        vals=p.locator(".flight").evaluate_all("es=>es.map(e=>({price:+e.querySelector('.flight-price').dataset.price,duration:+e.querySelector('.time-duration').dataset.duration}))")
        best=min(range(len(vals)),key=lambda i:vals[i]["price" if m[1]=="cheapest" else "duration"])
        box=p.locator(".flight-price").nth(best).bounding_box()
        area=p.locator("#area").bounding_box()
        if box["y"]+box["height"]>area["y"]+area["height"] or box["y"]<area["y"]:
            # One counted wheel operation, with no hidden scrolling between actions.
            dy=max(-2000,min(2000,round(3*(box["y"]-area["y"]-area["height"]/2))))
            do({"tool":"scroll","dy":dy})
        click(".flight-price",best)
    if not env.done or not env.success:
        raise ValueError(f"Native reference did not achieve exact full success for {env.family}")
    if len(actions)>12:
        raise ValueError(f"Native reference uses {len(actions)} > 12 calls")
    return actions


def _generate_miniwob(family,seed,tier):
    record={"family":family,"seed":seed,"tier":tier,"goal":"",
            "data":{"native_seed":int(_digest([family, seed, tier])[:8],16),"task":MINIWOB_NAMES[family],"layout":0 if tier=="hard" else 1,
                    "miniwob_revision":MINIWOB_PIN,"browsergym_revision":BROWSERGYM_PIN}}
    env=MiniwobEnv(record)
    try:
        record["goal"]=env.goal
        screenshot=env.render()
        screenshot_hash=hashlib.sha256(screenshot.tobytes()).hexdigest()
        observable_hash=env.observable_fingerprint()
        actions=_reference_native(env)
        record["reference_actions"]=actions
        record["certificate"]={"method":"native_browsergym_reference_replay","initial_pixels_sha256":screenshot_hash,
                               "observable_sha256":observable_hash,
                               "pixel_hash_role":"same_platform_diagnostic_only",
                               "native_terminal":True,"raw_reward":1,"reference_calls":len(actions)}
        return record
    finally:
        env.close()


def _certify_miniwob(record):
    env=MiniwobEnv(record)
    try:
        if env.observable_fingerprint()!=record["certificate"]["observable_sha256"]:
            raise ValueError("Native visible content or layout drifted")
        for a in record["reference_actions"]:
            result=env.step(a)
            if not result["valid"]:
                raise ValueError("Native reference replay invalid")
        if not env.done or not env.success or len(record["reference_actions"])>12:
            raise ValueError("Native reference replay failed or exceeded budget")
        return {"valid":True,"success":True,"reference_calls":len(record["reference_actions"]),"certificate_sha256":_digest(record["certificate"])}
    finally:
        env.close()
