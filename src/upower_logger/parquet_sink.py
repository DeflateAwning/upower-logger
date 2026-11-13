"""Parquet output: buffer rows in memory, write hourly partitions, compact into monthly files.

Layout under the output directory:

    hourly/YYYY-MM-DDTHH.parquet   # transient; one per UTC hour
    monthly/YYYY-MM.parquet        # steady state; one per UTC month

Lifecycle:
- Rows for the current UTC hour are held in memory.
- When the hour rolls over, the buffer is written to that hour's file (one write per hour).
- When the day rolls over, and on close, all completed hourly files are merged into their
  monthly file (rewritten atomically) and then deleted. On close, the current hour is
  flushed and compacted too, so a clean shutdown leaves only monthly files.
- On startup, the current hour's file (left behind by a crash) is loaded back into memory,
  and any older hourly files are compacted.
"""

import datetime
import os
from pathlib import Path

import polars as pl
from loguru import logger

HOUR_FORMAT = "%Y-%m-%dT%H"
MONTH_FORMAT = "%Y-%m"
TIMESTAMP_COL = "timestamp_utc"

# Stable schema so that hourly/monthly files concatenate cleanly, regardless of which
# optional fields upower reported (e.g., time-to-empty vs. time-to-full).
SCHEMA: dict[str, pl.DataType] = {
    "native_path": pl.String(),
    "vendor": pl.String(),
    "model": pl.String(),
    "serial": pl.String(),
    "power_supply": pl.Boolean(),
    "updated": pl.String(),
    "has_history": pl.Boolean(),
    "has_statistics": pl.Boolean(),
    "battery_present": pl.Boolean(),
    "battery_rechargeable": pl.Boolean(),
    "battery_state": pl.String(),
    "battery_warning_level": pl.String(),
    "battery_energy_wh": pl.Float64(),
    "battery_energy_empty_wh": pl.Float64(),
    "battery_energy_full_wh": pl.Float64(),
    "battery_energy_full_design_wh": pl.Float64(),
    "battery_energy_rate_w": pl.Float64(),
    "battery_voltage_v": pl.Float64(),
    "battery_charge_cycles": pl.Int64(),
    "battery_time_to_empty_h": pl.Float64(),
    "battery_time_to_full_h": pl.Float64(),
    "battery_percentage": pl.Float64(),
    "battery_capacity": pl.Float64(),
    "battery_technology": pl.String(),
    "battery_icon_name": pl.String(),
    TIMESTAMP_COL: pl.Datetime("us"),
    "system_boot_time_utc": pl.Datetime("us"),
}


def normalize(df: pl.DataFrame) -> pl.DataFrame:
    """Cast known columns to SCHEMA, add missing known columns as nulls, keep any extras."""
    exprs = [
        pl.col(name).cast(dtype, strict=False) if name in df.columns else pl.lit(None, dtype=dtype).alias(name)
        for name, dtype in SCHEMA.items()
    ]
    extras = [c for c in df.columns if c not in SCHEMA]
    return df.select(*exprs, *extras)


def rows_to_df(rows: list[dict]) -> pl.DataFrame:
    return normalize(pl.DataFrame(rows, infer_schema_length=None, strict=False))


def write_parquet_atomic(df: pl.DataFrame, path: Path) -> None:
    tmp_path = path.with_name(path.name + ".tmp")
    df.write_parquet(tmp_path)
    os.replace(tmp_path, path)


class ParquetSink:
    def __init__(self, output_dir: str | Path, now: datetime.datetime | None = None):
        self.output_dir = Path(output_dir)
        self.hourly_dir = self.output_dir / "hourly"
        self.monthly_dir = self.output_dir / "monthly"
        self.hourly_dir.mkdir(parents=True, exist_ok=True)
        self.monthly_dir.mkdir(parents=True, exist_ok=True)

        now = now or datetime.datetime.utcnow()
        self.current_hour: str = now.strftime(HOUR_FORMAT)
        self.rows: list[dict] = []
        self.loaded: pl.DataFrame | None = None

        # Leftovers from an unclean shutdown: compact older hours, resume the current one.
        self.compact(include_current_hour=False)
        current_path = self._hourly_path(self.current_hour)
        if current_path.exists():
            self.loaded = normalize(pl.read_parquet(current_path))
            logger.info(f"Loaded {self.loaded.height} rows from existing hourly file: {current_path}")

        logger.info(f"Using parquet output directory: {self.output_dir}")

    def _hourly_path(self, hour: str) -> Path:
        return self.hourly_dir / f"{hour}.parquet"

    def _monthly_path(self, month: str) -> Path:
        return self.monthly_dir / f"{month}.parquet"

    def add(self, row: dict) -> None:
        """Buffer a row. Flushes/compacts when the row's hour/day differs from the buffer's."""
        hour = row[TIMESTAMP_COL].strftime(HOUR_FORMAT)
        if hour != self.current_hour:
            previous_day = self.current_hour[:10]
            self.flush()
            self.rows = []
            self.loaded = None
            self.current_hour = hour
            if hour[:10] != previous_day:
                self.compact(include_current_hour=False)
        self.rows.append(row)

    def flush(self) -> None:
        """Write the in-memory buffer (plus any rows loaded on startup) to the current hour's file."""
        frames = [f for f in (self.loaded, rows_to_df(self.rows) if self.rows else None) if f is not None]
        if not frames:
            return
        df = pl.concat(frames, how="diagonal_relaxed")
        path = self._hourly_path(self.current_hour)
        write_parquet_atomic(df, path)
        logger.info(f"Wrote {df.height} rows to hourly file: {path}")

    def compact(self, include_current_hour: bool) -> None:
        """Merge hourly files into their monthly files, then delete the hourly files."""
        by_month: dict[str, list[Path]] = {}
        for path in sorted(self.hourly_dir.glob("*.parquet")):
            if path.stem == self.current_hour and not include_current_hour:
                continue
            month = datetime.datetime.strptime(path.stem, HOUR_FORMAT).strftime(MONTH_FORMAT)
            by_month.setdefault(month, []).append(path)

        for month, hourly_paths in by_month.items():
            monthly_path = self._monthly_path(month)
            sources = ([monthly_path] if monthly_path.exists() else []) + hourly_paths
            df = (
                pl.concat([normalize(pl.read_parquet(p)) for p in sources], how="diagonal_relaxed")
                # Guards against duplicates if a previous compaction died before deleting hourly files.
                .unique(subset=[TIMESTAMP_COL], keep="first", maintain_order=True)
                .sort(TIMESTAMP_COL)
            )
            write_parquet_atomic(df, monthly_path)
            for p in hourly_paths:
                p.unlink()
            logger.info(f"Compacted {len(hourly_paths)} hourly file(s) into {monthly_path} ({df.height} rows)")

    def close(self) -> None:
        self.flush()
        self.rows = []
        self.loaded = None
        self.compact(include_current_hour=True)
