"""Reproduce real V3 + live/cache NASA integration evidence without modifying inputs."""

import argparse
import hashlib
import json
from pathlib import Path

from app.integration.engine import AnalysisEngine, Scenario
from app.integration.grid import Filters, Registry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    registry = Registry(args.grid_root)
    if registry.errors:
        raise ValueError(registry.errors)
    dataset = next(
        d
        for d in registry.datasets.values()
        if d.metadata.region == "Site04" and not d.metadata.synthetic
    )
    quality = "source_lola_count_and_uncertainty_not_supplied"
    filters = Filters(qualities=[quality], limit=2)
    selected = dataset.select(filters)[0]["cell_ids"]
    if len(selected) != 2:
        raise ValueError("Need two eligible real cells")
    request = Scenario(
        dataset_id=dataset.metadata.dataset_id,
        cell_ids=selected,
        start_utc="2026-11-15T00:00:00Z",
        end_utc="2026-11-22T00:00:00Z",
        step_minutes=60,
        minimum_shared_minutes=60,
        filters=filters,
    )
    result = AnalysisEngine(registry).delay(request, selected[0])
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "real_v3_delay.json").write_text(json.dumps(result, indent=2, allow_nan=False))
    vectors = [dataset.vector(c.cell_id) for c in dataset.cells]
    fingerprint = hashlib.sha256(
        json.dumps(vectors, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    summary = dict(
        dataset_id=dataset.metadata.dataset_id,
        grid_version=dataset.metadata.grid_version,
        tile_processing_version=dataset.metadata.processing_version,
        cell_count=len(dataset.cells),
        dataset_sha256=dataset.digest,
        all_static_vectors_sha256=fingerprint,
        selected_cell_ids=selected,
        outcome=result["outcome"],
        quality_limitations=quality,
        observer_altitude_km=0,
        horizon_model="GEOMETRIC_IDEAL",
        scenarios={},
    )
    for scenario in ("original", "delayed"):
        summary["scenarios"][scenario] = [
            dict(
                cell_id=r["cell_id"],
                status=r["status"],
                features=r["dynamic_vector"]["features"] if r["dynamic_vector"] else None,
                queries={
                    k: {
                        name: q[name]
                        for name in ("raw_sha256", "source_url", "retrieved_at_utc", "delivery")
                    }
                    for k, q in r["dynamic_vector"]["provenance"]["queries"].items()
                }
                if r["dynamic_vector"]
                else None,
            )
            for r in result[scenario]["results"]
        ]
    (output / "validation_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False))
    # Small real-data CI fixture: unmodified physical values, original IDs, full provenance.
    fixture = dict(
        metadata=dataset.metadata.model_dump(),
        cells=[dataset.cell(cid).model_dump() for cid in selected],
    )
    (output / "real_v3_two_cells.json").write_text(json.dumps(fixture, indent=2, allow_nan=False))
    print(json.dumps({k: v for k, v in summary.items() if k != "scenarios"}, indent=2))
    if any(
        r["dynamic_vector"] is None
        for name in ("original", "delayed")
        for r in result[name]["results"]
    ):
        raise RuntimeError("NASA evaluation incomplete; see saved evidence")


if __name__ == "__main__":
    main()
