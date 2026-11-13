# upower-logger
A time series logger for upower to track a laptop battery's health over the duration of its ownership

## Description
The main Python script can be started on boot in userspace (no superuser permissions required).

It logs the battery info, provided by the `upower` command, to a SQLite database.

## Usage
This project is managed with [uv](https://docs.astral.sh/uv/).

```bash
# Run directly from the repo
uv run upower-logger --sqlite-file ~/upower_logger.sqlite --log-file ~/upower_logger.log

# Or install as a tool, so `upower-logger` is on your PATH
uv tool install .
upower-logger --sqlite-file ~/upower_logger.sqlite
```

Options: `--sqlite-file`, `--json-file`, `--log-file`, `--interval` (seconds, default 60).

## Development
```bash
uv sync
uv run pytest
```

## License
This project is licensed under the [The Unlicense](https://unlicense.org/), a public domain equivalent license for software.
