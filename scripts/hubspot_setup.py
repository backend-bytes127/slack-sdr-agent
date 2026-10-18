"""Create the custom HubSpot contact properties the agent writes, and print owners for sdr_owner_map.

  python3 scripts/hubspot_setup.py
Reads HUBSPOT_TOKEN from .env. Safe to re-run (existing properties are skipped).
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from slack_sim import env  # noqa: E402

API = "https://api.hubapi.com"
PROPERTIES = [
    {"name": "linkedin_url", "label": "LinkedIn URL (SDR Agent)", "type": "string", "fieldType": "text"},
    {"name": "linkedin_followers", "label": "LinkedIn followers (SDR Agent)", "type": "number", "fieldType": "number"},
    {"name": "linkedin_connections", "label": "LinkedIn connections (SDR Agent)", "type": "number", "fieldType": "number"},
    {"name": "research_summary", "label": "Research summary (SDR Agent)", "type": "string", "fieldType": "textarea"},
]


def request(method, path, token, body=None):
    req = urllib.request.Request(f"{API}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            return res.status, json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}")


def main():
    token = env().get("HUBSPOT_TOKEN")
    if not token:
        sys.exit("HUBSPOT_TOKEN is empty in .env")
    for prop in PROPERTIES:
        status, body = request("POST", "/crm/v3/properties/contacts", token,
                               {**prop, "groupName": "contactinformation"})
        if status in (200, 201):
            print(f"created  {prop['name']}")
        elif status == 409:
            print(f"exists   {prop['name']}")
        else:
            sys.exit(f"failed   {prop['name']}: {status} {body.get('message')}")
    status, owners = request("GET", "/crm/v3/owners?limit=100", token)
    if status != 200:
        sys.exit(f"could not list owners: {status} {owners.get('message')}")
    print("\nOwners (put these in sdr_owner_map: slack_user_id -> hubspot_owner_id):")
    for o in owners.get("results", []):
        print(f"  {o['id']:>12}  {o.get('email')}  {o.get('firstName', '')} {o.get('lastName', '')}")


if __name__ == "__main__":
    main()
