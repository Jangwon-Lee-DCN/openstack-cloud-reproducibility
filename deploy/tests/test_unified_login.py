import base64
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
    assert "DCN OpenStack" in (theme / "messages/messages_en.properties").read_text()
    css = (theme / "resources/css/dcn-openstack.css").read_text()
    assert "#kc-social-providers a svg" in css
    assert "max-width: 20px" in css
    assert "height: 44px" in css


def test_iam_reconciler_selects_theme_without_user_password_grant():
    reconciler = (ROOT / "deploy/scripts/reconcile-iam-dcn.sh").read_text()
    assert '.loginTheme="dcn-openstack"' in reconciler
    assert 'directAccessGrantsEnabled:false' in reconciler


def test_production_horizon_requires_explicit_keycloak_websso():
    values = (ROOT / "deploy/values/site/horizon.yaml").read_text()
    assert "default_redirect: false" in values
    assert "default_redirect_protocol: keycloak_dcn" in values
    assert "initial_choice: keycloak_dcn" in values


def test_rendered_horizon_keeps_login_page_until_explicit_websso():
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
    assert "WEBSSO_DEFAULT_REDIRECT = False" in settings
    assert 'WEBSSO_INITIAL_CHOICE = "keycloak_dcn"' in settings
    assert (
        'WEBSSO_DEFAULT_REDIRECT_REGION = '
        '"https://cloud.dcn.ssu.ac.kr/identity/v3"'
    ) in settings


def test_keystone_resolves_protocol_only_websso_to_keycloak_issuer():
    values = yaml.safe_load((ROOT / "deploy/values/site/keystone.yaml").read_text())
    assert (
        values["conf"]["keystone"]["federation"]["remote_id_attribute"]
        == "HTTP_OIDC_ISS"
    )
