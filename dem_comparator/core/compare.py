"""Pairwise comparison of aligned DEMs.

For a list of aligned rasters we either:

- generate every C(n,2) pair difference, or
- use one raster as the reference and subtract it from the others.

Output: difference GeoTIFFs on disk and per-pair statistics (mean bias,
MAE, RMSE, std-dev, min, max, count of valid pixels).
"""
from __future__ import annotations

import itertools
import os
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

import numpy as np
from osgeo import gdal

from .align import NODATA

_PAIR_INDEX_PREFIX = "DIFF_"


@dataclass
class PairStat:
    """Stats describing the difference of one DEM against another."""

    label_a: str
    label_b: str
    valid_pixels: int
    mean_bias: float
    mae: float
    rmse: float
    std_dev: float
    diff_min: float
    diff_max: float
    diff_raster: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ComparisonResult:
    """Container returned by :class:`Comparator`."""

    pairs: List[PairStat]
    reference: Optional[str]
    labels: List[str]

    def as_dict(self) -> dict:
        return {
            "reference": self.reference,
            "labels": list(self.labels),
            "pairs": [p.as_dict() for p in self.pairs],
        }


class Comparator:
    """Compute DEM-A minus DEM-B rasters and per-pair stats."""

    def __init__(
        self,
        output_dir: str,
        reference: Optional[str] = None,
    ) -> None:
        """``reference`` = label of the reference raster, or None for all-pairs."""
        self.output_dir = output_dir
        self.reference = reference
        os.makedirs(self.output_dir, exist_ok=True)

    # ---------------------------------------------------------- public
    def compare(self, rasters: List[Tuple[str, str]]) -> ComparisonResult:
        """Compute differences.

        :param rasters: list of (label, aligned_path) pairs.
        :returns: ComparisonResult with paths and stats.
        """
        labels = [label for label, _ in rasters]
        labels_set = set(labels)

        if self.reference is not None:
            if self.reference not in labels_set:
                raise ValueError(
                    f"Reference raster '{self.reference}' is not in the supplied list"
                )
            ref_label, ref_path = next((l, p) for l, p in rasters if l == self.reference)
            pairs_to_compute = [
                (other_label, other_path)
                for other_label, other_path in rasters
                if other_label != ref_label
            ]
        else:
            ref_label = None
            pairs_to_compute = []

        pair_stats: List[PairStat] = []

        if self.reference is not None:
            ref_arr, ref_ds = _read_as_float(ref_path)
            try:
                for other_label, other_path in pairs_to_compute:
                    other_arr, _ = _read_as_float(other_path)
                    other_arr = _match_extent(arr=other_arr, ds=other_arr.shape, ref_ds=ref_ds)
                    diff_path, stats = _write_diff_and_stats(
                        ref_label,
                        other_label,
                        ref_arr,
                        other_arr,
                        ref_ds,
                        self.output_dir,
                    )
                    pair_stats.append(stats)
            finally:
                ref_ds = None
        else:
            # All pairs.
            for (la, pa), (lb, pb) in itertools.combinations(rasters, 2):
                a_arr, a_ds = _read_as_float(pa)
                b_arr, b_ds = _read_as_float(pb)
                try:
                    # They were warped to the same grid, but be defensive.
                    b_arr = _match_extent(arr=b_arr, ds=b_arr.shape, ref_ds=a_ds)
                    diff_path, stats = _write_diff_and_stats(
                        la, lb, a_arr, b_arr, a_ds, self.output_dir
                    )
                    pair_stats.append(stats)
                finally:
                    a_ds = None
                    b_ds = None

        return ComparisonResult(pairs=pair_stats, reference=self.reference, labels=labels)


# ---------------------------------------------------------------------- helpers


