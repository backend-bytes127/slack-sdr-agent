"""WF3 Actions: every Slack button click and modal submit."""
from lib import Workflow, call, code, http, if_true, noop, respond, slack, sql, switch, webhook
from subs import guard

A = "$('Parse Slack payload').first().json"
VALID_EMAIL = "['valid', 'deliverable', 'verified'].includes(String({l}.email_status).toLowerCase())"
TALKING_POINT = ("(String({l}.talking_points || '').split('\\n')[0].replace(/^[•*-]\\s*/, '').trim() "
                 "|| ({l}.title ? 'your work as ' + {l}.title : 'your role'))")
NOW = "$now.setZone($env.TZ || 'UTC').toFormat('HH:mm')"
LATEST_DRAFT = ("(select message from outreach_events o where o.lead_id = leads.id "
                "and o.action = 'message_drafted' order by o.created_at desc limit 1)")


def _ephemeral(wf, name, text_expr, pos=None):
    return slack(wf, name, "'chat.postEphemeral'",
                 f"({{ channel: {A}.channel, user: {A}.user_id, text: {text_expr} }})", pos=pos)


def _claim(wf, name, new_status, from_statuses, extra_returning=""):
    allowed = ", ".join(f"'{s}'" for s in from_statuses)
    return sql(wf, name,
               f"update leads set status = '{new_status}' where id = $1::uuid and status in ({allowed}) "
               f"returning *{extra_returning}",
               f"[{A}.lead_id]", always_output=True)


