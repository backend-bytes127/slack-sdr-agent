"""Local mock of Slack, HubSpot, HeyReach, Instantly, Deepline, Prospeo and the Clay webhooks, for end-to-end tests.

Run:  python3 scripts/mock_apis.py [port] [log_file]
Then point the *_API_BASE / CLAY_*_WEBHOOK_URL env vars at http://host.docker.internal:<port>/...
Every request is appended to the log file as one JSON line so payloads can be inspected.
"""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9911
LOG = sys.argv[2] if len(sys.argv) > 2 else "mock_requests.jsonl"


ACME = {"name": "Acme GmbH", "domain": "acme.io", "linkedin_url": "https://www.linkedin.com/company/acme",
        "employee_count": 120, "employee_range": "51-200", "industry": "Software",
        "description": "Revenue operations software for B2B teams"}
COLLEAGUES = [
    ("Bob", "Ops", "Head of RevOps", "https://linkedin.com/in/Bob-Ops/"),
    ("Jane", "Doe", "VP Sales", "https://www.linkedin.com/in/jane-doe-e2e"),  # the original lead: must be excluded
    ("Cara", "Cmo", "Chief Marketing Officer", "https://www.linkedin.com/in/cara-cmo"),
    ("Ian", "Intern", "Sales Intern", "https://www.linkedin.com/in/ian-intern"),  # persona exclusion
]


def name_from_url(url):
    """jane-doe-e2e -> ("Jane", "Doe")"""
    parts = str(url or "").rstrip("/").split("/")[-1].split("-")
    return parts[0].title(), (parts[1] if len(parts) > 1 else "Lead").title()


def deepline(tool, payload):
    if tool == "harvestapi_get_profile":
        first, last = name_from_url(payload.get("url"))
        element = {"firstName": first, "lastName": last, "headline": "Building revenue teams",
                   "about": "Runs a 12-person SDR team and is hiring AEs in DACH.",
                   "location": {"linkedinText": "Berlin, Germany"}, "followerCount": 1204, "connectionsCount": 500,
                   "currentPosition": [{"position": "VP Sales", "companyName": ACME["name"],
                                        "companyLinkedinUrl": ACME["linkedin_url"]}]}
        return {"job_id": "mock", "status": "completed", "result": {"data": {"element": element}}}
    if tool == "harvestapi_get_company":
        return {"status": "completed", "result": {"data": {"element": {"name": ACME["name"], "website": "https://www.acme.io/",
                                                                      "linkedinUrl": ACME["linkedin_url"]}}}}
    if tool in ("datagma_find_email", "hunter_email_finder"):
        email = f"{payload.get('first_name', 'x').lower()}.{payload.get('last_name', 'y').lower()}@{payload.get('domain')}"
        return {"status": "completed", "result": {"data": {"email": email, "status": "Valid"}}}
    if tool == "harvestapi_search_leads":
        return {"status": "completed", "result": {"data": {"elements": []}}}
    return {"status": "completed", "result": {"data": {}}}


def prospeo(path, body):
    if path.endswith("/enrich-person"):
        first, last = name_from_url((body.get("data") or {}).get("linkedin_url"))
        person = {"first_name": first, "last_name": last, "full_name": f"{first} {last}", "current_job_title": "VP Sales",
                  "email": {"email": f"{first.lower()}.{last.lower()}@acme.io", "status": "VERIFIED"},
                  "mobile": {"mobile": "+49 30 1234567", "revealed": True}}
        return {"error": False, "person": person, "company": ACME}
    if path.endswith("/search-person"):
        results = [{"person": {"first_name": f, "last_name": l, "full_name": f"{f} {l}", "current_job_title": title,
                               "linkedin_url": url, "location": {"city": "Berlin", "country": "Germany"}},
                    "company": ACME} for f, l, title, url in COLLEAGUES]
        return {"error": False, "results": results, "pagination": {"total_count": len(results)}}
    return {"error": True, "error_code": "NO_MATCH"}


def respond_for(path, body):
    if path.startswith("/deepline/integrations/"):
        return deepline(path.split("/")[3], (body or {}).get("payload") or {})
    if path.startswith("/prospeo/"):
        return prospeo(path, body or {})
    if path.startswith("/slack/"):
        return {"ok": True, "ts": f"{time.time():.6f}", "channel": (body or {}).get("channel", "C_TEST")}
    if path.startswith("/hubspot/"):
        if path.endswith("/search"):
            return {"total": 0, "results": []}
        if "/associations/" in path:
            return {"status": "COMPLETE"}
        if "/companies" in path:
            return {"id": "9001"}
        if "/contacts" in path:
            return {"id": "5001"}
        if "/notes" in path:
            return {"id": "n-1"}
        if "/calls" in path:
            return {"id": "call-1"}
    if path.startswith("/heyreach/"):
        return {"addedLeadsCount": 1, "updatedLeadsCount": 0, "failedLeadsCount": 0}
    if path.startswith("/instantly/"):
        return {"id": "instantly-lead-1", "email": (body or {}).get("email")}
    if path.startswith("/clay"):
        return {"ok": True}
    return {"ok": True, "note": "unmocked path"}


class Handler(BaseHTTPRequestHandler):
    def _handle(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode() if length else ""
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = raw
        with open(LOG, "a") as fh:
            fh.write(json.dumps({"t": time.time(), "method": self.command, "path": self.path, "body": body}) + "\n")
        out = json.dumps(respond_for(self.path, body if isinstance(body, dict) else None)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    do_POST = do_PUT = do_PATCH = do_GET = _handle

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"mock APIs on :{PORT}, logging to {LOG}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
