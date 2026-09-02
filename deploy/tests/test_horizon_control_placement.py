from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_horizon_spread_is_hard_and_revision_scoped():
    values = yaml.safe_load((ROOT / "deploy/values/site/horizon.yaml").read_text())
    constraints = values["pod"]["topology_spread_constraints"]
    assert constraints == [{
        "maxSkew": 1,
        "topologyKey": "topology.kubernetes.io/zone",
        "whenUnsatisfiable": "DoNotSchedule",
        "matchLabelKeys": ["pod-template-hash"],
        "labelSelector": {
            "matchLabels": {"application": "horizon", "component": "server"}
        },
    }]