def branch_no_answer(wf, sw):
    wf._x = 900
    L = "$('No answer: claim').first().json"
    claim = _claim(wf, "No answer: claim", "called_no_answer", ["in_crm", "enriched"],
                   ", exists(select 1 from outreach_events o where o.lead_id = leads.id and o.action = 'heyreach_enrolled') as hr_done"
                   ", exists(select 1 from outreach_events o where o.lead_id = leads.id and o.action = 'instantly_enrolled') as in_done")
    claimed = if_true(wf, "No answer: claimed?", "Boolean($json.id)")
    already = _ephemeral(wf, "No answer: already handled", "'Already handled: this lead is already sequenced. Nothing changed.'",
                         pos=[wf._x, 150])
    log = sql(wf, "No answer: log call",
              "insert into call_logs (lead_id, sdr_slack_id, outcome) values ($1::uuid, $2, 'no_answer') returning lead_id",
              f"[{L}.id, {A}.user_id ?? null]")
    need_hr = if_true(wf, "HeyReach needed?", f"!{L}.hr_done")
    tp = TALKING_POINT.format(l=L)
    heyreach = http(wf, "HeyReach: no-answer campaign", "POST",
                    "={{ ($env.HEYREACH_API_BASE || 'https://api.heyreach.io/api/public') + '/campaign/AddLeadsToCampaignV2' }}", "heyreach",
                    body_expr=f"JSON.stringify({{ campaignId: Number($env.HEYREACH_NOANSWER_CAMPAIGN_ID), accountLeadPairs: [{{ "
                              f"linkedInAccountId: Number($env.HEYREACH_LINKEDIN_ACCOUNT_ID), lead: {{ "
                              f"firstName: {L}.first_name || '', lastName: {L}.last_name || '', profileUrl: {L}.linkedin_url, "
                              f"companyName: {L}.company_name || '', position: {L}.title || '', emailAddress: {L}.work_email || '', "
                              f"customUserFields: [{{ name: 'talking_point', value: {tp} }}] }} }}] }})", retry=True)
    rec_hr = sql(wf, "Record HeyReach enrolment",
                 "insert into outreach_events (lead_id, channel, action, external_id) "
                 "values ($1::uuid, 'linkedin', 'heyreach_enrolled', $2) on conflict do nothing returning lead_id",
                 f"[{L}.id, String($env.HEYREACH_NOANSWER_CAMPAIGN_ID)]", always_output=True)
    email_ok = if_true(wf, "Valid email, not enrolled?", f"{VALID_EMAIL.format(l=L)} && !{L}.in_done")
    instantly = http(wf, "Instantly: create lead", "POST", "={{ ($env.INSTANTLY_API_BASE || 'https://api.instantly.ai/api/v2') + '/leads' }}", "instantly",
                     body_expr=f"JSON.stringify({{ campaign: $env.INSTANTLY_CAMPAIGN_ID, email: {L}.work_email, "
                               f"first_name: {L}.first_name, last_name: {L}.last_name, company_name: {L}.company_name, "
                               f"personalization: {tp}, custom_variables: {{ talking_point: {tp}, linkedin_url: {L}.linkedin_url }} }})",
                     retry=True)
    rec_in = sql(wf, "Record Instantly enrolment",
                 "insert into outreach_events (lead_id, channel, action, external_id) "
                 "values ($1::uuid, 'email', 'instantly_enrolled', $2) on conflict do nothing returning lead_id",
                 f"[{L}.id, $json.id ?? $env.INSTANTLY_CAMPAIGN_ID]", always_output=True)
    rec_skip = sql(wf, "Record email skipped",
                   "insert into outreach_events (lead_id, channel, action, message) "
                   "values ($1::uuid, 'email', 'email_skipped', $2) returning lead_id",
                   f"[{L}.id, {L}.in_done ? 'already enrolled in Instantly' : 'no valid email (status: ' + ({L}.email_status || 'none') + ')']",
                   pos=[wf._x, 150])
    seq = sql(wf, "Mark sequenced", "update leads set status = 'sequenced' where id = $1::uuid returning *",
              f"[{L}.id]")
    hs = call(wf, "HubSpot: log no-answer call", "hs_call", {
        "lead_id": f"{L}.id", "disposition": "'no_answer'", "title": "'Call: no answer'",
        "body": "'Enrolled in HeyReach' + ($('Instantly: create lead').isExecuted ? ' and Instantly' : '') + ' follow-up by the SDR Agent.'"})
    card = call(wf, "Update card: no answer", "lead_card", {
        "lead_id": f"{L}.id", "mode": "'update'",
        "note": f"':telephone_receiver: *No answer*: enrolled in LinkedIn' + ($('Instantly: create lead').isExecuted ? ' and email' : '') "
                f"+ ' sequences by <@' + {A}.user_id + '> at ' + {NOW} + '.' "
                f"+ ($('Instantly: create lead').isExecuted ? '' : ' Email skipped: ' + ({L}.in_done ? 'already enrolled.' : 'no valid email.')) "
                f"+ ' Finding more people at ' + ({L}.company_name || 'the company') + '…'"})
    expand = call(wf, "Start expansion (no answer)", "exp_start", {"lead_id": f"{L}.id"})

    wf.connect(sw, claim, out=0)
    wf.connect(claim, claimed)
    wf.connect(claimed, log, out=0)
    wf.connect(claimed, already, out=1)
    wf.connect(log, need_hr)
    wf.connect(need_hr, heyreach, out=0)
    wf.connect(need_hr, email_ok, out=1)
    wf.chain(heyreach, rec_hr, email_ok)
    wf.connect(email_ok, instantly, out=0)
    wf.connect(email_ok, rec_skip, out=1)
    wf.chain(instantly, rec_in, seq)
    wf.connect(rec_skip, seq)
    wf.chain(seq, hs, card, expand)
    guard(wf, heyreach, f"{A}.lead_id")
    guard(wf, instantly, f"{A}.lead_id")


