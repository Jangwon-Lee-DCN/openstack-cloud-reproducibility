import os


# Fail closed until the exact Keystone DCN project UUID is supplied by the
# deployment values. Project names are mutable and therefore not accepted.
DCN_BAREMETAL_ADMIN_PROJECT_ID = os.environ.get("DCN_BAREMETAL_ADMIN_PROJECT_ID", "")
