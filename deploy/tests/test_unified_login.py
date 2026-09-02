import base64
import hashlib
from pathlib import Path
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_keycloak_image_packages_dcn_openstack_theme():
    dockerfile = (ROOT / "images/keycloak/Dockerfile").read_text()
    theme = ROOT / "images/keycloak/themes/dcn-openstack/login"
    assert "COPY --chown=keycloak:keycloak themes/dcn-openstack" in dockerfile
    assert "parent=keycloak.v2" in (theme / "theme.properties").read_text()
    assert "Keycloak" not in (theme / "messages/messages_en.properties").read_text()
    messages = (theme / "messages/messages_en.properties").read_text()
    assert "Sign in to DCN Cloud" in messages
    assert "DCN OpenStack" not in messages
    css = (theme / "resources/css/dcn-openstack.css").read_text()
    assert "#kc-social-providers a svg" in css
    assert "max-width: 20px" in css
    assert "height: 44px" in css
    assert ".dcn-resource-panel" in css
    assert "flex-direction: column" in css
    assert "order: 1" in css
    assert "order: 2" in css
    properties = (theme / "theme.properties").read_text()
    assert "scripts=js/dcn-portals.js" in properties
    portals = (theme / "resources/js/dcn-portals.js").read_text()
    for url in (
        "https://platform.dcn.ssu.ac.kr/grafana/",
        "https://platform.dcn.ssu.ac.kr/netbox/",
        "https://billing.dcn.ssu.ac.kr/",
        "https://platform.dcn.ssu.ac.kr/git/",
        "https://registry.dcn.ssu.ac.kr/",
    ):
        assert url in portals
    for forbidden in ("prometheus", "alertmanager", "hubble", "rabbitmq"):
        assert forbidden not in portals.lower()


def test_iam_reconciler_selects_theme_without_user_password_grant():
    reconciler = (ROOT / "deploy/scripts/reconcile-iam-dcn.sh").read_text()
    assert '.loginTheme="dcn-openstack"' in reconciler
    assert 'directAccessGrantsEnabled:false' in reconciler


def test_iam_reconciler_creates_baremetal_roles_and_limits_admin_marker():
    reconciler = (ROOT / "deploy/scripts/reconcile-iam-dcn.sh").read_text()
    for role in ("baremetal_admin", "baremetal_requester", "baremetal_operator"):
        assert role in reconciler
    assert '[openstack-admins]="admin baremetal_admin"' in reconciler
    assert '[openstack-members]="member"' in reconciler
    assert 'INHERITED_PROJECT_ROLES' not in reconciler
    assert '/OS-INHERIT/domains/${DOMAIN_ID}/groups/${member_group_id}/roles/${requester_role_id}/inherited_to_projects' in reconciler
    assert '-X DELETE' in reconciler
    assert 'legacy inherited baremetal_requester assignment is absent' in reconciler
    assert '/projects/${PROJECT_ID}/groups/${member_group_id}/roles/${requester_role_id}' in reconciler
    assert '"/openstack-members"' in reconciler
    assert '/groups/${member_group_id}' in reconciler
    assert 'startswith("service-account-")' in reconciler


def test_unified_login_proves_default_member_can_open_baremetal_requests():
    runner = (ROOT / "deploy/scripts/verify-unified-login-browser.sh").read_text()
    browser = (ROOT / "deploy/scripts/verify-unified-login-browser.js").read_text()
    assert '/users/$user_id/groups/$group_id' not in runner
    assert "Bare Metal Access" in browser
    assert "/horizon/project/baremetal_access/" in browser
    assert "Request nodes" in browser
    assert "baseline DCN member received approval UI" in browser


def test_horizon_image_flushes_local_session_before_oidc_logout():
    patcher = (ROOT / "images/horizon-complete/patch_federated_logout.py").read_text()
    dockerfile = (ROOT / "images/horizon-complete/Dockerfile").read_text()
    builder = (ROOT / "deploy/scripts/build-horizon-image.sh").read_text()
    queued_builder = (ROOT / "deploy/scripts/build-images.sh").read_text()
    assert "auth.logout(request)" in patcher
    assert "auth_user.unset_session_user_variables(request)" in patcher
    assert "source.count(old) != 1" in patcher
    assert "COPY patch_federated_logout.py" in dockerfile
    assert "python3 /tmp/patch_federated_logout.py" in dockerfile
    assert 'cp "$REPO_ROOT/images/horizon-complete/patch_federated_logout.py"' in builder
    assert 'cp "$REPO_ROOT/images/horizon-complete/patch_federated_logout.py"' in queued_builder