def branch_wrong_person(wf, sw):
    wf._x = 900
    L = "$('Wrong person: claim').first().json"
    claim = _claim(wf, "Wrong person: claim", "disqualified", ["in_crm", "enriched"])
    claimed = if_true(wf, "Wrong person: claimed?", "Boolean($json.id)")
    already = _ephemeral(wf, "Wrong person: already handled", "'Already handled. Nothing changed.'")
    log = sql(wf, "Wrong person: log call",
              "insert into call_logs (lead_id, sdr_slack_id, outcome) values ($1::uuid, $2, 'wrong_person') returning lead_id",
              f"[{L}.id, {A}.user_id ?? null]")
    hs = call(wf, "HubSpot: log wrong person", "hs_call", {
        "lead_id": f"{L}.id", "disposition": "'wrong_number'", "title": "'Call: wrong person'",
        "body": "'SDR flagged this as the wrong person. Lead disqualified; searching the account for the right person.'"})
    card = call(wf, "Update card: wrong person", "lead_card", {
        "lead_id": f"{L}.id", "mode": "'update'",
        "note": f"':no_entry: *Wrong person*, flagged by <@' + {A}.user_id + '> at ' + {NOW} + '. Finding the right person at ' + ({L}.company_name || 'the company') + '…'"})
    expand = call(wf, "Start expansion (wrong person)", "exp_start", {"lead_id": f"{L}.id"})
    wf.connect(sw, claim, out=2)
    wf.connect(claim, claimed)
    wf.connect(claimed, log, out=0)
    wf.connect(claimed, already, out=1)
    wf.chain(log, hs, card, expand)


def branch_connected(wf, sw):
    wf._x = 900
    modal = code(wf, "Build call-notes modal", "modals")
    open_ = slack(wf, "Open call-notes modal", "'views.open'", "$json.payload")
    wf.connect(sw, modal, out=1)
    wf.connect(modal, open_)


def _post_draft(wf, prefix, source_expr, update_in_place):
    """Code (prep) -> draft blocks -> Slack. Returns (first, last) node names."""
    target = (f"channel: {A}.channel, message_ts: {A}.message_ts" if update_in_place else
              "channel: $('Notes: claim').first().json.slack_channel_id, thread_ts: $('Notes: claim').first().json.slack_thread_ts")
    prep = wf.add(f"{prefix}: prep draft", "n8n-nodes-base.code", 2, {"jsCode": (
        f"const src = {source_expr};\nreturn [{{ json: {{ lead_id: src.lead_id, draft: src.draft, {target} }} }}];")})
    blocks = code(wf, f"{prefix}: draft blocks", "draft_blocks")
    post = slack(wf, f"{prefix}: post draft", "$json.method", "$json.payload")
    wf.chain(prep, blocks, post)
    return prep, post


def branch_notes_submit(wf, sw):
    wf._x = 900
    L = "$('Notes: claim').first().json"
    V = f"{A}.values"
    claim = _claim(wf, "Notes: claim", "called_connected", ["in_crm", "enriched"])
    claimed = if_true(wf, "Notes: claimed?", "Boolean($json.id)")
    already = _ephemeral(wf, "Notes: already logged", "'This call was already logged. Nothing changed.'")
    log = sql(wf, "Notes: log call",
              "insert into call_logs (lead_id, sdr_slack_id, outcome, call_result, message_goal, notes) "
              "values ($1::uuid, $2, 'connected', $3, $4, $5) returning lead_id",
              f"[{L}.id, {A}.user_id ?? null, {V}.call_result ?? null, {V}.message_goal ?? null, {V}.call_notes ?? null]")
    hs = call(wf, "HubSpot: log connected call", "hs_call", {
        "lead_id": f"{L}.id", "disposition": "'connected'",
        "title": f"'Call: connected (' + String({V}.call_result || '').replace(/_/g, ' ') + ')'",
        "body": f"{V}.call_notes || ''"})
    card = call(wf, "Update card: connected", "lead_card", {
        "lead_id": f"{L}.id", "mode": "'update'",
        "note": f"':white_check_mark: *Picked up* (' + String({V}.call_result || '').replace(/_/g, ' ') + '), notes logged by <@' + {A}.user_id + '> at ' + {NOW}"})
    wants = if_true(wf, "Draft a message?", f"{V}.call_result !== 'not_interested'")
    draft = call(wf, "AI draft (sub)", "draft", {
        "lead_id": f"{L}.id", "notes": f"{V}.call_notes || ''", "goal": f"{V}.message_goal || ''",
        "sdr_name": f"{A}.user_name || ''", "previous_draft": "''"})
    prep, post = _post_draft(wf, "Notes", "$('AI draft (sub)').first().json", update_in_place=False)
    save = sql(wf, "Record draft",
               "with e as (insert into outreach_events (lead_id, channel, action, message, external_id) "
               "values ($1::uuid, 'linkedin', 'message_drafted', $2, $3) returning id), "
               "u as (update leads set status = 'message_drafted' where id = $1::uuid returning *) "
               "select * from u",
               f"[{L}.id, $('AI draft (sub)').first().json.draft, $json.ts ?? null]")
    wf.connect(sw, claim, out=3)
    wf.connect(claim, claimed)
    wf.connect(claimed, log, out=0)
    wf.connect(claimed, already, out=1)
    wf.chain(log, hs, card, wants)
    wf.connect(wants, draft, out=0)
    wf.connect(draft, prep)
    wf.connect(post, save)


