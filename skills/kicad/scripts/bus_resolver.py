"""Facade (v3 round 4): bus resolution lives in schematic/connectivity.py beside build_net_map. Retires in round 9."""
from schematic.connectivity import (  # noqa: F401
    BusGraph, expand_bus_name, match_ports,
    _EPSILON, _GROUP_RE, _MAX_DEPTH, _VECTOR_RE, _point_on_segment,
)
