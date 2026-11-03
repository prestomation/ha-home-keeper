"""Unit tests for ci/check_ha_log.py.

Run with: python -m pytest tests/unit/test_check_ha_log.py -v
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "ci" / "check_ha_log.py"
_spec = importlib.util.spec_from_file_location("check_ha_log", SCRIPT)
assert _spec is not None and _spec.loader is not None
check_ha_log = importlib.util.module_from_spec(_spec)
sys.modules["check_ha_log"] = check_ha_log
_spec.loader.exec_module(check_ha_log)

TS = "2026-11-02 10:00:00.123"

CLEAN_LOG = f"""\
{TS} INFO (MainThread) [homeassistant.core] Starting Home Assistant
{TS} WARNING (SyncWorker_0) [homeassistant.loader] We found a custom integration home_keeper which has not been tested by Home Assistant. This component might cause stability problems, be sure to disable it if you experience issues with Home Assistant
{TS} DEBUG (MainThread) [custom_components.home_keeper.coordinator] debug line is fine
{TS} INFO (MainThread) [custom_components.home_keeper] Setup done
{TS} WARNING (MainThread) [homeassistant.components.foo] Other integration warning
"""

BLOCKING_LOG = f"""\
{TS} INFO (MainThread) [homeassistant.core] Starting Home Assistant
{TS} WARNING (MainThread) [homeassistant.util.loop] Detected blocking call to read_text with args (PosixPath('/config/custom_components/home_keeper/manifest.json'),) inside the event loop by custom integration 'home_keeper' at custom_components/home_keeper/diagnostics.py, line 33: manifest_data = json.loads(manifest_path.read_text(encoding="utf-8")) (offender: /usr/local/lib/python3.13/pathlib/_local.py, line 546: return f.read()), please create a bug report at https://github.com/prestomation/ha-home-keeper/issues
Traceback (most recent call last):
  File "/config/custom_components/home_keeper/diagnostics.py", line 33, in async_get_config_entry_diagnostics
