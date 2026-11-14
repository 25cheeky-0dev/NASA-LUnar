export type Outcome = 'KEEP_SITE_AFTER_DELAY' | 'SWITCH_SITE_AFTER_DELAY' | 'POSTPONE_AND_REEVALUATE' | 'NO_QUALIFYING_OPTION_WITHIN_SEARCH' | 'INSUFFICIENT_DATA' | 'NEEDS_INPUT';
export type SiteID = 'R01' | 'R04';
export interface MissionRequest {
  original_site_id: SiteID | null; original_arrival_utc: string | null; study_duration_hours: number | null;
  delay_hours: 168; min_continuous_overlap_minutes: number; candidate_site_ids: SiteID[];
  horizon_model: 'GEOMETRIC' | 'LOCAL_TERRAIN'; observer_height_m: number; step_minutes: number; future_search_days: number;
}
export interface Sky { az_deg: number | null; el_deg: number | null; east: number | null; north: number | null; up: number | null; status: 'KNOWN' | 'UNKNOWN' }
export interface Record { timestamp_utc: string; sun: Sky | null; earth: Sky | null; status: 'KNOWN' | 'UNKNOWN'; gap_reason: string | null }
export interface Window { start_utc: string; end_utc: string; duration_minutes: number; kind: 'SUN' | 'EARTH' | 'BOTH'; estimate_status: string; boundary_uncertainty_seconds: number; model: string }
export interface Provenance { source_urls?: string[]; raw_sha256?: string[]; sample_step_minutes?: number | null; [key: string]: unknown }
export interface Scientific { source_type: string; calculation_mode: string; data_quality: string; limitations: string[]; provenance: Provenance; computed_at_utc?: string; api_version?: string; backend_version?: string }
export interface Scenario extends Scientific {
  scenario_id: string; site_id: SiteID; arrival_utc: string; end_utc: string; horizon_model: string;
  sun_windows: Window[]; earth_windows: Window[]; shared_windows: Window[]; longest_shared_minutes: number | null;
  earliest_qualifying_window: Window | null; known_fraction: number; unknown_fraction: number;
  qualifying_status: 'QUALIFIES' | 'FAILS' | 'UNKNOWN'; reason_codes: string[]; visibility_series: Record[];
  unknown_intervals?: { start_utc: string; end_utc: string; reason: string }[]; time_to_first_qualifying_minutes?: number | null;
}
export interface Recovery extends Scientific {
  request: MissionRequest; original_scenarios: Scenario[]; delayed_scenarios: Scenario[]; future_scenarios?: Scenario[];
  ranked_eligible: Scenario[]; recommended_outcome: Outcome; recommended_site_id: SiteID | null;
  recommended_window: Window | null; recommendation_reason?: string; missing_fields?: string[];
  search_scope: { original_arrival_utc?: string; delayed_arrival_utc?: string; study_duration_hours?: number; future_search_days?: number; future_arrivals_evaluated?: string[] };
  rejections: unknown[]; unknowns: unknown[]; scientific_disclaimer: string;
}
export interface Cell { cell_id: string; grid_version: string; cell_size_m: number; center_lat_deg: number; center_lon_east_deg: number; center_x_m: number; center_y_m: number; boundary_lonlat_east: number[][]; raster_coverage: string; ephemeris_status: string; observations_represent_center_only: boolean }
export interface Grid { site_id: SiteID; cells: Cell[]; center_cell_id: string; projection: { wkt_or_proj: string } }
export interface Feature { cell_id: string; scenario_id: string; feature_names: string[]; values: (number | null)[]; quality: string; observation_point_type?: string; site_id?: SiteID }
export interface Features { points: Feature[]; reference_points?: Feature[]; scatter_axes: { x: string; y: string; z: string } }
export const BASE = (import.meta.env.VITE_API_BASE_URL ?? (import.meta.env.PROD ? '' : 'http://localhost:8000')).replace(/\/$/, '');
export const MOCK = import.meta.env.VITE_USE_MOCKS === 'true';
export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(BASE + path, { method: body === undefined ? 'GET' : 'POST', headers: body === undefined ? {} : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(240000) });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail ?? data.error_code ?? response.status));
  return data as T;
}
