"""Read battery info directly from the Linux kernel's power_supply sysfs interface.

This works on any Linux distro (it's the same interface upower itself reads), with no
dependency on the upower daemon/CLI. Output keys and units match `upower_to_dict()`, so
both sources produce the same columns.

Kernel docs: https://www.kernel.org/doc/Documentation/ABI/testing/sysfs-class-power
Units in sysfs: µWh (energy_*), µAh (charge_*), µW (power_*), µA (current_*), µV (voltage_*).
"""

from pathlib import Path

POWER_SUPPLY_DIR = Path("/sys/class/power_supply")

# Map kernel values onto upower's vocabulary, for continuity with data logged via upower.
STATE_MAP = {
    "charging": "charging",
    "discharging": "discharging",
    "full": "fully-charged",
    "not charging": "pending-charge",
    "unknown": "unknown",
}
TECHNOLOGY_MAP = {
    "li-ion": "lithium-ion",
    "li-poly": "lithium-polymer",
    "life": "lithium-iron-phosphate",
    "nimh": "nickel-metal-hydride",
    "nicd": "nickel-cadmium",
    "limn": "lithium-manganese",
    "unknown": "unknown",
}


def find_battery(root: Path = POWER_SUPPLY_DIR) -> Path:
    """Return the first system battery (skipping peripheral batteries like wireless mice)."""
    candidates = sorted(root.glob("*")) if root.exists() else []
    for path in candidates:
        if _read_str(path, "type") == "Battery" and _read_str(path, "scope") != "Device":
            return path
    names = [p.name for p in candidates]
    raise FileNotFoundError(f"No system battery found in {root} (found: {names or 'nothing'})")


def _read_str(path: Path, name: str) -> str | None:
    try:
        return (path / name).read_text().strip()
    except OSError:
        # Missing attribute, or one the driver can't currently provide (reads can fail with ENODEV/EIO).
        return None


def _read_int(path: Path, name: str) -> int | None:
    value = _read_str(path, name)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def read_battery(path: Path) -> dict:
    """Read one battery's sysfs directory into a dict with the same keys as upower_to_dict()."""
    result: dict = {
        "native_path": path.name,
        "vendor": _read_str(path, "manufacturer"),
        "model": _read_str(path, "model_name"),
        "serial": _read_str(path, "serial_number"),
        "power_supply": _read_str(path, "scope") != "Device",
        "battery_present": _read_int(path, "present") == 1 if (path / "present").exists() else None,
    }

    status = _read_str(path, "status")
    if status is not None:
        result["battery_state"] = STATE_MAP.get(status.lower(), status.lower())

    technology = _read_str(path, "technology")
    if technology is not None:
        result["battery_technology"] = TECHNOLOGY_MAP.get(technology.lower(), technology.lower())

    voltage_now = _read_int(path, "voltage_now")
    if voltage_now is not None:
        result["battery_voltage_v"] = voltage_now / 1e6

    # Batteries report either energy_* (µWh) or charge_* (µAh). Convert charge to energy using
    # the design voltage, as upower does.
    if (path / "energy_now").exists() or (path / "energy_full").exists():
        energy_scale = 1e6  # µWh -> Wh
        prefix = "energy"
    else:
        voltage_design = _read_int(path, "voltage_min_design") or _read_int(path, "voltage_max_design") or voltage_now
        energy_scale = 1e12 / voltage_design if voltage_design else None  # µAh * µV -> Wh
        prefix = "charge"

    def energy_wh(suffix: str) -> float | None:
        raw = _read_int(path, f"{prefix}_{suffix}")
        return raw / energy_scale if raw is not None and energy_scale else None

    energy_now = energy_wh("now")
    energy_full = energy_wh("full")
    energy_full_design = energy_wh("full_design")
    energy_empty = energy_wh("empty")
    for key, value in [
        ("battery_energy_wh", energy_now),
        ("battery_energy_empty_wh", energy_empty if energy_empty is not None else (0.0 if energy_now is not None else None)),
        ("battery_energy_full_wh", energy_full),
        ("battery_energy_full_design_wh", energy_full_design),
    ]:
        if value is not None:
            result[key] = value

    # Rate: power_now (µW), or current_now (µA) * voltage_now (µV). Some firmware reports negatives.
    power_now = _read_int(path, "power_now")
    current_now = _read_int(path, "current_now")
    if power_now is not None:
        rate_w = abs(power_now) / 1e6
    elif current_now is not None and voltage_now:
        rate_w = abs(current_now) * voltage_now / 1e12
    else:
        rate_w = None
    if rate_w is not None:
        result["battery_energy_rate_w"] = rate_w

    cycle_count = _read_int(path, "cycle_count")
    if cycle_count is not None:
        result["battery_charge_cycles"] = cycle_count

    # Percentage = charge level; capacity = health (full vs. design), matching upower's meanings.
    if energy_now is not None and energy_full:
        result["battery_percentage"] = min(energy_now / energy_full * 100, 100.0)
    elif (capacity := _read_int(path, "capacity")) is not None:
        result["battery_percentage"] = float(capacity)
    if energy_full is not None and energy_full_design:
        result["battery_capacity"] = min(energy_full / energy_full_design * 100, 100.0)

    if rate_w and energy_now is not None:
        state = result.get("battery_state")
        if state == "discharging":
            result["battery_time_to_empty_h"] = energy_now / rate_w
        elif state == "charging" and energy_full is not None:
            result["battery_time_to_full_h"] = max(energy_full - energy_now, 0.0) / rate_w

    return result
