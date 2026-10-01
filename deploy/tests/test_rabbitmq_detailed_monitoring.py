from pathlib import Path
import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_rabbitmq_keeps_aggregate_and_bounded_queue_scrapes_separate() -> None:
    documents = list(
        yaml.safe_load_all(
            (ROOT / "deploy/monitoring/manifests/native-service-monitors.yaml").read_text()
        )
    )
    monitor = next(
        item
        for item in documents
        if item
        and item.get("kind") == "ServiceMonitor"
        and item["metadata"]["name"] == "openstack-rabbitmq"
    )
    aggregate, queues = monitor["spec"]["endpoints"]
    assert aggregate == {"port": "metrics", "interval": "30s", "scrapeTimeout": "10s"}
    assert queues["path"] == "/metrics/detailed"
    assert queues["interval"] == "60s"
    assert queues["scrapeTimeout"] == "20s"
    assert queues["params"]["family"] == [
        "queue_coarse_metrics",
        "queue_consumer_count",
        "queue_delivery_metrics",
        "queue_exchange_metrics",
    ]
    assert queues["relabelings"] == [
        {"action": "replace", "targetLabel": "job", "replacement": "rabbitmq-queues"}
    ]
