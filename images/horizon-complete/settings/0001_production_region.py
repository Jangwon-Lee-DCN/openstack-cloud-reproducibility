AVAILABLE_REGIONS = [
    ("https://cloud.dcn.ssu.ac.kr/identity/v3", "seoul-ssu-1"),
]

DEFAULT_SERVICE_REGIONS = {
    "*": "seoul-ssu-1",
}

# Use Horizon's project image table so the catalogue can expose explicit,
# mutually exclusive ownership views.  Public visibility alone must never be
# treated as proof that an image is platform-maintained.
ANGULAR_FEATURES["images_panel"] = False

# Keystone project ID of the platform image publisher (the admin project).
# Future publisher projects can be appended without changing dashboard code.
PLATFORM_IMAGE_OWNER_IDS = (
    "fe9c1a5f82f440c68baf3d9c8fb40ea2",
)

# The production default is the namespace-local Governance API.  Development
# overrides it explicitly with its isolated endpoint.
GOVERNANCE_FAKE_API_ENDPOINT = os.environ.get(
    "GOVERNANCE_API_ENDPOINT",
    "http://governance-api.governance-system.svc.cluster.local",
)
GOVERNANCE_API_CA_FILE = "/etc/openstack-dashboard/governance-ca/tls.crt"
