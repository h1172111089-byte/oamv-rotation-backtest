"""Export compact, dated research evidence without copying market data or secrets."""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def package_summary(source):
    source = Path(source)
    payload = source.read_bytes()
    summary = json.loads(payload)
    required = {"asof", "snapshot", "results", "research_gates", "production_ready"}
    if not required.issubset(summary):
        raise ValueError("Incomplete research summary")
    manifest_path = Path(summary["snapshot"]) / "manifest.json"
    manifest_payload = manifest_path.read_bytes()
    manifest = json.loads(manifest_payload)
    exported = {key: value for key, value in summary.items() if key not in {"snapshot", "feature_audit"}}
    exported["artifact_type"] = "sealed_historical_research_summary"
    exported["input_manifest"] = manifest
    exported["provenance"] = {
        "source_run": source.parent.name,
        "source_summary_sha256": hashlib.sha256(payload).hexdigest(),
        "input_manifest_sha256": hashlib.sha256(manifest_payload).hexdigest(),
        "full_outputs_synced": False,
        "raw_inputs_synced": False,
        "note": "Read-only historical evidence; a new download is not the same input snapshot.",
    }
    return exported


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="Explicit completed-run summary.json")
    parser.add_argument("--output", type=Path, required=True, help="New dated results/*.json")
    args = parser.parse_args()
    destination = args.output.resolve()
    allowed = (ROOT / "results").resolve()
    if not destination.is_relative_to(allowed) or destination.suffix != ".json":
        parser.error("Output must be a new JSON file under this repository's results directory")
    packaged = package_summary(args.source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(packaged, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(f"Exported historical summary: {destination}")


if __name__ == "__main__":
    main()
