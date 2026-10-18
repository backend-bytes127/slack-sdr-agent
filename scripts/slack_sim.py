"""Send correctly signed fake Slack requests to the local n8n webhooks (for testing).

  python3 scripts/slack_sim.py prospect <linkedin_url> [user_id]
  python3 scripts/slack_sim.py button <action_id> <lead_id> [user_id]
  python3 scripts/slack_sim.py clay1 <json_file>        # fake Clay Table 1 callback
  python3 scripts/slack_sim.py clay2 <json_file>        # fake Clay Table 2 callback
"""
import hashlib
import hmac
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://localhost:8088/webhook"


def env():
    out = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def post(path, body, headers):
    req = urllib.request.Request(f"{BASE}/{path}", data=body.encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return res.status, res.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode()


def slack_post(path, form):
    body = urllib.parse.urlencode(form)
    ts = str(int(time.time()))
    secret = env().get("SLACK_SIGNING_SECRET", "")
    sig = "v0=" + hmac.new(secret.encode(), f"v0:{ts}:{body}".encode(), hashlib.sha256).hexdigest()
    return post(path, body, {"Content-Type": "application/x-www-form-urlencoded",
                             "X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig})


def main(argv):
    cfg = env()
    cmd = argv[1]
    if cmd == "prospect":
        user = argv[3] if len(argv) > 3 else "U_TEST"
        print(slack_post("sdr-intake", {"command": "/prospect", "text": argv[2], "user_id": user,
                                        "channel_id": cfg.get("SLACK_CHANNEL_ID", "C_TEST"),
                                        "response_url": "https://httpbin.org/post"}))
    elif cmd == "button":
        user = argv[4] if len(argv) > 4 else "U_TEST"
        payload = {"type": "block_actions", "user": {"id": user, "name": "tester"}, "trigger_id": "fake.trigger",
                   "channel": {"id": cfg.get("SLACK_CHANNEL_ID", "C_TEST")},
                   "container": {"message_ts": "1.1", "channel_id": cfg.get("SLACK_CHANNEL_ID", "C_TEST")},
                   "actions": [{"action_id": argv[2], "value": argv[3]}]}
        print(slack_post("sdr-actions", {"payload": json.dumps(payload)}))
    elif cmd in ("clay1", "clay2"):
        path = "sdr-enriched" if cmd == "clay1" else "sdr-expansion"
        print(post(path, Path(argv[2]).read_text(), {"Content-Type": "application/json",
                                                     "x-sdr-secret": cfg.get("CLAY_CALLBACK_SECRET", "")}))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
