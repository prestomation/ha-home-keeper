"""Unit tests for the pure document helpers (``documents.py``).

These cover the security-critical, HA-free pieces of the offline-manuals feature:
magic-byte sniffing, filename sanitization, the upload allowlist/size guard, and the
path-traversal guard. The HA-bound storage/HTTP wiring lives in ``manuals.py`` and is
exercised by the Docker integration tests.
"""

from pathlib import Path

import hk_documents as d
import pytest
from hk_assets import AssetValidationError

PDF = b"%PDF-1.7\n..."
PNG = b"\x89PNG\r\n\x1a\n\x00\x00"
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF"
GIF = b"GIF89a\x01\x00"
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 "


def test_sniff_recognizes_allowlisted_types():
    assert d.sniff_content_type(PDF) == "application/pdf"
    assert d.sniff_content_type(PNG) == "image/png"
    assert d.sniff_content_type(JPEG) == "image/jpeg"
    assert d.sniff_content_type(GIF) == "image/gif"
    assert d.sniff_content_type(WEBP) == "image/webp"


def test_sniff_rejects_unknown_bytes():
    assert d.sniff_content_type(b"MZ\x90\x00") is None  # an .exe
    assert d.sniff_content_type(b"") is None


def test_safe_filename_strips_path_and_forces_extension():
    assert d.safe_filename("../../etc/passwd", "application/pdf") == "passwd.pdf"
    out = d.safe_filename("My Manual (v2).pdf", "application/pdf")
    assert out.endswith(".pdf") and "Manual" in out and "/" not in out
    # A spoofed extension is replaced with the content type's canonical one.
    assert d.safe_filename("photo.exe", "image/png") == "photo.png"
    # An empty/dotfile name still yields a usable basename.
    assert d.safe_filename("", "application/pdf") == "document.pdf"
    assert d.safe_filename("...", "image/jpeg") == "document.jpg"


def test_safe_filename_caps_length():
    name = d.safe_filename("a" * 500 + ".pdf", "application/pdf")
    assert name.endswith(".pdf")
    assert len(name) <= 120 + len(".pdf")


def test_validate_upload_accepts_pdf_and_returns_sniffed_type():
    # The content type is sniffed from the bytes (no client-declared MIME is consulted).
    content_type, filename = d.validate_upload("manual.pdf", PDF)
    assert content_type == "application/pdf"
    assert filename == "manual.pdf"


def test_validate_upload_rejects_empty_oversized_and_unknown():
    with pytest.raises(AssetValidationError):
        d.validate_upload("x.pdf", b"")
    with pytest.raises(AssetValidationError):
        d.validate_upload("x.exe", b"MZ\x90\x00garbage")
    big = PDF + b"0" * (25 * 1024 * 1024 + 1)
    with pytest.raises(AssetValidationError):
        d.validate_upload("big.pdf", big)


def test_safe_segment_reduces_or_rejects():
    assert d.safe_segment("abc-123") == "abc-123"
    # Separators are reduced to the basename (never escape via the path).
    assert d.safe_segment("/etc/passwd") == "passwd"
    assert d.safe_segment("a/b") == "b"
    # Pure traversal / empty markers have no usable basename — rejected outright.
    for bad in ("..", ".", "", "/", "../.."):
        with pytest.raises(AssetValidationError):
            d.safe_segment(bad)


def test_resolve_under_root_keeps_paths_inside_root(tmp_path: Path):
    root = tmp_path / "documents"
    p = d.resolve_under_root(root, "asset1", "doc1__manual.pdf")
    assert p.is_relative_to(root.resolve())
    assert p.name == "doc1__manual.pdf"


def test_resolve_under_root_blocks_escape(tmp_path: Path):
    root = tmp_path / "documents"
    rroot = root.resolve()
    # Components with separators are reduced to a basename, so the result stays inside
    # the root rather than escaping it.
    for asset_id in ("../../etc", "/abs", "a/b/c"):
        p = d.resolve_under_root(root, asset_id, "doc__x.pdf")
        assert p.is_relative_to(rroot)
        assert ".." not in p.parts
    # A pure traversal/empty marker has no usable basename — rejected outright.
    for asset_id in ("..", ".", ""):
        with pytest.raises(AssetValidationError):
            d.resolve_under_root(root, asset_id, "doc__x.pdf")


def test_document_path_composes_id_and_filename(tmp_path: Path):
    root = tmp_path / "documents"
    p = d.document_path(root, "asset-1", "doc-9", "manual.pdf")
    assert p.parent.name == "asset-1"
    assert p.name == "doc-9__manual.pdf"
    assert p.is_relative_to(root.resolve())
