-- Slack SDR Agent: source-of-truth schema (Supabase / Postgres)
-- Based on the Stable GTM project doc, plus the columns the workflows need.

create extension if not exists pgcrypto;

create table if not exists leads (
  id uuid primary key default gen_random_uuid(),
  linkedin_url text unique not null,
  first_name text, last_name text, full_name text,
  title text, headline text, location text, about text,
  company_name text, company_domain text, company_linkedin_url text,
  company_size text, industry text, company_description text,
  work_email text, email_status text,
  phone text, phone_type text,
  linkedin_followers int, linkedin_connections int,
  research_summary text, talking_points text,
  icp_fit text,
  enrichment jsonb,
  hubspot_contact_id text, hubspot_company_id text,
  sdr_slack_id text, slack_channel_id text, slack_thread_ts text,
  card_message_ts text,
  source text not null default 'slack_command',   -- or 'account_expansion'
  parent_lead_id uuid references leads(id),       -- set for suggested colleagues
  expansion_run_id uuid,                          -- which expansion run suggested this person
  fit_score int,
  fit_reason text,                                -- why the expansion search suggested this person
  status text not null default 'received',
  status_changed_at timestamptz default now(),
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists expansion_runs (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid references leads(id),
  company_domain text,
  company_name text,
  expected_total int,
  received_count int default 0,
  slack_channel_id text,
  slack_thread_ts text,
  slack_message_ts text,
  status text default 'searching',   -- searching, posted, empty, error
  created_at timestamptz default now()
);

create table if not exists call_logs (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid references leads(id),
  sdr_slack_id text,
  outcome text check (outcome in ('no_answer','connected','wrong_person','voicemail')),
  call_result text,      -- meeting_booked, interested, not_now, not_interested
  message_goal text,
  notes text,
  created_at timestamptz default now()
);

create table if not exists outreach_events (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid references leads(id),
  channel text check (channel in ('linkedin','email')),
  action text,       -- heyreach_enrolled, instantly_enrolled, email_skipped, message_drafted, message_sent
  message text,
  external_id text,  -- campaign or message ID from HeyReach / Instantly, or 'manual'
  created_at timestamptz default now()
);

create table if not exists workflow_errors (
  id bigserial primary key,
  workflow text, step text,
  lead_id uuid, error text, payload jsonb,
  created_at timestamptz default now()
);

-- Slack user -> HubSpot owner mapping (one row per SDR)
create table if not exists sdr_owner_map (
  slack_user_id text primary key,
  hubspot_owner_id text,
  sdr_name text
);

create index if not exists leads_status_idx on leads (status);
create index if not exists leads_parent_idx on leads (parent_lead_id);
create index if not exists leads_domain_idx on leads (company_domain);
create index if not exists call_logs_lead_idx on call_logs (lead_id);
create index if not exists outreach_lead_idx on outreach_events (lead_id);
create index if not exists expansion_domain_idx on expansion_runs (company_domain, created_at);

-- Enrolments happen at most once per lead per tool (double-click safety net)
create unique index if not exists outreach_enrol_once
  on outreach_events (lead_id, action)
  where action in ('heyreach_enrolled', 'instantly_enrolled', 'heyreach_postcall_enrolled');

-- Keep updated_at / status_changed_at honest
create or replace function touch_lead() returns trigger as $$
begin
  new.updated_at := now();
  if new.status is distinct from old.status then
    new.status_changed_at := now();
  end if;
  return new;
end $$ language plpgsql;

drop trigger if exists leads_touch on leads;
create trigger leads_touch before update on leads
  for each row execute function touch_lead();

-- Reporting views
create or replace view v_leads_per_sdr_per_day as
  select sdr_slack_id, date_trunc('day', created_at)::date as day, count(*) as leads
  from leads where source = 'slack_command' or status not in ('suggested','skipped')
  group by 1, 2;

create or replace view v_connect_rate as
  select sdr_slack_id,
         count(*) filter (where outcome = 'connected') as connected,
         count(*) as called,
         round(100.0 * count(*) filter (where outcome = 'connected') / nullif(count(*), 0), 1) as connect_rate_pct
  from call_logs group by 1;

create or replace view v_daily_summary as
  select
    (select count(*) from leads where created_at::date = current_date and source = 'slack_command') as new_leads,
    (select count(*) from call_logs where created_at::date = current_date) as calls,
    (select count(*) from call_logs where created_at::date = current_date and outcome = 'connected') as connected,
    (select count(distinct lead_id) from outreach_events where created_at::date = current_date and action = 'heyreach_enrolled') as sequenced,
    (select count(*) from leads where source = 'account_expansion' and status not in ('suggested','skipped') and updated_at::date = current_date) as colleagues_added,
    (select count(*) from leads where status = 'skipped' and updated_at::date = current_date) as colleagues_skipped,
    (select count(*) from outreach_events where created_at::date = current_date and action = 'message_sent') as messages_sent;

-- Supabase: keep Row Level Security on. n8n connects as the table owner (postgres) and bypasses it;
-- the publishable/anon key gets no access because no policies are defined.
alter table leads enable row level security;
alter table expansion_runs enable row level security;
alter table call_logs enable row level security;
alter table outreach_events enable row level security;
alter table workflow_errors enable row level security;
alter table sdr_owner_map enable row level security;
alter view v_leads_per_sdr_per_day set (security_invoker = true);
alter view v_connect_rate set (security_invoker = true);
alter view v_daily_summary set (security_invoker = true);
