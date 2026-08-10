#!/usr/bin/env python3
"""Extract only the persistent Barbican KEK into a mode-0600 Helm override."""
from pathlib import Path
import subprocess
import sys

import yaml

if len(sys.argv) != 2:
    raise SystemExit("usage: generate-barbican-kek-override.py OUTPUT")

root = Path(__file__).resolve().parents[1]
values = yaml.safe_load(subprocess.check_output(
    ["sops", "-d", str(root / "secrets" / "barbican.values.sops.yaml")],
    text=True,
))
kek = values["conf"]["barbican"]["simple_crypto_plugin"]["kek"]
output = Path(sys.argv[1])
output.write_text(yaml.safe_dump({
    "conf": {"barbican": {"simple_crypto_plugin": {"kek": kek}}}
}, sort_keys=False))
output.chmod(0o600)
