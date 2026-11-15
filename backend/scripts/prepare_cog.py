"""Generate a bounded, hash-recorded lunar COG from the verified LOLA source."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import rasterio
from rasterio.transform import from_origin
from lunar_global.sources import SourceProduct
from lunar_global.features import native_terrain
from lunar_global.grid import RADIUS_M
from lunar_global.storage import sha256


def build(root):
    root=Path(root)
    source=SourceProduct.model_validate_json((root/'source_products/lola/source.json').read_text())
    z,_,_=native_terrain(root/'source_products/lola/ldem_4.img',source)
    output=root/'derived/lola-ldem4-elevation.cog.tif'
    manifest=output.with_suffix('.json')
    if output.exists():
        old=json.loads(manifest.read_text())
        if old['source_sha256']!=source.source_checksum or old['sha256']!=sha256(output):
            raise ValueError('Existing COG source or output hash mismatch')
        return old
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.with_suffix('.partial.tif')
    step=np.pi*RADIUS_M/720
    with rasterio.open(temporary,'w',driver='COG',width=1440,height=720,count=1,dtype='float32',
                       crs=f'+proj=eqc +lat_ts=0 +lon_0=0 +R={RADIUS_M} +units=m',
                       transform=from_origin(0,np.pi*RADIUS_M/2,step,step),
                       compress='DEFLATE',blocksize=256,nodata=float('nan'),overview_resampling='average') as dst:
        dst.write(z.astype('float32'),1)
        dst.update_tags(source_id=source.source_id,source_sha256=source.source_checksum,
                        coordinate_frame=source.coordinate_frame,vertical_reference=source.vertical_reference,units='m')
    with rasterio.open(temporary) as raster:
        assert raster.crs is not None and raster.width==1440 and raster.height==720
        assert np.allclose(raster.read(1),z)
    temporary.replace(output)
    result={'source_sha256':source.source_checksum,'sha256':sha256(output),
            'source':source.model_dump(),'processing':'decode int16 x0.5; lunar equidistant cylindrical; lossless float32 COG',
            'output':output.name,'units':'m','grid_version':'native-LDEM4-0.25deg',
            'scientific_limitations':['Overview data only; no datum compatibility with Horizons asserted.']}
    manifest.write_text(json.dumps(result,indent=2))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',default='data/lunar-v1');a=p.parse_args()
    print(json.dumps(build(a.root),indent=2))
