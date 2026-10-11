from datetime import timedelta

from app.clock import today
from conftest import PW, jpeg_bytes, make_user, new_client, noisy_png

D = "2026-09-13"


def add_float(c, amount, label="Week float", **kw):
    r = c.post("/api/floats", json={"label": label, "amount": amount, "issued_on": D, "source": "Boss", **kw})
    assert r.status_code == 200, r.text
    return r.json()


def add_exp(c, fid, amount, desc="Item", expect=200, **kw):
    body = {"description": desc, "amount": amount, "category": kw.pop("category", "Transport"),
            "spent_on": kw.pop("spent_on", D), **kw}
    r = c.post(f"/api/floats/{fid}/expenses", json=body)
    assert r.status_code == expect, r.text
    return r.json()


def attach(c, eid, data=None, kind="Receipt"):
    r = c.post(f"/api/expenses/{eid}/proof", files={"file": ("p.jpg", data or jpeg_bytes(), "image/jpeg")},
               data={"kind": kind})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- setup & sign-in

def test_first_run_setup_only_once(admin):
    assert admin.me["role"] == "admin" and admin.me["phone"] == "0712000001"
    r = new_client().post("/api/auth/setup", json={"full_name": "X", "phone": "0700000000", "password": PW})
    assert r.status_code == 409
    assert new_client().get("/api/auth/state").json() == {"needs_setup": False, "user": None}


def test_login_accepts_any_phone_format_and_locks_after_5_fails(admin):
    c = new_client()
    assert c.post("/api/auth/login", json={"phone": "+254 712 000 001", "password": PW}).status_code == 200
    c = new_client()
    for _ in range(5):
        assert c.post("/api/auth/login", json={"phone": "0712000001", "password": "nope"}).status_code == 401
    r = c.post("/api/auth/login", json={"phone": "0712000001", "password": PW})
    assert r.status_code == 429  # locked even with the right password


def test_requests_without_page_header_are_blocked(admin):
    r = admin.post("/api/floats", json={"label": "x", "amount": 1}, headers={"x-cashbook": "0"})
    assert r.status_code == 403


def test_signed_out_user_cannot_read_anything(admin):
    add_float(admin, 1000)
    assert new_client().get("/api/floats").status_code == 401


def test_password_change(admin):
    assert admin.post("/api/auth/password", json={"current_password": "wrong", "new_password": "NewPass#99"}).status_code == 400
    assert admin.post("/api/auth/password", json={"current_password": PW, "new_password": "short"}).status_code == 400
    assert admin.post("/api/auth/password", json={"current_password": PW, "new_password": "NewPass#99"}).status_code == 200
    assert new_client().post("/api/auth/login", json={"phone": "0712000001", "password": "NewPass#99"}).status_code == 200


# ---------------------------------------------------------------- accounting

def test_float_balance_counts_mpesa_charges(admin):
    f = add_float(admin, 30000)
    add_exp(admin, f["id"], 15000, "Canisters", category="Canisters")
    add_exp(admin, f["id"], 4850, "Boda", fee=50)            # 4,850 + 50 charge
    f = admin.get(f"/api/floats/{f['id']}").json()
    assert f["spent"] == 19900 and f["balance"] == 10100


def test_overspend_and_cents_are_exact(admin):
    f = add_float(admin, 100.10)
    add_exp(admin, f["id"], 0.10)
    add_exp(admin, f["id"], 0.20)
    add_exp(admin, f["id"], 100.00)
    f = admin.get(f"/api/floats/{f['id']}").json()
    assert f["spent"] == 100.30 and f["balance"] == -0.20


def test_bad_amounts_dates_and_categories_are_rejected(admin):
    f = add_float(admin, 5000)
    add_exp(admin, f["id"], -10, expect=400)
    add_exp(admin, f["id"], 0, expect=400)
    add_exp(admin, f["id"], "abc", expect=400)
    add_exp(admin, f["id"], 10, fee=-1, expect=400)
    add_exp(admin, f["id"], 10, spent_on=(today() + timedelta(days=1)).isoformat(), expect=400)
    add_exp(admin, f["id"], 10, category="Holiday", expect=400)
    add_exp(admin, f["id"], 10, desc="  ", expect=400)
    assert admin.post("/api/floats", json={"label": "x", "amount": 100,
                                           "issued_on": (today() + timedelta(days=2)).isoformat()}).status_code == 400


