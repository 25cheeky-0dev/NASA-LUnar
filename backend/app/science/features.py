from app.catalog import SITES
from app.metadata import metadata
from app.science.grid import neighborhood, cell_at

NAMES = ['sun_visible_fraction', 'earth_visible_fraction', 'shared_visible_fraction', 'longest_shared_hours', 'unknown_fraction', 'terrain_slope_deg']


def point(cell_id, scenario_id, values, quality, **extra):
    available = [name for name, value in zip(NAMES, values) if value is not None]
    return dict(cell_id=cell_id, scenario_id=scenario_id, feature_names=NAMES, values=values, normalized_values=None,
        normalization_version='v1', available_features=available, missing_features=[n for n in NAMES if n not in available],
        similarity_eligible=False, quality=quality, **extra)


def feature_space(scenario):
    site = SITES[scenario['site_id']]
    cells = neighborhood(scenario['site_id'])['cells']
    metrics = scenario.get('metrics', {})
    # Incomplete interval fractions are not silently used as complete-vector features.
    complete = scenario['known_fraction'] >= 1-1e-9
    values = [metrics.get(k) if complete else None for k in ('sun_visible_fraction', 'earth_visible_fraction', 'both_visible_fraction')]
    values += [scenario['longest_shared_minutes']/60 if scenario['longest_shared_minutes'] is not None else None,
               scenario['unknown_fraction'], None]
    reference = point(cell_at(site['lat_deg'], site['lon_east_deg'])['cell_id'], scenario['scenario_id'], values,
        scenario['data_quality'], observation_point_type='REFERENCE_SITE', site_id=scenario['site_id'],
        observer_lat_deg=site['lat_deg'], observer_lon_east_deg=site['lon_east_deg'],
        arrival_utc=scenario['arrival_utc'], end_utc=scenario['end_utc'], horizon_model=scenario['horizon_model'],
        observer_height_m=scenario['observer_height_m'], does_not_evaluate_cell_center=True)
    return dict(scenario_id=scenario['scenario_id'], feature_definitions=[dict(name=n, unit='hours' if n=='longest_shared_hours' else 'degrees' if n=='terrain_slope_deg' else 'fraction', direction='descriptive') for n in NAMES],
        points=[point(c['cell_id'], scenario['scenario_id'], [None]*6, 'UNEVALUATED') for c in cells],
        reference_points=[reference], scatter_axes=dict(x=NAMES[0], y=NAMES[3], z=NAMES[1]),
        normalization={'method': None, 'reason': 'No complete terrain vectors; raw physical axes only'},
        ignored_or_missing=[dict(cell_id=c['cell_id'], reason='CELL_CENTER_UNEVALUATED') for c in cells],
        **metadata(scenario['source_type'], scenario['calculation_mode'], scenario['data_quality'], scenario['provenance'],
            ['Reference-point features are separate from cell-center features. Unknown slope is null. No PCA, embeddings or similarity ranking is claimed.']))
