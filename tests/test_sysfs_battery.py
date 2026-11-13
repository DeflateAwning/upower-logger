from pathlib import Path

import pytest

from upower_logger.sysfs_battery import find_battery, read_battery


def make_supply(root: Path, name: str, **attrs) -> Path:
    path = root / name
    path.mkdir(parents=True)
    for key, value in attrs.items():
        (path / key).write_text(f"{value}\n")
    return path


def test_energy_based_battery(tmp_path):
    # Same battery as the upower parser test case.
    bat = make_supply(
        tmp_path, "BAT1",
        type="Battery", present=1, status="Discharging", technology="Li-ion",
        manufacturer="NVT", model_name="Model1", serial_number="0005",
        energy_now=53407200, energy_full=53407200, energy_full_design=55008800,
        power_now=10934000, voltage_now=17240000, cycle_count=67, capacity=100,
    )
    result = read_battery(bat)
    numeric = {k: v for k, v in result.items() if isinstance(v, float)}
    other = {k: v for k, v in result.items() if not isinstance(v, float)}
    assert other == {
        "native_path": "BAT1",
        "vendor": "NVT",
        "model": "Model1",
        "serial": "0005",
        "power_supply": True,
        "battery_present": True,
        "battery_state": "discharging",
        "battery_technology": "lithium-ion",
        "battery_charge_cycles": 67,
    }
    assert numeric == pytest.approx({
        "battery_voltage_v": 17.24,
        "battery_energy_wh": 53.4072,
        "battery_energy_empty_wh": 0.0,
        "battery_energy_full_wh": 53.4072,
        "battery_energy_full_design_wh": 55.0088,
        "battery_energy_rate_w": 10.934,
        "battery_percentage": 100.0,
        "battery_capacity": 97.0885,
        "battery_time_to_empty_h": 53.4072 / 10.934,
    }, rel=1e-4)


def test_charge_based_battery_converts_to_energy(tmp_path):
    # Some batteries report µAh + µA instead of µWh + µW.
    bat = make_supply(
        tmp_path, "BAT0",
        type="Battery", present=1, status="Charging",
        charge_now=2000000, charge_full=4000000, charge_full_design=5000000,
        current_now=-1000000, voltage_now=12000000, voltage_min_design=11000000,
    )
    result = read_battery(bat)
    assert result["battery_energy_wh"] == pytest.approx(22.0)  # 2 Ah * 11 V
    assert result["battery_energy_full_wh"] == pytest.approx(44.0)
    assert result["battery_energy_full_design_wh"] == pytest.approx(55.0)
    assert result["battery_energy_rate_w"] == pytest.approx(12.0)  # |−1 A| * 12 V
    assert result["battery_percentage"] == pytest.approx(50.0)
    assert result["battery_capacity"] == pytest.approx(80.0)
    assert result["battery_time_to_full_h"] == pytest.approx(22.0 / 12.0)
    assert "battery_time_to_empty_h" not in result


def test_state_mapping_and_missing_attrs(tmp_path):
    bat = make_supply(tmp_path, "BAT0", type="Battery", status="Not charging", capacity=80)
    result = read_battery(bat)
    assert result["battery_state"] == "pending-charge"
    assert result["battery_percentage"] == 80.0
    assert "battery_energy_wh" not in result


def test_find_battery_skips_ac_and_peripherals(tmp_path):
    make_supply(tmp_path, "AC", type="Mains")
    make_supply(tmp_path, "hidpp_battery_0", type="Battery", scope="Device")
    make_supply(tmp_path, "BAT0", type="Battery")
    assert find_battery(tmp_path).name == "BAT0"


def test_find_battery_raises_when_none(tmp_path):
    make_supply(tmp_path, "AC", type="Mains")
    with pytest.raises(FileNotFoundError, match="No system battery"):
        find_battery(tmp_path)
