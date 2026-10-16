"""Facade for pre-v3 importers: the copper connectivity graph lives in pcb/connectivity.py.

Consumer: user scripts and the scripts README; no harness import (inventory 2026-10-14). Retire round 9.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pcb.connectivity import (  # noqa: E402,F401
    UnionFind, _SpatialGrid, _bucket_coord, _dist_point_to_segment, _expand_copper_layers,
    _node_fill_regions, _node_probe_points, _stackup_sort_key, build_connectivity_graph,
)
