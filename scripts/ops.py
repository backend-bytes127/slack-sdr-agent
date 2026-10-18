"""WF4: error workflow, stuck sweeps, daily summary and 90-day cleanup."""
from lib import Workflow, call, slack, sql

STUCK_LEADS_SQL = """
update leads set status = 'error'
where status = 'enriching' and status_changed_at < now() - interval '15 minutes'
returning id, full_name, linkedin_url
""".strip()

STUCK_RUNS_SQL = """
update expansion_runs set status = 'posting'
where status = 'searching' and created_at < now() - interval '10 minutes'
returning id
""".strip()

CLEANUP_SQL = """
with gone as (
  delete from leads
  where status = 'skipped' and source = 'account_expansion' and updated_at < now() - interval '90 days'
  returning id
)
select count(*) as deleted from gone
""".strip()


def wf4_errors():
    wf = Workflow("wf4", "SDR · WF4 Errors, sweeps & reporting", error_workflow=False)

    # Catch-all: any unhandled failure in WF1/2/3/5 or a sub-workflow
    trig = wf.add("Error Trigger", "n8n-nodes-base.errorTrigger", 1, {}, pos=[0, 0])
    log = sql(wf, "Log workflow error",
              "insert into workflow_errors (workflow, step, error, payload) values ($1, $2, $3, $4::jsonb) returning id",
              "[$json.workflow?.name ?? null, $json.execution?.lastNodeExecuted ?? null, "
              "String($json.execution?.error?.message ?? 'unknown error').slice(0, 2000), "
              "JSON.stringify({ execution_id: $json.execution?.id ?? null, url: $json.execution?.url ?? null })]",
              pos=[240, 0])
    alert = slack(wf, "Alert channel", "'chat.postMessage'",
                  "({ channel: $env.SLACK_CHANNEL_ID, text: ':rotating_light: Something failed in *' + "
                  "$('Error Trigger').first().json.workflow.name + '* at *' + "
                  "($('Error Trigger').first().json.execution.lastNodeExecuted || 'unknown step') + '*: ' + "
                  "String($('Error Trigger').first().json.execution.error?.message || '').slice(0, 500) })",
                  pos=[480, 0])
    wf.chain(trig, log, alert)

    # Stuck sweeps every 10 minutes
    every10 = wf.add("Every 10 minutes", "n8n-nodes-base.scheduleTrigger", 1.2,
                     {"rule": {"interval": [{"field": "minutes", "minutesInterval": 10}]}}, pos=[0, 250])
    stuck = sql(wf, "Find stuck enrichments", STUCK_LEADS_SQL, pos=[240, 200])
    report = call(wf, "Alert stuck lead", "report_err", {
        "workflow": "'SDR · WF4 sweep'", "step": "'Enrichment (no result after 15 min)'",
        "lead_id": "$json.id", "error": "'Enrichment never finished for ' + ($json.full_name || $json.linkedin_url)",
        "mark_lead": "false"}, pos=[480, 200], each=True)
    runs = sql(wf, "Find stuck expansion runs", STUCK_RUNS_SQL, pos=[240, 350])
    partial = call(wf, "Post partial expansion card", "exp_card", {"run_id": "$json.id"},
                   pos=[480, 350], each=True)
    wf.connect(every10, stuck)
    wf.connect(stuck, report)
    wf.connect(every10, runs)
    wf.connect(runs, partial)

    # Daily summary at 18:00
    daily = wf.add("Daily at 18:00", "n8n-nodes-base.scheduleTrigger", 1.2,
                   {"rule": {"interval": [{"field": "days", "triggerAtHour": 18}]}}, pos=[0, 550])
    stats = sql(wf, "Daily stats", "select * from v_daily_summary", pos=[240, 550])
    post = slack(wf, "Post daily summary", "'chat.postMessage'",
                 "({ channel: $env.SLACK_CHANNEL_ID, text: ':bar_chart: *SDR Agent today*\\n' + "
                 "'• New leads: ' + $json.new_leads + '\\n• Calls: ' + $json.calls + ' (connected ' + $json.connected + ')\\n' + "
                 "'• No-answer leads sequenced: ' + $json.sequenced + '\\n• Colleagues added / skipped: ' + "
                 "$json.colleagues_added + ' / ' + $json.colleagues_skipped + '\\n• Messages sent: ' + $json.messages_sent })",
                 pos=[480, 550])
    wf.chain(daily, stats, post)

    # Compliance: delete skipped suggestions after 90 days
    nightly = wf.add("Nightly at 03:00", "n8n-nodes-base.scheduleTrigger", 1.2,
                     {"rule": {"interval": [{"field": "days", "triggerAtHour": 3}]}}, pos=[0, 750])
    clean = sql(wf, "Delete old skipped suggestions", CLEANUP_SQL, pos=[240, 750])
    wf.connect(nightly, clean)
    return wf
