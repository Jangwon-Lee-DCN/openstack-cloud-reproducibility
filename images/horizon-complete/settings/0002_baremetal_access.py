import os


# Fail closed until the exact Keystone DCN project UUID is supplied by the
# deployment values. Project names are mutable and therefore not accepted.
DCN_BAREMETAL_ADMIN_PROJECT_ID = os.environ.get("DCN_BAREMETAL_ADMIN_PROJECT_ID", "")
DCN_BAREMETAL_DOMAIN_ID = os.environ.get("DCN_BAREMETAL_DOMAIN_ID", "")
BAREMETAL_ACCESS_API_URL = os.environ.get(
    "BAREMETAL_ACCESS_API_URL",
    "http://baremetal-access.netbox-ironic-controller.svc.cluster.local:8080",
)
