import json
import os
import time
from datetime import datetime, timezone

import pika

from .store import store_from_env


def publish_once(store, rabbit_url, exchange="dcn.track-a.operations"):
    connection = pika.BlockingConnection(pika.URLParameters(rabbit_url))
    channel = connection.channel()
    channel.exchange_declare(exchange=exchange, exchange_type="topic", durable=True)
    queue = "dcn.track-a.operations.audit"
    channel.queue_declare(queue=queue, durable=True)
    channel.queue_bind(queue=queue, exchange=exchange, routing_key="#")
    channel.confirm_delivery()
    published = 0
    try:
        with store.tx() as db:
            rows = list(db.execute("SELECT id,topic,aggregate_id,payload_json FROM outbox WHERE published_at IS NULL "
                                   "ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 100"))
            for row in rows:
                payload = row["payload_json"]
                body = payload if isinstance(payload, str) else json.dumps(payload, sort_keys=True, separators=(",", ":"))
                channel.basic_publish(exchange=exchange, routing_key=row["topic"], body=body.encode(), mandatory=True,
                                      properties=pika.BasicProperties(delivery_mode=2, content_type="application/json",
                                                                      message_id=str(row["id"]),
                                                                      correlation_id=str(row["aggregate_id"])))
                db.execute("UPDATE outbox SET published_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), row["id"]))
                published += 1
    finally:
        connection.close()
    return published


def main():
    rabbit_url = os.environ.get("CORE_RABBITMQ_URL")
    if not rabbit_url: raise RuntimeError("CORE_RABBITMQ_URL is required")
    store = store_from_env(os.environ)
    poll = float(os.environ.get("OUTBOX_POLL_SECONDS", "1"))
    while True:
        if not publish_once(store, rabbit_url): time.sleep(poll)


if __name__ == "__main__": main()
