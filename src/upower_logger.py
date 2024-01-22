
from loguru import logger
from argparse import ArgumentParser
import subprocess
import json
import polars as pl
import datetime
import time
from pathlib import Path
import sqlite3

from upower_parser import upower_to_dict

def parse_args():
    parser = ArgumentParser()
    parser.add_argument('--log-file', help='Path to log file', type=str)
    parser.add_argument('--json-file', help='Path to JSON file to store dumps in', type=str)
    parser.add_argument('--sqlite-file', help='Path to SQLite database file', type=str)
    parser.add_argument('--interval', dest='interval_sec', help='Interval in seconds between upower calls', type=int, default=60)
    #parser.add_argument('--debug', action='store_true')
    return parser.parse_args()

def get_upower_output() -> str:
    output = subprocess.check_output(['upower', '-i', '/org/freedesktop/UPower/devices/battery_BAT1'])
    return output.decode('utf-8')

def json_dumps_with_datetime(obj: dict) -> str:
    """ Dumps a dictionary to JSON, but converts datetime objects to strings first. """
    for key, value in obj.items():
        if isinstance(value, datetime.datetime):
            obj[key] = value.isoformat()
    return json.dumps(obj)

def make_sqlite_conn_str(sqlite_file_path: str) -> str:
    # sqlite_conn_str has total 4 slashes for absolute path
    return f"sqlite:///{sqlite_file_path}"

def execute_sqlite_ddl(sqlite_file_path: str):
    ddl = """
        CREATE TABLE IF NOT EXISTS upower_log (
            native_path TEXT, 
            vendor TEXT, 
            model TEXT, 
            serial TEXT, 
            power_supply BOOLEAN, 
            updated TEXT, 
            has_history BOOLEAN, 
            has_statistics BOOLEAN, 
            battery_present BOOLEAN, 
            battery_rechargeable BOOLEAN, 
            battery_state TEXT, 
            battery_warning_level TEXT, 
            battery_energy_wh FLOAT, 
            battery_energy_empty_wh FLOAT, 
            battery_energy_full_wh FLOAT, 
            battery_energy_full_design_wh FLOAT, 
            battery_energy_rate_w FLOAT, 
            battery_voltage_v FLOAT, 
            battery_charge_cycles BIGINT, 
            battery_time_to_empty_h FLOAT, 
            battery_time_to_full_h FLOAT, 
            battery_percentage FLOAT, 
            battery_capacity FLOAT, 
            battery_technology TEXT, 
            battery_icon_name TEXT, 
            timestamp_utc DATETIME
        );
    """
    
    with sqlite3.connect(sqlite_file_path) as con:
        con.execute(ddl)
    logger.info(f"Created 'upower_log' table in sqlite database (if necessary) with CREATE TABLE IF NOT EXISTS")

@logger.catch
def execute_log_event_json(json_file_path: str, upower_dict: dict):
    with open(json_file_path, 'a') as f:
        f.write(json_dumps_with_datetime(upower_dict) + '\n')

@logger.catch
def execute_log_event_sqlite(sqlite_file_path: str, upower_dict: dict):
    sqlite_conn_str = make_sqlite_conn_str(sqlite_file_path)
    # logger.debug(f"{sqlite_conn_str=}")

    df = pl.DataFrame([upower_dict])
    df.write_database(
        table_name = 'upower_log',
        connection = sqlite_conn_str,
        if_table_exists = 'append',
        # engine = 'adbc', # auto-select between 'sqlalchemy' and 'adbc'
    )

@logger.catch
def execute_log_event(sqlite_file_path: str | None = None, json_file_path: str | None = None):
    upower_output_str = get_upower_output()
    upower_dict = upower_to_dict(upower_output_str)

    # add extra columns
    upower_dict['timestamp_utc'] = datetime.datetime.utcnow()

    # ensure that all columns are present (e.g., when charging, the time-to-empty col isn't present)
    full_col_list: list[str] = []
    for col in full_col_list:
        if col not in upower_dict.keys():
            upower_dict[col] = None

    logger.info(f"upower output: {upower_dict}")

    if sqlite_file_path is not None:
        execute_log_event_sqlite(sqlite_file_path, upower_dict)

    if json_file_path is not None:
        execute_log_event_json(json_file_path, upower_dict)

def main():
    args = parse_args()

    sqlite_file_path: str | None = None
    json_file_path: str | None = None

    logger.info(f'Running main() with arguments: {args}')

    if (not args.log_file) and (not args.sqlite_file) and (not args.json_file):
        logger.warning('No output specified. Logs will only go to stdout. You may want to specify --log-file, --sqlite-file, or --json-file.')
    
    if args.log_file is not None:
        logger.add(args.log_file)

    if args.sqlite_file is not None:
        sqlite_file_path = args.sqlite_file
        
        assert isinstance(sqlite_file_path, str)
        execute_sqlite_ddl(sqlite_file_path)

        logger.info(f'Using sqlite database at: {sqlite_file_path}')

    if args.json_file is not None:
        json_file_path = args.json_file
        logger.info(f'Using JSON file at: {json_file_path}')

    logger.info('Starting upower logger')

    while 1:
        execute_log_event(args.sqlite_file, args.json_file)
        time.sleep(args.interval_sec)

if __name__ == '__main__':
    main()