def test_edit_and_delete_expense_are_audited(admin):
    f = add_float(admin, 5000)
    e = add_exp(admin, f["id"], 1200, "Boda Kayole")
    r = admin.patch(f"/api/expenses/{e['id']}", json={"amount": 1000})
    assert r.status_code == 200 and r.json()["amount"] == 1000
    assert admin.delete(f"/api/expenses/{e['id']}").status_code == 200
    actions = [a["action"] for a in admin.get("/api/audit").json()]
    assert {"expense_added", "expense_edited", "expense_deleted"} <= set(actions)
    assert admin.get(f"/api/floats/{f['id']}").json()["spent"] == 0


# ---------------------------------------------------------------- M-Pesa

def test_duplicate_mpesa_code_blocked_across_all_managers(admin, charles):
    f1 = add_float(admin, 5000)
    f2 = add_float(charles, 5000)
    add_exp(admin, f1["id"], 500, mpesa_code="qgh3xk21k0")
    r = charles.post(f"/api/floats/{f2['id']}/expenses",
                     json={"description": "x", "amount": 500, "category": "Data", "spent_on": D, "mpesa_code": "QGH3XK21K0"})
    assert r.status_code == 409 and "already recorded" in r.json()["detail"]
    add_exp(admin, f1["id"], 10, mpesa_code="bad code!", expect=400)


def test_editing_keeps_own_code_but_cannot_steal_another(admin):
    f = add_float(admin, 5000)
    a = add_exp(admin, f["id"], 100, mpesa_code="AAAAAAAAA1")
    b = add_exp(admin, f["id"], 100, mpesa_code="BBBBBBBBB2")
    assert admin.patch(f"/api/expenses/{a['id']}", json={"mpesa_code": "AAAAAAAAA1", "amount": 150}).status_code == 200
    assert admin.patch(f"/api/expenses/{b['id']}", json={"mpesa_code": "AAAAAAAAA1"}).status_code == 409


def test_parse_mpesa_message_including_charge(admin):
    msg = ("TJK4XY12AB Confirmed. Ksh1,500.00 sent to JOHN KAMAU 0712345678 on 21/9/26 at 3:15 PM. "
           "New M-PESA balance is Ksh2,000.00. Transaction cost, Ksh23.00. Amount you can transact within the day is 498,500.00.")
    p = admin.post("/api/tools/parse-mpesa", json={"text": msg}).json()
    assert p == {"mpesa_code": "TJK4XY12AB", "amount": 1500.0, "fee": 23.0,
                 "payee": "JOHN KAMAU 0712345678", "date": "2026-09-21"}
    p = admin.post("/api/tools/parse-mpesa", json={"text": "TJK4XY12AC Confirmed. Ksh250.00 paid to PESSICAH AIRTEL. on 2/10/26 at 9:01 AM"}).json()
    assert p["amount"] == 250 and p["payee"] == "PESSICAH AIRTEL" and p["date"] == "2026-10-02"


# ---------------------------------------------------------------- proof rule & photos

def test_proof_rule_blocks_submit_until_photo_attached(admin, boss):
    f = add_float(admin, 10000)
    big = add_exp(admin, f["id"], 600)
    add_exp(admin, f["id"], 300)  # under KES 500: no proof needed
    assert big["needs_proof"] is True
    r = admin.post(f"/api/floats/{f['id']}/submit", json={"note": "ok"})
    assert r.status_code == 409 and "need proof" in r.json()["detail"]
    attach(admin, big["id"], kind="M-Pesa")
    assert admin.post(f"/api/floats/{f['id']}/submit", json={"note": "Balance 9,100 returned"}).status_code == 200


def test_fee_counts_towards_proof_threshold(admin):
    f = add_float(admin, 1000)
    e = add_exp(admin, f["id"], 490, fee=10)
    assert e["needs_proof"] is True


def test_threshold_setting_admin_only(admin, charles):
    assert charles.put("/api/settings", json={"proof_threshold": 100}).status_code == 403
    assert admin.put("/api/settings", json={"proof_threshold": 2000}).json()["proof_threshold"] == 2000
    f = add_float(admin, 5000)
    assert add_exp(admin, f["id"], 1500)["needs_proof"] is False


