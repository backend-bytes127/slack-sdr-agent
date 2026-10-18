"""Print recent n8n executions with their error (reads the n8n SQLite DB from the container).

  python3 scripts/executions.py [limit]
"""
import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(limit):
    with tempfile.TemporaryDirectory() as tmp:
        cid = subprocess.check_output(["docker", "compose", "ps", "-q", "n8n"], cwd=ROOT, text=True).strip()
        for suffix in ("", "-wal", "-shm"):
            subprocess.run(["docker", "cp", f"{cid}:/home/node/.n8n/database.sqlite{suffix}", tmp],
                           capture_output=True)
        db = sqlite3.connect(Path(tmp) / "database.sqlite")
        rows = db.execute(
            "select e.id, w.name, e.status, e.startedAt, d.data from execution_entity e "
            "join workflow_entity w on w.id = e.workflowId left join execution_data d on d.executionId = e.id "
            "order by e.id desc limit ?", (limit,)).fetchall()
        for eid, name, status, started, data in rows:
            line = f"#{eid} {started} {status:8} {name}"
            if status not in ("success",) and data:
                line += "  -> " + summarize(data)
            print(line)


def summarize(raw):
    """n8n stores run data in a flattened 'flatted' format; pull out error messages and last node."""
    try:
        arr = json.loads(raw)
    except ValueError:
        return raw[:200]
    msgs = []
    for v in arr:
        if isinstance(v, dict) and "message" in v and isinstance(v["message"], str):
            idx = v["message"]
            text = arr[int(idx)] if idx.isdigit() and int(idx) < len(arr) else idx
            if isinstance(text, str) and text not in msgs:
                msgs.append(text)
        if isinstance(v, dict) and "lastNodeExecuted" in v:
            idx = v["lastNodeExecuted"]
            node = arr[int(idx)] if isinstance(idx, str) and idx.isdigit() else idx
            msgs.insert(0, f"[last node: {node}]")
    return " | ".join(str(m)[:300] for m in msgs[:4])


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 10)
