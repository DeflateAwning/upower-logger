from src.upower_parser import upower_to_dict

def test_upower_to_dict():
    upower_output_1 = """
  native-path:          BAT1
  vendor:               NVT
  model:                Model1
  serial:               0005
  power supply:         yes
  updated:              2024-01-15T17:30:22 MST (79 seconds ago)
  has history:          yes
  has statistics:       yes
  battery
    present:             yes
    rechargeable:        yes
    state:               discharging
    warning-level:       none
    energy:              53.4072 Wh
    energy-empty:        0 Wh
    energy-full:         53.4072 Wh
    energy-full-design:  55.0088 Wh
    energy-rate:         10.934 W
    voltage:             17.24 V
    charge-cycles:       67
    time to empty:       4.9 hours
    percentage:          100%
    capacity:            97.0885%
    technology:          lithium-ion
    icon-name:          'battery-full-symbolic'
  History (rate):
    1705365022	10.934	discharging
    """

    expected_1 = {
        'native_path': 'BAT1',
        'vendor': 'NVT',
        'model': 'Model1',
        'serial': '0005',
        'power_supply': True,
        'updated': '2024-01-15T17:30:22 MST (79 seconds ago)',
        'has_history': True,
        'has_statistics': True,
        'battery_present': True,
        'battery_rechargeable': True,
        'battery_state': 'discharging',
        'battery_warning_level': None,
        'battery_energy_wh': 53.4072,
        'battery_energy_empty_wh': 0,
        'battery_energy_full_wh': 53.4072,
        'battery_energy_full_design_wh': 55.0088,
        'battery_energy_rate_w': 10.934,
        'battery_voltage_v': 17.24,
        'battery_charge_cycles': 67,
        'battery_time_to_empty_h': 4.9,
        'battery_percentage': 100,
        'battery_capacity': 97.0885,
        'battery_technology': 'lithium-ion',
        'battery_icon_name': 'battery-full-symbolic',
        }
    
    assert upower_to_dict(upower_output_1) == expected_1
