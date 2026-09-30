"""Home-Assistant-aware driver for sensor-based tasks.

Subscribes to the entities that sensor-based tasks are bound to, reads their live
values — numeric for ``usage``/``threshold``, the state string for ``state`` — and
feeds the pure evaluators in ``sensor_tasks.py`` to arm a task (via
``store.trigger_task``) or stamp/reset a usage baseline (via
``store.set_sensor_baseline``). Unlike ``problem_sync.py`` this is **evaluation
only**: sensor tasks are user-created, so there is no registry enumeration,
auto-creation/deletion, exclusion options, or entry reload — the watcher never
changes which tasks exist, only their armed/dormant state and meter baseline.

Edge state for the threshold/state modes (was-the-condition-true, when-it-crossed)
lives in this object's memory and is baselined on startup (``async_baseline``) so a
restart never replays a spurious arm — mirroring how the coordinator baselines the
overdue/due-soon transitions. A binding with a ``for_seconds`` hold also gets a timer.
The hold ends in its own time, so the watcher books one re-evaluation per task for the
moment the pure evaluator says the hold is due, and releases every pending timer on
unload. Without that timer the hold ends nowhere: the only things that re-evaluate the
task are the next state change of the bound entity — which an entity that has gone
unavailable never sends — and the coordinator's five-minute tick.

Completion normally flows through the user surfaces; the
one exception is a binding with ``clear_on_recover``, where the watcher completes the
task itself (tagged ``ORIGIN_SENSOR_RECOVER``) once the condition goes away.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
)
from homeassistant.helpers.template import TemplateError
from homeassistant.util import dt as dt_util

from . import sensor_tasks, template_context
from .const import (
    DOMAIN,
    ORIGIN_SENSOR_RECOVER,
    REC_SENSOR,
    SENSOR_MODE_AVAILABILITY,
    SENSOR_MODE_STATE,
    SENSOR_MODE_TEMPLATE,
    SENSOR_MODE_THRESHOLD,
    SENSOR_MODE_USAGE,
)

if TYPE_CHECKING:
    from .coordinator import HomeKeeperCoordinator

_LOGGER = logging.getLogger(__name__)

# hass.data namespace holding, per config entry, the ids of sensor tasks that were
# materialized after the last baseline pass. It lives on ``hass.data`` rather than on
# the watcher (or the reconciler) because materializing a task with per-task entities
# reloads the config entry, and the reload destroys both objects while
# ``async_baseline`` runs again. A genuine HA restart starts with an empty
# ``hass.data``, so a task that existed before setup keeps the ordinary treatment.
_NEW_TASKS_STORE = f"{DOMAIN}_new_sensor_tasks"


def _new_tasks_store(hass: HomeAssistant) -> dict[str, set[str]]:
    """The process-lifetime just-made-task map keyed by config-entry id."""
    return hass.data.setdefault(_NEW_TASKS_STORE, {})


@callback
def async_mark_tasks_new(
    hass: HomeAssistant, entry_id: str, task_ids: Iterable[str]
) -> None:
    """Record tasks made just now so the next baseline pass leaves their edge unset.

    A task made one second ago has no history to protect: the condition its companion
    watches may be true right now, and that is exactly what the user wants a task
    for. Without this the baseline records it as already-met-without-a-crossing and
    the task stays dormant until the condition goes away and comes back.
    """
    ids = {tid for tid in task_ids if tid}
    if not ids:
        return
    _new_tasks_store(hass).setdefault(entry_id, set()).update(ids)


@callback
def async_discard_new_tasks(hass: HomeAssistant, entry_id: str) -> None:
    """Drop an entry's just-made-task set (called when the entry is removed)."""
    _new_tasks_store(hass).pop(entry_id, None)


def _entity_loaded(hass: HomeAssistant, entity_id: str | None) -> bool:
    """Whether *entity_id* has a real state in the state machine.

    At start-up Home Assistant writes an ``unavailable`` placeholder with the
    attribute ``restored: true`` for each registered entity that its integration has
    not loaded yet. That placeholder says nothing about the device, so it counts as
    not loaded (B14-4).
    """
    if not entity_id:
        return False
    state = hass.states.get(entity_id)
    return state is not None and state.attributes.get("restored") is not True


def _reading_stamp(hass: HomeAssistant, cfg: dict[str, Any] | None) -> Any | None:
    """The time the bound entity last reported, or ``None`` when it has no state.

    Two passes that see the same stamp saw the same reading. The usage-meter reset
    check uses this to count readings of the entity, not evaluation passes (B14-3).
    ``last_reported`` also moves when the entity reports the same value again.
    """
    entity_id = (cfg or {}).get("entity_id")
    state = hass.states.get(entity_id) if entity_id else None
    if state is None:
        return None
    return getattr(state, "last_reported", None) or state.last_updated


