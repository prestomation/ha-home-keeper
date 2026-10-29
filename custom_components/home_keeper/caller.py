"""The context of the caller that changes Home Keeper data (#467).

Home Assistant gives each service call, websocket command and entity action a
``Context`` that names the user who started it. The store fires its events deep
below the handler, so the handler sets the context here and ``store._fire`` reads
it. The event then carries the user and the service call, and the logbook and the
recorder show who made the change.

A change that Home Keeper makes on its own, such as a time-based crossing or a
sensor reading, has no caller. Its event gets a new context with no user.

Imports Home Assistant only for type checking, so the unit tier runs it as is.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import (
        Context,
        ServiceCall,
        ServiceRegistry,
        ServiceResponse,
    )

    type ServiceHandler = Callable[[ServiceCall], Coroutine[Any, Any, ServiceResponse]]

_CALLER: ContextVar[Context | None] = ContextVar("home_keeper_caller", default=None)


def current() -> Context | None:
    """The context of the caller that changes the data now, or None."""
    return _CALLER.get()


@contextmanager
def caller(context: Context | None) -> Iterator[None]:
    """Make *context* the caller in the block.

    A task that starts in the block gets a copy of the caller, so the store events
    that it fires carry the caller too.
    """
    token = _CALLER.set(context)
    try:
        yield
    finally:
        _CALLER.reset(token)


def service(handler: ServiceHandler) -> ServiceHandler:
    """*handler*, run with the context of its service call as the caller."""

    @wraps(handler)
    async def _with_caller(call: ServiceCall) -> ServiceResponse:
        with caller(call.context):
            return await handler(call)

    return _with_caller


class ContextServices:
    """``hass.services`` that registers each handler with :func:`service`."""

    def __init__(self, services: ServiceRegistry) -> None:
        self._services = services

    def async_register(
        self,
        domain: str,
        name: str,
        handler: ServiceHandler,
        schema: Any = None,
        **kwargs: Any,
    ) -> None:
        """Register *handler* as ``hass.services.async_register`` does."""
        self._services.async_register(domain, name, service(handler), schema, **kwargs)


def websocket(handler: Callable[..., Any]) -> Callable[..., Any]:
    """*handler*, run with the context of its websocket message as the caller.

    ``wraps`` copies the command and the schema that Home Assistant reads off the
    handler. An ``async_response`` handler starts its task in the block, so the task
    keeps the caller.
    """

    @wraps(handler)
    def _with_caller(hass: Any, connection: Any, msg: dict[str, Any]) -> Any:
        with caller(connection.context(msg)):
            return handler(hass, connection, msg)

    return _with_caller
