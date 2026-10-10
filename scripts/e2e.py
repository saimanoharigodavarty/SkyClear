"""End-to-end test of the whole platform in a real browser: visitor, pilot, officer, admin.

Needs: the app running with MongoDB and the mail catcher (./run.sh --demo), then
  pip install playwright && playwright install chromium
  python scripts/e2e.py
Uses the logins in data/demo_credentials.txt and reads one-time codes from the mail catcher. Cleans up the notices it creates.
Set CHROME_PATH to use an installed Chrome instead of Playwright's Chromium.
"""
import json, re, time, urllib.request, os
from playwright.sync_api import sync_playwright
BASE = os.getenv("BASE_URL", "http://localhost:8000"); B = BASE; MP = os.getenv("MAILPIT_URL", "http://localhost:8025")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PNG = os.path.join(ROOT, "data", ".e2e.png")
SHOTS = os.path.join(ROOT, "data", ".e2e-shots"); os.makedirs(SHOTS, exist_ok=True)
open(PNG, "wb").write(bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082"))
rows=[l.split() for l in open(os.path.join(ROOT, "data", "demo_credentials.txt")).read().splitlines() if l.strip()]
cred={}
for r in rows: cred[r[1]]=r[2]
ADMIN = next((e, p) for e, p in cred.items() if any(r[0] == "admin" and r[1] == e for r in rows))
POLICE = next((e, p) for e, p in cred.items() if e.startswith("a-pol@"))
N=str(int(time.time()))[-6:]; EMAIL=f"flow{N}@example.com"; PW="a-long-password-1"
def code_for(to):
    for _ in range(30):
        for m in json.load(urllib.request.urlopen(MP+"/api/v1/messages"))["messages"]:
            if any(t["Address"]==to for t in m["To"]):
                return re.search(r"code is (\d{6})",json.load(urllib.request.urlopen(MP+"/api/v1/message/"+m["ID"]))["Text"]).group(1)
        time.sleep(0.5)
    raise SystemExit("no email for "+to)
def api(path, method="GET", body=None, token=None):
    req=urllib.request.Request(B+path, data=None if body is None else json.dumps(body).encode(), method=method, headers={"Content-Type":"application/json", **({"Authorization":"Bearer "+token} if token else {})})
    return json.load(urllib.request.urlopen(req))
def cleanup():
    t=api("/auth/login","POST",{"identifier":ADMIN[0],"password":ADMIN[1]})["token"]
    for n in api("/notices",token=t):
        if n["status"]=="active" and n["title"].startswith("Flow test"): api(f"/notices/{n['notice_id']}/cancel","POST",token=t)
cleanup()
ok=[]
def step(name, cond):
    ok.append((name,bool(cond))); print(("PASS " if cond else "FAIL ")+name)
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.getenv("CHROME_PATH") or None)
    errs=[]
    def page(w=1440,h=900):
        pg=b.new_context(viewport={"width":w,"height":h}).new_page()
        pg.on("pageerror", lambda e: errs.append("PAGEERR "+str(e))); pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None); return pg
    def signin(pg,email,pw,land):
        pg.goto(B+"/account.html"); pg.fill("#lId",email); pg.fill("#lPass",pw); pg.click("#signinForm button[type=submit]"); pg.wait_for_url("**/"+land); pg.wait_for_timeout(1500)
    # 1 visitor
    v=page(); v.goto(B+"/"); v.wait_for_timeout(2500)
    step("visitor: example buttons built from database", len(v.query_selector_all("#examples button"))>=4)
    v.click("#examples button >> nth=1"); v.wait_for_selector("#result .verdict"); step("visitor: check returns a verdict with rules", v.query_selector("#result .cite") is not None)
    v.click("[data-tab=ask]"); v.fill("#askQ","Do I need permission to fly near an airport?"); v.click("#askGo"); v.wait_for_selector("#askResult .cite"); step("visitor: Ask answers with cited rules", "R-001" in v.inner_text("#askResult"))
    v.click("[data-tab=sim]"); v.click("#exRoute"); v.click("#run"); v.wait_for_selector("#simResult .verdict", timeout=60000); step("visitor: route simulation finishes with a summary", "First issue" in v.inner_text("#simResult") or "No restriction" in v.inner_text("#simResult"))
    # 2 new pilot registers (code by email), adds a drone, uploads documents
    pg=page(); pg.goto(B+"/account.html?tab=register"); pg.fill("#rName","Flow Tester"); pg.fill("#rEmail",EMAIL); pg.fill("#rPhone","96"+N+"31"); pg.fill("#rPass",PW); pg.check("#rConsent")
    pg.click("#registerForm button[type=submit]"); pg.wait_for_selector("#otpForm:not(.hidden)"); pg.fill("#otpCode",code_for(EMAIL)); pg.click("#otpForm button[type=submit]"); pg.wait_for_url("**/index.html"); pg.wait_for_timeout(1500)
    step("pilot: registered with an emailed code", True)
    pg.click("[data-tab=flights]"); pg.wait_for_selector("#checklist"); 
    pg.fill("#dName","Test Quad"); pg.fill("#dWeight","900"); pg.click("#droneForm button[type=submit]"); pg.wait_for_selector("form[data-dv]")
    pg.fill("#pvCert","RPC-FLOW-"+N); pg.set_input_files("#pvFile",PNG); pg.click("#pvForm button[type=submit]"); pg.wait_for_selector("text=Waiting for an officer")
    pg.fill("form[data-dv] input[name=serial]","SER-FLOW-"+N); pg.set_input_files("form[data-dv] input[name=file]",PNG); pg.click("form[data-dv] button[type=submit]"); pg.wait_for_timeout(1500)
    step("pilot: sent pilot and drone documents for verification", "Waiting for an officer" in pg.inner_text("#pilotVerify"))
    # 3 admin verifies both
    a=page(); signin(a,*ADMIN,"official.html"); a.click("[data-tab=verify]"); a.wait_for_selector("#verList .item")
    n=0
    while a.query_selector("#verList [data-vd=approved]") and n<4:
        a.click("#verList [data-vd=approved] >> nth=0"); a.wait_for_timeout(1200); n+=1
    step("admin: verified the pilot and the drone", n>=2)
    # 4 pilot requests permission in a yellow zone
    pg.reload(); pg.wait_for_timeout(2000)
    sel=pg.query_selector("#drone"); opts=pg.eval_on_selector_all("#drone option","o=>o.map(x=>[x.value,x.textContent])")
    mine=[o for o in opts if "Test Quad" in o[1]][0]; pg.select_option("#drone",mine[0])
    # find a yellow-zone example
    texts=[t.inner_text() for t in pg.query_selector_all("#examples button")]
    idx=[i for i,t in enumerate(texts) if "Secretariat" in t][0]; pg.click(f"#examples button >> nth={idx}", timeout=8000); pg.wait_for_timeout(5000); print("RESULT:", pg.inner_text("#result")[:200].replace("\n"," | ")); print("ACTIONS:", pg.inner_text("#actions")[:200].replace("\n"," | ")); print("DRONE:", pg.evaluate("document.getElementById('drone').selectedOptions[0].textContent")); pg.wait_for_selector("#fAsk", timeout=15000)
    pg.select_option("#drone",mine[0]); pg.click("#go"); pg.wait_for_selector("#fAsk"); pg.wait_for_timeout(1200)
    step("pilot: sees which office will review the request", "Reviewed by" in pg.inner_text("#routeInfo"))
    pg.fill("#fPurpose","End to end test"); pg.click("#fAsk"); pg.wait_for_selector("#fMsg .msg"); step("pilot: permission request sent and routed", "Reviewed by" in pg.inner_text("#fMsg"))
    pg.screenshot(path=SHOTS+"/z1_request.png")
    # 5 the right officer approves
    o=page(); signin(o,*POLICE,"official.html"); o.wait_for_selector("#reqList .item"); step("officer: sees the request in their own queue", "Flow Tester" in o.inner_text("#reqList"))
    o.fill("#reqList textarea","Daylight only\nStay 50 m from the building"); o.click("#reqList [data-decide=approved] >> nth=0"); o.wait_for_timeout(1500)
    o.screenshot(path=SHOTS+"/z2_officer.png")
    # 6 pilot sees the permit, passes preflight, and the flight moves to "Cleared"
    pg.click("[data-tab=flights]"); pg.wait_for_selector(".permit"); step("pilot: permit with QR appears", pg.query_selector(".permit svg") is not None)
    step("pilot: the flight shows its lifecycle", "Approved" in pg.inner_text("#flightList .flow"))
    pg.click("[data-pre] >> nth=0"); pg.wait_for_selector("[data-launch]", timeout=20000); step("pilot: preflight cleared and Take off is offered", "Cleared" in pg.inner_text("#flightList .next") or pg.query_selector("[data-launch]") is not None)
    pg.screenshot(path=SHOTS+"/z3_cleared.png")
    # 7 pilot takes off: the drone is in the air and the bar shows it
    pg.click("[data-launch] >> nth=0"); pg.wait_for_selector("#flightBar:not(.hidden)", timeout=20000); pg.wait_for_timeout(3500)
    step("pilot: took off, the flight bar shows the drone", "flying" in pg.inner_text("#flightBar").lower())
    step("pilot: live numbers are on the flight card", pg.query_selector("#flightList .telemetry .n") is not None)
    pg.screenshot(path=SHOTS+"/z4_flying.png")
    tok = json.loads(pg.evaluate("localStorage.getItem('skyclear.session')"))["access_token"]
    mine = json.loads(urllib.request.urlopen(urllib.request.Request(B+"/live/drones", headers={"Authorization": "Bearer "+tok})).read())["drones"]
    step("pilot: sees their own drone on the live feed", len(mine) == 1 and mine[0]["kind"] == "flight")
    # 8 the officer sees it in the air
    a.click("[data-tab=live]"); a.wait_for_selector("#airList .item", timeout=20000); step("admin: sees the flight in the air on the Live tab", "Flow Tester" in a.inner_text("#airList"))
    a.screenshot(path=SHOTS+"/z5_live.png")
    # 9 admin publishes a restriction over the flight: pilot is alerted and the drone is told it is inside
    flight = json.loads(urllib.request.urlopen(urllib.request.Request(B+"/flights", headers={"Authorization": "Bearer "+tok})).read())[0]
    a.click("[data-tab=publish]"); a.evaluate(f"setCentre({{lat:{flight['lat']},lng:{flight['lng']}}})"); a.fill("#nTitle","Flow test VIP movement"); a.fill("#nRadius","1"); a.click("#nGo"); a.wait_for_selector("#nMsg .msg")
    msg=a.inner_text("#nMsg"); step("admin: notice published and alerted the pilot's flight", "alerted" in msg); step("admin: notice lists the conflicting permit", "conflict" in msg)
    pg.wait_for_selector("#banner:not(.hidden)", timeout=20000); step("pilot: red alert banner appears", "Flow test VIP movement" in pg.inner_text("#bannerText") or "restricted airspace" in pg.inner_text("#bannerText").lower())
    pg.click("[data-tab=alerts]"); pg.wait_for_timeout(1500)
    for _ in range(12):
        if "entered restricted airspace" in pg.inner_text("#alertList"): break
        pg.click("[data-tab=check]"); pg.wait_for_timeout(2500); pg.click("[data-tab=alerts]"); pg.wait_for_timeout(1500)
    step("pilot: told the drone is inside the restricted airspace", "entered restricted airspace" in pg.inner_text("#alertList"))
    pg.screenshot(path=SHOTS+"/z6_breach.png")
    # 10 the officer recalls the drone by revoking the permit: it flies home and lands
    o.click("#fAll"); o.wait_for_selector("[data-revoke]"); o.fill("[id^=rv-]","Superseded by the VIP movement"); o.click("[data-revoke]"); o.wait_for_timeout(1500)
    step("officer: revoked the permit", "Revoked" in o.inner_text("#reqList"))
    pg.click("[data-tab=flights]"); pg.wait_for_timeout(3500)
    step("pilot: the flight bar says the drone was recalled", "recalled" in pg.inner_text("#flightBar").lower() or "returning" in pg.inner_text("#flightBar").lower())
    pg.click("[data-land] >> nth=0"); pg.wait_for_selector("#flightList .msg:has-text('Flight log')", timeout=20000)
    step("pilot: landed, and the flight log shows the breach", "restricted airspace entered 1 time" in pg.inner_text("#flightList") or "restricted airspace entered" in pg.inner_text("#flightList"))
    step("pilot: the lifecycle ends as Recalled", "Recalled" in pg.inner_text("#flightList .flow"))
    pg.screenshot(path=SHOTS+"/z7_landed.png")
    cleanup()
    print("\nconsole errors:", [e for e in errs if "404" not in e and "nominatim" not in e.lower()][:5])
    b.close()
print(f"\n{sum(1 for _,c in ok if c)}/{len(ok)} steps passed")
