"""WF1 Intake, WF2 Enriched, WF5 Expansion results."""
from lib import Workflow, call, code, http, if_true, respond, slack, sql, webhook

ACK = "={{ JSON.stringify({ response_type: 'ephemeral', text: 'Got it, enriching now.' }) }}"


def wf1_intake():
    wf = Workflow("wf1", "SDR · WF1 Intake (/prospect)")
    norm = "$('Normalize URL').first().json"
    hook = webhook(wf, "Slack /prospect", "sdr-intake", raw=True)
    verify = code(wf, "Verify Slack signature", "verify_slack")
    valid = if_true(wf, "Valid signature?", "$json.valid")
    ack = respond(wf, "Ack within 3s", ACK)
    reject = respond(wf, "Reject 401", "={{ JSON.stringify({ error: 'invalid signature' }) }}", code=401,
                     pos=[wf._x - 240, 250])
    normalize = code(wf, "Normalize URL", "normalize_url")
    ok = if_true(wf, "Valid LinkedIn URL?", "$json.ok")
    bad = http(wf, "Reply invalid URL", "POST", "={{ $json.response_url }}",
               body_expr="JSON.stringify({ response_type: 'ephemeral', text: ':x: ' + $json.error })",
               pos=[wf._x, 250])
    insert = sql(wf, "Create lead (dedupe)",
                 "insert into leads (linkedin_url, sdr_slack_id, slack_channel_id, status, source) "
                 "values ($1, $2, $3, 'received', 'slack_command') "
                 "on conflict (linkedin_url) do nothing returning *",
                 "[$json.linkedin_url, $json.user_id ?? null, $env.SLACK_CHANNEL_ID ?? null]",
                 always_output=True)
    created = if_true(wf, "New lead?", "Boolean($json.id)")
    existing = sql(wf, "Load existing lead", "select * from leads where linkedin_url = $1",
                   f"[{norm}.linkedin_url]", pos=[wf._x, 250])
    dup = http(wf, "Reply already in pipeline", "POST", f"={{{{ {norm}.response_url }}}}",
               body_expr="JSON.stringify({ response_type: 'ephemeral', text: ':repeat: Already in the pipeline, owned by ' "
                         "+ ($json.sdr_slack_id ? '<@' + $json.sdr_slack_id + '>' : 'another SDR') + ', status `' + $json.status + '`' "
                         "+ ($json.slack_thread_ts ? ' · <https://slack.com/archives/' + $json.slack_channel_id + '/p' "
                         "+ String($json.slack_thread_ts).replace('.', '') + '|open thread>' : '') })",
               pos=[wf._x + 240, 250])
    thread = slack(wf, "Open Slack thread", "'chat.postMessage'",
                   f"({{ channel: $env.SLACK_CHANNEL_ID, unfurl_links: false, "
                   f"text: ':hourglass_flowing_sand: Enriching ' + {norm}.linkedin_url + ' for <@' + {norm}.user_id + '>' }})")
    save = sql(wf, "Save thread ts",
               "update leads set slack_channel_id = $2, slack_thread_ts = $3 where id = $1::uuid returning *",
               "[$('Create lead (dedupe)').first().json.id, $json.channel ?? null, $json.ts ?? null]")
    enrich = call(wf, "Enrich lead (sub)", "enrich", {"lead_id": "$json.id"})

    wf.chain(hook, verify, valid)
    wf.connect(valid, ack, out=0)
    wf.connect(valid, reject, out=1)
    wf.chain(ack, normalize, ok)
    wf.connect(ok, insert, out=0)
    wf.connect(ok, bad, out=1)
    wf.connect(insert, created)
    wf.connect(created, thread, out=0)
    wf.connect(created, existing, out=1)
    wf.connect(existing, dup)
    wf.chain(thread, save, enrich)
    return wf


WF2_UPDATE_SQL = """
update leads set
  first_name = $2, last_name = $3, full_name = $4, title = $5, headline = $6, location = $7, about = $8,
  company_name = $9, company_domain = $10, company_linkedin_url = $11, company_size = $12, industry = $13,
  company_description = $14, work_email = $15, email_status = $16, phone = $17, phone_type = $18,
  linkedin_followers = $19::int, linkedin_connections = $20::int, research_summary = $21, talking_points = $22,
  icp_fit = $23, enrichment = $24::jsonb, status = 'enriched'
where id = $1::uuid and status in ('received', 'enriching', 'error')
returning *
""".strip()

