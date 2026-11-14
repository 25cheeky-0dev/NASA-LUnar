"""Time integration of piecewise-linear target-center elevation estimates.

Only adjacent, aligned, known samples within the declared cadence support a
segment. No extrapolation across gaps or outside the observation interval.
"""
from datetime import timedelta
from app.metadata import iso, parse


def positive_range(a, b):
    if a > 0 and b > 0:
        return 0., 1.
    if a <= 0 and b <= 0:
        return None
    crossing = -a / (b-a)
    return (crossing, 1.) if b > 0 else (0., crossing)


def find_windows(records, kind, step_minutes):
    windows = []
    for left, right in zip(records, records[1:]):
        a, b = parse(left['timestamp_utc']), parse(right['timestamp_utc'])
        seconds = (b-a).total_seconds()
        if seconds <= 0 or seconds > step_minutes * 60 + .01:
            continue
        targets = ['sun', 'earth'] if kind == 'BOTH' else [kind.lower()]
        if any(not row.get(target) or row[target].get('status') != 'KNOWN' for row in (left, right) for target in targets):
            continue
        ranges = [positive_range(left[target]['el_deg'], right[target]['el_deg']) for target in targets]
        if any(r is None for r in ranges):
            continue
        low, high = max(r[0] for r in ranges), min(r[1] for r in ranges)
        if high <= low:
            continue
        start, end = a + timedelta(seconds=low*seconds), a + timedelta(seconds=high*seconds)
        # Do not merge through a sampled zero, even if the two open intervals touch.
        join = windows and windows[-1]['end_utc'] == iso(start) and all(left[t]['el_deg'] > 0 for t in targets)
        if join:
            windows[-1]['end_utc'] = iso(end)
            windows[-1]['duration_minutes'] = (end-parse(windows[-1]['start_utc'])).total_seconds()/60
        else:
            windows.append(dict(start_utc=iso(start), end_utc=iso(end), duration_minutes=(end-start).total_seconds()/60,
                kind=kind, estimate_status='MODEL_ESTIMATE', boundary_uncertainty_seconds=step_minutes*60,
                model='GEOMETRIC_IDEAL'))
    return windows


def summarize(records, start, end, step_minutes, minimum):
    total = (end-start).total_seconds()
    known_seconds = 0.
    unknowns = []
    cursor = start
    for left, right in zip(records, records[1:]):
        a, b = parse(left['timestamp_utc']), parse(right['timestamp_utc'])
        if a > cursor:
            unknowns.append(dict(start_utc=iso(cursor), end_utc=iso(a), reason='MISSING_INTERVAL'))
        known = 0 < (b-a).total_seconds() <= step_minutes*60+.01 and all(
            row.get(t) and row[t].get('status') == 'KNOWN' for row in (left, right) for t in ('sun', 'earth'))
        if known:
            known_seconds += (b-a).total_seconds()
        else:
            unknowns.append(dict(start_utc=iso(a), end_utc=iso(b), reason='MISSING_OR_GAPPED_OBSERVATIONS'))
        cursor = b
    if cursor < end:
        unknowns.append(dict(start_utc=iso(cursor), end_utc=iso(end), reason='UNOBSERVED_TAIL'))
    windows = {kind: find_windows(records, kind, step_minutes) for kind in ('SUN', 'EARTH', 'BOTH')}
    eligible = [w for w in windows['BOTH'] if w['duration_minutes'] + 1e-9 >= minimum]
    known_fraction = min(1., known_seconds/total)
    status = 'QUALIFIES' if eligible else ('UNKNOWN' if known_fraction < 1-1e-9 else 'FAILS')
    crossings = {}
    for target in ('sun', 'earth'):
        crossing = None
        for a, b in zip(records, records[1:]):
            if not a.get(target) or not b.get(target):
                continue
            dt = (parse(b['timestamp_utc'])-parse(a['timestamp_utc'])).total_seconds()
            x, y = a[target]['el_deg'], b[target]['el_deg']
            if 0 < dt <= step_minutes*60 and x > 0 >= y:
                crossing = iso(parse(a['timestamp_utc'])+timedelta(seconds=dt*x/(x-y)))
                break
        crossings[target+'set'] = dict(timestamp_utc=crossing, reason=None if crossing else 'not_observed_in_range', boundary_uncertainty_seconds=step_minutes*60)
    return dict(sun_windows=windows['SUN'], earth_windows=windows['EARTH'], shared_windows=windows['BOTH'],
        longest_shared_minutes=max((w['duration_minutes'] for w in windows['BOTH']), default=0.) if known_seconds else None,
        earliest_qualifying_window=eligible[0] if eligible else None, known_fraction=known_fraction,
        unknown_fraction=max(0., 1-known_fraction), qualifying_status=status,
        reason_codes=[] if eligible else ['UNKNOWN_OBSERVATIONS' if status == 'UNKNOWN' else 'NO_CONTINUOUS_SHARED_WINDOW_MEETS_THRESHOLD'],
        unknown_intervals=unknowns, next_crossings=crossings,
        metrics={kind.lower()+'_visible_fraction': sum(w['duration_minutes']*60 for w in windows[kind])/total if known_seconds else None for kind in windows})
