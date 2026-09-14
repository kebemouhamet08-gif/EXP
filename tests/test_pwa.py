import json
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def png_dimensions(path):
    with path.open("rb") as image:
        assert image.read(8) == b"\x89PNG\r\n\x1a\n"
        assert image.read(4) == b"\x00\x00\x00\r"
        assert image.read(4) == b"IHDR"
        return struct.unpack(">II", image.read(8))


def test_manifest_is_accessible_and_valid(client):
    response = client.get("/static/manifest.webmanifest")
    try:
        assert response.status_code == 200
        manifest = json.loads(response.get_data(as_text=True))
    finally:
        response.close()
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
    assert manifest["scope"] == "/"
    assert "standalone" in manifest["display_override"]


def test_manifest_has_required_install_icons():
    manifest = json.loads((ROOT / "static" / "manifest.webmanifest").read_text(encoding="utf-8"))
    icons = {icon["sizes"]: icon for icon in manifest["icons"] if icon["purpose"] == "any"}
    assert icons["192x192"]["src"] == "/static/icons/icon-192.png"
    assert icons["512x512"]["src"] == "/static/icons/icon-512.png"
    assert png_dimensions(ROOT / "static" / "icons" / "icon-192.png") == (192, 192)
    assert png_dimensions(ROOT / "static" / "icons" / "icon-512.png") == (512, 512)


def test_service_worker_is_accessible_with_root_scope(client):
    response = client.get("/static/sw.js")
    try:
        assert response.status_code == 200
        assert response.headers["Service-Worker-Allowed"] == "/"
    finally:
        response.close()


def test_base_references_manifest_and_icons():
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    assert "manifest.webmanifest" in base
    assert "favicon-16x16.png" in base
    assert "favicon-32x32.png" in base
    assert "icon-180.png" in base


def test_private_routes_are_absent_from_service_worker_precache():
    worker = (ROOT / "static" / "sw.js").read_text(encoding="utf-8")
    precache = worker.split("const PRECACHE_URLS = [", 1)[1].split("];", 1)[0]
    forbidden = (
        "/connexion", "/inscription", "/deconnexion", "/changer-compte", "/auth/",
        "/dashboard", "/eleve", "/professeur", "/devoir/", "/uploads/", "/mon-compte",
    )
    assert all(route not in precache for route in forbidden)
