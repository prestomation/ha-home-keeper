"""The task photo thumbnail (``photo_thumbs.py``, #399).

Pillow is a dependency of Home Assistant, and ``requirements-test.txt`` names it for
the bare unit lane, so these import it plainly.
"""

from __future__ import annotations

import io
from pathlib import Path

import hk_photo_thumbs as thumbs
import pytest
from asserts import raises_exactly
from PIL import Image


def _write(path: Path, image: Image.Image, fmt: str, **kwargs) -> Path:
    image.save(path, fmt, **kwargs)
    return path


def _open(path: Path) -> Image.Image:
    image = Image.open(path)
    image.load()
    return image


def test_a_large_jpeg_fits_in_the_box(tmp_path):
    src = _write(tmp_path / "a.jpg", Image.new("RGB", (1200, 600), "red"), "JPEG")
    dst = tmp_path / "out" / "thumb.jpg"
    thumbs.make_thumbnail(src, dst, 256)
    out = _open(dst)
    assert out.format == "JPEG"
    assert out.size == (256, 128)


def test_a_small_image_is_not_made_larger(tmp_path):
    src = _write(tmp_path / "a.png", Image.new("RGB", (40, 30), "blue"), "PNG")
    dst = tmp_path / "thumb.jpg"
    thumbs.make_thumbnail(src, dst, 256)
    assert _open(dst).size == (40, 30)


def test_the_default_box_is_256(tmp_path):
    src = _write(tmp_path / "a.png", Image.new("RGB", (512, 1024)), "PNG")
    dst = tmp_path / "thumb.jpg"
    thumbs.make_thumbnail(src, dst)
    assert _open(dst).size == (128, 256)


def test_the_exif_orientation_is_applied(tmp_path):
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees clockwise to show
    src = _write(tmp_path / "side.jpg", Image.new("RGB", (400, 200)), "JPEG", exif=exif)
    dst = tmp_path / "thumb.jpg"
    thumbs.make_thumbnail(src, dst, 256)
    assert _open(dst).size == (128, 256)


def test_transparency_goes_on_white(tmp_path):
    src = _write(tmp_path / "a.png", Image.new("RGBA", (10, 10), (0, 0, 0, 0)), "PNG")
    dst = tmp_path / "thumb.jpg"
    thumbs.make_thumbnail(src, dst, 256)
    out = _open(dst)
    assert out.mode == "RGB"
    assert all(channel > 245 for channel in out.getpixel((5, 5)))


def test_a_palette_gif_gives_rgb(tmp_path):
    src = _write(tmp_path / "a.gif", Image.new("P", (20, 20), 3), "GIF")
    dst = tmp_path / "thumb.jpg"
    thumbs.make_thumbnail(src, dst, 256)
    assert _open(dst).mode == "RGB"


def test_a_greyscale_image_gives_rgb(tmp_path):
    src = _write(tmp_path / "a.png", Image.new("L", (20, 20), 128), "PNG")
    dst = tmp_path / "thumb.jpg"
    thumbs.make_thumbnail(src, dst, 256)
    assert _open(dst).mode == "RGB"


def test_a_file_that_is_not_an_image_is_refused(tmp_path):
    src = tmp_path / "fake.jpg"
    # The JPEG magic bytes pass the upload sniff, but the rest is not a JPEG.
    src.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 64)
    dst = tmp_path / "thumb.jpg"
    with raises_exactly(thumbs.ThumbnailError, "the image could not be read"):
        thumbs.make_thumbnail(src, dst, 256)
    assert not dst.exists()


def test_a_truncated_png_is_refused(tmp_path):
    buffer = io.BytesIO()
    Image.new("RGB", (300, 300), "green").save(buffer, "PNG")
    src = tmp_path / "cut.png"
    src.write_bytes(buffer.getvalue()[:80])
    with pytest.raises(thumbs.ThumbnailError):
        thumbs.make_thumbnail(src, tmp_path / "thumb.jpg", 256)


def test_too_many_pixels_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(thumbs, "_MAX_PIXELS", 99)
    src = _write(tmp_path / "a.png", Image.new("RGB", (10, 10)), "PNG")
    with raises_exactly(thumbs.ThumbnailError, "the image is too large to read"):
        thumbs.make_thumbnail(src, tmp_path / "thumb.jpg", 256)


@pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")
def test_a_jpeg_has_its_own_higher_limit(tmp_path, monkeypatch):
    # Draft mode decodes an 800x800 JPEG for a 32px thumbnail at 1/8: 100x100. The
    # JPEG limit is Pillow's own: 2 x MAX_IMAGE_PIXELS.
    monkeypatch.setattr(thumbs, "_MAX_PIXELS", 100 * 100)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 800 * 800 / 2)
    src = _write(tmp_path / "a.jpg", Image.new("RGB", (800, 800)), "JPEG")
    dst = tmp_path / "thumb.jpg"
    thumbs.make_thumbnail(src, dst, 32)
    assert _open(dst).size == (32, 32)
    # One pixel over: Pillow's own check in Image.open refuses it, and the message
    # says the image is too large, not that it cannot be read.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", (800 * 800 - 1) / 2)
    with raises_exactly(thumbs.ThumbnailError, "the image is too large to read"):
        thumbs.make_thumbnail(src, dst, 32)


