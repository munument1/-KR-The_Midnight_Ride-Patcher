"""Core MO2/TMR inventory helpers for the unofficial Korean patcher."""
from __future__ import annotations

import configparser
import hashlib
import json
from pathlib import Path
import re

VERSION = "1.0.2"
PLUGIN_SUFFIXES = {".esm", ".esp", ".esl"}
LOOSE_PREFIXES = ("mcm/", "interface/translations/", "interface/")


def qt_value(value: str) -> str:
    value = (value or "").strip()
    match = re.fullmatch(r"@ByteArray\((.*)\)", value, re.DOTALL)
    if match:
        value = match.group(1)
    return value.replace("\\\\", "\\")


def list_lines(path: Path, encoding: str = "utf-8-sig") -> list[str]:
    if not path.is_file():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding=encoding, errors="replace").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def safe_relative(value: str) -> str:
    value = value.replace("\\", "/").strip("/")
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe relative path: {value!r}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Installation:
    def __init__(self, root: Path, profile: str | None = None, game_dir: Path | None = None):
        self.root = root.resolve()
        ini = self.root / "ModOrganizer.ini"
        if not ini.is_file():
            raise ValueError(f"ModOrganizer.ini is missing: {self.root}")

        config = configparser.ConfigParser(interpolation=None, strict=False)
        config.read_string(ini.read_text(encoding="utf-8-sig", errors="replace"))
        general = config["General"]
        game_name = qt_value(general.get("gameName", "")).casefold()
        if game_name not in {"fallout 4", "fallout4"}:
            raise ValueError(f"This is not a Fallout 4 MO2 instance: {game_name!r}")

        settings = config["Settings"] if config.has_section("Settings") else {}
        base_value = qt_value(settings.get("base_directory", str(self.root)))
        base_value = base_value.replace("%BASE_DIR%", str(self.root))
        base_path = Path(base_value)
        self.base = (base_path if base_path.is_absolute() else self.root / base_path).resolve()

        def configured(key: str, default: str) -> Path:
            value = qt_value(settings.get(key, default)).replace("%BASE_DIR%", str(self.base))
            path = Path(value)
            return (path if path.is_absolute() else self.root / path).resolve()

        self.mods = configured("mod_directory", "%BASE_DIR%/mods")
        self.profiles = configured("profiles_directory", "%BASE_DIR%/profiles")
        self.overwrite = configured("overwrite_directory", "%BASE_DIR%/overwrite")

        selected = profile or qt_value(general.get("selected_profile", ""))
        if not selected or Path(selected).name != selected or selected in {".", ".."}:
            raise ValueError("A valid MO2 profile is required")
        self.profile = selected
        self.profile_dir = (self.profiles / selected).resolve()
        if not self.profile_dir.is_dir():
            raise ValueError(f"MO2 profile is missing: {self.profile_dir}")

        configured_game = qt_value(general.get("gamePath", ""))
        if not game_dir and not configured_game:
            raise ValueError("MO2 gamePath is absent")
        self.game = (game_dir or Path(configured_game)).resolve()
        self.data = self.game / "Data"
        if not (self.data / "Fallout4.esm").is_file():
            raise ValueError(f"Fallout4.esm is missing: {self.data}")

        self.providers: dict[str, list[dict]] = {}
        self.enabled_mods: list[str] = []
        self.warnings: list[str] = []
        self.scan()

    def add_tree(self, root: Path, provider: str):
        if not root.is_dir():
            self.warnings.append(f"Provider directory is missing: {root}")
            return
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            suffix = path.suffix.casefold()
            lower = relative.casefold()
            if suffix in PLUGIN_SUFFIXES and "/" not in relative:
                category = "plugin"
            elif lower.startswith(LOOSE_PREFIXES) and suffix in {".json", ".ini", ".txt", ".xml"}:
                category = "loose_text_candidate"
            else:
                continue
            key = safe_relative(relative).casefold()
            self.providers.setdefault(key, []).append({
                "path": relative,
                "provider": provider,
                "physical": str(path.resolve()),
                "category": category,
            })

    def scan(self):
        self.add_tree(self.data, "game:Data")

        # MO2 stores highest-priority enabled mods first in modlist.txt.
        modlist = list_lines(self.profile_dir / "modlist.txt")
        for line in reversed(modlist):
            if line.startswith("+") and not line.endswith("_separator"):
                name = safe_relative(line[1:])
                if "/" in name:
                    raise ValueError(f"Invalid MO2 mod name: {name}")
                self.enabled_mods.append(name)
                self.add_tree(self.mods / name, name)

        if self.overwrite.is_dir():
            self.add_tree(self.overwrite, "MO2:overwrite")

        loadorder = list_lines(self.profile_dir / "loadorder.txt")
        plugin_lines = list_lines(self.profile_dir / "plugins.txt")

        starred = [line[1:] for line in plugin_lines if line.startswith("*")]
        if loadorder:
            active = loadorder
        else:
            active = starred
            self.warnings.append("loadorder.txt is absent; using starred plugins.txt entries")

        active = [safe_relative(name) for name in active]
        if any("/" in name or Path(name).suffix.casefold() not in PLUGIN_SUFFIXES for name in active):
            raise ValueError("Invalid plugin name in active load order")
        if len({name.casefold() for name in active}) != len(active):
            raise ValueError("Duplicate active plugin names")

        self.active = active
        self.active_keys = {name.casefold() for name in active}
        for name in active:
            if name.casefold() not in self.providers:
                self.warnings.append(f"Active plugin has no loose provider: {name}")

    def source(self, relative: str) -> Path:
        key = safe_relative(relative).casefold()
        chain = self.providers.get(key)
        if not chain:
            raise ValueError(f"No provider for: {relative}")
        winner = chain[-1]
        if winner["category"] == "plugin" and key not in self.active_keys:
            raise ValueError(f"Plugin is inactive: {relative}")
        return Path(winner["physical"])

    def inventory(self) -> dict:
        files = []
        for key, chain in sorted(self.providers.items()):
            winner = chain[-1]
            source = Path(winner["physical"])
            files.append({
                **winner,
                "size": source.stat().st_size,
                "sha256": sha256(source),
                "active": key in self.active_keys if winner["category"] == "plugin" else None,
                "provider_chain": [row["provider"] for row in chain],
            })
        return {
            "schema_version": 1,
            "tool_version": VERSION,
            "mo2_root": str(self.root),
            "profile": self.profile,
            "game_dir": str(self.game),
            "active_plugins": self.active,
            "enabled_mods_low_to_high": self.enabled_mods,
            "files": files,
            "warnings": self.warnings,
        }


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
