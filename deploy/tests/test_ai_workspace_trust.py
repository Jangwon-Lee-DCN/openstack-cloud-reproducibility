import base64
import importlib.util
import pathlib


PATH = pathlib.Path(__file__).parents[1] / "scripts" / "render-ai-workspace-trust.py"
SPEC = importlib.util.spec_from_file_location("render_ai_workspace_trust", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_render_installs_ca_and_keeps_tls_verification_enabled():
    ca = b"-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----\n"
    rendered = MODULE.render(ca, "https://s3.example.test/")
    assert base64.b64encode(ca).decode() in rendered
    assert "update-ca-certificates" in rendered
    assert "https://s3.example.test/" in rendered
    assert "--insecure" not in rendered
    assert "AI_WORKSPACE_RGW_TLS_OK" in rendered


def test_render_rejects_non_certificate_input():
    try:
        MODULE.render(b"not a certificate", "https://s3.example.test/")
    except ValueError as exc:
        assert "PEM certificate" in str(exc)
    else:
        raise AssertionError("non-certificate input was accepted")
