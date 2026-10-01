from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_cilium_envoy_gateway_metrics_are_bounded_and_scraped() -> None:
    documents = list(
        yaml.safe_load_all(
            (ROOT / "deploy/monitoring/manifests/native-service-monitors.yaml").read_text()
        )
    )
    monitor = next(
        item
        for item in documents
        if item.get("kind") == "ServiceMonitor"
        and item["metadata"]["name"] == "cilium-envoy-openstack-gateway"
    )
    assert monitor["spec"]["namespaceSelector"]["matchNames"] == ["kube-system"]
    assert monitor["spec"]["selector"]["matchLabels"] == {"k8s-app": "cilium-envoy"}
    endpoint = monitor["spec"]["endpoints"][0]
    assert endpoint["port"] == "envoy-metrics"
    assert endpoint["relabelings"][0]["replacement"] == "cilium-envoy"
    assert endpoint["metricRelabelings"] == [
        {
            "action": "keep",
            "sourceLabels": ["__name__"],
            "regex": "envoy_cluster_upstream_rq_(total|xx|time_bucket|time_sum|time_count|timeout)",
        }
    ]
