"""Tiny helpers to build n8n workflow JSON without hand-writing node boilerplate."""
import json
import uuid
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "workflows" / "src"

# Fixed IDs so workflows can reference each other and credentials after CLI import.
CRED = {
    "pg": ("sdrPostgres00001", "SDR Postgres", "postgres"),
    "slack": ("sdrSlackBot00001", "Slack Bot (Bearer)", "httpHeaderAuth"),
    "hubspot": ("sdrHubspot000001", "HubSpot Private App", "httpHeaderAuth"),
    "heyreach": ("sdrHeyreach00001", "HeyReach API Key", "httpHeaderAuth"),
    "instantly": ("sdrInstantly0001", "Instantly API v2", "httpHeaderAuth"),
    "claycb": ("sdrClayCb0000001", "Clay Callback Secret", "httpHeaderAuth"),
    "openai": ("sdrOpenAi0000001", "LLM (OpenAI-compatible)", "openAiApi"),
    "deepline": ("sdrDeepline00001", "Deepline API (Bearer)", "httpHeaderAuth"),
    "prospeo": ("sdrProspeo000001", "Prospeo API (X-KEY)", "httpHeaderAuth"),
}

WF = {
    "wf1": "sdrWf1Intake0001",
    "wf2": "sdrWf2Enriched01",
    "wf3": "sdrWf3Actions001",
    "wf4": "sdrWf4Errors0001",
    "wf5": "sdrWf5Expansion1",
    "slack": "sdrSubSlackApi01",
    "enrich": "sdrSubEnrich0001",
    "hs_sync": "sdrSubHsSync0001",
    "hs_call": "sdrSubHsCall0001",
    "hs_note": "sdrSubHsNote0001",
    "lead_card": "sdrSubLeadCard01",
    "exp_start": "sdrSubExpStart01",
    "exp_card": "sdrSubExpCard001",
    "draft": "sdrSubDraft00001",
    "report_err": "sdrSubReportErr1",
}


def js(name):
    return (SRC / f"{name}.js").read_text()


def cred(key):
    cid, cname, ctype = CRED[key]
    return {ctype: {"id": cid, "name": cname}}


class Workflow:
    def __init__(self, key, name, error_workflow=True):
        self.id = WF[key]
        self.name = name
        self.nodes = []
        self.connections = {}
        self._x = 0
        self.error_workflow = error_workflow

    def add(self, name, ntype, version, params, creds=None, pos=None, **extra):
        if pos is None:
            pos = [self._x, 0]
            self._x += 240
        node = {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{self.id}/{name}")),
            "name": name,
            "type": ntype,
            "typeVersion": version,
            "position": pos,
            "parameters": params,
        }
        if creds:
            node["credentials"] = creds
        node.update(extra)
        self.nodes.append(node)
        return name

    def connect(self, src, dst, out=0, kind="main", inp=0):
        outs = self.connections.setdefault(src, {}).setdefault(kind, [])
        while len(outs) <= out:
            outs.append([])
        outs[out].append({"node": dst, "type": kind, "index": inp})

    def chain(self, *names):
        for a, b in zip(names, names[1:]):
            self.connect(a, b)
        return names[-1]

    def to_json(self):
        settings = {"executionOrder": "v1", "saveManualExecutions": True,
                    "callerPolicy": "workflowsFromSameOwner"}
        if self.error_workflow:
            settings["errorWorkflow"] = WF["wf4"]
        return {
            "id": self.id,
            "name": self.name,
            "active": False,
            "nodes": self.nodes,
            "connections": self.connections,
            "settings": settings,
            "pinData": {},
        }


# ---------- node factories ----------

def webhook(wf, name, path, raw=False, clay_auth=False, pos=None):
    params = {"httpMethod": "POST", "path": path, "responseMode": "responseNode",
              "options": {"rawBody": True} if raw else {}}
    creds = None
    if clay_auth:
        params["authentication"] = "headerAuth"
        creds = cred("claycb")
    return wf.add(name, "n8n-nodes-base.webhook", 2.1, params, creds, pos, webhookId=path)


def respond(wf, name, body=None, code=200, pos=None):
    if body is None:
        params = {"respondWith": "noData", "options": {"responseCode": code}}
    else:
        params = {"respondWith": "json", "responseBody": body, "options": {"responseCode": code}}
    return wf.add(name, "n8n-nodes-base.respondToWebhook", 1.4, params, pos=pos)


def code(wf, name, src_name, pos=None, mode=None):
    params = {"jsCode": js(src_name)}
    if mode == "each":
        params["mode"] = "runOnceForEachItem"
    return wf.add(name, "n8n-nodes-base.code", 2, params, pos=pos)


