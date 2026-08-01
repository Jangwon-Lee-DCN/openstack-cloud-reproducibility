#!/usr/bin/env python3
"""Regression checks for provisioned Grafana dashboard JSON payloads."""

import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1] / "manifests"


def embedded_json_documents(path: pathlib.Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    documents = []
    markers = [i for i, line in enumerate(lines) if line.startswith("  ") and line.rstrip().endswith(".json: |")]
    for position, marker in enumerate(markers):
        end = markers[position + 1] if position + 1 < len(markers) else len(lines)
        payload = "\n".join(line[4:] for line in lines[marker + 1:end] if not line or line.startswith("    "))
        documents.append(json.loads(payload))
    return documents


def embedded_json(path: pathlib.Path) -> dict:
    return embedded_json_documents(path)[0]


def main() -> int:
    dashboards = {}
    for path in sorted(ROOT.glob("*dashboard*.yaml")):
        try:
            candidates = embedded_json_documents(path)
        except StopIteration:
            continue
        except (ValueError, json.JSONDecodeError) as exc:
            print(f"{path}: invalid embedded dashboard JSON: {exc}", file=sys.stderr)
            return 1
        for dashboard in candidates:
            uid = dashboard.get("uid")
            if not uid or uid in dashboards:
                print(f"{path}: missing or duplicate dashboard uid {uid!r}", file=sys.stderr)
                return 1
            dashboards[uid] = path
            panel_ids = [panel.get("id") for panel in dashboard.get("panels", [])]
            if len(panel_ids) != len(set(panel_ids)):
                print(f"{path}: duplicate panel ids", file=sys.stderr)
                return 1

    eni = embedded_json(ROOT / "vpc-control-plane-dashboard.yaml")
    variables = {item.get("name") for item in eni.get("templating", {}).get("list", [])}
    required_variables = {"project_namespace", "vpc", "subnet", "network_interface", "request_id"}
    if not required_variables <= variables:
        print(f"ENI dashboard missing variables: {sorted(required_variables - variables)}", file=sys.stderr)
        return 1
    datasource_uids = {panel.get("datasource", {}).get("uid") for panel in eni.get("panels", []) if isinstance(panel.get("datasource"), dict)}
    if not {"prometheus", "loki"} <= datasource_uids:
        print("ENI dashboard must connect Prometheus and Loki", file=sys.stderr)
        return 1
    serialized = json.dumps(eni)
    for contract in ("attachment success SLO", "tempo", "vpc_network_interface_info"):
        if contract.lower() not in serialized.lower():
            print(f"ENI dashboard missing contract {contract!r}", file=sys.stderr)
            return 1
    print(f"validated {len(dashboards)} Grafana dashboards")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