"""


def run(log: str, domain: str = "home_keeper", allowlist=None):
    records = check_ha_log.parse_records(log.splitlines())
    return check_ha_log.check_records(records, domain, allowlist or [])


def test_clean_log_has_no_findings():
    assert run(CLEAN_LOG) == []


def test_generic_custom_integration_notice_is_ignored():
    log = (
        f"{TS} WARNING (SyncWorker_0) [homeassistant.loader] We found a custom "
        "integration home_keeper which has not been tested by Home Assistant. "
        "This component might cause stability problems\n"
    )
    assert run(log) == []


@pytest.mark.parametrize("level", ["WARNING", "ERROR", "CRITICAL"])
def test_integration_logger_at_warning_or_higher_fails(level):
    log = f"{TS} {level} (MainThread) [custom_components.home_keeper.engine] boom\n"
    findings = run(log)
    assert len(findings) == 1
    assert "custom_components.home_keeper.engine" in findings[0].rule


def test_integration_root_logger_fails():
    log = f"{TS} ERROR (MainThread) [custom_components.home_keeper] boom\n"
    assert len(run(log)) == 1


def test_logger_of_other_domain_is_not_ours():
    log = f"{TS} ERROR (MainThread) [custom_components.home_keeper_extra] boom\n"
    assert run(log) == []
    log = f"{TS} ERROR (MainThread) [custom_components.other] boom\n"
    assert run(log) == []


def test_blocking_call_for_our_domain_fails():
    findings = run(BLOCKING_LOG)
    assert len(findings) == 1
    assert "blocking call" in findings[0].rule
    assert "diagnostics.py, line 33" in findings[0].text


def test_blocking_call_for_other_domain_is_ignored():
    log = (
        f"{TS} WARNING (MainThread) [homeassistant.util.loop] Detected blocking "
        "call to open inside the event loop by custom integration 'other' at "
        "custom_components/other/x.py, line 1\n"
    )
    assert run(log) == []


def test_docker_compose_prefix_is_accepted():
    log = "homeassistant-1  | " + BLOCKING_LOG.splitlines()[1] + "\n"
    assert len(run(log)) == 1


@pytest.mark.parametrize(
    "message",
    [
        (
            "/config/custom_components/home_keeper/engine.py:10: RuntimeWarning: "
            "coroutine 'foo' was never awaited"
        ),
        (
            "Task exception was never retrieved\nTraceback (most recent call last):\n"
            '  File "/config/custom_components/home_keeper/coordinator.py", line 5'
        ),
        (
            "Executing <Task pending name='Task-9' coro=<run() running at "
            "/config/custom_components/home_keeper/coordinator.py:55>> "
            "took 0.350 seconds"
        ),
        (
            "Unclosed client session client_session: <aiohttp.ClientSession> "
            "created at /config/custom_components/home_keeper/x.py:3"
        ),
        (
            "The integration 'home_keeper' uses a deprecated call "
            "(custom_components/home_keeper/__init__.py)"
        ),
    ],
)
def test_known_bad_patterns_for_our_domain_fail(message):
    log = f"{TS} WARNING (MainThread) [asyncio] {message}\n"
    assert len(run(log)) == 1


def test_known_bad_patterns_for_other_code_are_ignored():
    log = (
        f"{TS} WARNING (MainThread) [asyncio] Executing <Task pending name='T' "
        "coro=<run() running at /usr/src/homeassistant/foo.py:5>> took 0.4 seconds\n"
        f"{TS} WARNING (MainThread) [py.warnings] /config/custom_components/other/a.py:1: "
        "RuntimeWarning: coroutine 'x' was never awaited\n"
    )
    assert run(log) == []


def test_traceback_lines_belong_to_the_record_before_them():
    log = (
        f"{TS} ERROR (MainThread) [asyncio] Task exception was never retrieved\n"
        "future: <Task finished>\n"
        "Traceback (most recent call last):\n"
        '  File "/config/custom_components/home_keeper/engine.py", line 1, in f\n'
        f"{TS} INFO (MainThread) [homeassistant.core] later line\n"
    )
    findings = run(log)
    assert len(findings) == 1
    assert findings[0].line_no == 1


def test_allowlist_entry_hides_a_finding(tmp_path):
    path = tmp_path / "allow.txt"
    path.write_text(
        "# The test setup has no real light, so this warning is expected.\n"
        "light\\.missing is unavailable\n"
    )
    allow = check_ha_log.load_allowlist(path)
    log = (
        f"{TS} WARNING (MainThread) [custom_components.home_keeper.engine] "
        "light.missing is unavailable\n"
        f"{TS} WARNING (MainThread) [custom_components.home_keeper.engine] other\n"
    )
    findings = run(log, allowlist=allow)
    assert len(findings) == 1
    assert "other" in findings[0].text


def test_allowlist_entry_without_reason_is_rejected(tmp_path):
    path = tmp_path / "allow.txt"
    path.write_text("light\\.missing is unavailable\n")
    with pytest.raises(ValueError, match="no reason"):
        check_ha_log.load_allowlist(path)


def test_allowlist_reason_does_not_carry_over_a_blank_line(tmp_path):
    path = tmp_path / "allow.txt"
    path.write_text("# Reason one.\nfirst\n\nsecond\n")
    with pytest.raises(ValueError, match="no reason"):
        check_ha_log.load_allowlist(path)


def test_shipped_allowlist_is_valid():
    check_ha_log.load_allowlist(SCRIPT.with_name("ha_log_allowlist.txt"))


def _cli(tmp_path, log_text, *extra):
    log = tmp_path / "ha.log"
    log.write_text(log_text)
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--domain", "home_keeper", *extra, str(log)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_exit_codes(tmp_path):
    assert _cli(tmp_path, CLEAN_LOG).returncode == 0
    failed = _cli(tmp_path, BLOCKING_LOG)
    assert failed.returncode == 1
    assert "diagnostics.py" in failed.stdout
    # An empty log must not pass.
    assert _cli(tmp_path, "").returncode == 2
    assert _cli(tmp_path, "no ha records here\n").returncode == 2


def test_cli_reads_stdin():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--domain", "home_keeper"],
        input=BLOCKING_LOG,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1


def test_cli_bad_allowlist_exits_2(tmp_path):
    allow = tmp_path / "allow.txt"
    allow.write_text("no reason here\n")
    assert _cli(tmp_path, CLEAN_LOG, "--allowlist", str(allow)).returncode == 2


# ---------------------------------------------------------------------------
# Realistic log text: compose prefix, colour codes, tracebacks
# ---------------------------------------------------------------------------

PREFIX = "homeassistant-1  | "

REAL_BLOCKING_LINE = (
    "2026-11-02 10:00:05.200 WARNING (MainThread) [homeassistant.util.loop] "
    "Detected blocking call to open with args "
    "(PosixPath('/config/custom_components/home_keeper/manifest.json'),) "
    "inside the event loop by custom integration 'home_keeper' at "
    "custom_components/home_keeper/diagnostics.py, line 34: "
    'manifest_data = json.loads(manifest_path.read_text(encoding="utf-8")) '
    "(offender: /usr/local/lib/python3.13/pathlib/_local.py, line 546: "
    "return f.read()), please create a bug report at "
    "https://github.com/prestomation/ha-home-keeper/issues"
)

REAL_COMPOSE_LOG = "\n".join(
    PREFIX + line
    for line in [
        "s6-rc: info: service s6rc-oneshot-runner: starting",
        "2026-11-02 10:00:00.100 INFO (MainThread) [homeassistant.bootstrap] Starting Home Assistant",
        "2026-11-02 10:00:01.000 WARNING (SyncWorker_3) [homeassistant.loader] We found a custom integration home_keeper which has not been tested by Home Assistant.",
        REAL_BLOCKING_LINE,
        "Traceback (most recent call last):",
        '  File "/config/custom_components/home_keeper/diagnostics.py", line 34, in async_get_config_entry_diagnostics',
        '    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))',
        "2026-11-02 10:00:06.000 INFO (MainThread) [homeassistant.components.http] Request done",
    ]
)


def test_real_compose_log_is_parsed():
    records = check_ha_log.parse_records(REAL_COMPOSE_LOG.splitlines())
    levels = [r.level for r in records]
    # The s6 line has no level. The other four are records.
    assert levels == [None, "INFO", "WARNING", "WARNING", "INFO"]
    assert records[3].logger == "homeassistant.util.loop"
    # The traceback lines belong to the blocking-call record.
    assert "manifest_path.read_text" in records[3].text
    assert "Traceback" in records[3].text


def test_real_compose_log_finds_the_blocking_call():
    findings = run(REAL_COMPOSE_LOG)
    assert len(findings) == 1
    assert "blocking call" in findings[0].rule
    assert "diagnostics.py, line 34" in findings[0].text


def test_colour_codes_are_removed():
    log = f"{PREFIX}\x1b[33m{REAL_BLOCKING_LINE}\x1b[0m\n"
    assert len(run(log)) == 1


def test_compose_prefix_with_colour_codes_is_removed():
    log = f"\x1b[36mhomeassistant-1  |\x1b[0m {REAL_BLOCKING_LINE}\n"
    assert len(run(log)) == 1


@pytest.mark.parametrize(
    "stamp",
    [
        "2026-11-02T10:00:05.200",
        "2026-11-02T10:00:05.200Z",
        "2026-11-02 10:00:05.200+00:00",
        "2026-11-02 10:00:05",
    ],
)
def test_other_timestamp_forms(stamp):
    log = f"{stamp} ERROR (MainThread) [custom_components.home_keeper] boom\n"
    assert len(run(log)) == 1


def test_prefix_forms():
    line = "2026-11-02 10:00:05.200 ERROR (MainThread) [custom_components.home_keeper] boom"
    for prefix in ("ha-1 | ", "ha_test.1  |", "homeassistant  | "):
        assert len(run(prefix + line + "\n")) == 1


def test_cli_prints_log_sample_when_no_records(tmp_path):
    lines = [f"unknown format line {i} " + "x" * 300 for i in range(40)]
    result = _cli(tmp_path, "\n".join(lines) + "\n")
    assert result.returncode == 2
    assert "no Home Assistant log records found" in result.stderr
    assert "unknown format line 0 " in result.stderr
    assert "unknown format line 14 " in result.stderr
    assert "unknown format line 15 " not in result.stderr
    assert "unknown format line 24 " not in result.stderr
    assert "unknown format line 39 " in result.stderr
    # Every shown line is cut to 200 characters (plus the "  | " lead).
    shown = [ln for ln in result.stderr.splitlines() if ln.startswith("  | ")]
    assert len(shown) == 30
    assert all(len(ln) <= 5 + 200 for ln in shown)


def test_cli_empty_log_exits_2_without_sample_lines(tmp_path):
    result = _cli(tmp_path, "")
    assert result.returncode == 2
    assert "no Home Assistant log records found" in result.stderr


# ---------------------------------------------------------------------------
# Allowlist and grouped output
# ---------------------------------------------------------------------------


def _companion_line(name: str, stamp: str = "10:00:07.000") -> str:
    return (
        f"2026-11-02 {stamp} WARNING (MainThread) "
        "[custom_components.home_keeper.transfer_runner] "
        f"Companion '{name}' export failed: the database is locked"
    )


def _real_blocking_line(call: str) -> str:
    return REAL_BLOCKING_LINE.replace("to open with", f"to {call} with")


# A narrow entry like the ones in ci/ha_log_allowlist.txt: the logger, the full message.
ALLOW_TEXT = (
    "# A test companion fails its export on purpose.\n"
    r"\[custom_components\.home_keeper\.transfer_runner\] Companion 'dogs' "
    r"export failed: the database is locked" + "\n"
)


@pytest.fixture
def allow(tmp_path):
    path = tmp_path / "allow.txt"
    path.write_text(ALLOW_TEXT, encoding="utf-8")
    return check_ha_log.load_allowlist(path)


REAL_JOB_LOG = "\n".join(
    PREFIX + line
    for line in [
        "2026-11-02 10:00:00.100 INFO (MainThread) [homeassistant.bootstrap] Starting Home Assistant",
        _companion_line("dogs"),
        _companion_line("dogs", "10:00:08.000"),
        _companion_line("cats"),
        _real_blocking_line("read_text"),
        _real_blocking_line("open"),
    ]
)


def test_allowlist_hides_only_the_named_warning(allow):
    findings = run(REAL_JOB_LOG, allowlist=allow)
    assert len(findings) == 3
    assert not any("'dogs'" in f.text for f in findings)


def test_allowlist_does_not_hide_blocking_calls(allow):
    assert len(run(_real_blocking_line("open"), allowlist=allow)) == 1


def test_allowlist_is_narrow(allow):
    # Another companion with the same message shape is still reported.
    assert len(run(_companion_line("cats"), allowlist=allow)) == 1
    # Another message from the same logger is still reported.
    other = _companion_line("dogs").replace("the database is locked", "boom")
    assert len(run(other, allowlist=allow)) == 1
    # Another logger with the same text is still reported.
    same = _companion_line("dogs").replace("transfer_runner", "store")
    assert len(run(same, allowlist=allow)) == 1


def test_findings_are_grouped_by_rule_and_shape():
    groups = check_ha_log.group_findings(run(REAL_JOB_LOG))
    assert [len(g.findings) for g in groups] == [3, 1, 1]
    # The three companion warnings differ only in the quoted name.
    assert groups[0].rule.startswith("WARNING from logger")
    assert groups[1].shape != groups[2].shape


def test_report_has_summary_counts_examples_and_details():
    report = check_ha_log.format_report(run(REAL_JOB_LOG))
    summary, details = report.split("Details:")
    assert "5 problem(s) in 3 group(s)" in summary
    assert "1. 3 x WARNING from logger" in summary
    # Only the first two examples are shown for a group of three.
    assert summary.count("Companion 'dogs'") == 2
    assert "Companion 'cats'" not in summary
    starts = [ln for ln in details.splitlines() if ln.startswith("line ")]
    assert len(starts) == 5
    assert "Companion 'cats'" in details


def _run_cli(tmp_path, *extra):
    log = tmp_path / "ha.log"
    log.write_text(REAL_JOB_LOG + "\n")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--domain", "home_keeper", *extra, str(log)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_with_an_allowlist_leaves_the_rest(tmp_path):
    allow_file = tmp_path / "allow.txt"
    allow_file.write_text(ALLOW_TEXT, encoding="utf-8")
    result = _run_cli(tmp_path, "--allowlist", str(allow_file))
    assert result.returncode == 1
    assert "3 problem(s) in 3 group(s)" in result.stdout
    assert "Companion 'dogs'" not in result.stdout


def test_cli_prints_the_final_line_last_in_one_stream(tmp_path):
    result = _run_cli(tmp_path)
    assert result.returncode == 1
    assert result.stderr == ""
    lines = result.stdout.rstrip("\n").splitlines()
    assert lines[0].startswith("Summary:")
    assert lines.index("Details:") < len(lines) - 1
    assert lines[-1].endswith(
        "Fix them, or add a reason and a pattern to the allowlist."
    )
    assert "problem(s) found for 'home_keeper'" in lines[-1]


# ---------------------------------------------------------------------------
# The shipped allowlist hides only the deliberate test inputs
# ---------------------------------------------------------------------------

SHIPPED = check_ha_log.load_allowlist(SCRIPT.with_name("ha_log_allowlist.txt"))
FIXTURE_TASK = "acb13a18-979a-4812-8a00-2e4a426df8db"


def _unknown_device(task: str, device: str) -> str:
    return (
        f"{TS} WARNING (MainThread) [custom_components.home_keeper.coordinator] "
        f"Home Keeper task {task} references unknown device_id {device}; "
        "falling back to a self-owned device\n"
    )


def test_shipped_allowlist_has_a_reason_for_each_entry_and_none_is_broad():
    assert len(SHIPPED) > 0
    for entry in SHIPPED:
        assert entry.reason
        # Each entry names its logger, so none can hide a whole class of message.
        assert r"\[custom_components\.home_keeper" in entry.pattern.pattern


def test_shipped_allowlist_hides_a_probe_device():
    log = _unknown_device(
        "11111111-2222-3333-4444-555555555555", "rename_probe_fake_device"
    )
    assert run(log, allowlist=SHIPPED) == []


def test_shipped_allowlist_hides_the_seeded_fixture_task():
    log = _unknown_device(FIXTURE_TASK, "5ff1f1bb41a19a763aa4ab750cd37c97")
    assert run(log, allowlist=SHIPPED) == []


def test_shipped_allowlist_reports_the_fixture_task_with_another_device():
    log = _unknown_device(FIXTURE_TASK, "b70e86128ced632224d29f01dee4b3af")
    assert len(run(log, allowlist=SHIPPED)) == 1


def test_shipped_allowlist_still_reports_another_unknown_device():
    other_task = _unknown_device(
        "11111111-2222-3333-4444-555555555555", "someone_elses_device"
    )
    other_device = _unknown_device(
        "11111111-2222-3333-4444-555555555555", "rename_probe_fake_device_2"
    )
    assert len(run(other_task, allowlist=SHIPPED)) == 1
    assert len(run(other_device, allowlist=SHIPPED)) == 1


def test_shipped_allowlist_never_hides_a_blocking_call():
    assert len(run(REAL_BLOCKING_LINE, allowlist=SHIPPED)) == 1


# ---------------------------------------------------------------------------
# A stale allowlist entry fails the gate
# ---------------------------------------------------------------------------

STALE_ALLOW = (
    "# The companion fails on purpose.\n"
    r"\[custom_components\.home_keeper\.transfer_runner\] Companion 'dogs'" + "\n"
    "\n"
    "# lane: noise\n"
    "# Only the noise lane shows this one.\n"
    r"\[custom_components\.home_keeper\.store\] noise only" + "\n"
    "\n"
    "# lane: integration, noise\n"
    "# A line that never appears.\n"
    r"\[custom_components\.home_keeper\.store\] never logged" + "\n"
)


@pytest.fixture
def stale_allow(tmp_path):
    path = tmp_path / "allow.txt"
    path.write_text(STALE_ALLOW, encoding="utf-8")
    return path, check_ha_log.load_allowlist(path)


def test_an_entry_reads_its_lanes_and_defaults_to_integration(stale_allow):
    _, entries = stale_allow
    assert [e.lanes for e in entries] == [
        ("integration",),
        ("noise",),
        ("integration", "noise"),
    ]
    assert [e.reason for e in entries][1] == "Only the noise lane shows this one."


def test_an_entry_that_hid_a_finding_is_used_and_one_that_hid_nothing_is_stale(
    stale_allow,
):
    _, entries = stale_allow
    used: set[int] = set()
    records = check_ha_log.parse_records(_companion_line("dogs").splitlines())
    assert check_ha_log.check_records(records, "home_keeper", entries, used) == []
    assert used == {0}
    stale = check_ha_log.stale_entries(entries, used, "integration")
    assert [e.line_no for e in stale] == [entries[2].line_no]


def test_an_entry_of_another_lane_is_not_stale_here(stale_allow):
    _, entries = stale_allow
    stale = check_ha_log.stale_entries(entries, {0, 2}, "integration")
    assert stale == []
    assert [
        e.line_no for e in check_ha_log.stale_entries(entries, {0, 2}, "noise")
    ] == [entries[1].line_no]


def test_an_entry_that_matches_a_record_that_is_no_finding_is_stale(tmp_path):
    # The text is in the log, but the record is an INFO line: the entry hid nothing.
    path = tmp_path / "allow.txt"
    path.write_text("# Reason.\n\\[custom_components\\.home_keeper\\] hello\n")
    entries = check_ha_log.load_allowlist(path)
    used: set[int] = set()
    log = f"{TS} INFO (MainThread) [custom_components.home_keeper] hello\n"
    records = check_ha_log.parse_records(log.splitlines())
    check_ha_log.check_records(records, "home_keeper", entries, used)
    assert len(check_ha_log.stale_entries(entries, used, "integration")) == 1


def _lane_cli(tmp_path, allow_path, *extra):
    log = tmp_path / "ha.log"
    log.write_text(CLEAN_LOG + _companion_line("dogs") + "\n")
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--domain",
            "home_keeper",
            "--allowlist",
            str(allow_path),
            *extra,
            str(log),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_fails_on_a_stale_entry_of_its_lane(tmp_path, stale_allow):
    path, _ = stale_allow
    result = _lane_cli(tmp_path, path, "--lane", "integration")
    assert result.returncode == 1
    assert "1 stale allowlist entry(ies) for lane 'integration'" in result.stdout
    assert "A line that never appears." in result.stdout
    assert "Only the noise lane" not in result.stdout


def test_cli_without_a_lane_does_not_check_for_stale_entries(tmp_path, stale_allow):
    path, _ = stale_allow
    result = _lane_cli(tmp_path, path)
    assert result.returncode == 0, result.stdout


def test_cli_passes_when_each_entry_of_the_lane_was_used(tmp_path):
    path = tmp_path / "allow.txt"
    path.write_text(STALE_ALLOW.split("\n\n")[0] + "\n", encoding="utf-8")
    result = _lane_cli(tmp_path, path, "--lane", "integration")
    assert result.returncode == 0, result.stdout
    assert "OK" in result.stdout


def test_cli_reports_findings_and_stale_entries_together(tmp_path, stale_allow):
    path, _ = stale_allow
    log = tmp_path / "ha.log"
    log.write_text(CLEAN_LOG + _companion_line("cats") + "\n")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--domain",
            "home_keeper",
            "--allowlist",
            str(path),
            "--lane",
            "integration",
            str(log),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "1 problem(s) found" in result.stdout
    assert "stale allowlist entry(ies)" in result.stdout


def test_a_reason_can_span_comment_lines(tmp_path):
    path = tmp_path / "allow.txt"
    path.write_text(
        "# First half of the reason.\n# Second half.\n"
        r"\[custom_components\.home_keeper\] x" + "\n"
    )
    (entry,) = check_ha_log.load_allowlist(path)
    assert entry.reason == "First half of the reason. Second half."
