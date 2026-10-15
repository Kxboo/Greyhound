"""Validate captured terrain layer identities before replaying their shaders."""
import struct


def runtime_layer_issues(sector):
    issues = []
    index = sector["sector"]
    layers = sector.get("layers", [])
    if not layers:
        return [f"sector {index}: no captured layers"]
    for layer in layers:
        slot = layer["slot"]
        prefix = f"sector {index} layer {slot}"
        runtime = layer.get("runtime")
        if not runtime or not runtime.get("raw_hex"):
            issues.append(f"{prefix}: runtime record missing")
            continue
        try:
            raw = bytes.fromhex(runtime["raw_hex"])
        except (ValueError, TypeError):
            raw = b""
        if len(raw) != 112:
            issues.append(f"{prefix}: expected 112 runtime bytes, got {len(raw)}")
            continue
        expected = layer.get("weight_source_slice")
        actual = struct.unpack_from("<I", raw, 32)[0]
        if expected is None:
            issues.append(f"{prefix}: source weight-slice identity missing")
        elif actual != int(expected):
            issues.append(f"{prefix}: runtime weight slice {actual} != captured source slice {expected}")
        uv = layer.get("uv_matrix_2x4")
        if uv is None or len(uv) != 8:
            issues.append(f"{prefix}: source UV rows missing")
        elif raw[:32] != struct.pack("<8f", *uv):
            issues.append(f"{prefix}: runtime UV rows do not match source")
    return issues


def require_runtime_layers(sectors):
    issues = [issue for sector in sectors for issue in runtime_layer_issues(sector)]
    if issues:
        raise ValueError(
            "BO4 terrain runtime layer capture is incomplete or mismatched: "
            + "; ".join(issues)
            + ". Recapture with the shared weight-slice reader fix before shader baking."
        )
