import copy
import json

import numpy as np
import pytest

from app.integration import representations as rep
from app.integration.uncertainty import uncertainty_status
from tests.test_integration import dataset as dataset
from tests.test_integration import payload as payload


def test_representation_distances_and_persistence(dataset, tmp_path):
    model = rep.fit(dataset, 3)
    rep.save(model, tmp_path)
    loaded = rep.load(model["model_sha256"], tmp_path, dataset)
    assert loaded == model
    assert rep.fit(dataset, 3) == model
    cell_id = dataset.cells[0].cell_id
    physical = rep.retrieve(dataset, model, cell_id, "physical-scales-v1")
    embedded = rep.retrieve(dataset, model, cell_id, "PCA_FEATURE_EMBEDDING")
    assert [m["distance"] for m in embedded["matches"]] == pytest.approx(
        [m["distance"] for m in physical["matches"]], abs=1e-12
    )
    assert physical["matches"][0]["distance"] == pytest.approx(0.001)
    assert physical["matches"][0]["physical_differences"] == [1, 0, 0]
    z = rep.retrieve(dataset, model, cell_id, "terrain-population-zscore-v1")
    assert z["matches"][0]["distance"] == pytest.approx(1 / np.sqrt(2 / 3))
    assert model["zscore"]["constant_feature_mask"] == [False, True, True]
    dataset.digest = "changed"
    with pytest.raises(ValueError, match="Stale"):
        rep.load(model["model_sha256"], tmp_path, dataset)


def test_model_corruption_and_invalid_space(dataset, tmp_path):
    model = rep.fit(dataset)
    path = rep.save(model, tmp_path)
    altered = copy.deepcopy(model)
    altered["components"][0][0] += 1
    path.write_text(json.dumps(altered))
    with pytest.raises(ValueError, match="integrity"):
        rep.load(model["model_sha256"], tmp_path, dataset)
    with pytest.raises(ValueError):
        rep.load("../escape", tmp_path, dataset)
    with pytest.raises(ValueError):
        rep.retrieve(dataset, model, dataset.cells[0].cell_id, "wrong-v2")


@pytest.mark.parametrize(
    "mutation", ["source", "unit", "negative", "null", "boolean", "definition"]
)
def test_uncertainty_semantics(dataset, mutation):
    c = dataset.cells[0]
    assert uncertainty_status(c, dataset.metadata) == "VERIFIED_NUMERICAL_UNCERTAINTY"
    if mutation == "source":
        c.uncertainty["source_id"] = "wrong"
    elif mutation == "definition":
        c.uncertainty["terrain_definition"] = "wrong"
    elif mutation == "unit":
        c.uncertainty["measurements"]["elevation_m"]["unit"] = "km"
    else:
        c.uncertainty["measurements"]["elevation_m"]["standard_uncertainty"] = {
            "negative": -1,
            "null": None,
            "boolean": True,
        }[mutation]
    assert uncertainty_status(c, dataset.metadata) == "INCOMPATIBLE_EVIDENCE"
    with pytest.raises(ValueError):
        dataset.similarity(c.cell_id, accept_unknown_uncertainty=True)


def test_unknown_requires_explicit_policy(dataset):
    for c in dataset.cells:
        c.uncertainty = {"sigma_m": None}
    with pytest.raises(ValueError):
        dataset.similarity(dataset.cells[0].cell_id)
    result = dataset.similarity(dataset.cells[0].cell_id, accept_unknown_uncertainty=True)
    assert result["evidence_policy"] == "DESCRIPTIVE_SIMILARITY_ONLY"
    assert len(result["matches"]) == 2


def test_unverified_obstruction_never_proves_visibility():
    from app.integration.engine import visibility

    horizon = dict(
        model="TERRAIN_PARTIAL",
        observer_reference_compatible=True,
        azimuth_samples=[dict(azimuth_deg=10, terrain_horizon_elevation_deg=50)],
    )
    assert visibility(10, 1, horizon)["modeled_visible"] is None


