"""Reproducible regional population fits and exact retrieval, separate from safety."""

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

import numpy as np

from .grid import FEATURES, NORMALIZATION
from .uncertainty import descriptive_source_supported

VERSION = "terrain-representation-v1"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()
    ).hexdigest()


def population(dataset):
    if len(dataset.cells) > 200000:
        raise ValueError("Population exceeds bounded fit limit")
    cells = sorted(dataset.cells, key=lambda c: c.cell_id)
    selected = [
        c
        for c in cells
        if c.valid
        and c.coverage_fraction == 1
        and descriptive_source_supported(c, dataset.metadata)
        and np.isfinite(dataset.raw[dataset.by_id[c.cell_id]]).all()
    ]
    if len(selected) < 2:
        raise ValueError("At least two complete source-backed cells required")
    evidence = dataset.evidence(selected[0])
    if any(dataset.evidence(c) != evidence for c in selected):
        raise ValueError("Population has incompatible scientific support")
    ids = [c.cell_id for c in selected]
    raw = dataset.raw[[dataset.by_id[c] for c in ids]]
    identity = dict(
        dataset_sha256=dataset.digest,
        ids=ids,
        raw=raw.tolist(),
        evidence=evidence,
        source=dataset.metadata.source,
    )
    return ids, raw, digest(identity), evidence


def fit(dataset, dimensions=2):
    if type(dimensions) is not int or not 1 <= dimensions <= 3:
        raise ValueError("PCA dimension must be 1..3")
    ids, raw, input_hash, evidence = population(dataset)
    mean, std = raw.mean(axis=0), raw.std(axis=0)
    # A constant feature maps to zero, explicitly, without inventing variance.
    scales = np.where(std == 0, 1, std)
    fixed = raw / np.array(NORMALIZATION["scales"])
    center = fixed.mean(axis=0)
    _, singular, components = np.linalg.svd(fixed - center, full_matrices=False)
    if dimensions > len(components):
        raise ValueError("Insufficient population for requested dimensions")
    for row in components:
        if row[np.argmax(abs(row))] < 0:
            row *= -1
    variance = singular**2 / (len(ids) - 1)
    ratio = variance / variance.sum() if variance.sum() else np.zeros_like(variance)
    model = dict(
        version=VERSION,
        kind="PCA_FEATURE_EMBEDDING",
        feature_order=FEATURES,
        dataset_id=dataset.metadata.dataset_id,
        dataset_sha256=dataset.digest,
        training_input_sha256=input_hash,
        population_ids=ids,
        missing_policy="Exclude incomplete, invalid, partial or non-source-backed cells; no imputation",
        evidence=evidence,
        preprocessing=NORMALIZATION,
        pca_center=center.tolist(),
        components=components[:dimensions].tolist(),
        dimension=dimensions,
        explained_variance_ratio=ratio[:dimensions].tolist(),
        zscore=dict(
            version="terrain-population-zscore-v1",
            means=mean.tolist(),
            standard_deviations=std.tolist(),
            effective_divisors=scales.tolist(),
            constant_feature_mask=(std == 0).tolist(),
        ),
        numerical_library=dict(
            numpy=np.__version__, algorithm="LAPACK SVD; largest-magnitude loading sign positive"
        ),
        limitations=[
            "Descriptive representation, not safety or uncertainty",
            "Degenerate singular subspaces may rotate across BLAS implementations; persisted model is authoritative",
        ],
    )
    model["model_sha256"] = digest(model)
    return model


def save(model, root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / (model["model_sha256"] + ".json")
    fd, temp = tempfile.mkstemp(dir=root, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(model, f, sort_keys=True, allow_nan=False)
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return target


def load(model_id, root, dataset):
    if not re.fullmatch("[a-f0-9]{64}", model_id):
        raise ValueError("Invalid model ID")
    model = json.loads((Path(root) / (model_id + ".json")).read_text())
    checksum = model.pop("model_sha256")
    if checksum != model_id or digest(model) != checksum or model["version"] != VERSION:
        raise ValueError("Model integrity or version mismatch")
    model["model_sha256"] = checksum
    if population(dataset)[2] != model["training_input_sha256"]:
        raise ValueError("Stale model: training population or source snapshot changed")
    return model


def retrieve(dataset, model, cell_id, space, limit=20):
    if space not in ("physical-scales-v1", "terrain-population-zscore-v1", "PCA_FEATURE_EMBEDDING"):
        raise ValueError("Incompatible vector space")
    ids, raw, current_hash, _ = population(dataset)
    if current_hash != model["training_input_sha256"]:
        raise ValueError("Stale model")
    if cell_id not in ids:
        raise ValueError("Reference is outside fitted population")
    fixed = raw / np.array(NORMALIZATION["scales"])
    if space == "physical-scales-v1":
        values = fixed
    elif space == "terrain-population-zscore-v1":
        values = (raw - model["zscore"]["means"]) / model["zscore"]["effective_divisors"]
    else:
        values = (fixed - model["pca_center"]) @ np.asarray(model["components"]).T
    index = ids.index(cell_id)
    distances = np.linalg.norm(values - values[index], axis=1)
    order = sorted(
        (i for i in range(len(ids)) if i != index), key=lambda i: (float(distances[i]), ids[i])
    )[:limit]
    return dict(
        reference_cell_id=cell_id,
        space=space,
        model_sha256=model["model_sha256"],
        training_input_sha256=current_hash,
        evidence_policy="DESCRIPTIVE_SIMILARITY_ONLY",
        reference_vector=values[index].tolist(),
        matches=[
            dict(
                cell_id=ids[i],
                distance=float(distances[i]),
                physical_differences=(raw[i] - raw[index]).tolist(),
                vector=values[i].tolist(),
            )
            for i in order
        ],
        feature_order=FEATURES,
        scope="Exact Euclidean same-population search; signed physical differences candidate minus reference; no safety interpretation",
    )
