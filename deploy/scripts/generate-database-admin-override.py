#!/usr/bin/env python3
"""Write a mode-0600 Helm override using active DB and RabbitMQ admins."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import quote

if len(sys.argv) != 3:
    raise SystemExit("usage: generate-database-admin-override.py RELEASE OUTPUT")

release, output_name = sys.argv[1:]
raw = subprocess.check_output(
    ["kubectl", "-n", os.environ.get("NAMESPACE", "openstack"), "get", "secret",
     "mariadb-dbadmin-password", "-o", "json"],
    text=True,
)
secret = json.loads(raw)
password = base64.b64decode(secret["data"]["MYSQL_DBADMIN_PASSWORD"]).decode()
rabbit_raw = subprocess.check_output(
    ["kubectl", "-n", os.environ.get("NAMESPACE", "openstack"), "get", "secret",
     "rabbitmq-admin-user", "-o", "json"],
    text=True,
)
rabbit = json.loads(rabbit_raw)["data"]
rabbit_user = base64.b64decode(rabbit["RABBITMQ_ADMIN_USERNAME"]).decode()
rabbit_password = base64.b64decode(rabbit["RABBITMQ_ADMIN_PASSWORD"]).decode()
identity_raw = subprocess.check_output(
    ["kubectl", "-n", os.environ.get("NAMESPACE", "openstack"), "get", "secret",
     "keystone-keystone-admin", "-o", "json"],
    text=True,
)
identity = json.loads(identity_raw)["data"]
identity_value = lambda key: base64.b64decode(identity[key]).decode()
output = Path(output_name)
output.write_text(
    "endpoints:\n"
    "  oslo_db:\n"
    "    auth:\n"
    "      admin:\n"
    f"        password: '{quote(password, safe='')}'\n"
    "  oslo_messaging:\n"
    "    auth:\n"
    "      admin:\n"
    f"        username: '{rabbit_user}'\n"
    f"        password: '{quote(rabbit_password, safe='')}'\n"
    "  identity:\n"
    "    auth:\n"
    "      admin:\n"
    f"        username: '{identity_value('OS_USERNAME')}'\n"
    f"        password: '{identity_value('OS_PASSWORD')}'\n"
    f"        project_name: '{identity_value('OS_PROJECT_NAME')}'\n"
    f"        user_domain_name: '{identity_value('OS_USER_DOMAIN_NAME')}'\n"
    f"        project_domain_name: '{identity_value('OS_PROJECT_DOMAIN_NAME')}'\n"
)
output.chmod(0o600)
