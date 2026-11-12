"""Minimal S-expression reader/writer for KiCad files (no external dependencies)."""
from __future__ import annotations

import re
from typing import Any

_TOKEN = re.compile(r'\s*(?:(\()|(\))|("(?:[^"\\]|\\.)*")|([^\s()"]+))', re.S)


class Sym(str):
    """An unquoted atom (keyword / number) as opposed to a quoted string."""


def parse(text: str) -> Any:
    stack: list[list] = [[]]
    pos = 0
    n = len(text)
    while pos < n:
        m = _TOKEN.match(text, pos)
        if not m:
            if text[pos:].strip() == "":
                break
            raise ValueError(f"bad token at {pos}: {text[pos:pos + 40]!r}")
        pos = m.end()
        lpar, rpar, qstr, atom = m.groups()
        if lpar:
            stack.append([])
        elif rpar:
            node = stack.pop()
            stack[-1].append(node)
        elif qstr is not None:
            stack[-1].append(_unescape(qstr[1:-1]) if "\\" in qstr else qstr[1:-1])
        elif atom is not None:
            stack[-1].append(Sym(atom))
    return stack[0][0] if len(stack[0]) == 1 else stack[0]


def _unescape(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            out.append({"n": "\n", "t": "\t", "\\": "\\", '"': '"'}.get(nxt, "\\" + nxt))
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def q(s: str) -> str:
    s = str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return '"' + s + '"'


def dump(node: Any, indent: int = 0) -> str:
    """Pretty-print close to KiCad's own formatting (tabs, one child list per line)."""
    if isinstance(node, Sym):
        return str(node)
    if isinstance(node, str):
        return q(node)
    if isinstance(node, (int, float)):
        return fmt_num(node)
    if not node:
        return "()"
    # the head of a KiCad list is always a bare keyword
    head = str(node[0]) if isinstance(node[0], str) else dump(node[0], indent)
    simple = all(not isinstance(c, list) for c in node[1:])
    if simple:
        return "(" + " ".join([head] + [dump(c, indent) for c in node[1:]]) + ")"
    out = "(" + head
    pending_atoms: list[str] = []
    for c in node[1:]:
        if isinstance(c, list):
            if pending_atoms:
                out += " " + " ".join(pending_atoms)
                pending_atoms = []
            out += "\n" + "\t" * (indent + 1) + dump(c, indent + 1)
        else:
            pending_atoms.append(dump(c, indent + 1))
    if pending_atoms:
        out += " " + " ".join(pending_atoms)
    out += "\n" + "\t" * indent + ")"
    return out


def fmt_num(x: float) -> str:
    if isinstance(x, int):
        return str(x)
    s = f"{x:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def find(node: list, key: str) -> list | None:
    for c in node[1:] if node and isinstance(node[0], str) else node:
        if isinstance(c, list) and c and c[0] == key:
            return c
    return None


def find_all(node: list, key: str) -> list[list]:
    return [c for c in node if isinstance(c, list) and c and c[0] == key]
