"""Source adapters for the experimental static compiler.

The pak dump already arrives in this repository as BinData JSON.  Those
JSON files are treated as extracted pak source data, not as hand-authored
rules.  Lua is parsed only for static declarations such as ``Enum.*``
tables; no Lua code is executed.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PAK_DATA_DIR = ROOT / "pak-public-kit" / "output" / "data"
DEFAULT_LUA_ROOT = ROOT / "pak-public-kit" / "output" / "scripts" / "lua"


@dataclass(frozen=True)
class SourceDigest:
    path: Path
    sha256: str
    size: int


def file_digest(path: Path) -> SourceDigest:
    data = path.read_bytes()
    return SourceDigest(path=path, sha256=hashlib.sha256(data).hexdigest(), size=len(data))


def stable_source_name(path: Path, root: Path = ROOT) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def combined_source_hash(files: Iterable[Path], root: Path = ROOT) -> str:
    h = hashlib.sha256()
    for path in sorted({p.resolve() for p in files}, key=lambda p: str(p)):
        digest = file_digest(path)
        h.update(stable_source_name(path, root).encode("utf-8"))
        h.update(b"\0")
        h.update(digest.sha256.encode("ascii"))
        h.update(b"\0")
        h.update(str(digest.size).encode("ascii"))
        h.update(b"\0")
    return h.hexdigest()


class PakSource:
    """Loader for extracted pak BinData tables."""

    def __init__(self, data_dir: Path = DEFAULT_PAK_DATA_DIR):
        self.data_dir = Path(data_dir)
        self.bin_dir = self.data_dir if self.data_dir.name == "BinData" else self.data_dir / "BinData"
        self._tables: dict[str, dict[int | str, dict[str, Any]]] = {}

    def table_path(self, table_name: str) -> Path:
        filename = table_name if table_name.endswith(".json") else f"{table_name}.json"
        return self.bin_dir / filename

    def table(self, table_name: str) -> dict[int | str, dict[str, Any]]:
        key = table_name.removesuffix(".json")
        if key in self._tables:
            return self._tables[key]
        path = self.table_path(table_name)
        with path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
        rows = data.get("RocoDataRows", data) if isinstance(data, dict) else data
        if not isinstance(rows, dict):
            raise ValueError(f"unexpected pak table shape: {path}")
        normalized = {_coerce_key(k): v for k, v in rows.items()}
        self._tables[key] = normalized
        return normalized

    def source_file(self, table_name: str) -> Path:
        path = self.table_path(table_name)
        if not path.exists():
            raise FileNotFoundError(f"missing pak table: {path}")
        return path


def _coerce_key(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


_ENUM_ASSIGN_RE = re.compile(r"\bEnum\.(?P<name>[A-Za-z_]\w*)\s*=\s*setmetatable\s*\(")
_ENUM_ENTRY_RE = re.compile(r"\b(?P<key>[A-Za-z_]\w*)\s*=\s*(?P<value>-?\d+)\b")
_ENUM_REF_RE = re.compile(r"\b(?:_G\.)?(?:Enum|ProtoEnum)\.(?P<enum>[A-Za-z_]\w*)\.(?P<member>[A-Za-z_]\w*)\b")


def parse_lua_enums(text: str, wanted: set[str] | None = None) -> dict[str, dict[str, int]]:
    """Parse ``Enum.NAME = setmetatable({ KEY = INT, ... }, EnumMeta)`` blocks."""
    out: dict[str, dict[str, int]] = {}
    pos = 0
    while True:
        match = _ENUM_ASSIGN_RE.search(text, pos)
        if match is None:
            return out
        enum_name = match.group("name")
        brace_pos = text.find("{", match.end())
        if brace_pos < 0:
            raise ValueError(f"Enum.{enum_name} has no table body")
        body, end_pos = _read_lua_braced_body(text, brace_pos)
        pos = end_pos
        if wanted is not None and enum_name not in wanted:
            continue
        out[enum_name] = _parse_lua_enum_body(enum_name, body)


def collect_enum_references(
    lua_root: Path,
    enum_names: Iterable[str],
    *,
    roots: Iterable[str] = ("Common", "NewRoco/Modules/Core/Battle"),
) -> dict[str, dict[str, int]]:
    """Count static ``Enum.X.Y`` / ``ProtoEnum.X.Y`` references in Lua files."""
    wanted = set(enum_names)
    counts: dict[str, Counter[str]] = {name: Counter() for name in wanted}
    for rel_root in roots:
        root = lua_root / rel_root
        if not root.exists():
            continue
        for path in root.rglob("*.lua"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for match in _ENUM_REF_RE.finditer(text):
                enum_name = match.group("enum")
                if enum_name in wanted:
                    counts[enum_name][match.group("member")] += 1
    return {name: dict(sorted(counter.items())) for name, counter in sorted(counts.items())}


class LuaEnumSource:
    """Parser facade for the extracted Lua tree."""

    def __init__(self, lua_root: Path = DEFAULT_LUA_ROOT):
        self.lua_root = Path(lua_root)
        self.enum_path = self.lua_root / "Data" / "Config" / "Enum.lua"
        self._all_enums: dict[str, dict[str, int]] | None = None

    def enums(self, names: Iterable[str] | None = None) -> dict[str, dict[str, int]]:
        if self._all_enums is None:
            text = self.enum_path.read_text(encoding="utf-8")
            self._all_enums = parse_lua_enums(text)
        if names is None:
            return dict(self._all_enums)
        wanted = set(names)
        missing = sorted(wanted - set(self._all_enums))
        if missing:
            raise KeyError(f"Lua Enum.lua missing expected enums: {missing}")
        return {name: self._all_enums[name] for name in sorted(wanted)}

    def source_file(self) -> Path:
        if not self.enum_path.exists():
            raise FileNotFoundError(f"missing Lua enum source: {self.enum_path}")
        return self.enum_path

    def enum_references(self, names: Iterable[str]) -> dict[str, dict[str, int]]:
        return collect_enum_references(self.lua_root, names)


def _read_lua_braced_body(text: str, brace_pos: int) -> tuple[str, int]:
    if text[brace_pos] != "{":
        raise ValueError("brace_pos must point at an opening brace")
    depth = 0
    body_start = brace_pos + 1
    i = brace_pos
    quote: str | None = None
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if quote is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            i += 1
            continue
        if ch == "-" and nxt == "-":
            line_end = text.find("\n", i + 2)
            i = len(text) if line_end < 0 else line_end + 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[body_start:i], i + 1
        i += 1
    raise ValueError("unterminated Lua table body")


def _parse_lua_enum_body(enum_name: str, body: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for match in _ENUM_ENTRY_RE.finditer(body):
        key = match.group("key")
        value = int(match.group("value"))
        if key in values:
            raise ValueError(f"Enum.{enum_name} declares {key!r} more than once")
        values[key] = value
    if not values:
        raise ValueError(f"Enum.{enum_name} has no integer entries")
    return values
