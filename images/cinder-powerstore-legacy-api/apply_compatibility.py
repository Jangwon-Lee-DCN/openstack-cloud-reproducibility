#!/usr/bin/env python3
"""Make the 2026.1 PowerStore driver work with pre-Metro REST APIs."""

from pathlib import Path
import sys


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"expected one {label} match, found {count}")
    return source.replace(old, new, 1)


def patch_driver(root: Path) -> None:
    client_path = root / "client.py"
    client = client_path.read_text()
    client = replace_once(
        client,
        '"select": "id,name,host_initiators,host_connectivity",',
        '"select": "id,name,host_initiators",',
        "host select",
    )
    client = replace_once(
        client,
        '                "initiators": ports,\n'
        '                "host_connectivity": connectivity,\n',
        '                "initiators": ports,\n',
        "host create payload",
    )
    client_path.write_text(client)

    adapter_path = root / "adapter.py"
    adapter = adapter_path.read_text()
    adapter = replace_once(
        adapter,
        '        if host["host_connectivity"] != self.host_connectivity:\n',
        '        if ("host_connectivity" in host and\n'
        '                host["host_connectivity"] != self.host_connectivity):\n',
        "host connectivity guard",
    )
    adapter_path.write_text(adapter)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply_compatibility.py POWERSTORE_DRIVER_DIR")
    patch_driver(Path(sys.argv[1]))

