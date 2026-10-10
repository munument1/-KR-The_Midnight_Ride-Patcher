"""Build translated plugin payloads for a TMR profile.

Priority:
1. Mod-specific SST (strict)
2. Fallout 4 + official DLC translation inheritance (best-effort)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import tmrkr
from tmrkr_plugin_safety import plugin_skip_reason
from export_plugin_sst import export_sst
from inventory_translation_sources import files_by_norm, find_sst


def form_key(row: dict) -> str:
    return f"{row['id']}:{row['owner']}".casefold()


def translation_key(row: dict) -> tuple[str, str]:
    return form_key(row), row["source"]


def run_json(command: list[str], timeout: int = 600) -> tuple[subprocess.CompletedProcess, dict | None]:
    run = subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
    )
    detail = None
    if run.stdout.strip():
        try:
            detail = json.loads(run.stdout.strip().splitlines()[-1])
        except json.JSONDecodeError:
            pass
    return run, detail


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mo2-root", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--sst-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--translator-dll", type=Path, required=True)
    parser.add_argument("--scanner-dll", type=Path, required=True)
    parser.add_argument("--fallback-bank", type=Path, required=True)
    parser.add_argument("--only", action="append", default=[],
                        help="Optional plugin filename filter; may be repeated")
    args = parser.parse_args()

    installation = tmrkr.Installation(args.mo2_root, args.profile)
    sst_index = files_by_norm(args.sst_dir, ".sst")

    fallback = json.loads(args.fallback_bank.read_text(encoding="utf-8-sig"))
    fallback_rows = fallback["mappings"]
    fallback_by_record: dict[str, list[dict]] = {}
    for row in fallback_rows:
        fallback_by_record.setdefault(form_key(row), []).append(row)

    mappings_dir = args.output_root / "_mappings"
    scans_dir = args.output_root / "_scans"
    plugins_dir = args.output_root / "plugins"
    mappings_dir.mkdir(parents=True, exist_ok=True)
    scans_dir.mkdir(parents=True, exist_ok=True)
    plugins_dir.mkdir(parents=True, exist_ok=True)

    official_masters = {
        "fallout4.esm",
        "dlcrobot.esm",
        "dlcworkshop01.esm",
        "dlccoast.esm",
        "dlcworkshop02.esm",
        "dlcworkshop03.esm",
        "dlcnukaworld.esm",
    }
    excluded_plugins = {
        "ptrfo4001_t60pistol.esl",
        "ptrfo4002_vangraff.esl",
    }

    results = []

    only = {name.casefold() for name in args.only}

    for plugin in installation.active:
        lower = plugin.casefold()
        if only and lower not in only:
            continue
        if (lower in official_masters
                or lower in excluded_plugins
                or (lower.startswith("cc") and lower.endswith(".esl"))):
            continue

        try:
            source = installation.source(plugin)
        except Exception as exc:
            results.append({"plugin": plugin, "status": "source_error", "error": repr(exc)})
            print(f"ERROR source {plugin}: {exc}")
            continue

        try:
            reason = plugin_skip_reason(source)
        except ValueError as exc:
            reason = f"Safety preflight failed: {exc}"
        if reason:
            results.append({"plugin": plugin, "status": "skipped_unsafe_plugin", "reason": reason})
            print(f"SKIP {plugin}: {reason}")
            continue

        scan_path = scans_dir / f"{Path(plugin).name}.json"
        scan_run, _ = run_json([
            "dotnet", str(args.scanner_dll), str(source), str(scan_path), "--keys-only"
        ])
        if scan_run.returncode:
            results.append({
                "plugin": plugin,
                "status": "scan_failed",
                "stderr": scan_run.stderr[-8000:],
                "stdout": scan_run.stdout[-4000:],
            })
            print(f"FAIL scan {plugin}")
            continue

        scan = json.loads(scan_path.read_text(encoding="utf-8-sig"))
        keys = {key.casefold() for key in scan["formKeys"]}
        inherited = []
        for key in keys:
            inherited.extend(fallback_by_record.get(key, []))

        candidates = find_sst(plugin, args.sst_dir, sst_index)
        if len(candidates) > 1:
            results.append({
                "plugin": plugin,
                "status": "ambiguous_sst",
                "candidates": candidates,
                "fallback_candidates": len(inherited),
            })
            print(f"SKIP ambiguous SST: {plugin} -> {len(candidates)}")
            continue

        direct = []
        sst = None
        if len(candidates) == 1:
            sst = Path(candidates[0])
            data = export_sst(sst)
            direct = [{**row, "origin": "catalog"} for row in data["mappings"]]

        # A mod-specific SST has priority over inherited base/DLC text.
        # Removing duplicate record+source fallback rows also avoids a second
        # traversal for thousands of UOF4P records.
        if direct and inherited:
            direct_keys = {translation_key(row) for row in direct}
            inherited = [row for row in inherited if translation_key(row) not in direct_keys]

        if not direct and not inherited:
            results.append({
                "plugin": plugin,
                "status": "no_applicable_mapping",
                "records": scan["records"],
                "direct_mappings": 0,
                "fallback_mappings": 0,
            })
            print(f"NONE {plugin}: no direct/fallback mappings")
            continue

        mapping_path = mappings_dir / f"{Path(plugin).name}.json"
        combined = {
            "schema_version": 1,
            "sst_format": "mixed",
            "source_file": sst.name if sst else None,
            "plugins": None,
            "target": plugin,
            "mappings": direct,
            "fallback_mappings": inherited,
        }
        mapping_path.write_text(
            json.dumps(combined, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        output = plugins_dir / Path(plugin).name
        if output.exists():
            output.unlink()

        try:
            run, detail = run_json([
                "dotnet",
                str(args.translator_dll),
                str(source),
                str(mapping_path),
                str(output),
            ])
            if run.returncode or not detail:
                results.append({
                    "plugin": plugin,
                    "status": "failed",
                    "source": str(source),
                    "sst": str(sst) if sst else None,
                    "direct_mappings": len(direct),
                    "fallback_mappings": len(inherited),
                    "stderr": run.stderr[-8000:],
                    "stdout": run.stdout[-4000:],
                })
                print(f"FAIL {plugin}: {run.stderr.splitlines()[-1] if run.stderr else run.returncode}")
                continue

            if detail.get("status", "").startswith("skipped_"):
                results.append({"plugin": plugin, "status": detail["status"], "detail": detail})
                print(f"SKIP {plugin}: {detail.get('reason', detail['status'])}")
                continue

            if detail.get("status") == "no_changes":
                results.append({
                    "plugin": plugin,
                    "status": "no_changes",
                    "source": str(source),
                    "sst": str(sst) if sst else None,
                    "direct_mappings": len(direct),
                    "fallback_mappings": len(inherited),
                    "detail": detail,
                })
                print(f"NOCHANGE {plugin}: fallback candidates {len(inherited)}")
                continue

            results.append({
                "plugin": plugin,
                "status": "translated",
                "source": str(source),
                "sst": str(sst) if sst else None,
                "output": str(output),
                "detail": detail,
                "source_sha256": tmrkr.sha256(source),
                "output_sha256": tmrkr.sha256(output),
            })
            print(
                f"OK {plugin}: {detail['changed']} changes "
                f"(direct {detail['direct']['Changed']}, inherited {detail['fallback']['Changed']})"
            )
        except Exception as exc:
            results.append({
                "plugin": plugin,
                "status": "exception",
                "source": str(source),
                "sst": str(sst) if sst else None,
                "error": repr(exc),
                "traceback": traceback.format_exc(),
            })
            print(f"ERROR {plugin}: {exc}")

    summary = {
        "translated": sum(x["status"] == "translated" for x in results),
        "no_changes": sum(x["status"] == "no_changes" for x in results),
        "no_applicable_mapping": sum(x["status"] == "no_applicable_mapping" for x in results),
        "failed": sum(x["status"] in {"failed", "exception", "scan_failed", "source_error"} for x in results),
        "ambiguous_sst": sum(x["status"] == "ambiguous_sst" for x in results),
        "total": len(results),
    }
    report = {
        "schema_version": 2,
        "profile": args.profile,
        "fallback_bank": str(args.fallback_bank.resolve()),
        "results": results,
        "summary": summary,
    }
    report_path = args.output_root / "build-report.json"
    tmrkr.write_json(report_path, report)
    print(json.dumps(summary, ensure_ascii=False))
    print(report_path)
    return 1 if summary["failed"] or summary["ambiguous_sst"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