def test_representation_http_missing_corrupt_and_capacity(dataset, monkeypatch, tmp_path):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from app.integration import api
    from app.main import app

    monkeypatch.setenv("WISPR_MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(
        api,
        "engine",
        lambda: SimpleNamespace(
            registry=SimpleNamespace(datasets={dataset.metadata.dataset_id: dataset}, errors=[])
        ),
    )
    with TestClient(app) as client:
        request = dict(
            dataset_id=dataset.metadata.dataset_id,
            model_id="0" * 64,
            cell_id=dataset.cells[0].cell_id,
            accept_descriptive_similarity=True,
        )
        assert (
            client.post("/api/v1/science/representations/search", json=request).status_code == 404
        )
        fitted = client.post(
            "/api/v1/science/representations/fit",
            json=dict(dataset_id=dataset.metadata.dataset_id, dimensions=2),
        )
        assert fitted.status_code == 200
        request["model_id"] = fitted.json()["metadata"]["model_sha256"]
        assert (
            client.post("/api/v1/science/representations/search", json=request).status_code == 200
        )
        api._gate.acquire()
        api._gate.acquire()
        try:
            assert (
                client.post("/api/v1/science/representations/search", json=request).status_code
                == 429
            )
        finally:
            api._gate.release()
            api._gate.release()
        dataset.digest = "stale"
        assert (
            client.post("/api/v1/science/representations/search", json=request).status_code == 422
        )
        request["model_id"] = "../bad"
        assert (
            client.post("/api/v1/science/representations/search", json=request).status_code == 422
        )


def test_thermal_request_rejects_invalid_channels_and_bounds():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        query = "/api/v1/science/global/thermal-observations?west=1&east=2&south=-90&north=-89&local_time_bin=0"
        assert client.get(query + "&channel=made_up").status_code == 422
        assert client.get(query.replace("east=2", "east=0")).status_code == 422


def test_native_topology_rejects_unreciprocated_edges():
    from pyproj import CRS, Transformer
    from shapely.geometry import box

    from app.integration.topology import validate_topology

    crs = CRS.from_proj4("+proj=stere +lat_0=-90 +lon_0=0 +R=1737400 +units=m")
    inverse = Transformer.from_crs(crs, crs.geodetic_crs, always_xy=True)
    rows, geometry = [], {}
    for i in range(2):
        x, y = 100 + i * 100, 100
        lon, lat = inverse.transform(x, y)
        key = str(i)
        polygon = box(x - 50, y - 50, x + 50, y + 50)
        rows.append(dict(cell_id=key, x_m=x, y_m=y, longitude=lon, latitude=lat))
        geometry[key] = dict(
            geometry_wkb=polygon.wkb, xmin_m=x - 50, ymin_m=y - 50, xmax_m=x + 50, ymax_m=y + 50
        )
    validate_topology(rows, geometry, {"0": ["1"], "1": ["0"]}, crs.to_wkt())
    with pytest.raises(ValueError, match="Nonreciprocal"):
        validate_topology(rows, geometry, {"0": ["1"], "1": []}, crs.to_wkt())
    with pytest.raises(ValueError, match="duplicate"):
        validate_topology(rows, geometry, {"0": ["1", "1"], "1": ["0"]}, crs.to_wkt())
    geometry["1"]["geometry_wkb"] = b"corrupt"
    with pytest.raises(ValueError, match="Corrupt"):
        validate_topology(rows, geometry, {"0": ["1"], "1": ["0"]}, crs.to_wkt())


@pytest.mark.parametrize(
    "url",
    [
        "https://pds-geosciences.wustl.edu:444/data",
        "https://user:pass@pds-geosciences.wustl.edu/data",
        "https://pds-geosciences.wustl.edu.evil.example/data",
        "http://pds-geosciences.wustl.edu/data",
    ],
)
def test_source_url_restrictions(url, tmp_path):
    from lunar_global.sources import download

    with pytest.raises(ValueError):
        download(url, tmp_path)
