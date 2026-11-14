"""python -m celestial_engine --output celestial_engine/outputs [--offline]."""

import argparse
import logging

from .celestial_service import CelestialService, export_result
from .horizons_client import HorizonsClient
from .schemas import EphemerisRequest

SAMPLE = dict(
    latitude_deg=-89.0,
    longitude_east_deg=45.0,
    altitude_km=0.0,
    altitude_reference="horizons_lunar_reference",
    start_utc="2026-11-15T00:00:00Z",
    end_utc="2026-11-22T00:00:00Z",
    step_minutes=60,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="celestial_engine/outputs")
    parser.add_argument("--cache-dir", default="data/celestial")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    service = CelestialService(HorizonsClient(args.cache_dir, offline=args.offline))
    result = service.ephemeris(EphemerisRequest(**SAMPLE))
    export_result(result, args.output)
    print(
        f"Exported {len(result.records)} samples; missing={result.metadata['missing_observations']}"
    )


if __name__ == "__main__":
    main()
