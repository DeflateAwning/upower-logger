from loguru import logger
from argparse import ArgumentParser
import subprocess
import orjson
import polars as pl
import datetime
import signal
import sqlite3
import threading
import psutil

from upower_logger.parser import upower_to_dict
from upower_logger.parquet_sink import ParquetSink

def parse_args():
    parser = ArgumentParser()
    parser.add_argument('--log-file', help='Path to log file', type=str)
    parser.add_argument('--json-file', help='Path to JSON file to store dumps in', type=str)
    parser.add_argument('--sqlite-file', help='Path to SQLite database file', type=str)
    parser.add_argument('--parquet-dir', help='Directory for parquet output (hourly partitions, compacted into monthly files)', type=str)
    parser.add_argument('--interval', dest='interval_sec', help='Interval in seconds between upower calls', type=int, default=60)
    #parser.add_argument('--debug', action='store_true')
    return parser.parse_args()

def get_upower_output() -> str:
    output = subprocess.check_output(['upower', '-i', '/org/freedesktop/UPower/devices/battery_BAT1'])
    return output.decode('utf-8')

def get_system_boot_time_utc() -> datetime.datetime:
    """ Gets the system's boot time in UTC. """
    boot_time_seconds = psutil.boot_time()
    boot_time_utc = datetime.datetime.utcfromtimestamp(boot_time_seconds)
    return boot_time_utc

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
            timestamp_utc DATETIME,
            system_boot_time_utc DATETIME
        );
    """
    
    with sqlite3.connect(sqlite_file_path) as con:
        con.execute(ddl)
    logger.info(f"Created 'upower_log' table in sqlite database (if necessary) with CREATE TABLE IF NOT EXISTS")

@logger.catch
def execute_log_event_json(json_file_path: str, upower_dict: dict):
    # orjson serializes datetimes natively (ISO 8601) and never mutates the input dict.
    with open(json_file_path, 'ab') as f:
        f.write(orjson.dumps(upower_dict, option=orjson.OPT_APPEND_NEWLINE))

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
def execute_log_event(sqlite_file_path: str | None = None, json_file_path: str | None = None, parquet_sink: ParquetSink | None = None):
    upower_output_str = get_upower_output()
    upower_dict = upower_to_dict(upower_output_str)

    # add extra columns
    upower_dict['timestamp_utc'] = datetime.datetime.utcnow()
    upower_dict['system_boot_time_utc'] = get_system_boot_time_utc()

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

    if parquet_sink is not None:
        logger.catch(parquet_sink.add)(upower_dict)

def main():
    args = parse_args()

    sqlite_file_path: str | None = None
    json_file_path: str | None = None

    logger.info(f'Running main() with arguments: {args}')

    if not (args.log_file or args.sqlite_file or args.json_file or args.parquet_dir):
        logger.warning('No output specified. Logs will only go to stdout. You may want to specify --log-file, --sqlite-file, --json-file, or --parquet-dir.')
    
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

    parquet_sink: ParquetSink | None = None
    if args.parquet_dir is not None:
        parquet_sink = ParquetSink(args.parquet_dir)

    # Stop cleanly on SIGTERM (systemctl stop) and SIGINT (Ctrl+C), so buffered data gets written.
    stop_event = threading.Event()
    def handle_stop_signal(signum, _frame):
        logger.info(f'Received {signal.Signals(signum).name}, shutting down')
        stop_event.set()
    signal.signal(signal.SIGTERM, handle_stop_signal)
    signal.signal(signal.SIGINT, handle_stop_signal)

    logger.info('Starting upower logger')

    try:
        while not stop_event.is_set():
            execute_log_event(args.sqlite_file, args.json_file, parquet_sink)
            stop_event.wait(args.interval_sec)
    finally:
        if parquet_sink is not None:
            parquet_sink.close()
        logger.info('Stopped upower logger')

if __name__ == '__main__':
    main()
