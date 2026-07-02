"""Integration tests for appliance documents (offline manuals).

Run against the real Home Assistant Docker container. Cover the link-document
services, and the file-document HTTP view round-trip (multipart upload → authenticated
download → removal deletes the stored copy), plus the upload allowlist.
"""

import time
import uuid

import requests
from conftest import HA_URL, call_service

PDF_BYTES = b"%PDF-1.7\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _assets(ha):
    resp = call_service(ha, "home_keeper", "list_assets", {}, return_response=True)
    return resp.get("service_response", resp)["assets"]


def _provision(ha, name):
    """Create a virtual appliance and return it once it has a device id."""
    call_service(ha, "home_keeper", "add_asset", {"name": name})
    for _ in range(20):
        match = next(
            (a for a in _assets(ha) if a["name"] == name and a.get("device_id")), None
        )
        if match:
            return match
        time.sleep(1)
    raise AssertionError(f"appliance {name!r} was not provisioned")


def _bearer(ha):
    return {"Authorization": ha.headers["Authorization"]}


def test_add_and_remove_link_document(ha):
    name = f"Doc link probe {uuid.uuid4().hex[:8]}"
    asset = _provision(ha, name)
    call_service(
        ha,
        "home_keeper",
        "add_asset_document",
        {
            "asset_id": asset["id"],
            "document": {"name": "Manual", "url": "https://example.com/manual.pdf"},
        },
    )
    after = next(a for a in _assets(ha) if a["id"] == asset["id"])
    docs = after.get("documents", [])
    assert len(docs) == 1 and docs[0]["kind"] == "link"
    assert docs[0]["url"] == "https://example.com/manual.pdf"
    doc_id = docs[0]["id"]

    call_service(
        ha,
        "home_keeper",
        "remove_asset_document",
        {"asset_id": asset["id"], "document_id": doc_id},
    )
    after = next(a for a in _assets(ha) if a["id"] == asset["id"])
    assert after.get("documents", []) == []
    call_service(ha, "home_keeper", "delete_asset", {"asset_id": asset["id"]})


def test_update_link_document_renames_and_changes_url(ha):
    name = f"Doc edit link {uuid.uuid4().hex[:8]}"
    asset = _provision(ha, name)
    call_service(
        ha,
        "home_keeper",
        "add_asset_document",
        {
            "asset_id": asset["id"],
            "document": {"name": "Manual", "url": "https://example.com/old.pdf"},
        },
    )
    doc_id = next(a for a in _assets(ha) if a["id"] == asset["id"])["documents"][0][
        "id"
    ]

    call_service(
        ha,
        "home_keeper",
        "update_asset_document",
        {
            "asset_id": asset["id"],
            "document_id": doc_id,
            "changes": {"name": "Owner's manual", "url": "https://example.com/new.pdf"},
        },
    )
    doc = next(a for a in _assets(ha) if a["id"] == asset["id"])["documents"][0]
    assert doc["id"] == doc_id  # id is stable across the edit
    assert doc["name"] == "Owner's manual"
    assert doc["url"] == "https://example.com/new.pdf"
    call_service(ha, "home_keeper", "delete_asset", {"asset_id": asset["id"]})


def test_update_file_document_renames_but_keeps_blob(ha):
    name = f"Doc edit file {uuid.uuid4().hex[:8]}"
    asset = _provision(ha, name)
    doc_id = uuid.uuid4().hex
    up = requests.post(
        f"{HA_URL}/api/home_keeper/document/{asset['id']}/{doc_id}",
        files={"file": ("manual.pdf", PDF_BYTES, "application/pdf")},
        data={"name": "Manual"},
        headers=_bearer(ha),
        timeout=30,
    )
    assert up.status_code == 200, up.text
    file_id = up.json()["document"]["id"]

    # A file is upload-only: only its display name is editable; its blob stays put.
    call_service(
        ha,
        "home_keeper",
        "update_asset_document",
        {
            "asset_id": asset["id"],
            "document_id": file_id,
            "changes": {"name": "Warranty card"},
        },
    )
    doc = next(
        d
        for d in next(a for a in _assets(ha) if a["id"] == asset["id"])["documents"]
        if d["id"] == file_id
    )
    assert doc["name"] == "Warranty card"
    assert doc["filename"] == "manual.pdf"
    assert doc["kind"] == "file"
    # The blob is untouched and still downloadable.
    dl = ha.get(f"{HA_URL}/api/home_keeper/document/{asset['id']}/{file_id}")
    assert dl.status_code == 200 and dl.content == PDF_BYTES
    call_service(ha, "home_keeper", "delete_asset", {"asset_id": asset["id"]})


