from __future__ import annotations

import json
import ssl
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, Request, build_opener, ProxyHandler


class GovernanceClient:
    def __init__(self, endpoint: str, identity: dict[str, str], opener=None,
                 ca_file=None):
        internal = {
            "http://governance-api.development-p1-governance-services.svc.cluster.local",
            "http://governance-api.governance-system.svc.cluster.local",
        }
        if endpoint not in internal and (
                not endpoint.startswith("https://") or
                not endpoint.endswith(".dev.dcn.ssu.ac.kr")):
            raise ValueError("managed governance endpoint required")
        self.endpoint = endpoint.rstrip("/")
        self.identity = identity
        if opener is not None:
            self.opener = opener
        elif endpoint.startswith("https://"):
            context = ssl.create_default_context(cafile=ca_file)
            self.opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context))
        else:
            self.opener = build_opener(ProxyHandler({}))

    def list(self, collection: str, *, limit=50, cursor=None):
        query = {"limit": limit}
        if cursor:
            query["cursor"] = cursor
        request = Request(f"{self.endpoint}/v1/{collection}?{urlencode(query)}",
                          headers=self.identity)
        with self.opener.open(request, timeout=5) as response:
            return json.load(response)

    def aws_forecast(self, *, period: str, price_profile_id: str,
                     calibration_profile_id=None, budget_id=None,
                     elapsed_fraction=None):
        query = {"period": period, "price_profile_id": price_profile_id}
        for key, value in (("calibration_profile_id", calibration_profile_id),
                           ("budget_id", budget_id),
                           ("elapsed_fraction", elapsed_fraction)):
            if value is not None:
                query[key] = value
        request = Request(f"{self.endpoint}/v1/aws-cost-forecast?{urlencode(query)}",
                          headers=self.identity)
        with self.opener.open(request, timeout=5) as response:
            return json.load(response)


COLLECTIONS = (
    ("notifications", "Notifications"), ("usage", "Usage & Cost"),
    ("budgets", "Budgets"), ("certificate-policies", "Certificates"),
    ("rotation-policies", "Secret Rotation"), ("audit-events", "Audit"),
    ("tag-policies", "Tag Policies"),
)

COST_COLLECTIONS = (("usage", "Usage & Cost"), ("budgets", "Budgets"))
ADMIN_COST_COLLECTIONS = (
    ("aws-price-profiles", "AWS Price Profiles"),
    ("aws-calibration-profiles", "AWS Calibration"),
)