def _raw_reading(hass: HomeAssistant, cfg: dict[str, Any] | None) -> Any | None:
    """The raw value a sensor binding points at, or ``None`` if there isn't one.

    Resolves the binding to a live value once — honouring the optional ``attribute``
    (read that attribute instead of the state) and rejecting a missing / unavailable /
    unknown entity — so the numeric and state readers can't disagree about what
    "there is no reading" means.
    """
    if not cfg:
        return None
    entity_id = cfg.get("entity_id")
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, "", None):
        return None
    attribute = cfg.get("attribute")
    return state.attributes.get(attribute) if attribute else state.state


def read_sensor_value(hass: HomeAssistant, cfg: dict[str, Any] | None) -> float | None:
    """Read the live numeric value a sensor binding points at, or ``None``.

    Returns ``None`` for a missing / unavailable / non-numeric entity so callers skip
    evaluation rather than arm on bad data.
    """
    return sensor_tasks.parse_reading(_raw_reading(hass, cfg))


def read_sensor_state(hass: HomeAssistant, cfg: dict[str, Any] | None) -> str | None:
    """Read the live **state string** a sensor binding points at, or ``None``.

    The ``state`` mode's counterpart to :func:`read_sensor_value`: a binary sensor
    reports ``on``/``off``, which has no numeric reading at all. An attribute value is
    coerced to ``str`` so an attribute holding a bool/number still compares against the
    binding's stored state.
    """
    raw = _raw_reading(hass, cfg)
    return None if raw is None else str(raw)


def read_availability_status(hass: HomeAssistant, cfg: dict[str, Any] | None) -> str:
    """Classify a binding's *availability*: available / unavailable / missing.

    The ``availability`` mode's counterpart to :func:`read_sensor_value` and
    :func:`read_sensor_state`, and **inverts** the "no reading = do nothing" policy
    those two share: this mode arms *because* the entity is unavailable/unknown,
    so the caller needs to distinguish "entity is unreachable" (arm signal) from
    "entity is not yet loaded" (indeterminate; hold edge state so a boot-time gap
    can never fabricate a spurious arm or clear).

    * ``"missing"`` — the binding has no entity_id, or the entity isn't in the
      state machine yet (never seen), or its state is the ``restored`` placeholder
      that Home Assistant writes at start-up before the integration loads it.
      Indeterminate.
    * ``"unavailable"`` — the entity is present but reporting ``unavailable`` /
      ``unknown``; or an attribute binding whose target attribute is missing or
      ``None``. The arm signal.
    * ``"available"`` — the entity has a real state and (if an attribute is
      bound) the attribute has a real value.

    Mirrors ``problem_sync._is_problem``'s three-way discipline.
    """
    if not cfg:
        return sensor_tasks.AVAILABILITY_MISSING
    entity_id = cfg.get("entity_id")
    if not entity_id:
        return sensor_tasks.AVAILABILITY_MISSING
    state = hass.states.get(entity_id)
    if state is None or state.attributes.get("restored") is True:
        return sensor_tasks.AVAILABILITY_MISSING
    if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN, "", None):
        return sensor_tasks.AVAILABILITY_UNAVAILABLE
    attribute = cfg.get("attribute")
    if attribute:
        value = state.attributes.get(attribute)
        if value is None or value == "":
            return sensor_tasks.AVAILABILITY_UNAVAILABLE
    return sensor_tasks.AVAILABILITY_AVAILABLE


# The only non-boolean renders read as a verdict. Home Assistant's own vocabulary for
# a yes/no answer, minus the numbers: a template that renders a *number* is answering
# some other question, and reading it as "anything but zero is true" is what made
# ``{{ state }}`` open a task for every entity a companion matched. Someone who means a
# literal true writes ``{{ true }}``, which never reaches here.
_TRUE_WORDS = frozenset({"true", "yes", "on", "enable"})
_FALSE_WORDS = frozenset({"false", "no", "off", "disable"})


