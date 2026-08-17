#!/usr/bin/env python3
import json
import pathlib
import sys


def verify(sbom_path, scan_path):
    sbom = json.loads(pathlib.Path(sbom_path).read_text())
    if sbom.get("bomFormat") != "CycloneDX" or not sbom.get("components"):
        raise ValueError("SBOM must be non-empty CycloneDX JSON")
    scan = json.loads(pathlib.Path(scan_path).read_text())
    counts = scan.get("summary", {})
    critical = int(counts.get("critical", counts.get("CRITICAL", 0)))
    high = int(counts.get("high", counts.get("HIGH", 0)))
    if critical:
        raise ValueError(f"critical vulnerabilities block publication: {critical}")
    print(json.dumps({"sbom_components": len(sbom["components"]), "critical": critical,
                      "high": high}, sort_keys=True))


if __name__ == "__main__":
    try:
        verify(sys.argv[1], sys.argv[2])
    except (IndexError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"image supply-chain verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
