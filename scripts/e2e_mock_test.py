"""End-to-end test of all workflows against scripts/mock_apis.py (real LLM, real Postgres).

  python3 scripts/e2e_mock_test.py <mock_log_file>
"""
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from slack_sim import env, slack_post  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MOCK_LOG = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "mock_requests.jsonl"
CHANNEL = env().get("SLACK_CHANNEL_ID", "C_TEST")
FAILURES = []


def q(sql):
    """Query whichever Postgres the n8n credential points at (PG_* in .env, else the local db container)."""
    cfg = env()
    if cfg.get("PG_HOST", "db") == "db":
        cmd = ["docker", "compose", "exec", "-T", "db", "psql", "-U", "sdr", "-d", "sdr"]
    else:
        conn = (f"host={cfg['PG_HOST']} port={cfg.get('PG_PORT', '5432')} user={cfg['PG_USER']} "
                f"dbname={cfg.get('PG_DATABASE', 'postgres')} sslmode=require")
        cmd = ["docker", "compose", "exec", "-T", "-e", f"PGPASSWORD={cfg['PG_PASSWORD']}", "db", "psql", conn]
    out = subprocess.check_output(cmd + ["-At", "-F", "|", "-c", sql], cwd=ROOT, text=True)
    return [line.split("|") for line in out.strip().splitlines() if line]


def wait_for(sql, expect, timeout=40):
    """Poll until the first column equals expect (or is one of expect, when a tuple)."""
    wanted = expect if isinstance(expect, tuple) else (expect,)
    deadline = time.time() + timeout
    rows = None
    while time.time() < deadline:
        rows = q(sql)
        if rows and rows[0][0] in wanted:
            return rows
        time.sleep(1.5)
    return rows


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def mock_calls(path_part, since):
    calls = []
    for line in MOCK_LOG.read_text().splitlines():
        rec = json.loads(line)
        if rec["t"] >= since and path_part in rec["path"]:
            calls.append(rec)
    return calls


def button(action, lead_id, user="U_TEST", message_ts="1.1"):
    payload = {"type": "block_actions", "user": {"id": user, "name": "tester"}, "trigger_id": "fake.trigger",
               "channel": {"id": CHANNEL}, "container": {"message_ts": message_ts, "channel_id": CHANNEL},
               "actions": [{"action_id": action, "value": lead_id}]}
    return slack_post("sdr-actions", {"payload": json.dumps(payload)})


def submit(callback_id, lead_id, values, user="U_TEST"):
    selects = {"call_result", "message_goal"}
    state = {"values": {k: {k: ({"selected_option": {"value": v}} if k in selects else {"value": v})}
                        for k, v in values.items()}}
    payload = {"type": "view_submission", "user": {"id": user, "name": "tester"},
               "view": {"callback_id": callback_id, "state": state,
                        "private_metadata": json.dumps({"lead_id": lead_id, "channel": CHANNEL, "message_ts": "2.2"})}}
    return slack_post("sdr-actions", {"payload": json.dumps(payload)})


