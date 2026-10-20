"""Pure tests for fresh logical-cell matching from fragmented terminal output."""

import pyte  # The dev extra pins the parser; absence is a test-environment failure.
import pytest
import threading
from types import SimpleNamespace

from tests.fixtures.hermes_terminal_screen import TerminalScreen
from tests.fixtures.hermes_tui_driver import TuiConsole


@pytest.mark.parametrize("baseline,redraw,expected", [
    ("Optional memory is absXnt.", "Optional memory is ab\x1b[1Cent.", "Optional memory is absent."),
    ("Completed rememXer.", "Completed rem\x1b[2Cber.", "Completed remember."),
])
def test_cursor_forward_preserves_saved_cells_in_visible_text(baseline, redraw, expected):
    screen = TerminalScreen(80, 5)
    screen.feed(baseline + "\r")
    mark = screen.mark(26)
    screen.feed(redraw)

    assert expected in screen.rendered
    assert screen.contains(expected, after=mark)


def test_fragmented_csi_and_osc_keep_parser_state():
    screen = TerminalScreen(80, 5)
    mark = screen.mark(0)
    for chunk in ("\x1b]0;old title\x1b", "\\old visible", "\r\x1b[2", "Knew session", " started"):
        screen.feed(chunk)

    assert "old title" not in screen.rendered
    assert screen.contains("new session started", after=mark)


def test_clear_and_same_text_redraw_in_one_feed_is_fresh():
    screen = TerminalScreen(80, 5)
    screen.feed("new session started\r")
    mark = screen.mark(20)
    screen.feed("\x1b[2Knew session started")

    assert screen.contains("new session started", after=mark)


def test_unchanged_old_text_and_unrelated_repaint_do_not_satisfy_mark():
    screen = TerminalScreen(80, 5)
    screen.feed("old session started\n")
    mark = screen.mark(20)
    screen.feed("unrelated repaint")

    assert "old session started" in screen.rendered
    assert not screen.contains("old session started", after=mark)


def test_missing_text_and_unmarked_cursor_fail_closed():
    screen = TerminalScreen(80, 5)
    mark = screen.mark(0)
    screen.feed("provider refused\r\n")

    assert not screen.contains("assistant answered", after=mark)
    assert not screen.contains("provider refused", after=999)


def test_unicode_text_uses_logical_cells_including_wide_and_modifier_chars():
    screen = TerminalScreen(80, 5)
    mark = screen.mark(0)
    screen.feed("Grüße 日本語 😂👍🏽")

    assert screen.contains("Grüße 日本語 😂👍🏽", after=mark)


def test_overwritten_wide_glyph_keeps_orphan_cell_column():
    screen = TerminalScreen(80, 5)
    screen.feed("界Z")
    mark = screen.mark(2)
    screen.feed("\x1b[1Gx")

    assert screen.rendered.startswith("x Z")
    assert "xZ" not in screen.rendered
    assert screen.contains("x Z", after=mark)


def test_frame_and_mark_limits_fail_closed_for_expired_cursors():
    screen = TerminalScreen(80, 5, frame_limit=2, mark_limit=2)
    expired_frame = screen.mark(1)
    screen.feed("first\r")
    screen.feed("second\r")
    screen.feed("third\r")
    assert not screen.contains("third", after=expired_frame)

    expired_mark = screen.mark(10)
    screen.mark(11)
    screen.mark(12)
    assert not screen.contains("third", after=expired_mark)


def test_unmarked_wait_checks_current_screen_after_history_expires():
    screen = TerminalScreen(80, 5, frame_limit=2, mark_limit=2)
    for index in range(5):
        screen.mark(index + 1)
        screen.feed(f"\r\x1b[2Kvisible {index}")
    assert screen.contains("visible 4")
    assert not screen.contains("visible 0")


def test_console_matches_screen_without_changing_raw_capture(tmp_path):
    console = TuiConsole.__new__(TuiConsole)
    console.parts = []
    console._init_screen_observer()
    console.stopped = threading.Event()
    console.tree = SimpleNamespace(error=None)
    console.proc = SimpleNamespace(isalive=lambda: True, cancel_io=lambda: None)
    console.reader = SimpleNamespace(join=lambda timeout: None)
    console.artifacts = tmp_path
    console.feed_output("Completed rememXer.\r")
    mark = console.mark()
    console.feed_output("Completed rem\x1b[2Cber.")
    console.wait("Completed remember.", after=mark, timeout=1)
    raw = "Completed rememXer.\rCompleted rem\x1b[2Cber."
    assert console.raw_text == raw
    console.close()
    assert (tmp_path / "terminal.txt").read_bytes() == raw.encode("utf-8")
    assert (tmp_path / "terminal-screen.txt").read_text(encoding="utf-8") == "Completed remember."