def _sent_payload(how):
    return (f"({{ channel: {A}.channel, ts: {A}.message_ts, text: 'Message sent', blocks: ["
            f"{{ type: 'section', text: {{ type: 'mrkdwn', text: '{how} by <@' + {A}.user_id + '> at ' + {NOW} }} }}, "
            f"{{ type: 'section', text: {{ type: 'mrkdwn', text: '```' + $('{{claim}}').first().json.draft + '```' }} }} ] }})")


def branch_send(wf, sw, out, prefix, manual):
    wf._x = 900
    claim_name = f"{prefix}: claim"
    L = f"$('{claim_name}').first().json"
    claim = _claim(wf, claim_name, "message_sent", ["message_drafted"], f", {LATEST_DRAFT} as draft")
    claimed = if_true(wf, f"{prefix}: claimed?", "Boolean($json.id)")
    already = _ephemeral(wf, f"{prefix}: already sent", "'This message was already sent. Nothing changed.'")
    external_id = "'manual'" if manual else "String($env.HEYREACH_POSTCALL_CAMPAIGN_ID)"
    record = sql(wf, f"{prefix}: record sent",
                 "insert into outreach_events (lead_id, channel, action, message, external_id) "
                 "values ($1::uuid, 'linkedin', 'message_sent', $2, $3) returning lead_id",
                 f"[{L}.id, {L}.draft ?? '', {external_id}]")
    how = ":clipboard: *Marked as sent manually*" if manual else ":white_check_mark: *Sent via HeyReach*"
    update = slack(wf, f"{prefix}: update draft message", "'chat.update'",
                   _sent_payload(how).replace("{claim}", claim_name))
    note = call(wf, f"{prefix}: HubSpot note", "hs_note", {
        "lead_id": f"{L}.id",
        "body": f"'LinkedIn message {'sent manually by SDR' if manual else 'sent via HeyReach'}:\\n' + ({L}.draft || '')"})
    wf.connect(sw, claim, out=out)
    wf.connect(claim, claimed)
    wf.connect(claimed, already, out=1)
    if manual:
        wf.connect(claimed, record, out=0)
    else:
        heyreach = http(wf, f"{prefix}: HeyReach post-call campaign", "POST",
                        "={{ ($env.HEYREACH_API_BASE || 'https://api.heyreach.io/api/public') + '/campaign/AddLeadsToCampaignV2' }}", "heyreach",
                        body_expr=f"JSON.stringify({{ campaignId: Number($env.HEYREACH_POSTCALL_CAMPAIGN_ID), accountLeadPairs: [{{ "
                                  f"linkedInAccountId: Number($env.HEYREACH_LINKEDIN_ACCOUNT_ID), lead: {{ "
                                  f"firstName: {L}.first_name || '', lastName: {L}.last_name || '', profileUrl: {L}.linkedin_url, "
                                  f"companyName: {L}.company_name || '', position: {L}.title || '', "
                                  f"customUserFields: [{{ name: 'custom_message', value: {L}.draft || '' }}] }} }}] }})", retry=True)
        wf.connect(claimed, heyreach, out=0)
        wf.connect(heyreach, record)
        guard(wf, heyreach, f"{A}.lead_id")
    wf.chain(record, update, note)


