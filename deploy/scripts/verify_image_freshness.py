#!/usr/bin/env python3
import argparse
import datetime
import json
import subprocess
import sys
import yaml

parser = argparse.ArgumentParser()
parser.add_argument("catalog")
parser.add_argument("--max-age-days", type=int, default=45)
args = parser.parse_args()
catalog = yaml.safe_load(open(args.catalog, encoding="utf-8"))
today = datetime.date.today()
errors = []
for item in catalog["images"]:
    built = datetime.date.fromisoformat(item["build_date"])
    age = (today - built).days
    if age > args.max_age_days:
        errors.append(f"{item['name']}: age={age}d exceeds {args.max_age_days}d")
    raw = subprocess.run(["openstack", "image", "show", item["name"], "-f", "json"],
                         check=True, capture_output=True, text=True).stdout
    image = json.loads(raw); properties = image.get("properties", {}) or {}
    if not properties.get("source_sha256"):
        errors.append(f"{item['name']}: source_sha256 missing")
print(json.dumps({"checked": len(catalog["images"]), "errors": errors}, sort_keys=True))
raise SystemExit(1 if errors else 0)