def test_production_horizon_uses_same_origin_keycloak_websso():
    values = (ROOT / "deploy/values/site/horizon.yaml").read_text()
    assert "default_redirect: true" in values
    assert "default_redirect_protocol: openid" in values
    assert "initial_choice: keycloak_dcn" in values


def test_horizon_qoe_uses_csrf_endpoint_when_visible_login_redirects_to_oidc():
    verifier = (ROOT / "deploy/scripts/verify-horizon-qoe.sh").read_text()
    assert "openssl rand -hex 16" in verifier
    assert '-b "csrftoken=$csrf"' in verifier
    assert "--data-urlencode auth_type=credentials" in verifier
    assert "for attempt in 1 2 3 4 5 6" in verifier
    assert "[[ $status == 302 || $status == 303 ]] && break" in verifier
    assert "Horizon login form has no CSRF token" not in verifier


def test_rendered_horizon_redirects_to_same_origin_websso():
    rendered = subprocess.run(
        [
            "helm",
            "template",
            "horizon",
            str(ROOT / "helm/openstack-helm/horizon"),
            "-f",
            str(ROOT / "deploy/values/site/horizon.yaml"),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    documents = [document for document in yaml.safe_load_all(rendered) if document]
    secret = next(
        document
        for document in documents
        if document.get("kind") == "Secret"
        and "local_settings" in document.get("data", {})
    )
    settings = base64.b64decode(secret["data"]["local_settings"]).decode()
    assert "WEBSSO_DEFAULT_REDIRECT = True" in settings
    assert 'WEBSSO_INITIAL_CHOICE = "keycloak_dcn"' in settings
    assert 'WEBSSO_DEFAULT_REDIRECT_PROTOCOL = "openid"' in settings
    assert (
        'WEBSSO_DEFAULT_REDIRECT_REGION = '
        '"https://cloud.dcn.ssu.ac.kr/identity/v3"'
    ) in settings


def test_locked_horizon_package_renders_same_origin_websso():
    lock = yaml.safe_load((ROOT / "release-lock.yaml").read_text())
    release = next(
        item for item in lock["spec"]["releases"] if item["name"] == "horizon"
    )
    package = ROOT / release["package"]
    assert hashlib.sha256(package.read_bytes()).hexdigest() == release["sha256"]
    rendered = subprocess.run(
        [
            "helm",
            "template",
            "horizon",
            str(package),
            "-f",
            str(ROOT / "deploy/values/site/horizon.yaml"),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    documents = [document for document in yaml.safe_load_all(rendered) if document]
    secret = next(
        document
        for document in documents
        if document.get("kind") == "Secret"
        and "local_settings" in document.get("data", {})
    )
    settings = base64.b64decode(secret["data"]["local_settings"]).decode()
    assert "WEBSSO_DEFAULT_REDIRECT = True" in settings
    assert 'WEBSSO_DEFAULT_REDIRECT_PROTOCOL = "openid"' in settings
    assert "WEBSSO_DEFAULT_REDIRECT_LOGOUT" in settings
    assert "oidc-callback?logout=" in settings
    assert "auth.cloud.dcn.ssu.ac.kr" not in settings


def test_keystone_resolves_protocol_only_websso_to_keycloak_issuer():
    values = yaml.safe_load((ROOT / "deploy/values/site/keystone.yaml").read_text())
    assert (
        values["conf"]["keystone"]["federation"]["remote_id_attribute"]
        == "HTTP_OIDC_ISS"
    )
    reconciler = (ROOT / "deploy/scripts/reconcile-iam-dcn.sh").read_text()
    assert "https://cloud.dcn.ssu.ac.kr/horizon/auth/idp/realms/dcn" in reconciler
    assert "https://auth.cloud.dcn.ssu.ac.kr/realms/dcn" not in reconciler
    generator = (ROOT / "deploy/scripts/generate-keycloak-oidc-override.py").read_text()
    assert (
        "http://keycloak-service.keycloak.svc.cluster.local:8080/realms/dcn/"
        in generator
    )
    assert "expected exactly one OIDCProviderMetadataURL directive" in generator
    assert "client-cookie:persistent:store_id_token" in generator
    assert 'OIDCLogoutRequestParams "client_id=keystone"' in generator
    assert '"post.logout.redirect.uris"' in reconciler
