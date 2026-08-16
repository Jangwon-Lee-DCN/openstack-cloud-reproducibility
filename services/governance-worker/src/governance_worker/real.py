from __future__ import annotations

import os
import json
from urllib.request import Request, urlopen
from dataclasses import dataclass

from governance_api.providers import OpenStackClient, ProviderError


class IntegrationError(RuntimeError):
    pass


def application_credential_token(auth_url: str, credential_id: str, secret: str) -> str:
    body = {"auth": {"identity": {"methods": ["application_credential"],
            "application_credential": {"id": credential_id, "secret": secret}}}}
    request = Request(auth_url.rstrip("/") + "/v3/auth/tokens",
                      data=json.dumps(body, separators=(",", ":")).encode(), method="POST",
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=10) as response:
        return response.headers["X-Subject-Token"]


@dataclass
class PostgresOutbox:
    dsn: str = ""

    def initialize(self):
        import psycopg
        kwargs = {"connect_timeout": 5}
        if not self.dsn:
            kwargs.update(host=os.environ["GOVERNANCE_POSTGRESQL_HOST"],
                          port=int(os.getenv("GOVERNANCE_POSTGRESQL_PORT", "5432")),
                          dbname=os.getenv("GOVERNANCE_POSTGRES_DB", "governance"),
                          user=os.environ["GOVERNANCE_POSTGRES_USER"],
                          password=os.environ["GOVERNANCE_POSTGRES_PASSWORD"])
        with psycopg.connect(self.dsn, **kwargs) as connection:
            connection.execute("""
              CREATE TABLE IF NOT EXISTS governance_worker_checkpoint(
                worker TEXT PRIMARY KEY, checkpoint TEXT NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT now()
              )
            """)


@dataclass
class RabbitEventBus:
    url: str
    queue: str = "governance.events"

    def initialize(self):
        import pika
        parameters = pika.URLParameters(self.url)
        parameters.socket_timeout = 5
        parameters.blocked_connection_timeout = 5
        connection = pika.BlockingConnection(parameters)
        try:
            connection.channel().queue_declare(
                queue=self.queue, durable=True, arguments={"x-queue-type": "quorum"})
        finally:
            connection.close()

    def publish(self, event: dict):
        import pika
        parameters = pika.URLParameters(self.url)
        parameters.socket_timeout = 5
        connection = pika.BlockingConnection(parameters)
        try:
            channel = connection.channel()
            channel.confirm_delivery()
            channel.basic_publish(exchange="", routing_key=self.queue,
                                  body=json.dumps(event, separators=(",", ":")),
                                  properties=pika.BasicProperties(delivery_mode=2,
                                                                  content_type="application/json"),
                                  mandatory=True)
        finally:
            connection.close()


class GovernanceProviders:
    """Real OpenStack API adapters; mutations are constrained to development names."""

    def __init__(self, token: str, prefix: str):
        if not prefix.startswith("governance-dev-"):
            raise IntegrationError("test resource prefix must start governance-dev-")
        self.clients = {
            name: OpenStackClient(os.environ[f"GOVERNANCE_{name.upper()}_URL"], token)
            for name in ("gnocchi", "barbican", "designate", "octavia", "nova", "cinder", "neutron", "glance")
        }
        self.project_id = os.environ["GOVERNANCE_KEYSTONE_PROJECT_ID"]

    def probe(self):
        paths = {"gnocchi": "/v1/resource/generic?limit=1", "barbican": "/v1/secrets?limit=1",
                 "designate": "/v2/zones?limit=1", "octavia": "/v2.0/lbaas/loadbalancers?limit=1",
                 "nova": f"/v2.1/{self.project_id}/servers?limit=1",
                 "cinder": f"/v3/{self.project_id}/volumes?limit=1",
                 "neutron": "/v2.0/networks?limit=1", "glance": "/v2/images?limit=1"}
        result = {}
        for name, client in self.clients.items():
            try:
                result[name] = client.request(paths[name])[0]
            except ProviderError as exc:
                # Keep the durable worker alive for independent providers. The
                # corresponding mutation adapter remains fail-closed and the
                # provider-specific blocker is retained in the startup result.
                result[name] = f"blocked:{exc}"
        return result


def initialize_real_integrations():
    required = ("GOVERNANCE_POSTGRESQL_HOST", "GOVERNANCE_POSTGRES_USER",
                "GOVERNANCE_POSTGRES_PASSWORD", "GOVERNANCE_RABBITMQ_URL")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise IntegrationError("missing required real integration configuration: " + ",".join(missing))
    PostgresOutbox().initialize()
    bus = RabbitEventBus(os.environ["GOVERNANCE_RABBITMQ_URL"])
    bus.initialize()
    # OpenStack mutation adapters remain disabled until a least-privilege governance
    # application credential is provisioned. Missing credentials never select fakes.
    credential_id = os.getenv("GOVERNANCE_APPLICATION_CREDENTIAL_ID")
    credential_secret = os.getenv("GOVERNANCE_APPLICATION_CREDENTIAL_SECRET")
    if not credential_id or not credential_secret:
        raise IntegrationError("governance application credential is required")
    token = application_credential_token(os.environ["GOVERNANCE_KEYSTONE_URL"],
                                         credential_id, credential_secret)
    probes = GovernanceProviders(token, os.environ["GOVERNANCE_TEST_RESOURCE_PREFIX"]).probe()
    print(json.dumps({"provider_probe": probes}, sort_keys=True), flush=True)
    return bus