def test_a_png_over_the_pillow_limit_says_too_large(tmp_path, monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)
    src = _write(tmp_path / "a.png", Image.new("RGB", (10, 10)), "PNG")
    with raises_exactly(thumbs.ThumbnailError, "the image is too large to read"):
        thumbs.make_thumbnail(src, tmp_path / "thumb.jpg", 256)


def test_no_pillow_limit_gives_no_jpeg_limit(monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", None)
    assert thumbs._max_pixels_jpeg() == float("inf")


def test_a_jpeg_that_draft_mode_does_not_shrink_is_refused(tmp_path, monkeypatch):
    # The higher JPEG limit is safe only when draft mode shrinks the decode.
    monkeypatch.setattr(thumbs, "_MAX_PIXELS", 99)
    monkeypatch.setattr(Image.Image, "draft", lambda self, mode, size: None)
    src = _write(tmp_path / "a.jpg", Image.new("RGB", (10, 10)), "JPEG")
    with raises_exactly(thumbs.ThumbnailError, "the image is too large to read"):
        thumbs.make_thumbnail(src, tmp_path / "thumb.jpg", 256)


def test_the_draft_check_is_inclusive(tmp_path, monkeypatch):
    # 320x240 for a 32px box decodes at 1/4: 80x60, which must fit _MAX_PIXELS.
    monkeypatch.setattr(thumbs, "_MAX_PIXELS", 80 * 60)
    src = _write(tmp_path / "a.jpg", Image.new("RGB", (320, 240)), "JPEG")
    dst = tmp_path / "thumb.jpg"
    thumbs.make_thumbnail(src, dst, 32)
    assert _open(dst).size == (32, 24)
    monkeypatch.setattr(thumbs, "_MAX_PIXELS", 80 * 60 - 1)
    with raises_exactly(thumbs.ThumbnailError, "the image is too large to read"):
        thumbs.make_thumbnail(src, dst, 32)


def test_pillow_marks_a_progressive_jpeg_with_both_keys(tmp_path):
    src = _write(
        tmp_path / "p.jpg", Image.new("RGB", (10, 10)), "JPEG", progressive=True
    )
    with Image.open(src) as image:
        assert image.info.get("progressive") == 1
        assert image.info.get("progression") == 1


def test_a_progressive_jpeg_gets_the_lower_limit(tmp_path):
    src = _write(
        tmp_path / "p.jpg", Image.new("RGB", (10, 10)), "JPEG", progressive=True
    )
    with Image.open(src) as image:
        assert thumbs._pixel_limit(image) == thumbs._MAX_PIXELS


def test_a_cmyk_jpeg_gets_the_lower_limit(tmp_path):
    src = _write(tmp_path / "c.jpg", Image.new("CMYK", (10, 10)), "JPEG")
    with Image.open(src) as image:
        assert thumbs._pixel_limit(image) == thumbs._MAX_PIXELS


@pytest.mark.parametrize("mode", ["RGB", "L"])
def test_a_baseline_jpeg_gets_the_higher_limit(tmp_path, mode):
    src = _write(tmp_path / "b.jpg", Image.new(mode, (10, 10)), "JPEG")
    with Image.open(src) as image:
        assert thumbs._pixel_limit(image) == thumbs._max_pixels_jpeg()


@pytest.mark.parametrize("fmt", ["PNG", "GIF", "WEBP"])
def test_other_formats_get_the_lower_limit(tmp_path, fmt):
    src = _write(tmp_path / f"x.{fmt.lower()}", Image.new("RGB", (10, 10)), fmt)
    with Image.open(src) as image:
        assert thumbs._pixel_limit(image) == thumbs._MAX_PIXELS


@pytest.mark.parametrize("fmt", ["TIFF", "BMP"])
def test_a_format_the_upload_does_not_accept_is_refused(tmp_path, fmt):
    src = _write(tmp_path / "x.img", Image.new("RGB", (10, 10)), fmt)
    with raises_exactly(thumbs.ThumbnailError, "the image could not be read"):
        thumbs.make_thumbnail(src, tmp_path / "thumb.jpg", 256)


def test_the_jpeg_limit_is_the_pillow_limit_and_a_huge_png_is_refused():
    # Home Keeper never changes Pillow's global, which all of Home Assistant shares.
    assert Image.MAX_IMAGE_PIXELS == 1024 * 1024 * 1024 // 4 // 3
    assert thumbs._max_pixels_jpeg() == 2 * Image.MAX_IMAGE_PIXELS
    assert thumbs._MAX_PIXELS <= 5e7


def test_the_thumbnail_drops_the_exif_data(tmp_path):
    exif = Image.Exif()
    exif[0x8825] = {2: (47.0, 36.0, 0.0)}  # a GPS block
    exif[0x0110] = "Phone model"
    src = _write(tmp_path / "a.jpg", Image.new("RGB", (40, 40)), "JPEG", exif=exif)
    dst = tmp_path / "thumb.jpg"
    thumbs.make_thumbnail(src, dst, 256)
    assert len(_open(dst).getexif()) == 0


def test_exactly_the_pixel_limit_is_read(tmp_path, monkeypatch):
    monkeypatch.setattr(thumbs, "_MAX_PIXELS", 100)
    src = _write(tmp_path / "a.png", Image.new("RGB", (10, 10)), "PNG")
    dst = tmp_path / "thumb.jpg"
    thumbs.make_thumbnail(src, dst, 256)
    assert dst.exists()