def branch_edit(wf, sw):
    wf._x = 900
    load = sql(wf, "Edit: load draft",
               f"select leads.id as lead_id, {LATEST_DRAFT} as draft from leads "
               "where leads.id = $1::uuid and leads.status = 'message_drafted'", f"[{A}.lead_id]")
    modal = code(wf, "Build edit modal", "modals")
    open_ = slack(wf, "Open edit modal", "'views.open'", "$json.payload")
    wf.connect(sw, load, out=5)
    wf.chain(load, modal, open_)


def branch_edit_submit(wf, sw):
    wf._x = 900
    save = sql(wf, "Edit: save draft",
               "insert into outreach_events (lead_id, channel, action, message, external_id) "
               "select id, 'linkedin', 'message_drafted', $2, 'edited' from leads "
               "where id = $1::uuid and status = 'message_drafted' returning lead_id, message as draft",
               f"[{A}.lead_id, {A}.values.draft_text ?? '']")
    prep, _ = _post_draft(wf, "Edit", "$json", update_in_place=True)
    wf.connect(sw, save, out=6)
    wf.connect(save, prep)


def branch_regenerate(wf, sw):
    wf._x = 900
    load = sql(wf, "Regenerate: load",
               f"select leads.id as lead_id, {LATEST_DRAFT} as draft, c.notes, c.message_goal from leads "
               "left join lateral (select notes, message_goal from call_logs where lead_id = leads.id "
               "and outcome = 'connected' order by created_at desc limit 1) c on true "
               "where leads.id = $1::uuid and leads.status = 'message_drafted'", f"[{A}.lead_id]")
    draft = call(wf, "AI redraft (sub)", "draft", {
        "lead_id": "$json.lead_id", "notes": "$json.notes || ''", "goal": "$json.message_goal || ''",
        "sdr_name": f"{A}.user_name || ''", "previous_draft": "$json.draft || ''"})
    save = sql(wf, "Regenerate: record draft",
               "insert into outreach_events (lead_id, channel, action, message, external_id) "
               "values ($1::uuid, 'linkedin', 'message_drafted', $2, 'regenerated') returning lead_id, message as draft",
               "[$json.lead_id, $json.draft]")
    prep, _ = _post_draft(wf, "Regenerate", "$json", update_in_place=True)
    wf.connect(sw, load, out=7)
    wf.chain(load, draft, save, prep)


def branch_suggested(wf, sw):
    wf._x = 900
    add = sql(wf, "Add: claim suggested",
              "update leads set status = 'received', sdr_slack_id = coalesce($2, sdr_slack_id) "
              "where id = $1::uuid and status = 'suggested' returning *",
              f"[{A}.lead_id, {A}.user_id ?? null]")
    card_a = call(wf, "Add: refresh expansion card", "exp_card", {"run_id": "$json.expansion_run_id"})
    enrich = call(wf, "Add: enrich (sub)", "enrich", {"lead_id": "$('Add: claim suggested').first().json.id"})
    wf.connect(sw, add, out=9)
    wf.chain(add, card_a, enrich)
    wf._x = 900
    skip = sql(wf, "Skip: mark skipped",
               "update leads set status = 'skipped' where id = $1::uuid and status = 'suggested' returning *",
               f"[{A}.lead_id]", pos=[900, 1500])
    card_s = call(wf, "Skip: refresh expansion card", "exp_card", {"run_id": "$json.expansion_run_id"},
                  pos=[1140, 1500])
    wf.connect(sw, skip, out=10)
    wf.connect(skip, card_s)


