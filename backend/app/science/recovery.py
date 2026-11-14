from datetime import timedelta
from app.metadata import aggregate, iso, parse


def rank_candidates(scenarios):
    eligible = [s for s in scenarios if s['qualifying_status'] == 'QUALIFIES' and s.get('earliest_qualifying_window')]
    return sorted(eligible, key=lambda s: (parse(s['earliest_qualifying_window']['start_utc']),
        -s['earliest_qualifying_window']['duration_minutes'], -s['known_fraction'], s['site_id']))


async def recover_mission(request, analyze_fn):
    missing = [key for key in ('original_site_id', 'original_arrival_utc', 'study_duration_hours') if getattr(request, key) is None]
    body = dict(request=request.model_dump(mode='json'), search_scope={}, original_scenarios=[], delayed_scenarios=[],
        future_scenarios=[], ranked_eligible=[], rejections=[], unknowns=[], alternatives=[], candidates_evaluated=[],
        recommended_site_id=None, recommended_window=None, missing_fields=missing,
        advisory='No actual mission command is issued.', ranking_criteria=['earliest_eligible_start_utc', 'longest_shared_duration', 'source_quality', 'site_id'],
        scientific_disclaimer='Model estimates among evaluated sites and dates only. No flight safety, power or communications certification.')
    if missing:
        return dict(**body, recommended_outcome='NEEDS_INPUT', **aggregate([]))
    original = request.original_arrival_utc
    delayed = original + timedelta(hours=168)
    duration = timedelta(hours=request.study_duration_hours)
    body['search_scope'] = dict(site_ids=request.candidate_site_ids, original_arrival_utc=iso(original), delayed_arrival_utc=iso(delayed),
        study_duration_hours=request.study_duration_hours, future_search_days=request.future_search_days,
        future_arrivals_evaluated=[], future_search_stride_hours=24, continuous_date_search=False,
        min_continuous_overlap_minutes=request.min_continuous_overlap_minutes)
    for key, start in [('original_scenarios', original), ('delayed_scenarios', delayed)]:
        for site in request.candidate_site_ids:
            body[key].append(await analyze_fn(site, start, start+duration, request))
    delayed_scenarios = body['delayed_scenarios']
    own = next(s for s in delayed_scenarios if s['site_id'] == request.original_site_id)
    ranked = rank_candidates(delayed_scenarios)
    selected = None
    if own['qualifying_status'] == 'QUALIFIES':
        outcome, selected = 'KEEP_SITE_AFTER_DELAY', own
    elif own['qualifying_status'] == 'UNKNOWN':
        outcome = 'INSUFFICIENT_DATA'
    elif ranked:
        outcome, selected = 'SWITCH_SITE_AFTER_DELAY', ranked[0]
    else:
        outcome = 'INSUFFICIENT_DATA' if any(s['qualifying_status'] == 'UNKNOWN' for s in delayed_scenarios) else 'NO_QUALIFYING_OPTION_WITHIN_SEARCH'
        for day in range(1, request.future_search_days+1):
            start = delayed + timedelta(days=day)
            body['search_scope']['future_arrivals_evaluated'].append(iso(start))
            day_results = [await analyze_fn(site, start, start+duration, request) for site in request.candidate_site_ids]
            body['future_scenarios'].extend(day_results)
        future_ranked = rank_candidates(body['future_scenarios'])
        # A later known option is useful even if earlier dates are unknown;
        # never claim earliest across unknown dates.
        if future_ranked:
            outcome, selected = 'POSTPONE_AND_REEVALUATE', future_ranked[0]
        elif any(s['qualifying_status'] == 'UNKNOWN' for s in body['future_scenarios']):
            outcome = 'INSUFFICIENT_DATA'
    all_scenarios = body['original_scenarios']+delayed_scenarios+body['future_scenarios']
    body['ranked_eligible'] = rank_candidates(delayed_scenarios+body['future_scenarios'])
    body['candidates_evaluated'] = [s['scenario_id'] for s in all_scenarios]
    body['alternatives'] = [dict(site_id=s['site_id'], scenario_id=s['scenario_id'], qualifying_status=s['qualifying_status']) for s in all_scenarios]
    body['rejections'] = [dict(site_id=s['site_id'], scenario_id=s['scenario_id'], reasons=s['reason_codes']) for s in all_scenarios if s['qualifying_status']=='FAILS']
    body['unknowns'] = [dict(site_id=s['site_id'], scenario_id=s['scenario_id'], reasons=s['reason_codes']) for s in all_scenarios if s['qualifying_status']=='UNKNOWN']
    body['recommended_site_id'] = selected['site_id'] if selected else None
    body['recommended_window'] = selected['earliest_qualifying_window'] if selected else None
    body['recommendation_reason'] = {
        'KEEP_SITE_AFTER_DELAY': 'The delayed original site meets the modeled continuous-window requirement.',
        'SWITCH_SITE_AFTER_DELAY': 'The delayed original site fails; the ranked alternative meets the modeled requirement.',
        'POSTPONE_AND_REEVALUATE': 'A modeled qualifying option exists on an explicitly evaluated later arrival date.',
        'INSUFFICIENT_DATA': 'Unknown observations or unsupported terrain prevent a definitive comparison.',
        'NO_QUALIFYING_OPTION_WITHIN_SEARCH': 'No modeled qualifying window was found at the evaluated sites and arrival dates.',
    }[outcome]
    return dict(**body, recommended_outcome=outcome, **aggregate(all_scenarios))
