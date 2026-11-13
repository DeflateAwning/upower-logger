# upower-logger
A time series logger for upower to track a laptop battery's health over the duration of its ownership

## Description
The main Python script can be started on boot in userspace (no superuser permissions required).

It logs the battery info (charge, energy, design capacity, health, cycle count, etc.) to Parquet, SQLite, and/or JSON.

Battery info is read directly from the Linux kernel's `/sys/class/power_supply/` interface by default, so it works on any Linux distro without needing the `upower` daemon. Use `--source upower` to read from the `upower` CLI instead; both produce the same columns. The battery is auto-detected (peripheral batteries like wireless mice are skipped), or set it with `--battery BAT0`.

## Usage
This project is managed with [uv](https://docs.astral.sh/uv/).

```bash
# Run directly from the repo
uv run upower-logger --sqlite-file ~/upower_logger.sqlite --log-file ~/upower_logger.log

# Or install as a tool, so `upower-logger` is on your PATH
uv tool install .
upower-logger --sqlite-file ~/upower_logger.sqlite
```

Options: `--parquet-dir`, `--sqlite-file`, `--json-file`, `--log-file`, `--interval` (seconds, default 60), `--source` (`sysfs` or `upower`), `--battery` (e.g. `BAT0`).

## Parquet output
With `--parquet-dir DIR`, rows are buffered in memory to minimize disk writes:

- `DIR/hourly/YYYY-MM-DDTHH.parquet`: written once when each UTC hour ends.
- `DIR/monthly/YYYY-MM.parquet`: at the end of each UTC day, and on shutdown, the hourly files are merged into their monthly file and deleted.

So the steady state is one parquet file per month. On startup, a leftover file for the current hour (e.g., after a crash) is loaded back into memory, and older leftovers are compacted. Query everything with:

```python
import polars as pl
df = pl.read_parquet("DIR/monthly/*.parquet")
```

## Running as a systemd user service
```bash
uv tool install .
mkdir -p ~/.config/systemd/user
cp systemd/upower-logger.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now upower-logger
journalctl --user -u upower-logger -f   # view logs
```

`systemctl --user stop upower-logger` sends SIGTERM, which flushes the in-memory buffer before exiting. To keep the service running while you are logged out, run `loginctl enable-linger $USER`. After changing the code, run `uv tool install --reinstall .` and restart the service.

## Development
```bash
uv sync
uv run pytest
```

## License
This project is licensed under the [The Unlicense](https://unlicense.org/), a public domain equivalent license for software.
