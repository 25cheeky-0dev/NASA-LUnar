SITES = {
    'R01': dict(site_id='R01', name='Connecting Ridge', lat_deg=-89.4632, lon_east_deg=222.51, dem_site_id='Site01'),
    'R04': dict(site_id='R04', name='Shackleton Rim', lat_deg=-89.7668, lon_east_deg=188.13, dem_site_id='Site04'),
}
SITE_WARNING = 'Team-supplied reference-region coordinates; not certified landing sites or independently verified NASA DEM centers.'
for site in SITES.values():
    site.update(reference_region_not_certified_site=True, dem_status='UNVERIFIED', geometry_source=SITE_WARNING)
