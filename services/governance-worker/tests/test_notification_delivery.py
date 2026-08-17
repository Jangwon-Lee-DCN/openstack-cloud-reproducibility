import json
import threading
import unittest
from http.server import ThreadingHTTPServer

from governance_api.store import Store
from governance_worker.delivery import NotificationEventBus, SmtpDevelopmentFixture, WebhookSender
from governance_worker.notification_sink import State, handler


class Rabbit:
    def __init__(self): self.events = []
    def publish(self, event): self.events.append(event)


class SmtpAdapter:
    def __init__(self): self.fixture = SmtpDevelopmentFixture({"dcn.ssu.ac.kr"})
    def send(self, delivery_id, recipient, subject, context):
        return self.fixture.send(recipient, subject, delivery_id, context)


class NotificationDeliveryTest(unittest.TestCase):
    def setUp(self):
        self.key = b"x" * 32
        self.state = State(self.key)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler(self.state))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.store = Store(":memory:")
        body = {"id": "sub", "channels": [
            {"type": "webhook", "url": f"http://127.0.0.1:{self.server.server_port}/events"},
            {"type": "smtp", "recipient": "ops@dcn.ssu.ac.kr"}], "event_types": ["budget.threshold"]}
        self.store.connection.execute(
            "INSERT INTO resources(kind,id,domain_id,project_id,revision,body,created_at,updated_at) VALUES(?,?,?,?,1,?,?,?)",
            ("subscription", "sub", "domain", "project", self.store.encode(body), "now", "now"))

    def tearDown(self): self.server.shutdown(); self.server.server_close()

    def test_real_webhook_hmac_and_smtp_fanout(self):
        rabbit, smtp = Rabbit(), SmtpAdapter()
        bus = NotificationEventBus(rabbit, self.store,
            WebhookSender(self.key, {"127.0.0.1"}, allow_http_test_host="127.0.0.1"), smtp)
        event = {"id": "event-1", "project_id": "project", "event_type": "budget.threshold", "payload": {"threshold": 80}}
        bus.publish(event)
        self.assertEqual(len(rabbit.events), 1)
        self.assertEqual(len(self.state.webhooks), 1)
        self.assertEqual(len(smtp.fixture.messages), 1)
        self.assertEqual(self.state.webhooks[0]["payload"]["event_id"], "event-1")


if __name__ == "__main__": unittest.main()
