"""Pin/net index primitives (kicad_core). Round 2 seeds it with the two net helpers that lived in kicad_utils; round 3 adds the typed index builders and BridgeFact."""


def get_two_pin_nets(pin_net: dict, ref: str) -> tuple[str | None, str | None]:
    """Get the two nets a 2-pin component connects to.

    Takes pin_net map explicitly instead of closing over it.
    Falls back to enumerating all pins when "1"/"2" aren't found.
    """
    n1, _ = pin_net.get((ref, "1"), (None, None))
    n2, _ = pin_net.get((ref, "2"), (None, None))
    if n1 is not None and n2 is not None:
        return n1, n2
    # Fallback for non-"1"/"2" pin numbering (Eagle imports, diodes A/K, etc.)
    ref_entries = {k[1]: v for k, v in pin_net.items() if k[0] == ref}
    if len(ref_entries) == 2:
        nets = [net for net, _ in ref_entries.values()]
        return nets[0], nets[1]
    return n1, n2


def build_net_id_map(pcb):
    """Return {net_id (int): net_name (str)} from PCB JSON.

    Handles both the current flat form pcb['nets'] = {"6": "GND", ...}
    and the legacy nested form pcb['nets']['net_info'] = [{"id": 6, ...}, ...].
    """
    nets = pcb.get('nets', {})
    out = {}
    if isinstance(nets, dict):
        for k, v in nets.items():
            if isinstance(v, str):
                try:
                    out[int(k)] = v
                except (ValueError, TypeError):
                    continue
        if out:
            return out
        for ni in nets.get('net_info', []) or []:
            try:
                out[int(ni.get('id', -1))] = ni.get('name', '')
            except (ValueError, TypeError):
                continue
    return out
