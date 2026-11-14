"""Reproduce real source downloads, terrain snapshots and visual layers."""

import argparse
from pathlib import Path

from lunar_global.features import ingest_lola
from lunar_global.imagery import register_lroc
from lunar_global.layers import add_context_layers, add_imagery_layer, build_layers
from lunar_global.sources import download, register_lola
from lunar_global.storage import verified_files
from lunar_global.thermal import BASE, NAME, ingest_diviner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/lunar-v1"))
    args = parser.parse_args()
    register_lola(args.root / "source_products/lola")
    manifests = list((args.root / "feature_snapshots/nside=128").glob("*/manifest.json"))
    if manifests:
        for manifest in manifests:
            verified_files(manifest.parent)
    else:
        ingest_lola(args.root)
    register_lroc(args.root)
    directory = args.root / "source_products/diviner"
    for suffix in (".lbl", ".tab"):
        download(BASE + NAME + suffix, directory, 192 * 1024 * 1024)
    download(
        "https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/label/dlre_gcp.fmt",
        directory,
    )
    manifests = list((args.root / "thermal_snapshots").glob("*/manifest.json"))
    if manifests:
        for manifest in manifests:
            verified_files(manifest.parent)
    else:
        ingest_diviner(args.root)
    if not (args.root / "visualization_tiles/layers.json").exists():
        build_layers(args.root)
    if not (args.root / "visualization_tiles/layers-v2.json").exists():
        add_context_layers(args.root)
    if not (args.root / "visualization_tiles/layers-v3.json").exists():
        add_imagery_layer(args.root)
    print("Verified LOLA, LROC and Diviner inputs; scientific snapshots and layers ready")


if __name__ == "__main__":
    main()
