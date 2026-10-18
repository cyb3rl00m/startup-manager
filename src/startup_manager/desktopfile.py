"""Minimal, round-trip-safe reader/writer for freedesktop .desktop files.

GLib.KeyFile would work too, but keeping this in plain Python means the core
logic can be unit-tested without GTK, and files we rewrite keep their original
order, comments and localized keys.
"""

from __future__ import annotations

import locale
import os
import re

MAIN_GROUP = "Desktop Entry"

_GROUP_RE = re.compile(r"^\[(?P<name>[^\[\]]+)\]\s*$")
_KEY_RE = re.compile(r"^(?P<key>[A-Za-z0-9-]+(?:\[[^\]]+\])?)\s*=\s?(?P<value>.*)$")


def unescape(value: str) -> str:
    """Decode the escape sequences allowed in desktop-file string values."""
    out = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            out.append({"s": " ", "n": "\n", "t": "\t", "r": "\r", "\\": "\\"}.get(nxt, "\\" + nxt))
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def escape(value: str) -> str:
    """Encode a string so it survives as a single desktop-file value."""
    value = value.replace("\\", "\\\\")
    value = value.replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")
    if value.startswith(" "):
        value = "\\s" + value[1:]
    return value


def quote_exec_arg(arg: str) -> str:
    """Quote one argument for an Exec= line (before string escaping).

    The spec requires double quotes around arguments containing reserved
    characters, and a backslash before `"`, `` ` ``, `$` and `\\` inside them.
    """
    reserved = set(" \t\n\"'\\><~|&;$*?#()`")
    if arg and not any(c in reserved for c in arg):
        return arg
    inner = "".join("\\" + c if c in '"`$\\' else c for c in arg)
    return f'"{inner}"'


def split_exec(exec_line: str) -> list[str]:
    """Split an (already unescaped) Exec value into arguments, per the spec."""
    args: list[str] = []
    cur: list[str] = []
    in_quotes = False
    have_arg = False
    i = 0
    while i < len(exec_line):
        ch = exec_line[i]
        if in_quotes:
            if ch == "\\" and i + 1 < len(exec_line) and exec_line[i + 1] in '"`$\\':
                cur.append(exec_line[i + 1])
                i += 2
                continue
            if ch == '"':
                in_quotes = False
            else:
                cur.append(ch)
        elif ch == '"':
            in_quotes = True
            have_arg = True
        elif ch in " \t":
            if cur or have_arg:
                args.append("".join(cur))
                cur, have_arg = [], False
        else:
            cur.append(ch)
        i += 1
    if cur or have_arg:
        args.append("".join(cur))
    return args


def strip_field_codes(exec_line: str) -> str:
    """Remove %f %U etc. so an Exec line can be shown or run as a command."""
    result = re.sub(r"\s*(?<!%)%[fFuUdDnNickvm]", "", exec_line)
    return result.replace("%%", "%").strip()


def _locale_candidates() -> list[str]:
    names = []
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var)
        if val:
            names.extend(val.split(":"))
            break
    if not names:
        try:
            loc = locale.getlocale()[0]
        except ValueError:
            loc = None
        if loc:
            names.append(loc)
    out: list[str] = []
    for name in names:
        name = name.split(".")[0].split("@")[0]
        if not name or name in ("C", "POSIX"):
            continue
        for cand in (name, name.split("_")[0]):
            if cand not in out:
                out.append(cand)
    return out


