import re

key_value_pattern = re.compile(r'\s*([^:\n]+):\s*([^\n]+)')

def upower_to_dict(upower_cmd_output: str) -> dict:
    """ Parses the output of the upower command into a dictionary.
    Example command: upower -i /org/freedesktop/UPower/devices/battery_BAT1
    """

    result = {}

    # TODO: refactor this into a function which operated on single lines to improve testability

    # Helper function to update the dictionary with key-value pairs
    def update_dict(key: str, value: str):
        key_out = key.strip().replace(' ', '_').replace('-', '_').lower()
        value_out = value.strip().strip("'")
        if value_out == 'yes':
            value_out = True
        elif value_out == 'no':
            value_out = False
        elif value_out == 'none':
            value_out = None
        elif value_out.endswith('%'):
            value_out = float(value_out[:-1].strip())
        elif value_out.endswith(' Wh'):
            value_out = float(value_out[:-2].strip())
            key_out += '_wh'
        elif value_out.endswith(' W'):
            value_out = float(value_out[:-1].strip())
            key_out += '_w'
        elif value_out.endswith(' V'):
            value_out = float(value_out[:-1].strip())
            key_out += '_v'
        elif value_out.endswith(' hours'):
            value_out = float(value_out[:-6].strip())
            key_out += '_h'
        elif value_out.endswith(' days'):
            value_out = float(value_out.rstrip(' days').strip()) * 24
            key_out += '_h'
        elif value_out.endswith(' minutes'):
            value_out = float(value_out[:-8].strip()) / 60
            key_out += '_h'
        elif value_out.endswith(' seconds'):
            value_out = float(value_out[:-8].strip()) / 3600
            key_out += '_h'
        elif key_out.endswith('_charge_cycles'):
            value_out = int(value_out)
            
        result[key_out] = value_out

    latest_heading: str | None = None

    for line in upower_cmd_output.splitlines():
        if line.strip() == "":
            continue

        if line.strip() == 'battery':
            latest_heading = 'battery'
            continue

        if line.strip().startswith('History'):
            break
        
        # Check if it's a key-value pair
        key_value_match = key_value_pattern.match(line)
        if key_value_match:
            key, value = key_value_match.groups()

            if latest_heading is not None:
                key = f'{latest_heading}_{key}'

            update_dict(key, value)
        
    return result
