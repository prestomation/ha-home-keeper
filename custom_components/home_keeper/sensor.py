"""Home Keeper sensors.

Three kinds, all living on a device page:

* ``HomeKeeperNextDueSensor`` — per-task "next due" timestamp, for tasks attached
  to a device.
* ``HomeKeeperTaskCountSensor`` — an aggregate count, one per profile plus one for
  every task Home Keeper keeps, on the integration's own service device. This is the
  number a dashboard badge shows.
* ``HomeKeeperAssetDateSensor`` — a tracked ``date`` metadata entry on an asset, so
  temporal attributes are automatable natively (e.g. "warranty expiring in 30 days
  -> notify") and show in state history. Only metadata dates the user opts into
  tracking (``track``) get a sensor; the rest are display-only.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import notifier, profiles, sensor_tasks, task_counts
from .const import (
    COMPLETION_ENTRY_FIELDS,
    DOMAIN,
    OPTION_PROFILES,
    SENSOR_MODE_USAGE,
)
from .coordinator import HomeKeeperCoordinator
from .devices import service_device_info
from .entity import HomeKeeperTaskEntity, prune_registry_entries
from .options import current_options
from .sensor_watcher import read_sensor_value

# Default icon for a tracked-date sensor when the asset has no custom icon.
_DATE_ICON = "mdi:calendar-clock"

# Unique id of the count sensor that spans every task, and the prefix/suffix pair the
# per-profile count sensors are keyed by. Anchored to the profile *id* rather than its
# name, so renaming a profile keeps the entity id it is already on a dashboard under.
_ALL_COUNT_UID = f"{DOMAIN}_tasks"
_PROFILE_COUNT_PREFIX = f"{DOMAIN}_profile_"
_PROFILE_COUNT_SUFFIX = "_tasks"


def _profile_count_uid(profile_id: str) -> str:
    return f"{_PROFILE_COUNT_PREFIX}{profile_id}{_PROFILE_COUNT_SUFFIX}"


def _tracked_dates(asset: dict[str, Any]) -> list[dict[str, Any]]:
    """The asset's metadata entries that are tracked dates with a value set."""
    return [
        entry
        for entry in (asset.get("metadata") or [])
        if entry.get("type") == "date" and entry.get("track") and entry.get("value")
    ]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the next-due, count and asset-date sensors."""
    coordinator: HomeKeeperCoordinator = entry.runtime_data

    count_entities, live_count_uids = _count_entities(coordinator, entry)

    task_ids = coordinator.device_attached_task_ids()
    live_task_ids = set(task_ids)

    # Build the set of live asset-date sensor unique-ids (only for assets that have
    # a resolvable device and tracked date entries with a value set).
    live_asset_meta_uids: set[str] = set()
    asset_entities: list[SensorEntity] = []
    for asset in coordinator.store.list_assets():
        device = coordinator.device_entry_for_device_id(asset.get("device_id"))
        if device is None:
            continue
        for meta in _tracked_dates(asset):
            uid = f"{DOMAIN}_asset_{asset['id']}_meta_{meta['id']}"
            live_asset_meta_uids.add(uid)
            asset_entities.append(
                HomeKeeperAssetDateSensor(coordinator, asset["id"], meta, device)
            )

    # Remove entity-registry entries for sensors whose source no longer exists:
    # • per-task next-due sensors for deleted/detached tasks
    # • asset date sensors for removed or un-tracked metadata entries
    task_prefix = f"{DOMAIN}_"
    task_suffix = "_next_due"
    asset_prefix = f"{DOMAIN}_asset_"
    asset_infix = "_meta_"

    def keep(uid: str) -> bool | None:
        # The count branches come first so the intent reads in order. They cannot
        # collide with the task branch below, which requires the ``_next_due`` suffix.
        if uid == _ALL_COUNT_UID:
            return True
        if uid.startswith(_PROFILE_COUNT_PREFIX) and uid.endswith(
            _PROFILE_COUNT_SUFFIX
        ):
            return uid in live_count_uids
        if uid.startswith(task_prefix) and uid.endswith(task_suffix):
            return uid[len(task_prefix) : -len(task_suffix)] in live_task_ids
        if uid.startswith(asset_prefix) and asset_infix in uid:
            return uid in live_asset_meta_uids
        return None

    prune_registry_entries(hass, entry, "sensor", keep)

    task_entities: list[SensorEntity] = [
        HomeKeeperNextDueSensor(coordinator, task_id) for task_id in task_ids
    ]
    async_add_entities(task_entities + asset_entities + count_entities)


def _count_entities(
    coordinator: HomeKeeperCoordinator, entry: ConfigEntry
) -> tuple[list[SensorEntity], set[str]]:
    """The count sensors to add, and the unique ids that are still live.

    The all-tasks sensor is built **unconditionally** — with no profiles, no assets
    and no tasks at all. That is what keeps at least one entity on the service device,
    which is what stops ``devices.async_prune_orphaned_devices`` removing it.
    """
    # No profile spans everything, so synthesize the filter the same way a stored one
    # is built: every include and exclude list empty, so the scope is every active
    # scheduled task. The state is then the overdue count, which is the badge case.
    all_filter = profiles.normalize_filter({"status": profiles.STATUS_OVERDUE})
    entities: list[SensorEntity] = [
        HomeKeeperTaskCountSensor(
            coordinator,
            unique_id=_ALL_COUNT_UID,
            translation_key="all_tasks",
            placeholders={},
            task_filter=all_filter,
        )
    ]
    live: set[str] = {_ALL_COUNT_UID}
    stored = profiles.normalize_profiles(current_options(entry).get(OPTION_PROFILES))
    for profile in stored:
        uid = _profile_count_uid(profile["id"])
        live.add(uid)
        entities.append(
            HomeKeeperTaskCountSensor(
                coordinator,
                unique_id=uid,
                translation_key="profile_tasks",
                placeholders={"profile": profile["name"]},
                task_filter=profile["filter"],
            )
        )
    return entities, live


#: The next-due sensor attribute each :func:`sensor_tasks.usage_interval_stats` key
#: is published as. One place to read the four names an automation depends on.
_USAGE_INTERVAL_ATTRS = {
    "last": "usage_last_interval",
    "average": "usage_avg_interval",
    "shortest": "usage_min_interval",
    "longest": "usage_max_interval",
}


class HomeKeeperNextDueSensor(HomeKeeperTaskEntity, SensorEntity):
    """Timestamp sensor reporting when a task is next due."""

    _attr_translation_key = "next_due"
    _attr_icon = "mdi:calendar-clock"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: HomeKeeperCoordinator, task_id: str) -> None:
        super().__init__(coordinator, task_id)
        self._attr_unique_id = f"{DOMAIN}_{task_id}_next_due"

    @property
    def native_value(self) -> datetime | None:
        due = self._task.get("next_due")
        return dt_util.parse_datetime(due) if due else None

    @property
    def extra_state_attributes(self) -> dict:
        task = self._task
        completions = task.get("completions", [])
        attrs: dict[str, Any] = {
            "task_id": self._task_id,
            "task_name": task.get("name"),
            "recurrence_type": task.get("recurrence_type"),
            "last_completed": task.get("last_completed"),
            "completions_count": len(completions),
        }
        # Surface the most recent completion's fields so automations/dashboards can
        # read "who did it / what did it cost / the note / the photo / where the meter
        # stood" without parsing the history array. Driven off the shared field list
        # rather than a local literal, so a new completion field lands here too — this
        # loop silently skipped ``reading`` for exactly that reason. Keys are only
        # present when that completion recorded them.
        if completions:
            # Match ``last_completed`` (the chronologically latest), not merely the
            # last appended, so an out-of-order seed can't shadow a real completion.
            latest = max(completions, key=lambda c: c.get("ts") or "")
            for key in COMPLETION_ENTRY_FIELDS:
                if key in latest:
                    attrs[f"last_completion_{key}"] = latest[key]
        attrs.update(self._usage_attributes(task))
        return attrs

    def _usage_attributes(self, task: dict[str, Any]) -> dict[str, Any]:
        """Meter progress for a usage sensor task, so automations can read it.

        A usage task's whole state is "how far through the interval am I" — the same
        figures a dedicated maintenance helper would expose as separate entities. They
        ride on this task's existing next-due sensor instead, which keeps one entity per
        task (Home Keeper's model) while still making the numbers automatable and
        templatable. Absent entirely for non-usage tasks.
        """
        cfg = sensor_tasks.sensor_config(task)
        if cfg is None or cfg.get("mode") != SENSOR_MODE_USAGE:
            return {}
        target = float(cfg["target"])
        attrs: dict[str, Any] = {"usage_target": target}
        if unit := cfg.get("unit"):
            attrs["usage_unit"] = unit
        reading = read_sensor_value(self.hass, cfg)
        baseline = cfg.get("baseline")
        if baseline is not None:
            # The anchor the consumed figure is measured from. Worth exposing in its
            # own right now that it is user-settable at creation and correctable from
            # the history: a dashboard showing "3,000 of 10,000 used" can say what the
            # odometer read when the oil was last changed.
            attrs["usage_baseline"] = float(baseline)
        if reading is not None and baseline is not None:
            consumed = max(0.0, reading - float(baseline))
            attrs["usage_consumed"] = round(consumed, 3)
            attrs["usage_remaining"] = round(target - consumed, 3)
            attrs["usage_percent"] = round(min(100.0, consumed / target * 100), 1)
        due_at = sensor_tasks.backstop_due(task, cfg)
        if due_at is not None:
            attrs["backstop_due"] = due_at.isoformat()
        # How much use each past service interval actually ran, summarized. The
        # readings are already in the history; a template that wants "is this one
        # running short?" should not have to fetch the whole log and subtract.
        # Absent until two completions carry a reading. The attribute names are
        # spelled out rather than derived from the stats keys, because they are the
        # public contract a template writes against.
        intervals = sensor_tasks.usage_interval_stats(task)
        for stat, attr in _USAGE_INTERVAL_ATTRS.items():
            if stat in intervals:
                attrs[attr] = round(intervals[stat], 3)
        return attrs


class HomeKeeperTaskCountSensor(CoordinatorEntity[HomeKeeperCoordinator], SensorEntity):
    """How many tasks a profile surfaces right now, plus the next one up.

    The state is the count **that profile's own status tier selects** — an overdue
    profile counts overdue tasks, a due-soon profile counts overdue and due-soon
    together, an every-scheduled-task profile counts its whole scope. That is the
    number a dashboard badge shows, and it is computed by
    ``profiles.matches_filter``, so it can never disagree with the panel, the
    dashboard card, a notification or a to-do list sync about the same profile.

    The attributes are taken over the profile's **scope** (the same filter with the
    status widened to "all"), so ``total`` keeps its meaning however the tier is set
    and the next-up pointers name a task even when the state is 0.

    Counts refresh on the coordinator's cadence, the same as
    ``binary_sensor.*_overdue``, so an overdue count can trail reality by a few
    minutes.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:clipboard-text-clock"
    # A plain count: MEASUREMENT makes Home Assistant keep long-term statistics, so a
    # user can graph "is the backlog growing". Deliberately no unit — a literal
    # "tasks" would not translate, and adding a unit to a recorded statistic later is
    # a migration rather than a free change.
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: HomeKeeperCoordinator,
        *,
        unique_id: str,
        translation_key: str,
        placeholders: dict[str, str],
        task_filter: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = unique_id
        self._attr_translation_key = translation_key
        self._attr_translation_placeholders = placeholders
        self._filter = task_filter
        self._attr_device_info = service_device_info()

    def _counts(self) -> dict[str, Any]:
        """The whole count result for this profile, as of now.

        Tasks go through ``notifier.effective_filter_tasks`` first: a task inherits
        labels and an area from the device it is attached to, and the pure filter only
        sees a task's own fields. Without the enrichment a profile filtering on an
        inherited label would count a different set here than the panel and the card
        show for that same profile.

        ``dt_util.now()`` — local time, never ``utcnow()``, because ``due_today`` is a
        calendar date in the user's own zone.
        """
        tasks = notifier.effective_filter_tasks(
            self.hass, list(self.coordinator.data.values())
        )
        return task_counts.count_tasks(tasks, self._filter, now=dt_util.now())

    @property
    def native_value(self) -> int:
        return int(self._counts()["state"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {key: value for key, value in self._counts().items() if key != "state"}


class HomeKeeperAssetDateSensor(CoordinatorEntity[HomeKeeperCoordinator], SensorEntity):
    """A single tracked ``date`` metadata entry for an asset, on its device page.

    The value lives in the asset's free-form ``metadata`` list (not the task map);
    asset edits reload the config entry, which recreates these entities, so a plain
    coordinator read is enough to stay current. The entity is named from the entry's
    user-supplied ``label`` (not a translation, since labels are free-form).
    """

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(
        self,
        coordinator: HomeKeeperCoordinator,
        asset_id: str,
        entry: dict[str, Any],
        device: dr.DeviceEntry,
    ) -> None:
        super().__init__(coordinator)
        self._asset_id = asset_id
        self._entry_id = entry["id"]
        # Name is the user's free-form label (no localization for custom fields).
        self._attr_name = entry.get("label")
        # A user-chosen appliance icon overrides the default.
        asset = coordinator.store.get_asset(asset_id) or {}
        self._attr_icon = asset.get("icon") or _DATE_ICON
        self._attr_unique_id = f"{DOMAIN}_asset_{asset_id}_meta_{entry['id']}"
        # Linked, not owned: the appliance device belongs to whoever created it.
        self.device_entry = device

    def _entry(self) -> dict[str, Any] | None:
        asset = self.coordinator.store.get_asset(self._asset_id) or {}
        for entry in asset.get("metadata") or []:
            if entry.get("id") == self._entry_id:
                return entry
        return None

    @property
    def native_value(self) -> date | None:
        entry = self._entry()
        value = entry.get("value") if entry else None
        if not value:
            return None
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None
