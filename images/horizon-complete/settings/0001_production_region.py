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

# Track B remains an isolated development service until its production
# promotion.  Horizon proxies the preview UI to its TLS endpoint; keeping the
# endpoint explicit prevents an unset setting from turning every Governance
# and Cost Management page into HTTP 500.
GOVERNANCE_FAKE_API_ENDPOINT = (
    "https://p1-governance-services.dev.dcn.ssu.ac.kr"
)
