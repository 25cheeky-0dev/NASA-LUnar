"""Selected-cell ephemerides, explicit horizon states and evidence comparisons."""

import re
from datetime import timedelta
from typing import Literal

from pydantic import Field, model_validator

from app.providers import terrain
from app.science.windows import summarize
from celestial_engine.celestial_service import CelestialService
from celestial_engine.horizons_client import SourceUnavailable
from celestial_engine.schemas import EphemerisRequest

from .grid import Filters


class Scenario(EphemerisRequest):
    # Coordinates always overwritten with the original selected cell's coordinates.
    latitude_deg: float = 0
    longitude_east_deg: float = 0
    dataset_id: str
    cell_ids: list[str] = Field(min_length=1, max_length=16)
    horizon_model: Literal["GEOMETRIC_IDEAL", "TERRAIN_PARTIAL"] = "GEOMETRIC_IDEAL"
    terrain_site_id: str | None = None
    observer_height_m: float = Field(default=1, ge=0, le=100)
    minimum_shared_minutes: float = Field(ge=0)
    filters: Filters = Field(default_factory=Filters)

    @model_validator(mode="after")
    def budget(self):
        if len(set(self.cell_ids)) != len(self.cell_ids):
            raise ValueError("Duplicate cell IDs")
        if len(self.timestamps()) * len(self.cell_ids) > 20000:
            raise ValueError("Total sample budget exceeds 20000")
        if self.horizon_model == "TERRAIN_PARTIAL" and not self.terrain_site_id:
            raise ValueError("Explicit terrain_site_id required for local DEM selection")
        return self


def horizon_at(dataset, cell, request):
    if request.horizon_model == "GEOMETRIC_IDEAL":
        return dict(
            model="GEOMETRIC_IDEAL",
            far_field_complete=False,
            limitations=["Ideal local normal plane; no terrain obstruction modeled"],
        )
    try:
        result = terrain.horizon(
            request.terrain_site_id,
            request.observer_height_m,
            5,
            position=(cell.latitude_deg, dataset.east_longitude(cell)),
        )
        manifest = result.get("source_manifest", {})
        compatible = (
            manifest.get("vertical_reference") == "horizons_lunar_reference"
            and abs(
                (result["observer_ground_height_m"] + request.observer_height_m) / 1000
                - request.altitude_km
            )
            < 1e-9
        )
        return dict(result, model="TERRAIN_PARTIAL", observer_reference_compatible=compatible)
    except (terrain.TerrainUnavailable, ImportError, KeyError) as exc:
        return dict(
            model="TERRAIN_PARTIAL",
            far_field_complete=False,
            azimuth_samples=[],
            limitations=[str(exc)],
            coverage="UNKNOWN",
        )


def visibility(az, elevation, horizon):
    if elevation is None or az is None:
        return dict(
            state="UNKNOWN", geometric_visible=None, modeled_visible=None, clearance_deg=None
        )
    geometric = elevation > 0
    if horizon["model"] == "GEOMETRIC_IDEAL":
        return dict(
            state="GEOMETRIC_VISIBLE" if geometric else "GEOMETRIC_HIDDEN",
            geometric_visible=geometric,
            modeled_visible=geometric,
            clearance_deg=elevation,
        )
    if horizon.get("observer_reference_compatible") is False:
        return dict(
            state="UNKNOWN_OBSERVER_REFERENCE",
            geometric_visible=geometric,
            modeled_visible=None,
            clearance_deg=None,
        )
    # The verified local provider cannot certify far-field clearance. No azimuth
    # interpolation is justified by its discrete rays. Only exact supported rays
    # may demonstrate obstruction; unsampled directions remain unknown.
    ray = next(
        (
            r
            for r in horizon.get("azimuth_samples", [])
            if abs((r["azimuth_deg"] - az + 180) % 360 - 180) < 1e-8
        ),
        None,
    )
    height = ray.get("terrain_horizon_elevation_deg") if ray else None
    clearance = elevation - height if height is not None else None
    blocked = clearance is not None and clearance <= 0
    return dict(
        state="TERRAIN_OBSTRUCTED" if blocked else "INCOMPLETE_HORIZON_COVERAGE",
        geometric_visible=geometric,
        modeled_visible=False if blocked else None,
        clearance_deg=clearance,
    )


