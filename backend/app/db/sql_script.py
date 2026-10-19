"""SQL script tokenizer.

Splits SQL text into individual statements while respecting quotes,
backticks, comments and the mysql-client DELIMITER command (needed for
triggers and stored programs, whose bodies contain ';').

Used by the database initializer, the lab reset and the free-form SQL policy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_DELIMITER_LINE = re.compile(r"DELIMITER[ \t]+(\S+)[ \t]*(?:\r?\n|$)", re.IGNORECASE)


@dataclass
class Statement:
    sql: str          # statement text without the trailing delimiter, comments removed
    line: int         # 1-based line where it starts (for error messages)


def split_statements(text: str, *, allow_delimiter_command: bool = True) -> list[Statement]:
    statements: list[Statement] = []
    delimiter = ";"
    buf: list[str] = []
    has_content = False   # buf holds more than whitespace
    start_line = 1
    line = 1
    i = 0
    n = len(text)

    def flush() -> None:
        nonlocal has_content
        sql = "".join(buf).strip()
        if sql:
            statements.append(Statement(sql, start_line))
        buf.clear()
        has_content = False

    while i < n:
        ch = text[i]

        # DELIMITER command — only valid at the start of a statement
        if allow_delimiter_command and not has_content and text[i:i + 9].upper() == "DELIMITER":
            match = _DELIMITER_LINE.match(text, i)
            if match:
                delimiter = match.group(1)
                line += match.group(0).count("\n")
                i = match.end()
                buf.clear()
                continue

        if not has_content:
            start_line = line

        # comments
        if ch == "#" or (text.startswith("--", i) and (i + 2 >= n or text[i + 2] in " \t\r\n")):
            end = text.find("\n", i)
            i = n if end == -1 else end
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end == -1:
                raise ValueError(f"Unterminated /* comment starting on line {line}")
            line += text.count("\n", i, end + 2)
            buf.append(" ")
            i = end + 2
            continue

        # quoted strings / identifiers
        if ch in ("'", '"', "`"):
            j = i + 1
            while j < n:
                c = text[j]
                if c == "\\" and ch != "`":
                    j += 2
                    continue
                if c == ch:
                    if j + 1 < n and text[j + 1] == ch:  # doubled quote escape
                        j += 2
                        continue
                    break
                j += 1
            if j >= n:
                raise ValueError(f"Unterminated quoted text starting on line {line}")
            chunk = text[i:j + 1]
            buf.append(chunk)
            has_content = True
            line += chunk.count("\n")
            i = j + 1
            continue

        # statement terminator
        if text.startswith(delimiter, i):
            flush()
            i += len(delimiter)
            continue

        if ch == "\n":
            line += 1
        elif not ch.isspace():
            has_content = True
        buf.append(ch)
        i += 1

    flush()
    return statements


def load_script(path: Path) -> list[Statement]:
    return split_statements(path.read_text(encoding="utf-8"))


_LEADING_WORDS = re.compile(r"[A-Za-z_]+")


def leading_keywords(sql: str, count: int = 3) -> list[str]:
    """First `count` keywords of a statement, upper-cased (comments already removed)."""
    return [w.upper() for w in _LEADING_WORDS.findall(sql[:200])[:count]]
