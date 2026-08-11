"""Unit tests for the pure document helpers (``documents.py``).

These cover the security-critical, HA-free pieces of the offline-manuals feature:
magic-byte sniffing, filename sanitization, the upload allowlist/size guard, and the
path-traversal guard. The HA-bound storage/HTTP wiring lives in ``manuals.py`` and is
exercised by the Docker integration tests.
"""

import os
from pathlib import Path

import hk_documents as d
from asserts import raises_exactly
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
    with raises_exactly(AssetValidationError, "uploaded file is empty"):
        d.validate_upload("x.pdf", b"")
    with raises_exactly(
        AssetValidationError,
        "unsupported file type (allowed: PDF, PNG, JPEG, WebP, GIF)",
    ):
        d.validate_upload("x.exe", b"MZ\x90\x00garbage")
    # Declared via the stream variant so the ceiling can be exercised without
    # allocating MAX_DOCUMENT_BYTES of ballast in the test process.
    with raises_exactly(AssetValidationError, "file exceeds the 100 MB limit"):
        d.validate_upload_stream("big.pdf", PDF, d.MAX_DOCUMENT_BYTES + 1)


def test_validate_upload_stream_matches_the_in_memory_variant():
    # The HTTP path never holds the file, so it validates from (header, size) instead
    # of the whole blob — the two must agree on type, name and every rejection.
    assert d.validate_upload_stream("manual.pdf", PDF, len(PDF)) == d.validate_upload(
        "manual.pdf", PDF
    )
    with raises_exactly(AssetValidationError, "uploaded file is empty"):
        d.validate_upload_stream("x.pdf", PDF, 0)
    with raises_exactly(
        AssetValidationError,
        "unsupported file type (allowed: PDF, PNG, JPEG, WebP, GIF)",
    ):
        d.validate_upload_stream("x.exe", b"MZ\x90\x00garbage", 64)


def test_validate_upload_stream_accepts_exactly_the_ceiling():
    content_type, filename = d.validate_upload_stream(
        "huge.pdf", PDF, d.MAX_DOCUMENT_BYTES
    )
    assert (content_type, filename) == ("application/pdf", "huge.pdf")


def test_sniff_bytes_covers_every_signature():
    # validate_upload_stream only ever sees SNIFF_BYTES of the file, so a signature
    # that reads past it would silently stop matching.
    for sample in (PDF, PNG, JPEG, GIF, WEBP):
        assert d.sniff_content_type(sample[: d.SNIFF_BYTES]) == d.sniff_content_type(
            sample
        )


def test_purge_stale_temps_spares_uploads_still_in_flight(tmp_path):
    # The whole reason this is age-based: setup re-runs on a config entry reload while
    # the upload view stays registered, so a blanket wipe would delete the temp file a
    # live upload is still writing. A fresh file must survive; an old one must not.
    fresh = tmp_path / "upload-live"
    fresh.write_bytes(b"partial")
    stale = tmp_path / "upload-abandoned"
    stale.write_bytes(b"leftover from a crash")
    os.utime(stale, (0, 0))  # epoch — unambiguously older than any cutoff

    d.purge_stale_temps(tmp_path, max_age_s=3600)

    assert fresh.exists(), "an in-flight upload must not be deleted"
    assert not stale.exists(), "a stray temp upload must be reclaimed"


def test_purge_stale_temps_ignores_foreign_files_and_missing_dir(tmp_path):
    # Only our own upload-* temps are ours to delete...
    other = tmp_path / "something-else"
    other.write_bytes(b"not ours")
    os.utime(other, (0, 0))
    d.purge_stale_temps(tmp_path, max_age_s=0)
    assert other.exists()
    # ...and a missing directory (nothing uploaded yet) is not an error.
    d.purge_stale_temps(tmp_path / "nope", max_age_s=0)


def test_purge_stale_temps_survives_an_unremovable_entry(tmp_path):
    # An entry that can't be deleted (here a directory, which unlink refuses) must not
    # abort the sweep — the real-world version is losing a race with the upload that
    # owns the file, and the rest of the strays still need reclaiming.
    blocker = tmp_path / "upload-directory"
    blocker.mkdir()
    os.utime(blocker, (0, 0))
    stale = tmp_path / "upload-stale"
    stale.write_bytes(b"leftover")
    os.utime(stale, (0, 0))

    d.purge_stale_temps(tmp_path, max_age_s=0)

    assert blocker.is_dir(), "an undeletable entry is skipped, not fatal"
    assert not stale.exists(), "the sweep continues past it"


def test_safe_segment_reduces_or_rejects():
    assert d.safe_segment("abc-123") == "abc-123"
    # Separators are reduced to the basename (never escape via the path).
    assert d.safe_segment("/etc/passwd") == "passwd"
    assert d.safe_segment("a/b") == "b"
    # Pure traversal / empty markers have no usable basename — rejected outright.
    for bad in ("..", ".", "", "/", "../.."):
        with raises_exactly(AssetValidationError, "invalid document path"):
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
        with raises_exactly(AssetValidationError, "invalid document path"):
            d.resolve_under_root(root, asset_id, "doc__x.pdf")


def test_document_path_composes_id_and_filename(tmp_path: Path):
    root = tmp_path / "documents"
    p = d.document_path(root, "asset-1", "doc-9", "manual.pdf")
    assert p.parent.name == "asset-1"
    assert p.name == "doc-9__manual.pdf"
    assert p.is_relative_to(root.resolve())