def dynamic_features(records, request):
    rows = []
    for record in records:
        row = dict(timestamp_utc=record["timestamp_utc"])
        for body in ("sun", "earth"):
            state = record[body]
            value = record[f"{body}_elevation_deg"]
            if request.horizon_model != "GEOMETRIC_IDEAL":
                value = -1.0 if state["modeled_visible"] is False else None
            row[body] = dict(status="KNOWN", el_deg=value) if value is not None else None
        rows.append(row)
    result = summarize(
        rows,
        request.start_utc,
        request.end_utc,
        request.step_minutes,
        request.minimum_shared_minutes,
    )
    # Each body's available duration survives missing samples from the other body.
    for body in ("sun", "earth"):
        supported = any(
            left.get(body) is not None and right.get(body) is not None
            for left, right in zip(rows, rows[1:])
        )
        result["metrics"][body + "_visible_fraction"] = (
            sum(w["duration_minutes"] for w in result[body + "_windows"])
            / ((request.end_utc - request.start_utc).total_seconds() / 60)
            if supported
            else None
        )
    for key in ("sun_windows", "earth_windows", "shared_windows"):
        for window in result[key]:
            window["model"] = request.horizon_model
    return dict(
        sun_modeled_visibility_fraction=result["metrics"]["sun_visible_fraction"],
        earth_modeled_visibility_fraction=result["metrics"]["earth_visible_fraction"],
        shared_modeled_visibility_fraction=result["metrics"]["both_visible_fraction"],
        longest_shared_minutes=result["longest_shared_minutes"],
        earliest_qualifying_shared_window=result["earliest_qualifying_window"],
        unknown_data_fraction=result["unknown_fraction"],
        summary=result,
        fraction_definition="Known modeled visible duration / full requested duration; lower bound when unknown > 0",
        window_model="Piecewise-linear elevation between adjacent UTC samples; no gap extrapolation",
        terrain_clearance_supported=any(
            r[b]["clearance_deg"] is not None for r in records for b in ("sun", "earth")
        )
        if request.horizon_model != "GEOMETRIC_IDEAL"
        else False,
    )