def test_big_photo_is_compressed_and_bad_files_rejected(admin):
    f = add_float(admin, 5000)
    e = add_exp(admin, f["id"], 800)
    raw = noisy_png()
    assert len(raw) > 1_500_000
    out = attach(admin, e["id"], data=raw)
    assert out["proof"]["size"] <= 250 * 1024
    img = admin.get(f"/api/expenses/{e['id']}/proof")
    assert img.headers["content-type"] == "image/jpeg" and img.content[:2] == b"\xff\xd8"
    r = admin.post(f"/api/expenses/{e['id']}/proof", files={"file": ("x.jpg", b"not an image", "image/jpeg")})
    assert r.status_code == 400


def test_evidence_pack_pdf(admin):
    f = add_float(admin, 5000, label="Week float 13-18 Sep")
    e = add_exp(admin, f["id"], 800, "Canister restock", category="Canisters", mpesa_code="QGH3XK21K0")
    attach(admin, e["id"], kind="M-Pesa")
    add_exp(admin, f["id"], 700, "Boda – no proof yet")
    r = admin.get(f"/api/floats/{f['id']}/evidence.pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF" and len(r.content) > 5000


# ---------------------------------------------------------------- submit, lock, boss sign-off

def test_note_required_when_balance_not_zero(admin):
    f = add_float(admin, 1000)
    add_exp(admin, f["id"], 400)
    assert admin.post(f"/api/floats/{f['id']}/submit", json={"note": ""}).status_code == 400
    f2 = add_float(admin, 400)
    add_exp(admin, f2["id"], 400)
    assert admin.post(f"/api/floats/{f2['id']}/submit", json={}).status_code == 200


def test_full_review_cycle_query_fix_resubmit_approve(admin, boss, charles):
    f = add_float(charles, 2000)
    e = add_exp(charles, f["id"], 300)
    assert charles.post(f"/api/floats/{f['id']}/submit", json={"note": "1,700 left"}).status_code == 200
    # locked while submitted
    add_exp(charles, f["id"], 50, expect=409)
    assert charles.delete(f"/api/expenses/{e['id']}").status_code == 409
    # managers can't sign off; boss must give a reason for a query
    assert charles.post(f"/api/floats/{f['id']}/review", json={"decision": "APPROVED"}).status_code == 403
    assert boss.post(f"/api/floats/{f['id']}/review", json={"decision": "QUERIED"}).status_code == 400
    r = boss.post(f"/api/floats/{f['id']}/review", json={"decision": "QUERIED", "comment": "Which boda?"})
    assert r.json()["status"] == "QUERIED"
    # unlocked again for the manager to fix
    assert charles.patch(f"/api/expenses/{e['id']}", json={"description": "Boda Kayole – Clinton"}).status_code == 200
    assert charles.post(f"/api/floats/{f['id']}/submit", json={"note": "Fixed"}).status_code == 200
    r = boss.post(f"/api/floats/{f['id']}/review", json={"decision": "APPROVED", "comment": "OK"})
    body = r.json()
    assert body["status"] == "APPROVED" and [x["decision"] for x in body["reviews"]] == ["QUERIED", "APPROVED"]
    # approved = locked for good
    add_exp(charles, f["id"], 10, expect=409)
    assert admin.delete(f"/api/floats/{f['id']}").status_code == 409
    assert boss.post(f"/api/floats/{f['id']}/review", json={"decision": "QUERIED", "comment": "x"}).status_code == 409


def test_admin_can_review_others_but_never_own_float(admin, charles):
    own = add_float(admin, 100)
    add_exp(admin, own["id"], 100)
    admin.post(f"/api/floats/{own['id']}/submit", json={})
    assert admin.post(f"/api/floats/{own['id']}/review", json={"decision": "APPROVED"}).status_code == 403
    theirs = add_float(charles, 100)
    add_exp(charles, theirs["id"], 100)
    charles.post(f"/api/floats/{theirs['id']}/submit", json={})
    assert admin.post(f"/api/floats/{theirs['id']}/review", json={"decision": "APPROVED"}).status_code == 200


def test_boss_is_read_only(boss, admin):
    assert boss.post("/api/floats", json={"label": "x", "amount": 10}).status_code == 403
    f = add_float(admin, 100)
    assert boss.post(f"/api/floats/{f['id']}/expenses",
                     json={"description": "x", "amount": 5, "category": "Other", "spent_on": D}).status_code == 403


# ---------------------------------------------------------------- isolation between managers

def test_managers_only_see_and_touch_their_own(admin, charles, erick, boss):
    fc = add_float(charles, 5000)
    ec = add_exp(charles, fc["id"], 800)
    add_float(erick, 4000)
    assert [f["manager"] for f in charles.get("/api/floats").json()] == ["Charles Mbugua Biaru"]
    assert erick.get(f"/api/floats/{fc['id']}").status_code == 404
    assert erick.get(f"/api/floats/{fc['id']}/evidence.pdf").status_code == 404
    assert erick.patch(f"/api/expenses/{ec['id']}", json={"amount": 1}).status_code == 404
    assert erick.delete(f"/api/expenses/{ec['id']}").status_code == 404
    assert erick.get(f"/api/expenses/{ec['id']}/proof").status_code == 404
    add_exp(erick, fc["id"], 10, expect=404)
    # managers can't record floats for others; admin can
    assert erick.post("/api/floats", json={"label": "x", "amount": 1, "manager_id": charles.me["id"]}).status_code == 403
    add_float(admin, 1000, manager_id=erick.me["id"])
    # admin sees but cannot edit someone else's float
    assert admin.patch(f"/api/expenses/{ec['id']}", json={"amount": 1}).status_code == 403
    assert len(boss.get("/api/floats").json()) == 3
    assert len(boss.get(f"/api/floats?manager_id={erick.me['id']}").json()) == 2


def test_dashboard_consolidation(admin, charles, boss):
    f = add_float(admin, 10000)
    add_exp(admin, f["id"], 2500)
    g = add_float(charles, 5000)
    add_exp(charles, g["id"], 6000)
    me = charles.get("/api/dashboard").json()
    assert "managers" not in me and me["me"]["balance"] == -1000
    d = boss.get("/api/dashboard").json()
    assert d["all"]["given"] == 15000 and d["all"]["spent"] == 8500
    names = {m["name"]: m["balance"] for m in d["managers"]}
    assert names == {"Gideon": 7500, "Charles Mbugua Biaru": -1000}


# ---------------------------------------------------------------- users

def test_user_management(admin, charles):
    assert charles.post("/api/users", json={"full_name": "x", "phone": "0700000001", "role": "manager", "password": PW}).status_code == 403
    assert admin.post("/api/users", json={"full_name": "Dup", "phone": "0712000002", "role": "manager", "password": PW}).status_code == 409
    assert admin.patch(f"/api/users/{admin.me['id']}", json={"is_active": False}).status_code == 400
    assert admin.patch(f"/api/users/{charles.me['id']}", json={"is_active": False}).status_code == 200
    assert charles.get("/api/floats").status_code == 401  # deactivated = signed out at once
    assert new_client().post("/api/auth/login", json={"phone": "0712000002", "password": PW}).status_code == 401


# ---------------------------------------------------------------- field & office reports

def test_field_reports_flow(admin, charles, boss):
    r = charles.post("/api/field-reports", json={"kind": "daily", "title": "Kayole KP machine down",
                                                 "body": "Pump failed at 10am.",
                                                 "decision_needed": "Approve KES 6,000 repair?"})
    assert r.status_code == 200
    rid = r.json()["id"]
    r = charles.post(f"/api/field-reports/{rid}/photos", files={"file": ("a.jpg", jpeg_bytes(), "image/jpeg")},
                     data={"caption": "Broken pump"})
    pid = r.json()["photos"][0]["id"]
    assert boss.get(f"/api/field-reports/{rid}/photos/{pid}").status_code == 200
    assert boss.post("/api/field-reports", json={"title": "x"}).status_code == 403
    assert charles.post(f"/api/field-reports/{rid}/decision", json={"status": "APPROVED"}).status_code == 403
    r = boss.post(f"/api/field-reports/{rid}/decision", json={"status": "APPROVED", "comment": "Go ahead"})
    assert r.json()["status"] == "APPROVED" and r.json()["replies"][0]["body"] == "[APPROVED] Go ahead"
    assert charles.post(f"/api/field-reports/{rid}/replies", json={"body": "Done, fixed by 3pm"}).status_code == 200
    erick = make_user(admin, "Erick Macharia", "0712000003", "manager")
    assert erick.get(f"/api/field-reports/{rid}").status_code == 404
    assert erick.get("/api/field-reports").json() == []
    pdf = boss.get(f"/api/field-reports/{rid}/report.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


# ---------------------------------------------------------------- misc

def test_health_and_spa(admin):
    assert admin.get("/api/health").json()["ok"] is True
    page = admin.get("/floats")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert admin.get("/api/nope").status_code == 404