def sql(wf, name, query, args_expr=None, pos=None, always_output=False, each=True):
    """Postgres executeQuery. args_expr is a JS array expression body, e.g. "[$json.id]".
    Every element must be null-coalesced: the node silently drops undefined values."""
    # The Postgres node emits {success: true} when a non-SELECT returns no rows, which would
    # let "0 rows = stop" guards fall through. Wrapping makes the top-level command a SELECT.
    if query.lstrip().lower().startswith(("insert", "update", "delete")):
        query = f"with _r as (\n{query}\n) select * from _r"
    options = {}
    if args_expr:
        options["queryReplacement"] = "={{ " + args_expr + " }}"
    extra = {"alwaysOutputData": True} if always_output else {}
    if not each:
        extra["executeOnce"] = True
    return wf.add(name, "n8n-nodes-base.postgres", 2.6,
                  {"operation": "executeQuery", "query": query, "options": options},
                  cred("pg"), pos, **extra)


def http(wf, name, method, url, cred_key=None, body_expr=None, pos=None, retry=False,
         on_error=None, query=None, full_response=False, never_error=False, timeout_ms=None):
    params = {"method": method, "url": url, "options": {}}
    creds = None
    if cred_key:
        params["authentication"] = "genericCredentialType"
        params["genericAuthType"] = "httpHeaderAuth"
        creds = cred(cred_key)
    if body_expr is not None:
        params.update({"sendBody": True, "specifyBody": "json", "jsonBody": "={{ " + body_expr + " }}"})
    if query:
        params.update({"sendQuery": True, "specifyQuery": "json", "jsonQuery": "={{ " + query + " }}"})
    if full_response:
        params["options"]["response"] = {"response": {"fullResponse": True, "neverError": True}}
    elif never_error:
        # 4xx "no match" answers (e.g. Prospeo NO_MATCH) come back as data instead of failing the run
        params["options"]["response"] = {"response": {"neverError": True}}
    if timeout_ms:
        params["options"]["timeout"] = timeout_ms
    extra = {}
    if retry:
        extra.update({"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 5000})
    if on_error:
        extra["onError"] = on_error
    return wf.add(name, "n8n-nodes-base.httpRequest", 4.2, params, creds, pos, **extra)


def if_true(wf, name, expr, pos=None):
    params = {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [{
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{wf.id}/{name}/c")),
                "leftValue": "={{ " + expr + " }}",
                "rightValue": "",
                "operator": {"type": "boolean", "operation": "true", "singleValue": True},
            }],
            "combinator": "and",
        },
        "looseTypeValidation": True,
        "options": {},
    }
    return wf.add(name, "n8n-nodes-base.if", 2.2, params, pos=pos)


def switch(wf, name, n_outputs, expr, pos=None):
    return wf.add(name, "n8n-nodes-base.switch", 3.2,
                  {"mode": "expression", "numberOutputs": n_outputs, "output": "={{ " + expr + " }}"},
                  pos=pos)


def sub_trigger(wf, inputs, name="Called by parent"):
    values = [{"name": n, "type": "any"} for n in inputs]
    return wf.add(name, "n8n-nodes-base.executeWorkflowTrigger", 1.1,
                  {"inputSource": "workflowInputs", "workflowInputs": {"values": values}})


def call(wf, name, target, inputs, pos=None, wait=True, each=False):
    """Execute a sub-workflow. inputs maps field -> expression body (no {{ }})."""
    value = {k: "={{ " + v + " }}" for k, v in inputs.items()}
    schema = [{"id": k, "displayName": k, "required": False, "defaultMatch": False,
               "display": True, "canBeUsedToMatch": True, "type": "any", "removed": False}
              for k in inputs]
    params = {
        "workflowId": {"__rl": True, "value": WF[target], "mode": "id"},
        "workflowInputs": {"mappingMode": "defineBelow", "value": value, "matchingColumns": [],
                           "schema": schema, "attemptToConvertTypes": False,
                           "convertFieldsToString": False},
        "mode": "each" if each else "once",
        "options": {"waitForSubWorkflow": wait},
    }
    # A sub-workflow whose last node outputs nothing (e.g. an IF false branch) would otherwise
    # stop the parent; parents reference upstream nodes by name, so always continue.
    return wf.add(name, "n8n-nodes-base.executeWorkflow", 1.2, params, pos=pos, alwaysOutputData=True)


def slack(wf, name, method_expr, payload_expr, pos=None):
    """Call the Slack API sub-workflow. method_expr is a JS expression, e.g. "'chat.postMessage'"."""
    return call(wf, name, "slack", {"method": method_expr, "payload": payload_expr}, pos=pos)


def noop(wf, name, pos=None):
    return wf.add(name, "n8n-nodes-base.noOp", 1, {}, pos=pos)
