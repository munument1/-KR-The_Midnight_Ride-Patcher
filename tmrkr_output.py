"""Build a merge-ready MO2 Output tree for The Midnight Ride Korean patcher."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import tmrkr
from tmrkr_mcm import translate_mcm_json

OFFICIAL_MASTERS = {
    "fallout4.esm", "dlcrobot.esm", "dlcworkshop01.esm", "dlccoast.esm",
    "dlcworkshop02.esm", "dlcworkshop03.esm", "dlcnukaworld.esm",
}
BASE_MOD = "FO4 KOREAN"
EXCLUDED_PLUGINS = {
    "ptrfo4001_t60pistol.esl",
    "ptrfo4002_vangraff.esl",
}


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _contained(root: Path, relative: str | Path) -> Path:
    root = root.resolve()
    target = (root / relative).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"Path escapes root: {relative}")
    return target


def _copy_tree(source: Path, target: Path) -> int:
    if not source.is_dir():
        return 0
    count = 0
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(source)
        dest = _contained(target, rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        count += 1
    return count


def _decode_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    if raw.startswith(b"\xff\xfe"):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


def _translate_interface(source: Path, mapping_path: Path, output: Path) -> dict:
    mapping = _read_json(mapping_path)
    text = _decode_text(source)
    out = []
    matched = 0
    missing = []
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        newline = line[len(body):]
        if "\t" not in body:
            out.append(line)
            continue
        key, value = body.split("\t", 1)
        translated = mapping.get(value)
        if translated is None:
            if value and not value.startswith("$"):
                missing.append(value)
            out.append(body + newline)
        else:
            matched += 1
            out.append(key + "\t" + translated + newline)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Interface translation tables require UTF-16 LE with a BOM.
    output.write_bytes(b"\xff\xfe" + "".join(out).encode("utf-16-le"))
    return {"matched": matched, "missing": len(missing), "encoding": "utf-16-le"}


def _copy_en_sidecars(source_dir: Path, target_strings: Path) -> int:
    strings = source_dir / "Strings"
    if not strings.is_dir():
        return 0
    copied = 0
    for path in strings.iterdir():
        if path.is_file() and "_en." in path.name.casefold():
            target_strings.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target_strings / path.name)
            copied += 1
    return copied


def _plugin_map(catalog_dir: Path, entry: dict) -> Path | None:
    rel = entry.get("direct_mapping")
    if not rel:
        return None
    path = _contained(catalog_dir, rel)
    return path if path.is_file() else None


def _verified_exact_payload(catalog_dir: Path, entry: dict) -> Path | None:
    # Legacy releases lost Korean text at serialization. Only payloads created
    # by the UTF-8 backend and checked by a text roundtrip may bypass translation.
    if (entry.get("payload_encoding") != "utf-8"
            or entry.get("text_roundtrip_verified") is not True
            or not entry.get("payload")):
        return None
    payload = _contained(catalog_dir, entry["payload"])
    if not payload.is_file():
        return None
    if tmrkr.sha256(payload) != entry.get("payload_sha256"):
        raise ValueError(f"Payload hash mismatch: {entry.get('name', payload.name)}")
    return payload


def _run_fallback(source: Path, plugin: str, entry: dict | None,
                  catalog_dir: Path, temp: Path) -> tuple[dict, Path | None]:
    backend = _contained(catalog_dir, "Backend/TmrPluginTranslator.exe")
    bank = _contained(catalog_dir, "fallback/fallout4-base-dlc-fallback.json")
    direct = _plugin_map(catalog_dir, entry or {})
    outdir = temp / "fallback" / plugin.replace(":", "_")
    outdir.mkdir(parents=True, exist_ok=True)
    output = outdir / plugin
    run = subprocess.run(
        [str(backend), str(source), str(direct) if direct else "-", str(bank), str(output)],
        text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=180)
    if run.returncode:
        raise RuntimeError(f"{plugin} fallback failed:\n{run.stderr[-4000:]}")
    lines = [x for x in run.stdout.splitlines() if x.strip()]
    detail = json.loads(lines[-1]) if lines else {}
    return detail, output if output.is_file() else None


def _winner(installation: tmrkr.Installation, relative: str) -> dict:
    key = tmrkr.safe_relative(relative).casefold()
    chain = installation.providers.get(key)
    if not chain:
        raise ValueError(f"No provider for: {relative}")
    return chain[-1]


def _provider_target(stage: Path, winner: dict) -> Path:
    provider = winner["provider"]
    relative = tmrkr.safe_relative(winner["path"])

    if provider == "game:Data":
        # Game/Creation files are overridden through the toggleable FO4 KOREAN MO2 mod.
        return _contained(stage / "mods" / BASE_MOD, relative)

    if provider == "MO2:overwrite":
        return _contained(stage / "overwrite", relative)

    mod_name = tmrkr.safe_relative(provider)
    if "/" in mod_name:
        raise ValueError(f"Invalid MO2 mod provider name: {provider}")
    return _contained(stage / "mods" / mod_name, relative)


def build_output(mo2_root: Path, base_package: Path, catalog_dir: Path,
                 output: Path, profile: str | None = None) -> dict:
    installation = tmrkr.Installation(mo2_root, profile)
    catalog = _read_json(catalog_dir / "catalog.json")
    if catalog.get("schema_version") != 1:
        raise ValueError("Unsupported catalog")

    for required in ("Interface", "Strings"):
        if not (base_package / required).is_dir():
            raise ValueError(f"Base Korean package is missing {required}: {base_package}")

    plugins_catalog = {row["name"].casefold(): row for row in catalog["plugins"]}
    output = output.resolve()
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    report = {
        "schema_version": 2,
        "tool_version": tmrkr.VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "mo2_root": str(installation.root),
        "profile": installation.profile,
        "base_package": "bundled:FO4_AE_1.11.191.Kor",
        "output": str(output),
        "plugins": [],
        "base_files": 0,
        "mcm": [],
        "interface": [],
        "warnings": list(installation.warnings),
    }

    with tempfile.TemporaryDirectory(prefix=".tmrkr-output-", dir=str(output.parent)) as tmp_name:
        temp = Path(tmp_name)
        stage = temp / "Output"
        base_mod = stage / "mods" / BASE_MOD

        for folder in ("Interface", "Programs", "Strings"):
            report["base_files"] += _copy_tree(base_package / folder, base_mod / folder)

        for plugin in installation.active:
            lower = plugin.casefold()
            if (lower in OFFICIAL_MASTERS
                    or lower in EXCLUDED_PLUGINS
                    or (lower.startswith("cc") and lower.endswith(".esl"))):
                continue
            try:
                source = installation.source(plugin)
                winner = _winner(installation, plugin)
            except Exception as exc:
                report["plugins"].append({"plugin": plugin, "status": "source_missing", "error": str(exc)})
                continue

            entry = plugins_catalog.get(lower)
            source_hash = tmrkr.sha256(source)
            target = _provider_target(stage, winner)
            result = {
                "plugin": plugin,
                "source_sha256": source_hash,
                "provider": winner["provider"],
                "relative_path": winner["path"],
            }

            if entry and source_hash == entry.get("source_sha256"):
                payload = _verified_exact_payload(catalog_dir, entry)
                if entry.get("baseline_status") == "translated" and payload is not None:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(payload, target)
                    sidecars = 0
                    if entry.get("sidecar_dir"):
                        sidecars = _copy_en_sidecars(
                            _contained(catalog_dir, entry["sidecar_dir"]),
                            target.parent / "Strings")
                    result.update(status="exact_payload", changed=entry.get("changed", 0), sidecars=sidecars)
                    report["plugins"].append(result)
                    continue
                elif entry.get("baseline_status") != "translated":
                    result.update(status="known_no_translation_needed", changed=0)
                    report["plugins"].append(result)
                    continue

                # A missing or unverified exact payload must use direct/fallback,
                # even when the original plugin's hash is a catalog match.

            detail, translated = _run_fallback(source, plugin, entry, catalog_dir, temp)
            if translated is None or detail.get("status") == "no_changes":
                result.update(status="updated_no_match" if entry else "new_no_match", changed=0, detail=detail)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(translated, target)
                sidecars = _copy_en_sidecars(translated.parent, target.parent / "Strings")
                result.update(
                    status="updated_fallback" if entry else "new_inherited",
                    changed=detail.get("changed", 0), sidecars=sidecars, detail=detail)
            report["plugins"].append(result)

        for spec in catalog.get("mcm", []):
            relative = spec["path"]
            try:
                source = installation.source(relative)
                winner = _winner(installation, relative)
            except Exception:
                continue
            target = _provider_target(stage, winner)
            stats = translate_mcm_json(source, _contained(catalog_dir, spec["mapping"]), target)
            report["mcm"].append({"path": relative, "provider": winner["provider"], **stats})

        for spec in catalog.get("interface", []):
            relative = spec["path"]
            try:
                source = installation.source(relative)
                winner = _winner(installation, relative)
            except Exception:
                continue
            target = _provider_target(stage, winner)
            stats = _translate_interface(source, _contained(catalog_dir, spec["mapping"]), target)
            report["interface"].append({"path": relative, "provider": winner["provider"], **stats})

        if not (stage / "mods").is_dir():
            raise RuntimeError("No output was generated")

        _write_json(stage / "TMR-Korean-Patcher-report.json", report)
        stage.rename(output)

    return report