def wait_for_webhooks(timeout=60):
    """n8n registers webhooks a few seconds after /healthz turns green; wait until intake answers."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            status, _ = slack_post("sdr-intake", {"text": "warm-up", "user_id": "U_TEST", "channel_id": CHANNEL,
                                                  "response_url": "http://host.docker.internal:9911/resp"})
            if status == 200:
                return
        except OSError:
            pass
        time.sleep(2)


def main():
    wait_for_webhooks()
    t0 = time.time()
    url = "https://www.linkedin.com/in/jane-doe-e2e"

    # WF1 intake + dedupe
    check("WF1 ack", slack_post("sdr-intake", {"text": url + "/?trk=x", "user_id": "U_TEST", "channel_id": CHANNEL,
                                               "response_url": "http://host.docker.internal:9911/resp"})[0] == 200)
    rows = wait_for(f"select status from leads where linkedin_url = '{url}'", ("enriching", "enriched", "in_crm"))
    check("WF1 lead created and enrichment started", bool(rows), rows)
    lead = q(f"select id, slack_thread_ts from leads where linkedin_url = '{url}'")[0]
    lead_id = lead[0]
    check("WF1 thread ts saved", bool(lead[1]))
    check("Enrich: Deepline profile called with the URL",
          any(c["body"]["payload"].get("url") == url for c in mock_calls("harvestapi_get_profile", t0)))
    check("Enrich: Prospeo person called", len(mock_calls("/prospeo/enrich-person", t0)) >= 1)
    slack_post("sdr-intake", {"text": url, "user_id": "U_OTHER", "channel_id": CHANNEL,
                              "response_url": "http://host.docker.internal:9911/resp"})
    time.sleep(4)
    check("WF1 dedupe", q(f"select count(*) from leads where linkedin_url = '{url}'")[0][0] == "1")
    check("WF1 duplicate reply", any("Already in the pipeline" in str(c["body"]) for c in mock_calls("/resp", t0)))

    # WF2 enrichment callback (posted by the enrich sub) -> HubSpot -> card
    wait_for(f"select (card_message_ts is not null)::text from leads where id = '{lead_id}'", "true")
    rows = wait_for(f"select status, hubspot_contact_id, card_message_ts from leads where id = '{lead_id}'", "in_crm")
    check("WF2 status in_crm + HubSpot id", rows and rows[0][0] == "in_crm" and rows[0][1] == "5001", rows)
    check("WF2 card ts saved", rows and bool(rows[0][2]))
    cards = [c for c in mock_calls("/slack/chat.postMessage", t0) if "Lead card" in str(c["body"].get("text"))]
    check("WF2 lead card has 3 buttons", cards and len(cards[-1]["body"]["blocks"][-1].get("elements", [])) == 3)
    row = q(f"select company_domain, work_email, email_status, research_summary is not null from leads where id = '{lead_id}'")[0]
    check("Enrich: domain, Prospeo email and LLM research saved",
          row[:3] == ["acme.io", "jane.doe@acme.io", "valid"] and row[3] == "t", row)

    # WF3 no answer -> HeyReach + Instantly + expansion
    t1 = time.time()
    button("call_no_answer", lead_id)
    rows = wait_for(f"select status from leads where id = '{lead_id}'", "sequenced")
    check("WF3 no-answer -> sequenced", rows and rows[0][0] == "sequenced", rows)
    time.sleep(4)
    check("WF3 HeyReach called once", len(mock_calls("/heyreach/", t1)) == 1)
    check("WF3 Instantly called once", len(mock_calls("/instantly/", t1)) == 1)
    ev = q(f"select action from outreach_events where lead_id = '{lead_id}' order by action")
    check("WF3 outreach events", [r[0] for r in ev] == ["heyreach_enrolled", "instantly_enrolled"], ev)
    check("WF3 HubSpot call logged", len(mock_calls("/hubspot/crm/v3/objects/calls", t1)) == 1)
    check("WF3 expansion searched Prospeo", len(mock_calls("/prospeo/search-person", t1)) == 1)
    button("call_no_answer", lead_id)
    time.sleep(5)
    check("WF3 double click ignored", len(mock_calls("/heyreach/", t1)) == 1)
    check("WF3 double click ephemeral", len(mock_calls("/slack/chat.postEphemeral", t1)) >= 1)

    # Expansion sub -> LLM fit -> Datagma -> WF5 callbacks -> one card
    t2 = t1
    rows = wait_for(f"select status, id from expansion_runs where lead_id = '{lead_id}'", "posted", timeout=90)
    check("WF5 run posted", rows and rows[0][0] == "posted", rows)
    run_id = rows[0][1] if rows else None
    sugg = q(f"select full_name, status, work_email from leads where expansion_run_id = '{run_id}' order by full_name")
    check("WF5 two suggestions (original + intern excluded)", [r[0] for r in sugg] == ["Bob Ops", "Cara Cmo"], sugg)
    check("WF5 suggestion emails from Datagma", sugg and sugg[0][2] == "bob.ops@acme.io", sugg)
    exp_cards = [c for c in mock_calls("/slack/chat.postMessage", t2) if "Account expansion" in str(c["body"].get("text"))]
    check("WF5 one expansion card", len(exp_cards) == 1)

    # WF3 add + skip
    bob = q("select id from leads where full_name = 'Bob Ops'")[0][0]
    cara = q("select id from leads where full_name = 'Cara Cmo'")[0][0]
    t3 = time.time()
    button("add_suggested_lead", bob)
    button("skip_suggested_lead", cara)
    rows = wait_for(f"select status from leads where id = '{bob}'", ("enriching", "enriched", "in_crm"))
    check("WF3 add as lead -> enrichment started", bool(rows), rows)
    check("WF3 skip", wait_for(f"select status from leads where id = '{cara}'", "skipped")[0][0] == "skipped")
    check("WF3 expansion card updated", len(mock_calls("/slack/chat.update", t3)) >= 2)

    # Second lead: connected path with real LLM
    url2 = "https://www.linkedin.com/in/max-connected-e2e"
    slack_post("sdr-intake", {"text": url2, "user_id": "U_TEST", "channel_id": CHANNEL,
                              "response_url": "http://host.docker.internal:9911/resp"})
    wait_for(f"select status from leads where linkedin_url = '{url2}'", "in_crm", timeout=90)
    lead2 = q(f"select id from leads where linkedin_url = '{url2}'")[0][0]
    t4 = time.time()
    button("call_connected", lead2)
    time.sleep(4)
    check("WF3 call-notes modal opened", len(mock_calls("/slack/views.open", t4)) == 1)
    submit("call_notes_submit", lead2, {"call_result": "interested", "message_goal": "share_a_resource",
                                        "call_notes": "They are hiring 3 AEs in DACH next quarter and hate manual CRM updates. Asked for our case study."})
    rows = wait_for(f"select status from leads where id = '{lead2}'", "message_drafted", timeout=90)
    check("WF3 AI draft created", rows and rows[0][0] == "message_drafted", rows)
    draft = q(f"select message from outreach_events where lead_id = '{lead2}' and action = 'message_drafted'")
    print("     draft:", draft[0][0] if draft else None)
    t5 = time.time()
    button("regenerate_message", lead2)
    time.sleep(20)
    check("WF3 regenerate", len(q(f"select 1 from outreach_events where lead_id = '{lead2}' and action = 'message_drafted'")) == 2)
    button("edit_message", lead2)
    time.sleep(4)
    check("WF3 edit modal opened", len(mock_calls("/slack/views.open", t5)) == 1)
    submit("edit_message_submit", lead2, {"draft_text": "Edited: great chat, sending the case study now."})
    time.sleep(5)
    button("send_message", lead2)
    rows = wait_for(f"select status from leads where id = '{lead2}'", "message_sent")
    check("WF3 send -> message_sent", rows and rows[0][0] == "message_sent", rows)
    time.sleep(3)
    hr = mock_calls("/heyreach/", t5)
    check("WF3 HeyReach post-call with edited text",
          hr and "Edited: great chat" in json.dumps(hr[-1]["body"]) and hr[-1]["body"]["campaignId"] == 333)
    check("No workflow errors", q("select count(*) from workflow_errors")[0][0] == "0",
          q("select workflow, step, left(error, 200) from workflow_errors"))

    print(f"\n{len(FAILURES)} failure(s)" + (": " + ", ".join(FAILURES) if FAILURES else ""))
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
