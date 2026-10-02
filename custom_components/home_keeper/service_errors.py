"""Translate store exceptions into localized service errors.

The store raises ``KeyError`` when no record has an id, and ``TaskValidationError``
or ``AssetValidationError`` for bad input. A service caller must get a
``ServiceValidationError`` with a translation key. The service handlers in
``__init__.py`` use the context managers here for that translation.

This module imports only the Home Assistant exception classes, so
``tests/unit`` can load it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from homeassistant.exceptions import ServiceValidationError

from .assets import AssetValidationError
from .const import DOMAIN
from .models import TaskValidationError


def service_error(key: str, **placeholders: str) -> ServiceValidationError:
    """A ``ServiceValidationError`` with the Home Keeper translation *key*."""
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=placeholders or None,
    )


def _not_found(
    *,
    task_id: str | None,
    asset_id: str | None,
    part_id: str | None,
    document_id: str | None,
    photo_id: str | None = None,
) -> ServiceValidationError | None:
    """The not-found error for a ``KeyError``, innermost record first."""
    if photo_id is not None:
        return service_error("unknown_task_photo", photo_id=photo_id)
    if asset_id is not None and part_id is not None:
        return service_error("unknown_part", asset_id=asset_id, part_id=part_id)
    if document_id is not None:
        return service_error("unknown_document", document_id=document_id)
    if asset_id is not None:
        return service_error("asset_not_found", asset_id=asset_id)
    if task_id is not None:
        return service_error("task_not_found", task_id=task_id)
    return None


@contextmanager
def store_errors(
    *,
    task_id: str | None = None,
    asset_id: str | None = None,
    part_id: str | None = None,
    document_id: str | None = None,
    photo_id: str | None = None,
) -> Iterator[None]:
    """Translate the exceptions of a store call into localized service errors.

    The ids name the record that a ``KeyError`` was for, innermost first:

    * ``asset_id`` and ``part_id`` give ``unknown_part``.
    * ``document_id`` gives ``unknown_document``. The handler must make sure that
      the appliance exists before the call (B02-6).
    * ``photo_id`` gives ``unknown_task_photo``. The same rule: the handler checks
      the task first.
    * ``asset_id`` alone gives ``asset_not_found``.
    * ``task_id`` gives ``task_not_found``.

    With no id, a ``KeyError`` goes to the caller unchanged.
    """
    try:
        yield
    except KeyError:
        error = _not_found(
            task_id=task_id,
            asset_id=asset_id,
            part_id=part_id,
            document_id=document_id,
            photo_id=photo_id,
        )
        if error is None:
            raise
        raise error from None
    except TaskValidationError as err:
        raise service_error("invalid_task", error=str(err)) from err
    except AssetValidationError as err:
        raise service_error("invalid_asset", error=str(err)) from err


@contextmanager
def declarative_companion_errors(*, spec_id: str | None = None) -> Iterator[None]:
    """Translate the exceptions of a declarative companion store call (B02-3).

    The websocket commands give the same 2 errors. A ``KeyError`` is an unknown
    spec when *spec_id* is set. Without *spec_id*, it goes to the caller unchanged.
    """
    try:
        yield
    except KeyError:
        if spec_id is None:
            raise
        raise service_error(
            "declarative_companion_not_found", spec_id=spec_id
        ) from None
    except TaskValidationError as err:
        raise service_error("invalid_declarative_companion", error=str(err)) from err