def _read_as_float(path: str) -> Tuple[np.ndarray, "gdal.Dataset"]:
    """Load a single-band raster as a masked float array."""
    ds = gdal.Open(path, gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError(f"Cannot open raster: {path}")
    band = ds.GetRasterBand(1)
    nodata = band.GetNoDataValue()
    if nodata is None:
        nodata = NODATA
    arr = band.ReadAsArray().astype(np.float32)
    return _as_masked(arr, nodata), ds


def _as_masked(arr: np.ndarray, nodata: float) -> np.ndarray:
    """Return a numpy masked array where nodata pixels are masked."""
    masked = np.ma.masked_array(arr, mask=np.isclose(arr, nodata))
    return np.ma.filled(masked, np.nan)


def _match_extent(arr: np.ndarray, ds, ref_ds) -> np.ndarray:
    """Best-effort crop/pad ``arr`` so its shape matches ``ref_ds``."""
    if arr.shape == (ref_ds.RasterYSize, ref_ds.RasterXSize):
        return arr
    ry, rx = ref_ds.RasterYSize, ref_ds.RasterXSize
    h, w = arr.shape
    out = np.full((ry, rx), np.nan, dtype=np.float32)
    h2 = min(h, ry)
    w2 = min(w, rx)
    out[:h2, :w2] = arr[:h2, :w2]
    return out


def _write_diff_and_stats(
    label_a: str,
    label_b: str,
    a: np.ndarray,
    b: np.ndarray,
    a_ds,
    output_dir: str,
) -> Tuple[str, PairStat]:
    """Write a difference raster and compute its stats."""
    valid = ~np.isnan(a) & ~np.isnan(b)
    diff = a - b
    diff_only_valid = diff[valid]
    count = int(valid.sum())

    if count == 0:
        # No overlapping valid pixels: emit NaNs but still produce a raster.
        mean_bias = mae = rmse = std_dev = diff_min = diff_max = float("nan")
    else:
        mean_bias = float(np.mean(diff_only_valid))
        mae = float(np.mean(np.abs(diff_only_valid)))
        rmse = float(np.sqrt(np.mean(np.square(diff_only_valid))))
        std_dev = float(np.std(diff_only_valid))
        diff_min = float(np.min(diff_only_valid))
        diff_max = float(np.max(diff_only_valid))

    base = f"{_PAIR_INDEX_PREFIX}{label_a}_minus_{label_b}.tif"
    out_path = os.path.join(output_dir, base)

    # Write a Float32 raster with NaN-pixels as nodata (we use -9999 for GDAL).
    diff_filled = np.where(np.isnan(diff), NODATA, diff).astype(np.float32)
    _write_raster(out_path, a_ds, diff_filled, nodata=NODATA)

    stats = PairStat(
        label_a=label_a,
        label_b=label_b,
        valid_pixels=count,
        mean_bias=mean_bias,
        mae=mae,
        rmse=rmse,
        std_dev=std_dev,
        diff_min=diff_min,
        diff_max=diff_max,
        diff_raster=out_path,
    )
    return out_path, stats


def _write_raster(path: str, template_ds, array: np.ndarray, nodata: float) -> None:
    """Write ``array`` to ``path`` using ``template_ds`` as spatial reference."""
    driver = gdal.GetDriverByName("GTiff")
    if driver is None:
        raise RuntimeError("GTiff driver not available")
    out = driver.Create(
        path,
        template_ds.RasterXSize,
        template_ds.RasterYSize,
        1,
        gdal.GDT_Float32,
        ["COMPRESS=DEFLATE"],
    )
    if out is None:
        raise RuntimeError(f"Cannot create raster: {path}")
    out.SetGeoTransform(template_ds.GetGeoTransform())
    out.SetProjection(template_ds.GetProjection())
    band = out.GetRasterBand(1)
    band.SetNoDataValue(nodata)
    band.WriteArray(array)
    out.FlushCache()
    out = None


def stats_summary(pairs: List[PairStat]) -> Dict[str, List[PairStat]]:
    """Group pairs by reference DEM to make the report easy to read."""
    grouped: Dict[str, List[PairStat]] = {}
    for p in pairs:
        grouped.setdefault(p.label_a, []).append(p)
    return grouped
