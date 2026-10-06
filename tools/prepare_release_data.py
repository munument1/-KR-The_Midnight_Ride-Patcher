"""Prepare public release data from validated local build artifacts.

This script is development-only. It never embeds developer absolute paths in the
release catalog.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import tmrkr
from tmrkr_sst import read_sst, custom_text_mapping


EXCLUDED_PLUGINS = {
    "ptrfo4001_t60pistol.esl",
    "ptrfo4002_vangraff.esl",
}

MCM_TARGETS = [
    ("MCM/Config/Complex Vendors/config.json", "Complex Vendors_config_en_ko.json"),
    ("MCM/Config/CraftingHighlightFix/config.json", "CraftingHighlightFix_config_en_ko.json"),
    ("MCM/Config/LegendariesTheyCanUse/config.json", "LegendariesTheyCanUse_config_en_ko.json"),
    ("MCM/Config/UnlimitedSurvivalMode/config.json", "UnlimitedSurvivalMode_config_en_ko.json"),
    ("MCM/Config/Upscaling/config.json", "Upscaling_config_en_ko.json"),
]

INTERFACE_TARGETS = [
    ("Interface/Translations/MCM_en.txt", "mcm_mcm_en_ko.sst", "MCM_en.json"),
    ("Interface/Translations/Safe Travels_en.txt", "safe travels_mcm_en_ko.sst", "Safe Travels_en.json"),
]


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_exact_sidecars(plugin: str, plugins_root: Path, target_root: Path) -> str | None:
    strings = plugins_root / "Strings"
    if not strings.is_dir():
        return None
    stem = Path(plugin).stem.casefold()
    matches = [p for p in strings.iterdir()
               if p.is_file() and p.name.casefold().startswith(stem + "_en.")]
    if not matches:
        return None
    rel = Path("exact-sidecars") / Path(plugin).stem
    dest = target_root / rel / "Strings"
    dest.mkdir(parents=True, exist_ok=True)
    for path in matches:
        shutil.copy2(path, dest / path.name)
    return rel.as_posix()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mo2-root", type=Path, required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--final-build", type=Path, required=True)
    ap.add_argument("--fallback-bank", type=Path, required=True)
    ap.add_argument("--mcm-mappings", type=Path, required=True)
    ap.add_argument("--sst-dir", type=Path, required=True)
    ap.add_argument("--backend-exe", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    out = args.output.resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    report = json.loads((args.final_build / "build-report.json").read_text(encoding="utf-8-sig"))
    installation = tmrkr.Installation(args.mo2_root, args.profile)
    result_by_name = {row["plugin"].casefold(): row for row in report["results"]}

    # Core backend/fallback data.
    backend = out / "Backend"
    backend.mkdir()
    shutil.copy2(args.backend_exe, backend / "TmrPluginTranslator.exe")
    fallback_dir = out / "fallback"
    fallback_dir.mkdir()
    shutil.copy2(args.fallback_bank, fallback_dir / "fallout4-base-dlc-fallback.json")

    exact_dir = out / "exact-plugins"
    maps_dir = out / "direct-maps"
    plugins = []

    official = {
        "fallout4.esm", "dlcrobot.esm", "dlcworkshop01.esm", "dlccoast.esm",
        "dlcworkshop02.esm", "dlcworkshop03.esm", "dlcnukaworld.esm",
    }

    for plugin in installation.active:
        lower = plugin.casefold()
        if lower in EXCLUDED_PLUGINS:
            continue
        if lower in official or (lower.startswith("cc") and lower.endswith(".esl")):
            continue

        source = installation.source(plugin)
        row = result_by_name.get(lower, {"status": "no_applicable_mapping"})
        entry = {
            "name": plugin,
            "source_sha256": tmrkr.sha256(source),
            "baseline_status": row["status"],
        }

        payload_source = args.final_build / "plugins" / plugin
        if row["status"] == "translated" and payload_source.is_file():
            detail = row.get("detail", {})
            if (detail.get("translation_encoding") != "utf-8"
                    or detail.get("text_roundtrip_verified") is not True):
                raise ValueError(f"Refusing unverified translation payload: {plugin}")
            payload_rel = Path("exact-plugins") / plugin
            payload_target = out / payload_rel
            payload_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(payload_source, payload_target)
            entry["payload"] = payload_rel.as_posix()
            entry["payload_sha256"] = tmrkr.sha256(payload_target)
            entry["payload_encoding"] = "utf-8"
            entry["text_roundtrip_verified"] = True
            entry["changed"] = row.get("detail", {}).get("changed", 0)
            sidecar = copy_exact_sidecars(plugin, args.final_build / "plugins", out)
            if sidecar:
                entry["sidecar_dir"] = sidecar

        map_source = args.final_build / "_mappings" / f"{plugin}.json"
        if map_source.is_file():
            raw = json.loads(map_source.read_text(encoding="utf-8-sig"))
            direct = raw.get("mappings") or []
            if direct:
                direct_rel = Path("direct-maps") / f"{plugin}.json"
                direct_doc = {
                    "schema_version": 1,
                    "sst_format": raw.get("sst_format"),
                    "source_file": raw.get("source_file"),
                    "plugins": raw.get("plugins"),
                    "target": plugin,
                    "mappings": direct,
                    "fallback_mappings": [],
                }
                write_json(out / direct_rel, direct_doc)
                entry["direct_mapping"] = direct_rel.as_posix()

        plugins.append(entry)

    # MCM mappings are already safe JSON exports from trusted local DB files.
    mcm_specs = []
    for relative, name in MCM_TARGETS:
        source = args.mcm_mappings / name
        if not source.is_file():
            continue
        rel = Path("mcm-maps") / name
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, out / rel)
        mcm_specs.append({"path": relative, "mapping": rel.as_posix()})

    # Convert custom-text SSTs to plain runtime JSON; xTranslator is not required by the release.
    interface_specs = []
    for relative, sst_name, json_name in INTERFACE_TARGETS:
        sst = read_sst(args.sst_dir / sst_name)
        mapping = custom_text_mapping(sst)
        rel = Path("interface-maps") / json_name
        write_json(out / rel, mapping)
        interface_specs.append({"path": relative, "mapping": rel.as_posix()})

    catalog = {
        "schema_version": 1,
        "version": tmrkr.VERSION,
        "profile_built_from": args.profile,
        "plugins": plugins,
        "mcm": mcm_specs,
        "interface": interface_specs,
        "fallback": {
            "source": "Fallout4.esm + official DLC SST dictionaries",
            "path": "fallback/fallout4-base-dlc-fallback.json",
        },
    }
    write_json(out / "catalog.json", catalog)

    print(json.dumps({
        "plugins": len(plugins),
        "exact_payloads": sum("payload" in x for x in plugins),
        "direct_maps": sum("direct_mapping" in x for x in plugins),
        "mcm": len(mcm_specs),
        "interface": len(interface_specs),
        "output": str(out),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