def test_update_asset_document_unknown_id_errors(ha):
    name = f"Doc edit missing {uuid.uuid4().hex[:8]}"
    asset = _provision(ha, name)
    r = ha.post(
        f"{HA_URL}/api/services/home_keeper/update_asset_document",
        json={
            "asset_id": asset["id"],
            "document_id": "does-not-exist",
            "changes": {"name": "x"},
        },
    )
    assert r.status_code >= 400, "editing an unknown document must fail"
    call_service(ha, "home_keeper", "delete_asset", {"asset_id": asset["id"]})


def test_add_asset_document_rejects_file_kind(ha):
    name = f"Doc file-guard {uuid.uuid4().hex[:8]}"
    asset = _provision(ha, name)
    r = ha.post(
        f"{HA_URL}/api/services/home_keeper/add_asset_document",
        json={
            "asset_id": asset["id"],
            "document": {"kind": "file", "filename": "x.pdf"},
        },
    )
    assert r.status_code >= 400, "file documents must be uploaded via the HTTP view"
    call_service(ha, "home_keeper", "delete_asset", {"asset_id": asset["id"]})


def test_upload_download_and_remove_file_document(ha):
    name = f"Doc upload probe {uuid.uuid4().hex[:8]}"
    asset = _provision(ha, name)
    doc_id = uuid.uuid4().hex
    url = f"{HA_URL}/api/home_keeper/document/{asset['id']}/{doc_id}"

    # Upload a PDF via multipart (no JSON content-type — fresh headers).
    up = requests.post(
        url,
        files={"file": ("manual.pdf", PDF_BYTES, "application/pdf")},
        data={"name": "Fridge manual"},
        headers=_bearer(ha),
        timeout=30,
    )
    assert up.status_code == 200, up.text
    body = up.json()
    doc = body["document"]
    assert doc["kind"] == "file"
    assert doc["content_type"] == "application/pdf"
    assert doc["size"] == len(PDF_BYTES)
    assert doc["name"] == "Fridge manual"

    # The asset now carries the file document.
    after = next(a for a in _assets(ha) if a["id"] == asset["id"])
    assert any(d["id"] == doc["id"] and d["kind"] == "file" for d in after["documents"])

    # Download it back (authenticated header works; signed URL is for the browser).
    dl = ha.get(f"{HA_URL}/api/home_keeper/document/{asset['id']}/{doc['id']}")
    assert dl.status_code == 200
    assert dl.content == PDF_BYTES
    assert dl.headers.get("Content-Type", "").startswith("application/pdf")

    # A signed URL can be minted over websocket and is openable too.
    # (Removal deletes the stored copy: a subsequent download 404s.)
    call_service(
        ha,
        "home_keeper",
        "remove_asset_document",
        {"asset_id": asset["id"], "document_id": doc["id"]},
    )
    gone = ha.get(f"{HA_URL}/api/home_keeper/document/{asset['id']}/{doc['id']}")
    assert gone.status_code == 404
    call_service(ha, "home_keeper", "delete_asset", {"asset_id": asset["id"]})


def test_download_streams_with_content_disposition(ha):
    # N10: the blob is written to disk BEFORE the metadata is persisted / the
    # home_keeper_asset_updated event fires, so a GET immediately after the upload
    # returns 200 (no 404 gap). The GET streams from disk via aiohttp's FileResponse,
    # which sets an inline Content-Disposition naming the file and a content type.
    name = f"Doc stream probe {uuid.uuid4().hex[:8]}"
    asset = _provision(ha, name)
    doc_id = uuid.uuid4().hex
    up = requests.post(
        f"{HA_URL}/api/home_keeper/document/{asset['id']}/{doc_id}",
        files={"file": ("owner-manual.pdf", PDF_BYTES, "application/pdf")},
        headers=_bearer(ha),
        timeout=30,
    )
    assert up.status_code == 200, up.text
    file_id = up.json()["document"]["id"]

    dl = ha.get(f"{HA_URL}/api/home_keeper/document/{asset['id']}/{file_id}")
    assert dl.status_code == 200
    assert dl.content == PDF_BYTES
    disposition = dl.headers.get("Content-Disposition", "")
    assert disposition.startswith("inline")
    assert "owner-manual.pdf" in disposition
    assert dl.headers.get("Content-Type", "").startswith("application/pdf")
    call_service(ha, "home_keeper", "delete_asset", {"asset_id": asset["id"]})


