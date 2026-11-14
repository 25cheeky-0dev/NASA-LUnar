"""Supplied atlas facade over canonical persistent region identities and jobs."""
import json,os
from pathlib import Path
from fastapi import APIRouter,HTTPException
from pydantic import Field
from app.regions.api import Selection,select,safe
from app.regions.tools import Strict
from app.regions.agent import AnalyzeRequest,launch
from app.regions import store
from .service import GlobalStore
router=APIRouter(prefix='/api/v1/science/adaptive',tags=['adaptive-atlas'])
class AtlasScreen(Strict):
    maximum_slope_deg:float=Field(default=5,ge=0,le=90)
    maximum_roughness_m:float|None=Field(default=None,ge=0)
    minimum_coverage:float=Field(default=1,ge=0,le=1)
    limit:int=Field(default=50,ge=1,le=100)
class RegionSelection(Strict):
    kind:str='POINT'
    latitude_deg:float|None=None
    longitude_deg:float|None=None
    target_width_m:float=250
    coordinates_lonlat:list[list[float]]|None=None
@router.post('/regions/select')
def select_region(req:RegionSelection):
    if req.kind=='POINT':s=safe(Selection,latitude=req.latitude_deg,longitude=req.longitude_deg,target_width_m=req.target_width_m)
    elif req.kind=='POLYGON':
        ring=req.coordinates_lonlat or []
        if len(ring)<3:raise HTTPException(422,'At least three polygon vertices required')
        if ring[0]!=ring[-1]:ring=ring+[ring[0]]
        s=safe(Selection,geometry={'type':'Polygon','coordinates':[ring]},target_width_m=req.target_width_m)
    else:raise HTTPException(422,'Unknown selection kind')
    c=select(s);g=c['region']
    return dict(g,center={'latitude_deg':g['latitude_deg'],'longitude_deg':g['longitude_deg']},boundary_lonlat=g['geometry']['coordinates'][0],context=c)
@router.get("/atlas/layers")
def atlas_layers():
    root = Path(os.getenv("WISPR_GLOBAL_ROOT", "data/lunar-v1"))
    manifest = root / "visualization_tiles" / "layers.json"
    if not manifest.exists():
        return {"records": [], "status": "NOT_BUILT", "build_hint": "python -m scripts.build_global"}
    try:
        layers = json.loads(manifest.read_text())
        # Existing global API verifies the layer file checksum on every image request.
        return {"records": [
            {"id": row["layer_id"], "color_legend":row.get("color_legend"), "status": row["status"], "units": row.get("units"),
             "minimum": row.get("minimum"), "maximum": row.get("maximum"),
             "native_resolution_m": row.get("native_resolution_m"),
             "source_id": row.get("source_id"), "snapshot_id": row.get("snapshot_id"),
             "description": row.get("rendering", row.get("reason", "")),
             "image_path": f"/api/v1/science/global/layer-images/{row['layer_id']}" if row["status"] == "AVAILABLE" else None}
            for row in layers], "status": "AVAILABLE"}
    except (ValueError, KeyError) as exc:
        raise HTTPException(503, "Layer manifest invalid") from exc


@router.post("/atlas/screen")
def screen_global_terrain(request: AtlasScreen):
    """Scan whole available NSIDE-128 snapshot; descriptive screening, not landing safety."""
    from .storage import query
    try:
        paths, manifest = GlobalStore(os.getenv("WISPR_GLOBAL_ROOT", "data/lunar-v1")).feature_files(128)
    except (ValueError, FileNotFoundError, OSError) as exc:
        raise HTTPException(503, "Verified global terrain snapshot unavailable") from exc
    if not paths:
        raise HTTPException(503, "No source-backed global terrain features available")
    where = ["elevation_m_coverage >= ?", "slope_deg_coverage >= ?", "roughness_m_coverage >= ?",
             "slope_deg IS NOT NULL", "roughness_m IS NOT NULL", "slope_deg <= ?"]
    parameters = [request.minimum_coverage] * 3 + [request.maximum_slope_deg]
    if request.maximum_roughness_m is not None:
        where.append("roughness_m <= ?")
        parameters.append(request.maximum_roughness_m)
    try:
        rows = query(paths, " AND ".join(where), parameters, request.limit, 0,
                     columns="cell_id,latitude_deg,longitude_deg,slope_deg,roughness_m,elevation_m,source_id,native_resolution_m,quality",
                     order="slope_deg ASC, roughness_m ASC, cell_id ASC")
    except (ValueError, OSError) as exc:
        raise HTTPException(503, "Global feature query failed") from exc
    return {
        "results": rows,
        "snapshot_id": manifest.get("snapshot_id"),
        "screening_level": 128,
        "selection_scope": "Global indexed terrain cells with complete source-backed inputs",
        "scientific_warning": "Exploratory ranking using coarse native DEM derivatives only. Not landing safety, not high-resolution terrain clearance.",
        "total_matching_count": None,
        "filter": request.model_dump(),
    }


@router.get('/atlas/elevation')
def global_elevation():
    import numpy as np
    from app.explorer import terrain_source
    root=os.getenv('WISPR_GLOBAL_ROOT','data/lunar-v1')
    try:
        image=Path(root)/'source_products/lola/ldem_4.img';stat=image.stat()
        source,arrays=terrain_source(root,stat.st_size,stat.st_mtime_ns)
    except (OSError,ValueError) as exc:raise HTTPException(503,'Verified global elevation unavailable') from exc
    # Bounded one-degree display samples. Measurements remain native source data.
    values=arrays[0][::4,::4]
    return {'rows':180,'columns':360,'elevation_m':[[float(v) if np.isfinite(v) else None for v in row] for row in values],
            'latitude_origin':89.875,'longitude_origin':.125,'spacing_degrees':1,
            'reference_radius_m':1737400,'source':source.model_dump(),'purpose':'DISPLAY_ONLY_NATIVE_DECIMATION'}
