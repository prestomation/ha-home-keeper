"""Integration tests for a part's single attached file.

Run against the real Home Assistant Docker container. A part's file reuses the same
upload/storage/validation machinery as appliance documents (see test_documents.py),
keyed by the part's own id instead of a document id, so most of this mirrors that
file's coverage — plus isolation from the generic update_asset write path.
"""

import time
import uuid

import requests
from conftest import HA_URL, call_service

PDF_BYTES = b"%PDF-1.7\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def _assets(ha):
    resp = call_service(ha, "home_keeper", "list_assets", {}, return_response=True)
    return resp.get("service_response", resp)["assets"]


def _provision_with_part(ha, name, part_name="Filter"):
    """Create a virtual appliance with one part; return (asset, part_id)."""
    call_service(
        ha,
        "home_keeper",
        "add_asset",
        {"name": name, "parts": [{"name": part_name, "type": "consumable"}]},
    )
    for _ in range(20):
        match = next(
            (a for a in _assets(ha) if a["name"] == name and a.get("device_id")), None
        )
        if match:
            return match, match["parts"][0]["id"]
        time.sleep(1)
    raise AssertionError(f"appliance {name!r} was not provisioned")


def _bearer(ha):
    return {"Authorization": ha.headers["Authorization"]}


def _part(ha, asset_id, part_id):
    asset = next(a for a in _assets(ha) if a["id"] == asset_id)
    return next(p for p in asset["parts"] if p["id"] == part_id)


def test_upload_download_and_remove_part_file(ha):
    name = f"Part file probe {uuid.uuid4().hex[:8]}"
    asset, part_id = _provision_with_part(ha, name)
    url = f"{HA_URL}/api/home_keeper/part_document/{asset['id']}/{part_id}"

    up = requests.post(
        url,
        files={"file": ("receipt.pdf", PDF_BYTES, "application/pdf")},
        data={"name": "Receipt"},
        headers=_bearer(ha),
        timeout=30,
    )
    assert up.status_code == 200, up.text
    body = up.json()
    assert body["part"]["file_name"] == "receipt.pdf"
    assert body["part"]["file_content_type"] == "application/pdf"
    assert body["part"]["file_size"] == len(PDF_BYTES)

    after = _part(ha, asset["id"], part_id)
    assert after["file_name"] == "receipt.pdf"

    dl = ha.get(url)
    assert dl.status_code == 200
    assert dl.content == PDF_BYTES
    assert dl.headers.get("Content-Type", "").startswith("application/pdf")

    call_service(
        ha, "home_keeper", "remove_part_file", {"asset_id": asset["id"], "part_id": part_id}
    )
    cleared = _part(ha, asset["id"], part_id)
    assert cleared["file_name"] is None
    gone = ha.get(url)
    assert gone.status_code == 404
    call_service(ha, "home_keeper", "delete_asset", {"asset_id": asset["id"]})


def test_upload_rejects_non_allowlisted_type(ha):
    name = f"Part file bad-type {uuid.uuid4().hex[:8]}"
    asset, part_id = _provision_with_part(ha, name)
    url = f"{HA_URL}/api/home_keeper/part_document/{asset['id']}/{part_id}"
    r = requests.post(
        url,
        files={
            "file": ("evil.exe", b"MZ\x90\x00not a pdf", "application/octet-stream")
        },
        headers=_bearer(ha),
        timeout=30,
    )
    assert r.status_code == 400, r.text
    after = _part(ha, asset["id"], part_id)
    assert after["file_name"] is None, "a rejected upload must not attach a file"
    call_service(ha, "home_keeper", "delete_asset", {"asset_id": asset["id"]})


