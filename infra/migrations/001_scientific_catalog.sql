BEGIN;
CREATE EXTENSION IF NOT EXISTS postgis;
INSERT INTO spatial_ref_sys(srid,auth_name,auth_srid,srtext,proj4text)
VALUES (910001,'WISPR',910001,'GEOGCS["Moon ME DE421",DATUM["Moon ME DE421",SPHEROID["Moon",1737400,0]],PRIMEM["Reference meridian",0],UNIT["degree",0.0174532925199433]]','+proj=longlat +R=1737400 +no_defs')
ON CONFLICT (srid) DO NOTHING;
CREATE TABLE IF NOT EXISTS source_product (
 source_id text PRIMARY KEY, product_version text NOT NULL, sha256 text NOT NULL CHECK(length(sha256)=64),
 metadata jsonb NOT NULL, object_uri text, created_utc timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS lunar_cell (
 dataset_id text NOT NULL, cell_id text NOT NULL, grid_version text NOT NULL,
 coordinate_frame text NOT NULL CHECK(coordinate_frame='MOON_ME_DE421'),
 longitude_deg double precision NOT NULL, latitude_deg double precision NOT NULL,
 boundary geometry(Geometry,910001), measurements jsonb NOT NULL, provenance jsonb NOT NULL,
 PRIMARY KEY(dataset_id,cell_id)
);
CREATE INDEX IF NOT EXISTS lunar_cell_boundary ON lunar_cell USING gist(boundary);
CREATE INDEX IF NOT EXISTS lunar_cell_location ON lunar_cell(dataset_id,latitude_deg,longitude_deg);
CREATE TABLE IF NOT EXISTS evidence (
 id text PRIMARY KEY CHECK(length(id)=64), kind text NOT NULL, created_utc timestamptz NOT NULL DEFAULT now(),
 payload bytea NOT NULL
);
CREATE INDEX IF NOT EXISTS evidence_kind_time ON evidence(kind,created_utc DESC);
CREATE TABLE IF NOT EXISTS representation (
 model_sha256 text PRIMARY KEY, dataset_id text NOT NULL, source_fingerprint text NOT NULL,
 feature_definition text NOT NULL, metadata jsonb NOT NULL, object_uri text NOT NULL
);
COMMIT;
-- Lunar angular geometry only: never cast these geometries to Earth geography.
-- Physical distances use the existing lunar spherical/projected algorithms.