WF2_FIELDS = ["lead_id", "first_name", "last_name", "full_name", "title", "headline", "location", "about",
              "company_name", "company_domain", "company_linkedin_url", "company_size", "industry",
              "company_description", "work_email", "email_status", "phone", "phone_type",
              "linkedin_followers", "linkedin_connections", "research_summary", "talking_points", "icp_fit"]


def wf2_enriched():
    wf = Workflow("wf2", "SDR · WF2 Enriched (enrichment callback)")
    hook = webhook(wf, "Enrichment callback", "sdr-enriched", clay_auth=True)
    ack = respond(wf, "Ack 200", None)
    norm = code(wf, "Normalize enrichment payload", "clay_t1_normalize")
    args = ", ".join(f"$json.{f} ?? null" for f in WF2_FIELDS) + ", JSON.stringify($json.enrichment)"
    save = sql(wf, "Save enrichment", WF2_UPDATE_SQL, f"[{args}]")
    hs = call(wf, "HubSpot sync (sub)", "hs_sync", {"lead_id": "$json.id"})
    card = call(wf, "Post lead card (sub)", "lead_card",
                {"lead_id": "$('Save enrichment').first().json.id", "mode": "'post'", "note": "''"})
    wf.chain(hook, ack, norm, save, hs, card)
    return wf


WF5_PERSON_SQL = """
with run as (
  update expansion_runs set received_count = received_count + 1 where id = $1::uuid returning *
),
p as (select l.* from leads l join run on l.id = run.lead_id),
ins as (
  insert into leads (linkedin_url, first_name, last_name, full_name, title, headline, location,
                     linkedin_followers, linkedin_connections, work_email, email_status, fit_score, fit_reason,
                     enrichment, company_name, company_domain, company_linkedin_url,
                     source, parent_lead_id, expansion_run_id, status, sdr_slack_id, slack_channel_id, slack_thread_ts)
  select $2, $3, $4, $5, $6, $7, $8, $9::int, $10::int, $11, $12, $13::int, $14, $15::jsonb,
         p.company_name, p.company_domain, p.company_linkedin_url,
         'account_expansion', p.id, $1::uuid, 'suggested', p.sdr_slack_id, p.slack_channel_id, p.slack_thread_ts
  from p where $2 is not null and $2 <> p.linkedin_url
  on conflict (linkedin_url) do nothing
  returning id
)
select run.*, (select count(*) from ins) as inserted from run
""".strip()

WF5_PERSON_FIELDS = ["linkedin_url", "first_name", "last_name", "full_name", "title", "headline", "location",
                     "linkedin_followers", "linkedin_connections", "work_email", "email_status", "fit_score",
                     "fit_reason"]


def wf5_expansion():
    wf = Workflow("wf5", "SDR · WF5 Expansion results (expansion callback)")
    hook = webhook(wf, "Expansion callback", "sdr-expansion", clay_auth=True)
    ack = respond(wf, "Ack 200", None)
    norm = code(wf, "Normalize callback", "expansion_normalize")
    kind = if_true(wf, "Expected total?", "$json.kind === 'total'")
    total = sql(wf, "Save expected total",
                "update expansion_runs set expected_total = $2::int where id = $1::uuid returning *",
                "[$json.run_id, $json.expected_total ?? 0]")
    args = "$json.run_id, " + ", ".join(f"$json.{f} ?? null" for f in WF5_PERSON_FIELDS) + \
           ", JSON.stringify($json.enrichment)"
    person = sql(wf, "Store suggested colleague", WF5_PERSON_SQL, f"[{args}]", pos=[wf._x - 240, 250])
    complete = sql(wf, "All arrived?",
                   "update expansion_runs set status = 'posting' where id = $1::uuid and status = 'searching' "
                   "and expected_total is not null and received_count >= expected_total returning *",
                   "[$json.id]")
    card = call(wf, "Post expansion card (sub)", "exp_card", {"run_id": "$json.id"})
    wf.chain(hook, ack, norm, kind)
    wf.connect(kind, total, out=0)
    wf.connect(kind, person, out=1)
    wf.connect(total, complete)
    wf.connect(person, complete)
    wf.chain(complete, card)
    return wf