def test_reupload_replaces_old_blob(ha):
    name = f"Part file reupload {uuid.uuid4().hex[:8]}"
    asset, part_id = _provision_with_part(ha, name)
    url = f"{HA_URL}/api/home_keeper/part_document/{asset['id']}/{part_id}"

    first = requests.post(
        url,
        files={"file": ("first.pdf", PDF_BYTES, "application/pdf")},
        headers=_bearer(ha),
        timeout=30,
    )
    assert first.status_code == 200, first.text

    second = requests.post(
        url,
        files={"file": ("second.png", PNG_BYTES, "image/png")},
        headers=_bearer(ha),
        timeout=30,
    )
    assert second.status_code == 200, second.text
    assert second.json()["part"]["file_name"] == "second.png"

    dl = ha.get(url)
    assert dl.status_code == 200
    assert dl.content == PNG_BYTES
    assert dl.headers.get("Content-Type", "").startswith("image/png")
    call_service(ha, "home_keeper", "delete_asset", {"asset_id": asset["id"]})


def test_update_asset_preserves_part_file(ha):
    # A generic update_asset that resends the parts list (without file_* keys, since
    # the panel never sends them) must NOT drop the attached file or orphan its blob.
    name = f"Part file preserve probe {uuid.uuid4().hex[:8]}"
    asset, part_id = _provision_with_part(ha, name)
    url = f"{HA_URL}/api/home_keeper/part_document/{asset['id']}/{part_id}"
    up = requests.post(
        url,
        files={"file": ("receipt.pdf", PDF_BYTES, "application/pdf")},
        headers=_bearer(ha),
        timeout=30,
    )
    assert up.status_code == 200, up.text

    call_service(
        ha,
        "home_keeper",
        "update_asset",
        {
            "asset_id": asset["id"],
            "parts": [{"id": part_id, "name": "Filter", "type": "consumable"}],
        },
    )
    after = _part(ha, asset["id"], part_id)
    assert after["file_name"] == "receipt.pdf"
    dl = ha.get(url)
    assert dl.status_code == 200 and dl.content == PDF_BYTES

    # ...nor can a generic write inject a spoofed file_name for a part that never
    # had one uploaded.
    call_service(
        ha,
        "home_keeper",
        "update_asset",
        {
            "asset_id": asset["id"],
            "parts": [
                {"id": part_id, "name": "Filter", "type": "consumable"},
                {"name": "Other", "type": "consumable", "file_name": "hacked.pdf"},
            ],
        },
    )
    other = next(
        p
        for p in next(a for a in _assets(ha) if a["id"] == asset["id"])["parts"]
        if p["name"] == "Other"
    )
    assert other["file_name"] is None
    call_service(ha, "home_keeper", "delete_asset", {"asset_id": asset["id"]})


def test_delete_asset_cleans_up_part_files(ha):
    name = f"Part file cleanup probe {uuid.uuid4().hex[:8]}"
    asset, part_id = _provision_with_part(ha, name)
    url = f"{HA_URL}/api/home_keeper/part_document/{asset['id']}/{part_id}"
    up = requests.post(
        url,
        files={"file": ("receipt.pdf", PDF_BYTES, "application/pdf")},
        headers=_bearer(ha),
        timeout=30,
    )
    assert up.status_code == 200, up.text

    call_service(ha, "home_keeper", "delete_asset", {"asset_id": asset["id"]})
    gone = ha.get(url)
    assert gone.status_code == 404


def test_remove_part_file_unknown_part_errors(ha):
    name = f"Part file unknown probe {uuid.uuid4().hex[:8]}"
    asset, _part_id = _provision_with_part(ha, name)
    r = ha.post(
        f"{HA_URL}/api/services/home_keeper/remove_part_file",
        json={"asset_id": asset["id"], "part_id": "does-not-exist"},
    )
    assert r.status_code >= 400, "removing an unknown part's file must fail"
    call_service(ha, "home_keeper", "delete_asset", {"asset_id": asset["id"]})


def test_part_file_view_requires_auth(ha):
    r = requests.get(
        f"{HA_URL}/api/home_keeper/part_document/whatever/whatever", timeout=10
    )
    assert r.status_code in (401, 403)
