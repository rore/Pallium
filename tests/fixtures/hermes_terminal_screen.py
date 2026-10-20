"""Bounded logical-screen observer for the released Hermes terminal UI."""
from __future__ import annotations

from collections import OrderedDict, deque


class TerminalScreen:
    """Apply VT text output to a pyte screen and match only fresh visible text."""

    def __init__(self, columns: int, lines: int, *, frame_limit: int = 1024, mark_limit: int = 64):
        import pyte

        self._frames = deque(maxlen=frame_limit)
        self._marks = OrderedDict()
        self._mark_limit = mark_limit
        self._sequence = 0
        self._initialized = False

        class ObservedScreen(pyte.Screen):
            def draw(inner, data):
                super().draw(data)
                observer._changed(inner)

            def erase_in_display(inner, *args, **kwargs):
                super().erase_in_display(*args, **kwargs)
                observer._changed(inner)

            def erase_in_line(inner, *args, **kwargs):
                super().erase_in_line(*args, **kwargs)
                observer._changed(inner)

            def reset(inner):
                super().reset()
                observer._changed(inner)

        observer = self
        self.screen = ObservedScreen(columns, lines)
        self.stream = pyte.Stream(self.screen)
        self._initialized = True
        self._frames.append((self._sequence, self.rendered))
        self.mark(0)

    @property
    def rendered(self) -> str:
        return "\n".join(line.rstrip() for line in self.screen.display).rstrip()

    def _changed(self, screen):
        if not self._initialized:
            return
        rendered = "\n".join(line.rstrip() for line in screen.display).rstrip()
        if self._frames and self._frames[-1][1] == rendered:
            return
        self._sequence += 1
        self._frames.append((self._sequence, rendered))

    def feed(self, chunk: str):
        self.stream.feed(chunk)

    def mark(self, raw_end: int) -> int:
        """Return a raw-output cursor and retain its screen baseline for freshness checks."""
        self._marks[raw_end] = (self._sequence, self.rendered)
        self._marks.move_to_end(raw_end)
        while len(self._marks) > self._mark_limit:
            self._marks.popitem(last=False)
        return raw_end

    def contains(self, expected: str, *, after: int = 0) -> bool:
        if not expected:
            return False
        if after == 0:
            return expected in self.rendered
        marker = self._marks.get(after)
        if marker is None:
            return False
        start_sequence, baseline = marker
        if not self._frames or start_sequence < self._frames[0][0]:
            return False
        baseline_count = baseline.count(expected)
        current_count = self.rendered.count(expected)
        if not current_count:
            return False
        disappeared = baseline_count == 0
        for sequence, frame in self._frames:
            if sequence <= start_sequence:
                continue
            if frame.count(expected) == 0:
                disappeared = True
        return current_count > baseline_count or disappeared