class AnalysisEngine:
    def __init__(self, registry, celestial=None, skyline=horizon_at):
        self.registry = registry
        self.celestial = celestial or CelestialService()
        self.skyline = skyline

    def analyze(self, request):
        dataset = self.registry.datasets[request.dataset_id]
        meta = dataset.metadata
        if meta.coordinate_frame != "MOON_ME_DE421" or not (
            meta.latitude_type == "planetodetic"
            or (
                meta.latitude_type == "planetocentric_spherical"
                and meta.reference_radius_m == 1737400
            )
        ):
            raise ValueError(
                "Unverified lunar reference frame or latitude type; explicit conversion required"
            )
        # Validate every requested ID before any expensive operation.
        cells = [dataset.cell(cid) for cid in request.cell_ids]
        _, reasons = dataset.select(request.filters)
        results = []
        for cell in cells:
            base = dict(
                cell_id=cell.cell_id,
                dataset_id=meta.dataset_id,
                grid_version=meta.grid_version,
                cell=cell.model_dump(),
                static_vector=dataset.vector(cell.cell_id),
                engineering_constraint_failures=reasons[cell.cell_id],
            )
            if reasons[cell.cell_id]:
                results.append(
                    dict(
                        base,
                        status="NOT_EVALUATED",
                        dynamic_vector=None,
                        reasons=reasons[cell.cell_id],
                    )
                )
                continue
            values = {k: getattr(request, k) for k in EphemerisRequest.model_fields}
            values.update(
                latitude_deg=cell.latitude_deg, longitude_east_deg=dataset.east_longitude(cell)
            )
            observer = EphemerisRequest(**values)
            try:
                ephemeris = self.celestial.ephemeris(observer)
            except SourceUnavailable as exc:
                results.append(
                    dict(base, status="UNKNOWN", dynamic_vector=None, reasons=[str(exc)])
                )
                continue
            if meta.latitude_type == "planetocentric_spherical":
                for query in ephemeris.metadata.get("queries", {}).values():
                    match = re.search(
                        r"Center radii\s*:\s*([0-9.]+)\s*[,x]\s*([0-9.]+)\s*[,x]\s*([0-9.]+)",
                        query.get("ephemeris_header", ""),
                    )
                    if not match or any(float(x) != 1737.4 for x in match.groups()):
                        raise ValueError(
                            "Horizons center shape does not verify spherical latitude identity"
                        )
                if len(ephemeris.metadata.get("queries", {})) != 2:
                    raise ValueError("Both NASA headers required for spherical latitude mapping")
            expected = set(observer.timestamps())
            indexed = {}
            for row in ephemeris.records:
                if row.timestamp_utc not in expected or row.timestamp_utc in indexed:
                    raise ValueError("Unexpected or duplicate UTC observation")
                if (row.latitude_deg, row.longitude_east_deg, row.altitude_km) != (
                    observer.latitude_deg,
                    observer.longitude_east_deg,
                    observer.altitude_km,
                ):
                    raise ValueError("Observation position does not match selected cell")
                indexed[row.timestamp_utc] = row
            horizon = self.skyline(dataset, cell, request)
            records = []
            for stamp in observer.timestamps():
                row = indexed.get(stamp)
                record = dict(cell_id=cell.cell_id, timestamp_utc=stamp.isoformat())
                for body in ("sun", "earth"):
                    az = getattr(row, f"{body}_azimuth_deg") if row else None
                    el = getattr(row, f"{body}_elevation_deg") if row else None
                    record[f"{body}_azimuth_deg"], record[f"{body}_elevation_deg"] = az, el
                    record[body] = visibility(az, el, horizon)
                records.append(record)
            features = dynamic_features(records, request)
            dynamic = dict(
                cell_id=cell.cell_id,
                grid_version=meta.grid_version,
                dataset_id=meta.dataset_id,
                start_utc=request.start_utc.isoformat(),
                end_utc=request.end_utc.isoformat(),
                observer=observer.model_dump(mode="json"),
                observer_height_m=request.observer_height_m,
                horizon_model=request.horizon_model,
                horizon=horizon,
                sampling_cadence_minutes=request.step_minutes,
                provenance=ephemeris.metadata,
                features=features,
                quality="COMPLETE_MODELED_INTERVAL"
                if features["unknown_data_fraction"] == 0
                else "INCOMPLETE",
                missing_data=features["unknown_data_fraction"] > 0,
                units=dict(longest_shared_minutes="minute", visibility_fraction="dimensionless"),
                records=records,
            )
            results.append(dict(base, status="EVALUATED", dynamic_vector=dynamic))
        return dict(
            dataset=meta.model_dump(),
            dataset_sha256=dataset.digest,
            scenario=request.model_dump(mode="json"),
            results=results,
            comparison=self.rank(results, request),
            scope="Only explicitly selected cells satisfying supplied filters; no global safety claim",
        )

    @staticmethod
    def rank(results, request):
        ranked, excluded = [], []
        for result in results:
            vector = result["dynamic_vector"]
            reasons = list(result.get("reasons", []))
            if vector is None:
                reasons.append("UNEVALUATED_OR_SOURCE_UNAVAILABLE")
            elif vector["missing_data"]:
                reasons.append("INCOMPLETE_DYNAMIC_EVIDENCE")
            elif vector["features"]["summary"]["qualifying_status"] != "QUALIFIES":
                reasons.append("VISIBILITY_CONSTRAINT")
            if reasons:
                excluded.append(dict(cell_id=result["cell_id"], reasons=reasons))
            else:
                ranked.append(
                    dict(
                        cell_id=result["cell_id"],
                        longest_shared_minutes=vector["features"]["longest_shared_minutes"],
                        static_measurements=result["static_vector"]["raw"],
                        terrain_evidence=result["static_vector"]["quality"],
                    )
                )
        ranked.sort(key=lambda row: (-row["longest_shared_minutes"], row["cell_id"]))
        return dict(
            ranked=ranked,
            excluded=excluded,
            temporal_resolution_minutes=request.step_minutes,
            significance_warning="Numerical ordering alone does not establish a meaningful difference, particularly below one cadence; no uncertainty raster is inferred.",
            criterion="Longest modeled shared visibility, descending; ID breaks ties",
            horizon_model=request.horizon_model,
            minimum_shared_minutes=request.minimum_shared_minutes,
            explanation="Same UTC interval, cadence, observer settings and horizon mode. Terrain measurements and source resolutions remain separate; no composite safety score.",
        )

    def delay(self, request, original_cell_id):
        if original_cell_id not in request.cell_ids:
            raise ValueError("Original cell must be in selected comparison scope")
        # Validate shifted date limits before performing either scenario.
        delayed = Scenario.model_validate(
            request.model_dump()
            | dict(
                start_utc=request.start_utc + timedelta(days=7),
                end_utc=request.end_utc + timedelta(days=7),
            )
        )
        original = self.analyze(request)
        shifted = self.analyze(delayed)
        ranked = shifted["comparison"]["ranked"]
        original_ranked = original["comparison"]["ranked"]
        missing_static = {"MISSING_TERRAIN", "QUALITY", "COVERAGE", "INVALID_CELL"}
        incomplete = any(
            r["dynamic_vector"] is None
            and (
                r["status"] != "NOT_EVALUATED"
                or bool(missing_static.intersection(r.get("reasons", [])))
            )
            or r["dynamic_vector"] is not None
            and r["dynamic_vector"]["missing_data"]
            for r in shifted["results"]
        )
        if ranked:
            choice = next((r for r in ranked if r["cell_id"] == original_cell_id), None)
            outcome = "KEEP" if choice else "SWITCH"
            choice = choice or ranked[0]
            reason = (
                "Original location still meets supplied constraints"
                if outcome == "KEEP"
                else "Evaluated alternative meets constraints; original does not have qualifying complete evidence"
            )
        else:
            choice = None
            outcome = "INSUFFICIENT DATA" if incomplete else "NO QUALIFYING MODELED OPTION"
            reason = (
                "No complete qualifying delayed option in selected scope; no later date evaluated"
            )
        return dict(
            outcome=outcome,
            selected=choice,
            reason=reason,
            original_cell_id=original_cell_id,
            delay_days=7,
            original=original,
            delayed=shifted,
            original_qualifying_ids=[r["cell_id"] for r in original_ranked],
            limitations=[
                "POSTPONE requires a separately evaluated later qualifying interval; not inferred here",
                "No globally safest site claim; recommendations apply only to supplied constraints and selected cells",
            ],
        )
