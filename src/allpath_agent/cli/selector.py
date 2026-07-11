from __future__ import annotations

import sys
from collections.abc import Sequence


def terminal_select(title: str, items: Sequence[str], searchable: bool = False) -> int | None:
    if not items or not sys.stdin.isatty() or not sys.stdout.isatty():
        return None
    try:
        import curses
    except ImportError:
        return None

    def run(screen) -> int | None:
        curses.curs_set(0)
        cursor = 0
        offset = 0
        query = ""
        searching = False
        while True:
            visible = [
                (index, label)
                for index, label in enumerate(items)
                if not query or query.lower() in label.lower()
            ]
            if not visible:
                cursor = 0
            else:
                cursor = min(cursor, len(visible) - 1)
            height, width = screen.getmaxyx()
            page_size = max(1, height - 4)
            offset = min(offset, max(0, len(visible) - page_size))
            if cursor < offset:
                offset = cursor
            elif cursor >= offset + page_size:
                offset = cursor - page_size + 1

            screen.erase()
            screen.addnstr(0, 0, title, max(1, width - 1), curses.A_BOLD)
            hint = "↑↓ move  Enter select  Esc cancel"
            if searchable:
                hint += "  / search"
            screen.addnstr(1, 0, hint, max(1, width - 1), curses.A_DIM)
            if searching or query:
                screen.addnstr(2, 0, f"Search: {query}", max(1, width - 1), curses.A_DIM)
            for row, (_, label) in enumerate(visible[offset : offset + page_size], start=3):
                selected = offset + row - 3 == cursor
                prefix = "→ " if selected else "  "
                screen.addnstr(
                    row,
                    0,
                    prefix + label,
                    max(1, width - 1),
                    curses.A_REVERSE if selected else curses.A_NORMAL,
                )
            screen.refresh()
            key = screen.get_wch()
            if searching:
                if key in ("\n", "\r", curses.KEY_ENTER, "\x1b"):
                    searching = False
                elif key in ("\b", "\x7f", curses.KEY_BACKSPACE):
                    query = query[:-1]
                    cursor = 0
                elif isinstance(key, str) and key.isprintable():
                    query += key
                    cursor = 0
                continue
            if key in (curses.KEY_UP, "k") and visible:
                cursor = (cursor - 1) % len(visible)
            elif key in (curses.KEY_DOWN, "j") and visible:
                cursor = (cursor + 1) % len(visible)
            elif key in ("\n", "\r", curses.KEY_ENTER) and visible:
                return visible[cursor][0]
            elif key in ("\x1b", "q"):
                return None
            elif searchable and key == "/":
                searching = True

    try:
        return curses.wrapper(run)
    except (curses.error, KeyboardInterrupt):
        return None