RETRY_SQL = """
update leads set status = case
  when enrichment is null then 'received'
  when hubspot_contact_id is null then 'enriched'
  when exists (select 1 from outreach_events o where o.lead_id = leads.id and o.action = 'message_drafted')
   and not exists (select 1 from outreach_events o where o.lead_id = leads.id and o.action = 'message_sent') then 'message_drafted'
  when exists (select 1 from outreach_events o where o.lead_id = leads.id and o.action = 'heyreach_enrolled') then 'sequenced'
  else 'in_crm' end
where id = $1::uuid and status = 'error'
returning *, (select message from outreach_events o where o.lead_id = leads.id and o.action = 'message_drafted'
              order by o.created_at desc limit 1) as draft
""".strip()


def branch_retry(wf, sw):
    wf._x = 900
    R = "$('Retry: reset status').first().json"
    reset = sql(wf, "Retry: reset status", RETRY_SQL, f"[{A}.lead_id]")
    route = switch(wf, "Retry: route", 4,
                   "({ received: 0, enriched: 1, message_drafted: 2 })[$json.status] ?? 3")
    enrich = call(wf, "Retry: re-enrich", "enrich", {"lead_id": f"{R}.id"})
    hs = call(wf, "Retry: HubSpot sync", "hs_sync", {"lead_id": f"{R}.id"})
    card = call(wf, "Retry: repost lead card", "lead_card", {"lead_id": f"{R}.id", "mode": "'post'", "note": "''"})
    prep = wf.add("Retry: prep draft", "n8n-nodes-base.code", 2, {"jsCode": (
        f"const l = {R};\nreturn [{{ json: {{ lead_id: l.id, draft: l.draft, channel: l.slack_channel_id, thread_ts: l.slack_thread_ts }} }}];")})
    blocks = code(wf, "Retry: draft blocks", "draft_blocks")
    post = slack(wf, "Retry: repost draft", "$json.method", "$json.payload")
    wf.connect(sw, reset, out=11)
    wf.connect(reset, route)
    wf.connect(route, enrich, out=0)
    wf.connect(route, hs, out=1)
    wf.connect(hs, card)
    wf.connect(route, prep, out=2)
    wf.chain(prep, blocks, post)
    wf.connect(route, card, out=3)


def wf3_actions():
    wf = Workflow("wf3", "SDR · WF3 Actions (buttons + modals)")
    hook = webhook(wf, "Slack interactivity", "sdr-actions", raw=True, pos=[0, 600])
    verify = code(wf, "Verify Slack signature", "verify_slack", pos=[200, 600])
    valid = if_true(wf, "Valid signature?", "$json.valid", pos=[400, 600])
    ack = respond(wf, "Ack 200", None, pos=[600, 500])
    reject = respond(wf, "Reject 401", "={{ JSON.stringify({ error: 'invalid signature' }) }}", code=401,
                     pos=[600, 750])
    parse = code(wf, "Parse Slack payload", "parse_action", pos=[800, 500])
    sw = switch(wf, "Route action", 13, "$json.route", pos=[1000, 500])
    ignore = noop(wf, "Unknown action", pos=[1250, 2300])
    wf.chain(hook, verify, valid)
    wf.connect(valid, ack, out=0)
    wf.connect(valid, reject, out=1)
    wf.chain(ack, parse, sw)
    wf.connect(sw, ignore, out=12)

    builders = [
        lambda: branch_no_answer(wf, sw),
        lambda: branch_connected(wf, sw),
        lambda: branch_wrong_person(wf, sw),
        lambda: branch_notes_submit(wf, sw),
        lambda: branch_send(wf, sw, 4, "Send", manual=False),
        lambda: branch_edit(wf, sw),
        lambda: branch_edit_submit(wf, sw),
        lambda: branch_regenerate(wf, sw),
        lambda: branch_send(wf, sw, 8, "Copy", manual=True),
        lambda: branch_suggested(wf, sw),
        lambda: branch_retry(wf, sw),
    ]
    for row, build in enumerate(builders):
        start = len(wf.nodes)
        build()
        for n in wf.nodes[start:]:
            if n["name"] != "Report error":
                n["position"] = [n["position"][0] + 400, row * 220]
    return wf
