"""Data model of the DBMS-Lab example catalog."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Param:
    name: str
    label: str
    type: str = "int"            # int | decimal | text
    default: object = None
    min: float | None = None
    max: float | None = None
    max_length: int = 100


@dataclass(frozen=True)
class Step:
    title: str
    sql: str
    role: str = "main"           # setup | before | main | after | restore
    conn: str | None = None      # account key; None = the example's own account.
                                 # Keys: reader | lab | dcl | demo ; suffix '#2' = a second session
    expect_error: bool = False   # the step demonstrates a rejection (constraint, privilege, ...)
    ignore_errors: tuple[int, ...] = ()   # MySQL errnos that only mean "nothing to do"
    repeat: int = 1              # >1 = timed step: 1 warm-up run + `repeat` measured runs
    timing_group: str | None = None       # 'before' / 'after' for index comparisons
    compare: str | None = None   # steps with the same key are shown side by side
    note: str = ""


@dataclass(frozen=True)
class Example:
    id: str
    category: str
    title: str
    description: str
    explanation: str
    steps: tuple[Step, ...]
    target: str = "lab"          # main | lab  (which database the example runs against)
    account: str = "lab"         # reader | lab | dcl
    params: tuple[Param, ...] = ()
    cleanup: tuple[Step, ...] = ()
    destructive: bool = False    # needs explicit confirmation before running
    min_role: str = "FACULTY"    # FACULTY | ADMIN
    tags: tuple[str, ...] = field(default_factory=tuple)

    def public(self) -> dict:
        return {
            "id": self.id, "category": self.category, "title": self.title,
            "description": self.description, "explanation": self.explanation,
            "target": self.target, "account": self.account, "destructive": self.destructive,
            "min_role": self.min_role, "has_cleanup": bool(self.cleanup), "tags": list(self.tags),
            "params": [p.__dict__ for p in self.params],
            "steps": [{"title": s.title, "sql": s.sql, "role": s.role, "conn": s.conn or self.account,
                       "expect_error": s.expect_error, "repeat": s.repeat, "compare": s.compare,
                       "note": s.note} for s in self.steps],
            "cleanup": [{"title": s.title, "sql": s.sql} for s in self.cleanup],
        }
