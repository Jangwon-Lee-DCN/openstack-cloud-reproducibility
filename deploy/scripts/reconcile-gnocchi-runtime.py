#!/usr/bin/env python3
"""Render Gnocchi runtime config and reconcile its MariaDB account."""
import base64
import configparser
import json
import os
import re
import subprocess
import sys
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import yaml

namespace = os.environ.get("NAMESPACE", "openstack")
root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def run(*args, input_text=None):
    return subprocess.check_output(args, input=input_text, text=True)


def secret(name):
    obj = json.loads(run("kubectl", "-n", namespace, "get", "secret", name, "-o", "json"))
    return {key: base64.b64decode(value).decode() for key, value in obj["data"].items()}


template = yaml.safe_load(run("sops", "-d", os.path.join(root, "secrets", "gnocchi-config.secret.sops.yaml")))
conf = configparser.ConfigParser(interpolation=None)
conf.optionxform = str
conf.read_string(base64.b64decode(template["data"]["gnocchi.conf"]).decode())

runtime = secret("gnocchi-runtime")
obc = secret("gnocchi-metrics")
obc_config = json.loads(run("kubectl", "-n", namespace, "get", "configmap", "gnocchi-metrics", "-o", "json"))["data"]

# Rook OBC users default to one bucket, while Gnocchi's S3 drivers create an
# incoming bucket and an aggregates bucket. Resolve the opaque OBC user by its
# access key in the ObjectStore realm, then raise only that user's bucket cap.
rgw_scope = [
    "--rgw-realm=openstack-object-store",
    "--rgw-zonegroup=openstack-object-store",
    "--rgw-zone=openstack-object-store",
]
if subprocess.run(
    ["kubectl", "-n", "rook-ceph", "get", "deployment", "rook-ceph-tools"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
).returncode == 0:
    try:
        user_info = json.loads(run(
            "kubectl", "-n", "rook-ceph", "exec", "deployment/rook-ceph-tools", "--",
            "radosgw-admin", *rgw_scope, "user", "info",
            f"--access-key={obc['AWS_ACCESS_KEY_ID']}", "--format=json",
        ))
        subprocess.run([
            "kubectl", "-n", "rook-ceph", "exec", "deployment/rook-ceph-tools", "--",
            "radosgw-admin", *rgw_scope, "user", "modify",
            f"--uid={user_info['user_id']}", "--max-buckets=10",
        ], check=True, stdout=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, KeyError, json.JSONDecodeError):
        raise SystemExit("failed to reconcile the Gnocchi RGW OBC user")


def replace_password(url, password):
    parsed = urlsplit(url)
    user = unquote(parsed.username or "")
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{quote(user, safe='')}:{quote(password, safe='')}@{host}{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


db_url = replace_password(conf["indexer"]["url"], runtime["DB_PASSWORD"])
conf["indexer"]["url"] = db_url
for section in conf.sections():
    if "coordination_url" in conf[section]:
        conf[section]["coordination_url"] = replace_password(
            conf[section]["coordination_url"], runtime["DB_PASSWORD"])
conf["keystone_authtoken"]["password"] = runtime["SERVICE_PASSWORD"]

endpoint = f"http://{obc_config['BUCKET_HOST']}:{obc_config['BUCKET_PORT']}"
for section in ("storage", "incoming"):
    conf[section]["s3_endpoint_url"] = endpoint
    conf[section]["s3_access_key_id"] = obc["AWS_ACCESS_KEY_ID"]
    conf[section]["s3_secret_access_key"] = obc["AWS_SECRET_ACCESS_KEY"]

from io import StringIO
rendered = StringIO()
conf.write(rendered)
template["data"]["gnocchi.conf"] = base64.b64encode(rendered.getvalue().encode()).decode()
try:
    current_config = json.loads(run(
        "kubectl", "-n", namespace, "get", "secret", "gnocchi-config", "-o", "json"
    ))["data"]["gnocchi.conf"]
except subprocess.CalledProcessError:
    current_config = None
config_changed = current_config != template["data"]["gnocchi.conf"]
run("kubectl", "apply", "-f", "-", input_text=yaml.safe_dump(template, sort_keys=False))

parsed = urlsplit(db_url)
db_user = unquote(parsed.username or "")
db_name = parsed.path.lstrip("/")
if not re.fullmatch(r"[A-Za-z0-9_]+", db_user) or not re.fullmatch(r"[A-Za-z0-9_]+", db_name):
    raise SystemExit("unsafe database identifier in Gnocchi URL")

def sql_quote(value):
    return "'" + value.replace("'", "''") + "'"

sql = (
    "SET sql_mode='NO_BACKSLASH_ESCAPES';\n"
    f"CREATE DATABASE IF NOT EXISTS `{db_name}`;\n"
    f"CREATE USER IF NOT EXISTS '{db_user}'@'%' IDENTIFIED BY {sql_quote(runtime['DB_PASSWORD'])};\n"
    f"ALTER USER '{db_user}'@'%' IDENTIFIED BY {sql_quote(runtime['DB_PASSWORD'])};\n"
    f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_user}'@'%';\n"
    "FLUSH PRIVILEGES;\n"
)
admin = secret("mariadb-dbadmin-password")["MYSQL_DBADMIN_PASSWORD"]
pods = json.loads(run(
    "kubectl", "-n", namespace, "get", "pod", "-l", "application=mariadb,component=server", "-o", "json"
))["items"]
pod = next(
    item["metadata"]["name"] for item in pods
    if any(c["type"] == "Ready" and c["status"] == "True" for c in item["status"].get("conditions", []))
)
db_command = [
    "kubectl", "-n", namespace, "exec", "-i", pod, "-c", "mariadb", "--",
    "env", f"MYSQL_PWD={admin}", "mariadb", "-uroot",
]
result = subprocess.run(db_command, input=sql, text=True, stdout=subprocess.DEVNULL)
if result.returncode:
    raise SystemExit("failed to reconcile the Gnocchi MariaDB account")
if config_changed:
    for deployment in ("gnocchi-api", "gnocchi-metricd"):
        if subprocess.run(
            ["kubectl", "-n", namespace, "get", "deployment", deployment],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0:
            subprocess.run(
                ["kubectl", "-n", namespace, "rollout", "restart", "deployment", deployment],
                check=True, stdout=subprocess.DEVNULL,
            )
print("Gnocchi runtime Secret and MariaDB account reconciled.")