def render_template_result(
    hass: HomeAssistant, source: str, variables: dict[str, Any]
) -> tuple[bool | None, str | None]:
    """Render *source* and read it as a boolean. Returns ``(result, error)``.

    ``result`` is ``None`` with an ``error`` message when the template could not be
    rendered, or when what it rendered is not true or false. Both are
    **indeterminate** for the caller: the task neither arms nor clears. The error text
    is what the companion preview shows the user, so it is the message Jinja produced,
    not a summary of it.

    ``parse_result=True`` is what makes ``{{ a >= b }}`` come back as a real ``bool``
    rather than the string ``"True"``. The declarative-companion name/notes renderer
    passes ``False`` instead, because a task name wants the text.

    The verdict is read by :data:`_TRUE_WORDS` / :data:`_FALSE_WORDS` rather than by
    ``template.result_as_boolean`` or by ``cv.boolean``, and each is rejected for its
    own reason. ``result_as_boolean`` reads anything it does not recognise as
    ``False``. ``cv.boolean`` looked right and is not: it maps **any** number to
    ``value != 0``, so ``{{ state }}`` on a printer-hours sensor rendered ``782`` and
    armed every task a companion matched, with a confident "Due now" in the preview
    and no error — and the same template went indeterminate the moment the entity
    reported ``unavailable``, because that is a string it does not recognise. One
    template, three regimes, none of them what the user asked for.

    A template rendering a timestamp, a device name, or a reading is not a condition
    that happens to be true — it is a template answering some other question, and the
    whole point of the preview is to say so rather than to let the companion open a task
    per matched entity.

    ``strict=True`` is load-bearing, and the reason is not obvious. Jinja's default
    undefined is lax about *comparison*: ``{{ stat == 'on' }}`` with ``stat``
    misspelled renders ``False`` rather than raising, because ``Undefined.__eq__``
    answers without touching the undefined-ness. So a typo in a variable name would
    not be an error at all — it would be a condition that is false forever, and on a
    binding with ``clear_on_recover`` the watcher would complete every armed task and
    record real completions for them. (A typo only raised when a *filter* touched it,
    as in ``{{ stat | float(0) }}``, which is what made this look covered.) Strict
    undefined turns the typo back into the error the indeterminate contract is for.

    The task name and notes renderer stays lax on purpose: ``{{ attributes.foo or
    'unknown' }}`` is a reasonable thing to write for a name, and a name that renders
    oddly is cosmetic where a trigger that renders wrongly closes people's work.

    Split out of the watcher class so the companion preview can render exactly what the
    watcher will, without standing one up.
    """
    if not source:
        return None, "sensor.template is empty"
    try:
        rendered = template_context.cached_template(
            hass, source, strict=True
        ).async_render(variables, parse_result=True, strict=True)
    except TemplateError as err:
        return None, str(err)
    if isinstance(rendered, bool):
        return rendered, None
    if isinstance(rendered, str):
        word = rendered.strip().lower()
        if word in _TRUE_WORDS:
            return True, None
        if word in _FALSE_WORDS:
            return False, None
    return None, f"the template rendered {rendered!r}, which is not true or false"


def read_template_result(
    hass: HomeAssistant, cfg: dict[str, Any] | None
) -> tuple[bool | None, str | None]:
    """Render a ``template`` binding against its bound entity. ``(result, error)``.

    The ``template`` mode's counterpart to :func:`read_sensor_value` and
    :func:`read_sensor_state`. Unlike those two it does **not** go through
    :func:`_raw_reading`: an unavailable entity is not "no reading" here, because a
    template is free to be about exactly that (``{{ state == 'unavailable' }}``).
    Whether a missing state means anything is the template's business, and
    ``{{ state }}`` is ``None`` when there is none.
    """
    if not cfg:
        return None, "the task has no sensor binding"
    entity_id = cfg.get("entity_id")
    if not entity_id:
        return None, "the binding names no entity"
    variables = template_context.template_variables(
        hass, template_context.registry_projection(hass, entity_id)
    )
    return render_template_result(hass, str(cfg.get("template") or ""), variables)


def _bound_to_any(cfg: dict[str, Any], entity_ids: frozenset[str]) -> bool:
    """Whether a state change of one of *entity_ids* can change this binding.

    The bound entity always can. A template can also read other entities, so a
    template that names one of them is evaluated too. A template that reads an
    entity in some other way waits for the periodic pass.
    """
    if cfg.get("entity_id") in entity_ids:
        return True
    if cfg.get("mode") != SENSOR_MODE_TEMPLATE:
        return False
    template = str(cfg.get("template") or "")
    return any(eid in template for eid in entity_ids)


