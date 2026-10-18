"""Build all workflow JSON files into workflows/ and credentials into .build/ (gitignored).

Usage: python3 scripts/build.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from actions import wf3_actions  # noqa: E402
from lib import CRED  # noqa: E402
from main_flows import wf1_intake, wf2_enriched, wf5_expansion  # noqa: E402
from ops import wf4_errors  # noqa: E402
from subs import all_subs  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "workflows"
BUILD = ROOT / ".build"


def load_env():
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def credentials(env):
    """Credential payloads for `n8n import:credentials` (n8n encrypts plain objects on import)."""
    data = {
        "pg": {"host": env.get("PG_HOST", "db"), "database": env.get("PG_DATABASE", "sdr"),
               "user": env.get("PG_USER", "sdr"), "password": env.get("PG_PASSWORD", env.get("SDR_DB_PASSWORD", "")),
               "port": int(env.get("PG_PORT", "5432")), "ssl": env.get("PG_SSL", "disable"),
               "allowUnauthorizedCerts": env.get("PG_ALLOW_UNAUTHORIZED_CERTS", "false") == "true"},
        "slack": {"name": "Authorization", "value": f"Bearer {env.get('SLACK_BOT_TOKEN', 'xoxb-missing')}"},
        "hubspot": {"name": "Authorization", "value": f"Bearer {env.get('HUBSPOT_TOKEN', 'missing')}"},
        "heyreach": {"name": "X-API-KEY", "value": env.get("HEYREACH_API_KEY", "missing")},
        "instantly": {"name": "Authorization", "value": f"Bearer {env.get('INSTANTLY_API_KEY', 'missing')}"},
        "claycb": {"name": "x-sdr-secret", "value": env.get("CLAY_CALLBACK_SECRET", "missing")},
        "deepline": {"name": "Authorization", "value": f"Bearer {env.get('DEEPLINE_API_KEY', 'missing')}"},
        "prospeo": {"name": "X-KEY", "value": env.get("PROSPEO_API_KEY", "missing")},
        "openai": {"apiKey": env.get("LLM_API_KEY", "missing"), "url": env.get("LLM_BASE_URL", "https://api.openai.com/v1")},
    }
    return [{"id": cid, "name": cname, "type": ctype, "data": data[key]}
            for key, (cid, cname, ctype) in CRED.items()]


def main():
    flows = all_subs() + [wf1_intake(), wf2_enriched(), wf3_actions(), wf4_errors(), wf5_expansion()]
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*.json"):
        old.unlink()
    for wf in flows:
        slug = wf.name.replace("SDR · ", "").replace(" · ", "_")
        slug = "".join(c if c.isalnum() else "_" for c in slug).strip("_").lower()
        (OUT / f"{slug}.json").write_text(json.dumps(wf.to_json(), indent=2, ensure_ascii=False))
    BUILD.mkdir(exist_ok=True)
    (BUILD / "workflows.json").write_text(json.dumps([wf.to_json() for wf in flows], ensure_ascii=False))
    (BUILD / "credentials.json").write_text(json.dumps(credentials(load_env())))
    print(f"Built {len(flows)} workflows -> {OUT}")


if __name__ == "__main__":
    main()
