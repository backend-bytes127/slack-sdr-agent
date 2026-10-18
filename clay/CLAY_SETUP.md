# Clay setup (2 tables)

> **As built (Table 1):** Workbook **SDR Agent** → table
> **SDR Agent: Enrich Person**. Built with Sculptor:
> lead_id / linkedin_url formulas → Enrich Person → Work Email waterfall → Validate Work Email →
> Enrich company firmographics → Mobile Phone waterfall (senior titles only) → Research (AI) → ICP Fit.
> Instead of mapping 20 fields into the HTTP body, a formula column **`n8n_payload`** packs everything into one
> JSON string (formulas evaluate even when inputs are empty; action columns don't). The **HTTP API** column posts
> `{"lead_id": "<lead_id>", "payload": <n8n_payload>}` with header `x-sdr-secret`, run condition
> `!!{{Research}} && !!{{lead_id}}` and a 120 s delay so the email/phone waterfalls can finish.
> n8n's `clay_t1_normalize.js` unpacks `payload` (person.latest_experience is the current employer).
> Known gap: "Enrich company firmographics" is wired to the first experience's domain, so for people with board
> seats it can return the wrong company; n8n discards firmographics whose domain ≠ the current employer's.

n8n sends rows in via each table's **Webhook source**, and Clay posts results back with an **HTTP API** column.
Every callback must send the header `x-sdr-secret: <CLAY_CALLBACK_SECRET from .env>`, or n8n rejects it with 403.

Public base URL = the ngrok URL (`WEBHOOK_URL` in `.env`).

## Table 1: `SDR Agent: Enrich Person`

1. **Source → Webhook.** Copy its URL into `.env` as `CLAY_T1_WEBHOOK_URL`.
   Incoming body: `{ lead_id, linkedin_url, source, sdr_slack_id }`
2. **Enrich person from LinkedIn profile** (input: `linkedin_url`): name, headline, title, location, about,
   followers, connections, current company LinkedIn URL and domain.
3. **Enrich company** (input: company LinkedIn URL or domain): size, industry, description.
4. **Work email waterfall** (name + domain), then **email validation**. Keep the status (`valid`, `invalid`, ...).
5. **Mobile phone waterfall**. Run condition: title matches persona seniority (VP, Head, Director, C-level, Founder).
6. **AI column `research`** (returns JSON):
   ```
   You are helping an SDR prepare a cold call. Person: {{full_name}}, {{title}} at {{company_name}}
   ({{company_size}}, {{industry}}). About: {{about}} Recent activity: {{recent_posts}}
   Company: {{company_description}}
   Return JSON with:
   - summary: 3 short bullets on who they are and what they likely care about
   - talking_points: 3 specific openers grounded ONLY in the data above
   No guesses. If data is missing, say so.
   ```
7. **Formula `icp_fit`** (optional): `yes` or `no` from seniority and company size.
8. **HTTP API column `Send to n8n`**:
   - Method `POST`, URL `<WEBHOOK_URL>webhook/sdr-enriched`
   - Header `x-sdr-secret: <CLAY_CALLBACK_SECRET>`
   - Run condition: the email validation and `research` columns are complete
   - Body (map each value to its column):
   ```json
   {
     "lead_id": "/lead_id",
     "first_name": "", "last_name": "", "full_name": "", "title": "", "headline": "",
     "location": "", "about": "", "linkedin_followers": "", "linkedin_connections": "",
     "company_name": "", "company_domain": "", "company_linkedin_url": "",
     "company_size": "", "industry": "", "company_description": "",
     "work_email": "", "email_status": "", "phone": "", "phone_type": "",
     "research": "/research", "icp_fit": ""
   }
   ```
   Numbers may be sent as strings (`"1,204"`), and `research` may be an object or a JSON string. n8n normalises both.

## Table 2: `SDR Agent: Account Expansion`

1. **Source → Webhook.** Copy its URL into `.env` as `CLAY_T2_WEBHOOK_URL`.
   Incoming body: `{ run_id, lead_id, company_domain, company_linkedin_url, company_name, original_linkedin_url, original_title, persona }`
2. **Find people at company** (domain or company LinkedIn URL), filtered by the persona
   (`BUYER_PERSONA` in `.env`: titles, departments, seniority, exclusions). **Limit 8.** Results go to a child table.
3. **Parent row: formula `expected_total`** = the number of people found.
4. **Parent row: HTTP API column** `POST <WEBHOOK_URL>webhook/sdr-expansion` with header `x-sdr-secret`:
   ```json
   { "type": "expected_total", "run_id": "/run_id", "expected_total": "/expected_total" }
   ```
   If it is 0, n8n posts "No other matching people found".
5. **Child table** (one row per person):
   - Formula: exclude the original person (`linkedin_url != original_linkedin_url`). n8n also dedupes against Supabase.
   - **Enrich person from LinkedIn profile** (headline, title, location, followers, connections)
   - **Work email waterfall + validation.** No phone lookup here; phones are found only for people the SDR adds.
   - **AI column `fit`**: given the persona, the original lead's title and this profile, return
     `{"score": 1-5, "reason": "one line"}`
   - **HTTP API column** `POST <WEBHOOK_URL>webhook/sdr-expansion` with header `x-sdr-secret`. Run only when email and `fit` are done:
   ```json
   {
     "type": "person", "run_id": "/run_id",
     "linkedin_url": "", "first_name": "", "last_name": "", "full_name": "", "title": "", "headline": "",
     "location": "", "linkedin_followers": "", "linkedin_connections": "",
     "work_email": "", "email_status": "", "fit": "/fit"
   }
   ```

The expansion card posts when `received_count` reaches `expected_total`. The WF4 sweep posts whatever has arrived after 10 minutes.
