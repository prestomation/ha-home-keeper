"""Make the small JPEG copy of a task photo (#399).

The task list and the photo strip show many photos at once, and a photo from a phone
is often several megabytes. So each upload gets a thumbnail at most
``TASK_PHOTO_THUMB_PX`` on its long side, and the panel loads the original only when
a person opens it.

Pillow is a dependency of Home Assistant itself, so the manifest needs no
requirement for it. The work is blocking: call :func:`make_thumbnail` from an
executor job.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .const import TASK_PHOTO_THUMB_PX

# A decompression bomb is a small file that expands to a huge bitmap. A baseline
# RGB or greyscale JPEG is decoded in draft mode, at 1/8 of its size or less for a
# thumbnail, so it can be as large as the biggest phone sensor (200 megapixels) and
# still decode to a few megapixels. A progressive JPEG keeps every coefficient at
# full size while it decodes, and a CMYK one has 4 channels, so those two get the
# limit of every other format: 50 megapixels of RGB is about 150 MB of memory.
_MAX_PIXELS_JPEG = 2.5e8
_MAX_PIXELS = 5e7
# The formats the upload accepts (see ``task_photos.IMAGE_TYPES``). Pillow tries
# only these, so a file it would read as TIFF or BMP is refused here as well.
_FORMATS = ("JPEG", "PNG", "GIF", "WEBP")


def _pixel_limit(image: Image.Image) -> float:
    """The largest image Home Keeper reads for *image*'s format and mode."""
    draft_decodes = (
        image.format == "JPEG"
        and image.mode in ("RGB", "L")
        and not image.info.get("progressive")
        and not image.info.get("progression")
    )
    return _MAX_PIXELS_JPEG if draft_decodes else _MAX_PIXELS


class ThumbnailError(ValueError):
    """The upload passed the magic-byte check but is not a readable image."""


def make_thumbnail(src: Path, dst: Path, px: int = TASK_PHOTO_THUMB_PX) -> None:
    """Write a JPEG of *src* that fits in *px* x *px* to *dst*.

    The EXIF orientation is applied, so a phone photo taken on its side shows
    upright. An image with transparency is put on white. A GIF gives its first
    frame. Raises :class:`ThumbnailError` when *src* cannot be read as an image.
    """
    try:
        # ``open`` reads only the header. Nothing is decoded until the size is known
        # to be in the limit.
        with Image.open(src, formats=_FORMATS) as image:
            if image.width * image.height > _pixel_limit(image):
                raise ThumbnailError("the image is too large to read")
            image.draft("RGB", (px, px))
            frame = ImageOps.exif_transpose(image) or image
            frame.thumbnail((px, px))
            if frame.mode in ("RGBA", "LA", "P"):
                rgba = frame.convert("RGBA")
                flat = Image.new("RGB", rgba.size, (255, 255, 255))
                flat.paste(rgba, mask=rgba.getchannel("A"))
                frame = flat
            elif frame.mode != "RGB":
                frame = frame.convert("RGB")
            dst.parent.mkdir(parents=True, exist_ok=True)
            frame.save(dst, "JPEG", quality=82, optimize=True)
    except ThumbnailError:
        raise
    # Pillow raises SyntaxError and ValueError as well as OSError for some broken
    # files, so all of them mean "not a readable image" here.
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        OSError,
        SyntaxError,
        ValueError,
    ) as err:
        raise ThumbnailError("the image could not be read") from err
