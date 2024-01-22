
from loguru import logger
from argparse import ArgumentParser
import subprocess
import json
import polars as pl
import datetime
import time

from upower_parser import upower_to_dict

def parse_args():
    parser = ArgumentParser()
    parser.add_argument('--log-file', help='Path to log file', type=str)
    parser.add_argument('--json-file', help='Path to JSON file to store dumps in', type=str)
    parser.add_argument('--sqlite-file', help='Path to SQLite database file', type=str)
    parser.add_argument('--interval', help='Interval in seconds between upower calls', type=int, default=60)
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

@logger.catch
def execute_log_event(sqlite_conn_str: str | None = None, json_file_path: str | None = None):
    upower_output_str = get_upower_output()
    upower_dict = upower_to_dict(upower_output_str)

    logger.info(f"upower output: {upower_dict}")

    # add extra columns
    upower_dict['timestamp_utc'] = datetime.datetime.utcnow()

    df = pl.DataFrame([upower_dict])

    if sqlite_conn_str is not None:
        df.write_database(
            table_name = 'upower_log',
            connection = sqlite_conn_str,
            if_table_exists = 'append',
            engine = 'sqlalchemy',
        )

    if json_file_path is not None:
        with open(json_file_path, 'a') as f:
            f.write(json_dumps_with_datetime(upower_dict) + '\n')

def main():
    args = parse_args()

    sqlite_conn_str: str | None = None
    json_file_path: str | None = None

    if (not args.log_file) and (not args.sqlite_file) and (not args.json_file):
        logger.warning('No output specified. Logs will only go to stdout. You may want to specify --log-file, --sqlite-file, or --json-file.')
    
    if args.log_file is not None:
        logger.add(args.log_file)

    if args.sqlite_file is not None:
        sqlite_conn_str = f'sqlite:///{args.sqlite_file}'
        logger.info(f'Using sqlite database at: {sqlite_conn_str}')

    if args.json_file is not None:
        json_file_path = args.json_file
        logger.info(f'Using JSON file at: {json_file_path}')

    logger.info('Starting upower logger')

    while 1:
        execute_log_event(args.sqlite_file, args.json_file)
        time.sleep(args.interval)

if __name__ == '__main__':
    main()