def test_upload_rejects_non_allowlisted_type(ha):
    name = f"Doc bad-type {uuid.uuid4().hex[:8]}"
    asset = _provision(ha, name)
    doc_id = uuid.uuid4().hex
    url = f"{HA_URL}/api/home_keeper/document/{asset['id']}/{doc_id}"
    r = requests.post(
        url,
        files={
            "file": ("evil.exe", b"MZ\x90\x00not a pdf", "application/octet-stream")
        },
        headers=_bearer(ha),
        timeout=30,
    )
    assert r.status_code == 400, r.text
    after = next(a for a in _assets(ha) if a["id"] == asset["id"])
    assert after.get("documents", []) == [], "a rejected upload must not add a document"
    call_service(ha, "home_keeper", "delete_asset", {"asset_id": asset["id"]})


def test_update_asset_preserves_uploaded_file_document(ha):
    # A generic update_asset that resends a documents list (links only) must NOT drop
    # an uploaded file document or orphan its blob — files are upload-only.
    name = f"Doc preserve probe {uuid.uuid4().hex[:8]}"
    asset = _provision(ha, name)
    doc_id = uuid.uuid4().hex
    up = requests.post(
        f"{HA_URL}/api/home_keeper/document/{asset['id']}/{doc_id}",
        files={"file": ("manual.pdf", PDF_BYTES, "application/pdf")},
        headers=_bearer(ha),
        timeout=30,
    )
    assert up.status_code == 200, up.text
    file_id = up.json()["document"]["id"]

    # A generic edit that also carries a documents array (a link + a phantom file).
    call_service(
        ha,
        "home_keeper",
        "update_asset",
        {
            "asset_id": asset["id"],
            "manufacturer": "Acme",
            "documents": [
                {"kind": "link", "url": "https://example.com/x"},
                {
                    "kind": "file",
                    "filename": "phantom.pdf",
                    "content_type": "application/pdf",
                },
            ],
        },
    )
    after = next(a for a in _assets(ha) if a["id"] == asset["id"])
    files = [d for d in after["documents"] if d["kind"] == "file"]
    # The original uploaded file survives; the phantom file entry was not injected.
    assert [d["id"] for d in files] == [file_id]
    # ...and its blob is still downloadable.
    dl = ha.get(f"{HA_URL}/api/home_keeper/document/{asset['id']}/{file_id}")
    assert dl.status_code == 200 and dl.content == PDF_BYTES
    call_service(ha, "home_keeper", "delete_asset", {"asset_id": asset["id"]})


def test_upload_larger_than_ha_app_limit_succeeds(ha):
    # Regression: HA's global aiohttp body cap (MAX_CLIENT_SIZE, 16 MB) is below our
    # 25 MB document ceiling, so the view must raise the per-request cap — otherwise a
    # 16-25 MB manual is rejected with a bare 413 before our handler runs.
    name = f"Doc big probe {uuid.uuid4().hex[:8]}"
    asset = _provision(ha, name)
    big = b"%PDF-1.7\n" + b"0" * (17 * 1024 * 1024) + b"\n%%EOF"
    r = requests.post(
        f"{HA_URL}/api/home_keeper/document/{asset['id']}/{uuid.uuid4().hex}",
        files={"file": ("big-manual.pdf", big, "application/pdf")},
        headers=_bearer(ha),
        timeout=60,
    )
    assert r.status_code == 200, (
        f"17 MB upload rejected: {r.status_code} {r.text[:200]}"
    )
    doc = r.json()["document"]
    assert doc["size"] == len(big)
    dl = ha.get(f"{HA_URL}/api/home_keeper/document/{asset['id']}/{doc['id']}")
    assert dl.status_code == 200 and len(dl.content) == len(big)
    call_service(ha, "home_keeper", "delete_asset", {"asset_id": asset["id"]})


def test_document_view_requires_auth(ha):
    # The view is auth-gated: an unauthenticated GET is rejected.
    r = requests.get(f"{HA_URL}/api/home_keeper/document/whatever/whatever", timeout=10)
    assert r.status_code in (401, 403)
