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

# A decompression bomb is a small file that expands to a huge bitmap. Pillow warns
# above its default limit and raises at twice that. Make it raise at the limit: a
# phone photo is far below it (a 200 megapixel sensor is 2e8 pixels).
_MAX_PIXELS = 2.5e8


class ThumbnailError(ValueError):
    """The upload passed the magic-byte check but is not a readable image."""


def make_thumbnail(src: Path, dst: Path, px: int = TASK_PHOTO_THUMB_PX) -> None:
    """Write a JPEG of *src* that fits in *px* x *px* to *dst*.

    The EXIF orientation is applied, so a phone photo taken on its side shows
    upright. An image with transparency is put on white. A GIF gives its first
    frame. Raises :class:`ThumbnailError` when *src* cannot be read as an image.
    """
    try:
        with Image.open(src) as image:
            if image.width * image.height > _MAX_PIXELS:
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
