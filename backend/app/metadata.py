from datetime import datetime, timezone

LIMITATIONS = [
    'Target-center visibility above an ideal zero-degree plane, not solar-disc illumination or radio-link margin.',
    'Sampled intervals are MODEL_ESTIMATE; between-sample behavior is not verified continuous visibility.',
    'No flight safety, power, battery, propellant or landing certification.',
    'Horizons reference-sphere height is independent of observer height above local DEM ground; no terrain datum conversion is claimed.',
]


def iso(value):
    return value.isoformat().replace('+00:00', 'Z')


def parse(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def metadata(source='UNAVAILABLE', mode='NOT_CALCULATED', quality='INSUFFICIENT_DATA', provenance=None, limitations=None):
    return dict(api_version='v1', backend_version='0.1.0', computed_at_utc=iso(datetime.now(timezone.utc)),
                source_type=source, calculation_mode=mode, data_quality=quality,
                provenance=provenance or dict(dataset_ids=[], source_urls=[], request_params={}, raw_sha256=[], coordinate_frame=None, sample_step_minutes=None),
                limitations=LIMITATIONS + (limitations or []))


def aggregate(items):
    sources = {s.get('source_type', 'UNAVAILABLE') for s in items}
    hashes = sorted({h for s in items for h in s.get('provenance', {}).get('raw_sha256', [])})
    if not sources or 'UNAVAILABLE' in sources:
        source = 'UNAVAILABLE'
    elif len(sources) == 1:
        source = next(iter(sources))
    else:
        source = 'MIXED_VERIFIED'
    partial = any(s.get('qualifying_status') == 'UNKNOWN' for s in items)
    mode = 'TERRAIN_UNAVAILABLE' if any(s.get('horizon_model') == 'LOCAL_TERRAIN' for s in items) else 'GEOMETRIC_IDEAL'
    return metadata(source, mode, 'INSUFFICIENT_DATA' if partial else 'MODEL_ESTIMATE',
                    dict(dataset_ids=['JPL Horizons'] if hashes else [], source_urls=['https://ssd.jpl.nasa.gov/horizons/'] if hashes else [],
                         raw_sha256=hashes, request_params={}, coordinate_frame='Lunar ME / DE421; local ENU', sample_step_minutes=None))
