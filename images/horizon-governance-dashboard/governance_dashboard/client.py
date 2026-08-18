from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler


class GovernanceClient:
    def __init__(self, endpoint: str, identity: dict[str, str], opener=None):
        if not endpoint.startswith("https://") or not endpoint.endswith(".dev.dcn.ssu.ac.kr"):
            raise ValueError("development fake endpoint required")
        self.endpoint = endpoint.rstrip("/")
        self.identity = identity
        self.opener = opener or build_opener(ProxyHandler({}))

    def list(self, collection: str, *, limit=50, cursor=None):
        query = {"limit": limit}
        if cursor:
            query["cursor"] = cursor
        request = Request(f"{self.endpoint}/v1/{collection}?{urlencode(query)}",
                          headers=self.identity)
        with self.opener.open(request, timeout=5) as response:
            return json.load(response)


COLLECTIONS = (
    ("notifications", "Notifications"), ("usage", "Usage & Cost"),
    ("budgets", "Budgets"), ("certificate-policies", "Certificates"),
    ("rotation-policies", "Secret Rotation"), ("audit-events", "Audit"),
    ("tag-policies", "Tag Policies"),
)