class SensorTaskWatcher:
    """Evaluates sensor-based tasks against their bound entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: HomeKeeperCoordinator,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self._unsub_state: CALLBACK_TYPE | None = None
        self._tracked: tuple[str, ...] = ()
        # In-memory threshold edge state, keyed by task id:
        #   {"condition_met": bool | None, "crossed_at": datetime | None,
        #    "condition": tuple}
        # ``condition_met`` is ``None`` when the baseline is unknown: the entity had no
        # reading when the baseline was taken (see ``async_baseline``).
        # ``condition`` is the binding the other 2 were decided against (see
        # ``sensor_tasks.condition_fingerprint``); an edit to the task or to the
        # declarative companion that owns it retires them.
        self._edge: dict[str, dict[str, Any]] = {}
        # One pending "the hold is up" timer per task id, keyed the same way. A
        # ``for_seconds`` hold ends in its own time, and the bound entity sends no
        # state change to mark the moment. An entity that has gone unavailable sends
        # nothing ever again, so the watcher books the re-evaluation itself. Each
        # entry is the timer's unsubscribe callback, released the same way as
        # ``_unsub_state``.
        self._hold_timers: dict[str, CALLBACK_TYPE] = {}
        # In-memory usage-meter reset-candidate state, keyed by task id: the reading
        # from a prior below-baseline reading, awaiting a second consecutive one
        # before we treat it as a genuine meter reset (debounces a transient dip/blip
        # to 0). Each candidate keeps the report time of the entity state it came
        # from (see ``_reading_stamp``), so only a new report of the entity confirms
        # it, not a second pass over the same state (B14-3).
        # Held in memory only — never persisted — so a restart safely re-evaluates
        # from the current reading rather than acting on a half-seen reset.
        self._usage_reset: dict[str, tuple[float, Any] | None] = {}
        # The last template-render error logged per task id, so a broken template is
        # reported once rather than on every pass. A companion may match up to 500
        # entities, and each one is a task: a single typo wrote 500 warnings every 5
        # minutes, plus a burst on every state change of a bound entity, for as long as
        # the companion stayed broken. The message still repeats when the error
        # *changes*, which is the only time it carries new information. Same shape as
        # ``todo_sync_driver._warned``.
        self._template_errors: dict[str, str] = {}
        # One evaluation pass runs at a time (B14-2). A request that comes while a
        # pass runs is added here, and the running pass does one more pass for it.
        # A pass that overlapped another held old task dicts across its awaits and
        # completed a ``clear_on_recover`` task again that the other pass had cleared.
        # ``_pending_entities`` holds the entities whose state changed; only the tasks
        # bound to them are evaluated again (B14-6). ``_pending_all`` asks for every
        # task, as the periodic tick and a hold timer do.
        self._running = False
        self._pending_all = False
        self._pending_entities: set[str] = set()
        self._pending_refresh = False

    # ── task / entity enumeration ──────────────────────────────────────────────
    def _sensor_tasks(self) -> dict[str, dict[str, Any]]:
        """Enabled sensor-based tasks, keyed by id."""
        return {
            tid: task
            for tid, task in self._coordinator.store.get_tasks().items()
            if task.get("recurrence_type") == REC_SENSOR and task.get("enabled", True)
        }

    def _bound_entities(self) -> tuple[str, ...]:
        ids = {
            eid
            for task in self._sensor_tasks().values()
            if (eid := sensor_tasks.bound_entity_id(task))
        }
        return tuple(sorted(ids))

    # ── lifecycle ──────────────────────────────────────────────────────────────
    async def async_baseline(self) -> None:
        """Baseline edge state and usage baselines without arming anything.

        Called once during setup (before the watcher is attached to the coordinator)
        so the first evaluation only reacts to genuine transitions: a threshold sensor
        already above its limit at boot is recorded as already-met (no rising edge), and
        a usage task with no baseline yet is anchored to the current reading.

        Tasks made after the last baseline pass are the one exception (see
        :func:`async_mark_tasks_new`). Materializing a declarative companion's tasks
        reloads the config entry, which runs this method again; baselining a task made
        a second ago would eat the very edge the user made the companion for. Their edge
        is left unset, so the first evaluation reads a standing condition as a fresh
        crossing and arms them. The set is consumed here, so it can neither grow
        without bound nor reach an unrelated later reload.
        """
        fresh = _new_tasks_store(self._hass).pop(self._entry.entry_id, set())
        for tid, task in self._sensor_tasks().items():
            cfg = sensor_tasks.sensor_config(task)
            if cfg is None:
                continue
            mode = cfg.get("mode")
            if tid in fresh and sensor_tasks.holds_edge_state(mode):
                # Made after the last baseline: leave the edge unset so the first
                # evaluation arms on a condition that is already true. A usage meter
                # has no edge, so it is still anchored below.
                continue
            # Recorded with the state, so an edit between now and the first
            # evaluation retires it (see :meth:`_carried_edge`).
            condition = sensor_tasks.condition_fingerprint(task)
            # An entity with no reading yet gets an unknown baseline (``None``), not
            # "not met" (B14-1). Home Keeper can set up before the integration that
            # owns the entity (MQTT discovery, ZHA, a retrying config entry). If the
            # baseline read "not met", the first real state was a rising edge, and
            # each restart armed a task again that the user had dealt with. The
            # first definite reading after an unknown baseline is a baseline too.
            if mode == SENSOR_MODE_THRESHOLD:
                reading = read_sensor_value(self._hass, cfg)
                met: bool | None = (
                    None
                    if reading is None
                    else sensor_tasks.compare(
                        reading, cfg["comparison"], float(cfg["value"])
                    )
                )
                self._edge[tid] = {
                    "condition_met": met,
                    "crossed_at": None,
                    "condition": condition,
                }
            elif mode == SENSOR_MODE_STATE:
                # Record an already-matching sensor as met-without-a-crossing, so a
                # vacuum still reporting "water tank low" across a restart doesn't
                # re-arm a task the user already dealt with.
                state = read_sensor_state(self._hass, cfg)
                self._edge[tid] = {
                    "condition_met": None
                    if state is None
                    else state == cfg.get("state"),
                    "crossed_at": None,
                    "condition": condition,
                }
            elif mode == SENSOR_MODE_AVAILABILITY:
                # Record an already-unavailable entity as met-without-a-crossing:
                # a device that was offline before HA restarted must not fabricate a
                # fresh "gone offline" task the first time we look at it. A ``missing``
                # (not-yet-loaded) entity is indeterminate, so its baseline is unknown.
                status = read_availability_status(self._hass, cfg)
                self._edge[tid] = {
                    "condition_met": None
                    if status == sensor_tasks.AVAILABILITY_MISSING
                    else status == sensor_tasks.AVAILABILITY_UNAVAILABLE,
                    "crossed_at": None,
                    "condition": condition,
                }
            elif mode == SENSOR_MODE_TEMPLATE:
                # Record an already-true template as met-without-a-crossing, the same
                # way the three modes above record theirs: a sensor that was quiet
                # before Home Assistant restarted must not open a second task for the
                # same silence. A template that cannot render, or an entity that is
                # not loaded yet, gives an unknown baseline.
                result: bool | None = None
                if _entity_loaded(self._hass, cfg.get("entity_id")):
                    result, _error = read_template_result(self._hass, cfg)
                self._edge[tid] = {
                    "condition_met": result,
                    "crossed_at": None,
                    "condition": condition,
                }
            else:
                reading = read_sensor_value(self._hass, cfg)
                if reading is not None and cfg.get("baseline") is None:
                    await self._coordinator.store.set_sensor_baseline(tid, reading)

    @callback
    def async_start_listeners(self) -> None:
        """Begin reacting to bound-entity state changes (torn down on unload)."""
        self._entry.async_on_unload(self._unsubscribe_state)
        self._entry.async_on_unload(self._cancel_hold_timers)
        self._entry.async_on_unload(
            self._hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED, self._handle_registry_update
            )
        )
        self._resubscribe_state()

    @callback
    def _unsubscribe_state(self) -> None:
        if self._unsub_state is not None:
            self._unsub_state()
            self._unsub_state = None

    @callback
    def _cancel_hold_timers(self) -> None:
        """Drop every pending hold timer.

        Registered with ``async_on_unload`` beside :meth:`_unsubscribe_state`, so a
        reload cannot leave a callback behind that would fire into the watcher the
        reload replaced.
        """
        for unsub in self._hold_timers.values():
            unsub()
        self._hold_timers.clear()

    @callback
    def _cancel_hold_timer(self, tid: str) -> None:
        """Drop the pending hold timer of one task, if it has one."""
        unsub = self._hold_timers.pop(tid, None)
        if unsub is not None:
            unsub()

    @callback
    def _schedule_hold(self, tid: str, due_at: datetime | None) -> None:
        """Keep exactly one pending hold timer for *tid*.

        *due_at* is what the pure evaluator decided (``None`` = nothing is pending).
        The prior timer is always released first, so a task can never hold two: a
        state change that re-evaluates the task replaces its timer, and a task that
        armed, recovered or lost its hold simply has it cancelled.
        """
        self._cancel_hold_timer(tid)
        if due_at is None:
            return
        self._hold_timers[tid] = async_track_point_in_time(
            self._hass, partial(self._handle_hold_due, tid), due_at
        )

    @callback
    def _handle_hold_due(self, tid: str, _now: datetime) -> None:
        """A hold is up: run the same evaluation a state change would run.

        The whole pass runs, not just this task, so the arm, the notes refresh and the
        events are the ones every other path produces. A task deleted in the meantime
        is simply not in the pass.
        """
        self._hold_timers.pop(tid, None)  # it has fired; there is nothing to cancel
        self._hass.async_create_task(self.async_evaluate(refresh=True))

    @callback
    def _resubscribe_state(self) -> None:
        """(Re)point the state listener at the currently bound entity set."""
        tracked = self._bound_entities()
        if tracked == self._tracked:
            return
        self._unsubscribe_state()
        self._tracked = tracked
        if tracked:
            self._unsub_state = async_track_state_change_event(
                self._hass, list(tracked), self._handle_state_change
            )

    @callback
    def _handle_state_change(self, event: Event[EventStateChangedData]) -> None:
        # A bound sensor moved — evaluate the tasks bound to it (and request a refresh
        # so any new arming surfaces as overdue/due-soon immediately, outside the
        # periodic tick). The other tasks did not change, so they wait for the tick.
        self._hass.async_create_task(
            self.async_evaluate(refresh=True, entity_ids=(event.data["entity_id"],))
        )

    @callback
    def _handle_registry_update(self, event: Event[Any]) -> None:
        """Follow an entity id rename into the tasks bound to the entity (X10-1).

        A sensor binding stores the entity id. Without this, a task bound to a
        renamed entity reads nothing, and it does not arm again.
        """
        data = event.data
        if data.get("action") != "update" or not data.get("old_entity_id"):
            return
        self._hass.async_create_task(
            self._async_follow_rename(data["old_entity_id"], data["entity_id"])
        )

    async def _async_follow_rename(
        self, old_entity_id: str, new_entity_id: str
    ) -> None:
        """Rewrite each binding on *old_entity_id* and keep its carried edge state.

        The store rewrites disabled tasks too, so a task that is enabled later does
        not bring the old id back. The carried edge state follows the task: the
        entity is the same, so its condition did not change.
        """
        changed = await self._coordinator.store.async_repoint_sensor_entity(
            old_entity_id, new_entity_id
        )
        tasks = self._coordinator.store.get_tasks()
        for tid in changed:
            edge = self._edge.get(tid)
            task = tasks.get(tid)
            if edge is None or task is None:
                continue
            renamed = sensor_tasks.condition_fingerprint(task)
            if edge.get("condition") == (old_entity_id, *renamed[1:]):
                edge["condition"] = renamed
        if changed:
            self._resubscribe_state()

    # ── evaluation ─────────────────────────────────────────────────────────────
    async def async_evaluate(
        self, *, refresh: bool, entity_ids: Iterable[str] | None = None
    ) -> None:
        """Evaluate sensor tasks, applying arm / re-baseline decisions.

        ``refresh`` requests a coordinator refresh when something armed — set from the
        state-change path (which runs outside the coordinator cycle). The periodic
        coordinator tick passes ``refresh=False`` because it runs the transition
        detection itself, immediately after, in the same cycle.

        ``entity_ids`` limits the pass to the tasks bound to those entities (B14-6).
        ``None`` evaluates every task.

        Only one pass runs at a time (B14-2). A call that comes while a pass runs
        is added to the pending work and returns at once, and the running pass does
        one more pass for it. That pass always requests a refresh, because the
        caller did not wait for it.
        """
        if entity_ids is None:
            self._pending_all = True
        else:
            self._pending_entities.update(entity_ids)
        self._pending_refresh = self._pending_refresh or refresh or self._running
        if self._running:
            return
        self._running = True
        try:
            while self._pending_all or self._pending_entities:
                only = None if self._pending_all else frozenset(self._pending_entities)
                refresh_now = self._pending_refresh
                self._pending_all = False
                self._pending_entities = set()
                self._pending_refresh = False
                await self._async_pass(only=only, refresh=refresh_now)
        finally:
            self._running = False

    def _live_sensor_task(self, tid: str) -> dict[str, Any] | None:
        """The current stored dict of *tid*, if it is still an enabled sensor task.

        A pass reads each task again just before it evaluates it. The store replaces
        a task dict on a completion, so a dict read before an await can be old.
        """
        task = self._coordinator.store.get_tasks().get(tid)
        if (
            task is None
            or task.get("recurrence_type") != REC_SENSOR
            or not task.get("enabled", True)
        ):
            return None
        return task

    async def _async_pass(self, *, only: frozenset[str] | None, refresh: bool) -> None:
        """One evaluation pass over the sensor tasks (see :meth:`async_evaluate`)."""
        # Keep the subscription aligned with the live task set (a task may have been
        # added/edited/removed since we last subscribed).
        self._resubscribe_state()
        now = dt_util.now()
        changed_any = False
        for tid in list(self._sensor_tasks()):
            task = self._live_sensor_task(tid)
            if task is None:
                continue
            cfg = sensor_tasks.sensor_config(task)
            if cfg is None:
                continue
            mode = cfg.get("mode")
            if only is not None and not _bound_to_any(cfg, only):
                continue
            if mode == SENSOR_MODE_STATE:
                # A missing state is handled inside the evaluator (it holds the edge
                # state rather than reading a dropout as a recovery), so unlike the
                # numeric modes there's nothing to skip here.
                if await self._evaluate_state(
                    tid, task, state=read_sensor_state(self._hass, cfg), now=now
                ):
                    changed_any = True
                continue
            if mode == SENSOR_MODE_AVAILABILITY:
                # Availability inverts the "no reading" policy: an ``unavailable``
                # entity is the arm signal here, not something to skip. The evaluator
                # holds edge state on ``missing`` (not-yet-loaded), so boot doesn't
                # fabricate transitions.
                if await self._evaluate_availability(
                    tid,
                    task,
                    status=read_availability_status(self._hass, cfg),
                    now=now,
                ):
                    changed_any = True
                continue
            if mode == SENSOR_MODE_TEMPLATE:
                # Matched explicitly, ahead of the numeric read below: the ``else`` at
                # the end of this chain treats an unrecognised mode as ``threshold``,
                # so a fall-through would compare a template binding against a
                # ``comparison`` and ``value`` it does not carry.
                result: bool | None = None
                error: str | None = None
                if _entity_loaded(
                    self._hass, cfg.get("entity_id")
                ) or not self._edge_unknown(tid, task):
                    # While the baseline is unknown, an entity that is not loaded yet
                    # keeps it unknown (B14-1): a template can render a definite
                    # answer for a missing entity, and that answer is not a baseline.
                    result, error = read_template_result(self._hass, cfg)
                self._report_template_error(tid, task, cfg, error)
                if await self._evaluate_template(tid, task, result=result, now=now):
                    changed_any = True
                continue
            reading = read_sensor_value(self._hass, cfg)
            if mode == SENSOR_MODE_USAGE:
                # A usage task with a time backstop must still be evaluable with no
                # reading — an appliance that's been offline for a year still owes its
                # annual service. Without one there's nothing a missing reading can
                # decide, so skip rather than churn.
                if reading is None and not cfg.get("also_every"):
                    continue
                if await self._evaluate_usage(tid, task, reading=reading, now=now):
                    changed_any = True
            else:
                # A missing reading is handled inside the evaluator, like the state
                # mode's missing state: it never arms on bad data, and it ends a
                # pending hold. Skipping it here left the crossing and its timer in
                # place, so the seconds an entity spent unreadable counted toward the
                # hold (#336).
                if await self._evaluate_threshold(tid, task, reading=reading, now=now):
                    changed_any = True
        # Drop edge state for tasks that no longer exist so it can't leak. A task that
        # went away (deleted, disabled, or no longer a sensor task) takes its pending
        # hold timer with it.
        live = set(self._sensor_tasks())
        for stale in [tid for tid in self._edge if tid not in live]:
            del self._edge[stale]
        for stale in [tid for tid in self._usage_reset if tid not in live]:
            del self._usage_reset[stale]
        for stale in [tid for tid in self._template_errors if tid not in live]:
            del self._template_errors[stale]
        for stale in [tid for tid in self._hold_timers if tid not in live]:
            self._cancel_hold_timer(stale)
        if changed_any and refresh:
            await self._coordinator.async_request_refresh()

    async def _evaluate_usage(
        self, tid: str, task: dict[str, Any], *, reading: float | None, now: Any
    ) -> bool:
        prior = self._usage_reset.get(tid)
        stamp = (
            _reading_stamp(self._hass, sensor_tasks.sensor_config(task))
            if reading is not None
            else None
        )
        candidate: float | None = None
        if prior is not None and (
            reading is None or stamp is None or stamp != prior[1]
        ):
            # A new report of the entity (or no reading, which leaves the candidate
            # as it is). The same report seen by a second pass is not a second
            # reading, so it does not confirm the reset (B14-3).
            candidate = prior[0]
        decision = sensor_tasks.evaluate_usage(
            task,
            reading=reading,
            reset_candidate=candidate,
            now=now,
        )
        next_candidate = decision["reset_candidate"]
        if next_candidate is None:
            self._usage_reset[tid] = None
        else:
            kept = stamp if reading is not None or prior is None else prior[1]
            self._usage_reset[tid] = (next_candidate, kept)
        action = decision["action"]
        if action == sensor_tasks.ACTION_REBASELINE:
            await self._coordinator.store.set_sensor_baseline(tid, decision["baseline"])
            return False
        if action == sensor_tasks.ACTION_ARM:
            await self._async_arm(tid)
            return True
        return False

    def _carried_edge(
        self, tid: str, task: dict[str, Any]
    ) -> tuple[bool | None, datetime | None]:
        """The carried ``(condition_met, crossed_at)`` for *task*, if it still applies.

        Edge state answers a question about one condition, so an edit to the task —
        or to the companion that owns it — retires it: the fingerprint recorded with the
        state no longer matches the binding being evaluated, and the pass starts from
        "nothing seen yet". A standing condition then reads as a fresh crossing and
        arms after its hold, which is what a person editing a task expects. The
        pending hold goes with the state it belonged to.
        """
        edge = self._edge.get(tid)
        if edge is None:
            return False, None
        if edge.get("condition") != sensor_tasks.condition_fingerprint(task):
            self._cancel_hold_timer(tid)
            return False, None
        return edge.get("condition_met"), edge.get("crossed_at")

    def _edge_unknown(self, tid: str, task: dict[str, Any]) -> bool:
        """Whether the carried baseline of *task* is unknown (see B14-1)."""
        edge = self._edge.get(tid)
        return (
            edge is not None
            and edge.get("condition_met") is None
            and edge.get("condition") == sensor_tasks.condition_fingerprint(task)
        )

    async def _evaluate_threshold(
        self, tid: str, task: dict[str, Any], *, reading: float | None, now: Any
    ) -> bool:
        condition_met_prev, crossed_at = self._carried_edge(tid, task)
        return await self._apply_edge(
            tid,
            task,
            sensor_tasks.evaluate_threshold(
                task,
                reading=reading,
                condition_met_prev=condition_met_prev,
                crossed_at=crossed_at,
                now=now,
            ),
        )

    async def _evaluate_state(
        self, tid: str, task: dict[str, Any], *, state: str | None, now: Any
    ) -> bool:
        condition_met_prev, crossed_at = self._carried_edge(tid, task)
        return await self._apply_edge(
            tid,
            task,
            sensor_tasks.evaluate_state(
                task,
                state=state,
                condition_met_prev=condition_met_prev,
                crossed_at=crossed_at,
                now=now,
            ),
        )

    async def _evaluate_availability(
        self, tid: str, task: dict[str, Any], *, status: str, now: Any
    ) -> bool:
        condition_met_prev, crossed_at = self._carried_edge(tid, task)
        return await self._apply_edge(
            tid,
            task,
            sensor_tasks.evaluate_availability(
                task,
                status=status,
                condition_met_prev=condition_met_prev,
                crossed_at=crossed_at,
                now=now,
            ),
        )

    def _report_template_error(
        self,
        tid: str,
        task: dict[str, Any],
        cfg: dict[str, Any],
        error: str | None,
    ) -> None:
        """Log a template that did not render, once per error rather than per pass.

        A template that cannot render decides nothing — the task neither arms nor
        clears — so without a log line the task just sits there and nothing says why.
        But the pass runs every 5 minutes and on every state change of a bound entity,
        and a companion materializes one task per matched entity, so logging it each
        time buried the rest of the log under one typo.

        Keyed by task and compared against the last message, so a template that starts
        failing *differently* is reported again. Clearing the entry on a good render is
        what makes a template that breaks, is fixed, then breaks again report twice.
        """
        if error is None:
            self._template_errors.pop(tid, None)
            return
        if self._template_errors.get(tid) == error:
            return
        self._template_errors[tid] = error
        _LOGGER.warning(
            "Template trigger for %s (%s) did not render: %s",
            task.get("name"),
            cfg.get("entity_id"),
            error,
        )

    async def _evaluate_template(
        self, tid: str, task: dict[str, Any], *, result: bool | None, now: Any
    ) -> bool:
        condition_met_prev, crossed_at = self._carried_edge(tid, task)
        return await self._apply_edge(
            tid,
            task,
            sensor_tasks.evaluate_template(
                task,
                result=result,
                condition_met_prev=condition_met_prev,
                crossed_at=crossed_at,
                now=now,
            ),
        )

    async def _async_arm(self, tid: str) -> None:
        """Arm a task, refreshing a declarative companion's notes first.

        The notes of a task a declarative companion manages are rendered from the
        entity's live state, but only when the reconciler runs — at creation, and on
        registry changes after that. A template that quotes the reading ("{{ state }}
        hours left") therefore describes the value from that moment, not the value
        that armed the task. Rendering again on the arm makes the note describe the
        reading the person is about to read it for.

        The arm transition is the only place this happens: rendering on every
        evaluation would write to the store on each tick, for no gain on a task
        nobody is looking at. The refresh runs *before* the arm so the
        ``home_keeper_task_triggered`` event already carries the fresh note.

        A refresh must never stop a task from arming, so a failure is logged and
        swallowed.
        """
        sync = self._coordinator.declarative_sync
        if sync is not None:
            try:
                await sync.async_refresh_task_notes(tid)
            except Exception:  # pragma: no cover - defensive
                _LOGGER.exception("Could not refresh the notes of task %s", tid)
        await self._coordinator.store.trigger_task(tid)

    async def _apply_edge(
        self, tid: str, task: dict[str, Any], decision: dict[str, Any]
    ) -> bool:
        """Carry an edge decision's state forward and apply its action.

        Returns whether the task's due-state changed. A ``clear_on_recover`` clear
        counts as much as an arming: the task drops off the overdue surfaces, and that
        should show up immediately rather than at the next periodic tick.

        The decision also says when a pending ``for_seconds`` hold completes, which is
        the moment this task must be evaluated again. While the bound entity stays
        quiet, only the five-minute coordinator tick would do it, and it would arm the
        task as much as five minutes late.
        """
        self._edge[tid] = {
            "condition_met": decision["condition_met"],
            "crossed_at": decision["crossed_at"],
            "condition": sensor_tasks.condition_fingerprint(task),
        }
        self._schedule_hold(tid, decision["hold_due_at"])
        action = decision["action"]
        if action == sensor_tasks.ACTION_ARM:
            await self._async_arm(tid)
            return True
        if action == sensor_tasks.ACTION_CLEAR:
            # The condition went away on its own, so the work is done: record a real
            # completion (history, events, the todo/calendar surfaces all follow) and
            # tag it so an automation can tell it apart from someone pressing Done.
            # Read the stored task again first: a task that is already dormant has
            # nothing to clear, and a second completion is a false record (B14-2).
            live = self._coordinator.store.get_tasks().get(tid)
            if live is None or live.get("next_due") is None:
                return False
            await self._coordinator.store.complete_task(
                tid, origin=ORIGIN_SENSOR_RECOVER
            )
            return True
        return False