class DesktopFile:
    """A parsed .desktop file that remembers its original layout."""

    def __init__(self, text: str = "", path: str | None = None):
        self.path = path
        # Each group: [name, [line, ...]] where a line is ("kv", key, raw_value)
        # or ("raw", text) for comments/blank lines.
        self._header: list[tuple] = []
        self._groups: list[list] = []
        self._parse(text)

    # ----- parsing / serialising -------------------------------------------
    @classmethod
    def load(cls, path: str) -> "DesktopFile":
        with open(path, encoding="utf-8", errors="replace") as fh:
            return cls(fh.read(), path)

    def _parse(self, text: str) -> None:
        current: list[tuple] = self._header
        for line in text.splitlines():
            m = _GROUP_RE.match(line)
            if m:
                group = [m.group("name"), []]
                self._groups.append(group)
                current = group[1]
                continue
            stripped = line.strip()
            m = _KEY_RE.match(stripped) if stripped and not stripped.startswith("#") else None
            if m and current is not self._header:
                current.append(("kv", m.group("key"), m.group("value")))
            else:
                current.append(("raw", line))

    def to_text(self) -> str:
        parts: list[str] = [ln[1] for ln in self._header]
        for name, lines in self._groups:
            parts.append(f"[{name}]")
            for ln in lines:
                parts.append(f"{ln[1]}={ln[2]}" if ln[0] == "kv" else ln[1])
        text = "\n".join(parts).strip("\n")
        return text + "\n"

    def save(self, path: str | None = None) -> None:
        path = path or self.path
        if not path:
            raise ValueError("No path to save to")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(self.to_text())
        os.replace(tmp, path)
        self.path = path

    # ----- groups ----------------------------------------------------------
    def groups(self) -> list[str]:
        return [g[0] for g in self._groups]

    def _group(self, name: str, create: bool = False) -> list | None:
        for g in self._groups:
            if g[0] == name:
                return g[1]
        if create:
            g = [name, []]
            # The main group must come first.
            if name == MAIN_GROUP:
                self._groups.insert(0, g)
            else:
                self._groups.append(g)
            return g[1]
        return None

    def keep_only_main_group(self) -> None:
        self._groups = [g for g in self._groups if g[0] == MAIN_GROUP]

    # ----- keys ------------------------------------------------------------
    def has(self, key: str, group: str = MAIN_GROUP) -> bool:
        return self.get_raw(key, group) is not None

    def get_raw(self, key: str, group: str = MAIN_GROUP) -> str | None:
        lines = self._group(group)
        if lines is None:
            return None
        for ln in lines:
            if ln[0] == "kv" and ln[1] == key:
                return ln[2]
        return None

    def get(self, key: str, default: str | None = None, group: str = MAIN_GROUP) -> str | None:
        raw = self.get_raw(key, group)
        return unescape(raw) if raw is not None else default

    def get_localized(self, key: str, default: str | None = None, group: str = MAIN_GROUP) -> str | None:
        for loc in _locale_candidates():
            val = self.get(f"{key}[{loc}]", group=group)
            if val:
                return val
        return self.get(key, default, group)

    def get_bool(self, key: str, default: bool = False, group: str = MAIN_GROUP) -> bool:
        raw = self.get(key, group=group)
        if raw is None:
            return default
        return raw.strip().lower() in ("true", "1", "yes")

    def get_list(self, key: str, group: str = MAIN_GROUP) -> list[str]:
        raw = self.get(key, group=group)
        if not raw:
            return []
        return [item for item in re.split(r"(?<!\\);", raw) if item]

    def set_raw(self, key: str, raw_value: str, group: str = MAIN_GROUP) -> None:
        lines = self._group(group, create=True)
        for idx, ln in enumerate(lines):
            if ln[0] == "kv" and ln[1] == key:
                lines[idx] = ("kv", key, raw_value)
                return
        # Insert after the last key so trailing blank lines/comments stay last.
        insert_at = len(lines)
        while insert_at > 0 and lines[insert_at - 1][0] == "raw" and not lines[insert_at - 1][1].strip():
            insert_at -= 1
        lines.insert(insert_at, ("kv", key, raw_value))

    def set(self, key: str, value: str, group: str = MAIN_GROUP) -> None:
        self.set_raw(key, escape(value), group)

    def set_bool(self, key: str, value: bool, group: str = MAIN_GROUP) -> None:
        self.set_raw(key, "true" if value else "false", group)

    def remove(self, key: str, group: str = MAIN_GROUP, with_translations: bool = False) -> None:
        lines = self._group(group)
        if lines is None:
            return
        lines[:] = [
            ln for ln in lines
            if not (ln[0] == "kv" and (ln[1] == key or (with_translations and ln[1].startswith(key + "["))))
        ]
