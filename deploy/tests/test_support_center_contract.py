from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]


def test_support_center_is_internal_and_durable(tmp_path):
    template = ROOT / "deploy/templates/support-center.yaml.tmpl"
    output = tmp_path / "rendered.yaml"
    image = "registry.invalid/support-api@sha256:" + "a" * 64
    subprocess.run([
        "python3", str(ROOT / "deploy/scripts/render-support-center.py"),
        "--template", str(template), "--output", str(output),
        "--namespace", "development-support-center",
        "--horizon-namespace", "development-support-center",
        "--image", image, "--keystone-url", "https://keystone.invalid/v3",
    ], check=True)
    rendered = output.read_text()
    assert image in rendered
    assert "kind: HTTPRoute" not in rendered
    assert "replicas: 3" in rendered
    assert "dcn-support-database" in rendered
    assert "minAvailable: 2" in rendered
    assert "readOnlyRootFilesystem: true" in rendered
    assert "path: /readyz" in rendered
    assert "@NAMESPACE@" not in rendered


def test_mutable_support_image_is_rejected(tmp_path):
    result = subprocess.run([
        "python3", str(ROOT / "deploy/scripts/render-support-center.py"),
        "--template", str(ROOT / "deploy/templates/support-center.yaml.tmpl"),
        "--output", str(tmp_path / "rendered.yaml"),
        "--namespace", "test", "--horizon-namespace", "test",
        "--image", "registry.invalid/support-api:latest",
        "--keystone-url", "https://keystone.invalid/v3",
    ])
    assert result.returncode != 0
