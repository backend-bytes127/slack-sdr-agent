# Setup guide

This takes about 45 minutes from zero. You'll create the accounts and keys, fill `.env`, deploy, and send one
`/prospect` to check it works.

**Prerequisites:** Docker Desktop, Python 3.10+, `psql`, an [ngrok](https://ngrok.com) account, and a Slack workspace
where you can install apps.

```bash
git clone https://github.com/backend-bytes127/slack-sdr-agent && cd slack-sdr-agent
cp .env.example .env
```

Every key below goes into `.env`. That file is gitignored; never commit it.

---

## 1. n8n + nginx (local)

```bash
# A long random string. n8n encrypts stored credentials with it, so keep it stable.
echo "N8N_ENCRYPTION_KEY=$(openssl rand -hex 24)" >> .env
docker compose up -d
open http://localhost:8088        # create the n8n owner account on first visit
```

nginx proxies `/webhook/*` publicly. The editor answers only on `localhost:8088`; through the tunnel it returns 403.

## 2. Supabase (database)

1. Create a project at [supabase.com](https://supabase.com).
2. In **Connect → Session pooler**, copy the host, user and password into `PG_HOST`, `PG_USER` and `PG_PASSWORD`. Then set `PG_PORT=5432`, `PG_DATABASE=postgres`, `PG_SSL=require` and `PG_ALLOW_UNAUTHORIZED_CERTS=true`. Use the pooler: the direct `db.<ref>` host is IPv6-only and Docker usually can't reach it.
3. Load the schema:
   ```bash
   psql "postgresql://$PG_USER:$PG_PASSWORD@$PG_HOST:5432/postgres?sslmode=require" -f db/schema.sql
   ```

## 3. Public URL (ngrok)

```bash
ngrok http 8088
```

Put the `https://….ngrok-free.app/` URL in `WEBHOOK_URL`, with the trailing slash. A free URL changes every time
ngrok restarts. A static domain avoids having to update Slack each time.

## 4. Slack app

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App → From a manifest**.
2. Paste [`slack/manifest.json`](../slack/manifest.json) after replacing `YOUR-NGROK-DOMAIN` with your ngrok host.
3. **Install to Workspace.** Copy the **Bot User OAuth Token** into `SLACK_BOT_TOKEN`.
4. Under **Basic Information**, copy the **Signing Secret** into `SLACK_SIGNING_SECRET`.
5. Create a channel (e.g. `#sdr-agent`), run `/invite @SDR Agent`, and copy the channel ID into `SLACK_CHANNEL_ID`. The ID is at the bottom of the channel details.

The manifest asks for these scopes: `commands`, `chat:write`, `chat:write.public`, `users:read`, `users:read.email`.

## 5. HubSpot

1. **Settings → Integrations → Private apps** (or a personal access key). Give it these scopes:
   - `crm.objects.contacts.read` / `write`
   - `crm.objects.companies.read` / `write`
   - `crm.objects.owners.read`
   - `crm.schemas.contacts.write`
2. Copy the token into `HUBSPOT_TOKEN`. Put the portal ID (the number in the HubSpot URL) in `HUBSPOT_PORTAL_ID`.
3. Create the custom contact properties (LinkedIn URL, followers, connections, research summary) and list your owners:
   ```bash
   python3 scripts/hubspot_setup.py
   ```
4. Map each SDR's Slack user to their HubSpot owner, so new contacts get the right owner:
   ```sql
   insert into sdr_owner_map (slack_user_id, hubspot_owner_id, sdr_name) values ('U0123ABC', '12345678', 'Your Name');
   ```

## 6. HeyReach (LinkedIn sequences)

1. Connect your LinkedIn account under **LinkedIn Accounts**. Its numeric ID goes in `HEYREACH_LINKEDIN_ACCOUNT_ID`.
2. Create two campaigns with that sender:
   - **No-answer follow-up**: connection request plus follow-ups. You can use the custom variable `{talking_point}`, which the agent fills from the research.
   - **Post-call follow-up**: one message step whose body is just `{custom_message}`. The agent sends the SDR-approved draft as that variable.
3. Put the campaign IDs (from each campaign's URL) in `HEYREACH_NOANSWER_CAMPAIGN_ID` and `HEYREACH_POSTCALL_CAMPAIGN_ID`.
4. **Settings → API**: create a key and put it in `HEYREACH_API_KEY`.
5. Start both campaigns. HeyReach sends only during the campaign's working hours, in its own batches, so a newly added lead can take a while to go from *Not enrolled yet* to *In progress*.

## 7. Instantly (email sequences)

1. Connect a sending mailbox under **Email Accounts**. Google Workspace or Microsoft 365 is best, and let it warm up first.
2. Create a campaign (e.g. *SDR Agent – No-answer*) and write the sequence. `{{firstName}}`, `{{companyName}}` and `{{talking_point}}` are available.
3. In the campaign's **Settings**, attach the mailbox under *Accounts To Use* and check the **schedule**: days, hours and timezone. Nothing sends outside it.
4. Launch the campaign. Put its ID (from the URL) in `INSTANTLY_CAMPAIGN_ID`.
5. **Settings → API keys**: create a v2 key with at least `leads:create` and `campaigns:read`. Put it in `INSTANTLY_API_KEY`.

The agent adds a lead to Instantly only when its email is verified valid.

## 8. Enrichment providers

| Key | Where to get it |
|---|---|
| `DEEPLINE_API_KEY` | [deepline.com](https://code.deepline.com): CLI `deepline auth register`, or the dashboard. One key covers HarvestAPI (LinkedIn), Datagma and Hunter |
| `PROSPEO_API_KEY` | [prospeo.io](https://prospeo.io) → API. The free plan includes credits |
| `ENRICH_PROVIDER` | `deepline_prospeo` (default), or `clay` to use the Clay tables in [`clay/CLAY_SETUP.md`](../clay/CLAY_SETUP.md) |

## 9. LLM

Any OpenAI-compatible endpoint works. Set `LLM_API_KEY` and `LLM_BASE_URL` (e.g. `https://api.openai.com/v1`, or an
Azure OpenAI `/openai/v1` URL), plus `LLM_MODEL` (default `gpt-5-mini`).

**Buyer persona.** `BUYER_PERSONA` is plain English that the expansion step scores people against. For example:

```
Titles: Head/VP/Director of Sales, Sales Ops, RevOps, Growth, Marketing, CRO, CEO/Founder (companies under 200).
Exclude: intern, recruiter, talent, HR, student, assistant.
```

## 10. Deploy and smoke test

```bash
./scripts/deploy.sh     # builds 15 workflows + credentials from .env, imports, publishes, restarts n8n
```

In Slack, run `/prospect https://www.linkedin.com/in/<a-test-profile>`. Within about 30 seconds you should see:

1. "Got it, enriching now" (only visible to you)
2. A thread: "⏳ Enriching …"
3. The lead card, with **Picked up / No answer / Wrong person**

Check the executions:

```bash
python3 scripts/executions.py      # recent runs, with the failing node and its error
```

Re-run `./scripts/deploy.sh` after any change to `.env` or `scripts/*.py`.

## 11. Run the test suite

```bash
python3 scripts/mock_apis.py 9911 /tmp/mock.jsonl &      # fake Slack, HubSpot, HeyReach, Instantly, Deepline, Prospeo
cp .env .env.real && cp .env.mock .env && ./scripts/deploy.sh
python3 scripts/e2e_mock_test.py /tmp/mock.jsonl         # 33 checks
cp .env.real .env && ./scripts/deploy.sh                 # back to the real config
```

`.env.mock` points every API at the mock server and the database at the local Postgres container. Copy `.env` to
`.env.mock` and change those values.

## Troubleshooting

| Symptom | Likely cause → fix |
|---|---|
| `/prospect` says "dispatch_failed" | ngrok isn't running, or the URL changed → update `WEBHOOK_URL`, the Slack manifest URLs, then `deploy.sh` |
| Slack shows "operation_timeout" | n8n was restarting. Wait about 10 s after a deploy; webhooks register a few seconds after the health check passes |
| Every request is rejected | Wrong `SLACK_SIGNING_SECRET` (signature check fails) |
| Lead stuck on "Enriching" | Check `executions.py`. After 15 minutes the sweep marks it `error` and posts **Retry** |
| "Already in the pipeline" | That LinkedIn URL already exists (dedupe). The message links to its thread |
| HubSpot 403 | Token missing a scope from step 5 |
| HeyReach lead stays "Not enrolled yet" | The campaign isn't started, or it's outside its working hours |
| Instantly shows 0 sent | The campaign is paused, has no mailbox attached, or it's outside the schedule (check days and timezone) |
| `server does not support SSL` | Using the local `db` container: set `PG_SSL=disable` |
