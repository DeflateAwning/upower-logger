import datetime

import polars as pl

from upower_logger.parquet_sink import ParquetSink


def row(ts: datetime.datetime, **extra) -> dict:
    return {"timestamp_utc": ts, "battery_percentage": 50.0, "battery_state": "discharging", **extra}


def hourly_files(tmp_path) -> list[str]:
    return sorted(p.name for p in (tmp_path / "hourly").glob("*.parquet"))


def monthly_files(tmp_path) -> list[str]:
    return sorted(p.name for p in (tmp_path / "monthly").glob("*.parquet"))


T0 = datetime.datetime(2026, 11, 12, 10, 0)


def test_rows_stay_in_memory_within_hour(tmp_path):
    sink = ParquetSink(tmp_path, now=T0)
    for m in range(5):
        sink.add(row(T0 + datetime.timedelta(minutes=m)))
    assert hourly_files(tmp_path) == []
    assert monthly_files(tmp_path) == []


def test_hour_rollover_writes_hourly_file(tmp_path):
    sink = ParquetSink(tmp_path, now=T0)
    sink.add(row(T0))
    sink.add(row(T0 + datetime.timedelta(minutes=30)))
    sink.add(row(T0 + datetime.timedelta(hours=1)))
    assert hourly_files(tmp_path) == ["2026-11-12T10.parquet"]
    assert pl.read_parquet(tmp_path / "hourly" / "2026-11-12T10.parquet").height == 2


def test_day_rollover_compacts_into_monthly(tmp_path):
    sink = ParquetSink(tmp_path, now=T0)
    sink.add(row(T0))
    sink.add(row(T0 + datetime.timedelta(hours=1)))
    sink.add(row(datetime.datetime(2026, 11, 13, 0, 5)))
    assert hourly_files(tmp_path) == []
    assert monthly_files(tmp_path) == ["2026-11.parquet"]
    assert pl.read_parquet(tmp_path / "monthly" / "2026-11.parquet").height == 2


def test_close_compacts_everything_with_stable_schema(tmp_path):
    sink = ParquetSink(tmp_path, now=T0)
    sink.add(row(T0, battery_time_to_empty_h=3.0))
    sink.add(row(T0 + datetime.timedelta(hours=1), battery_time_to_full_h=1.5, battery_state="charging"))
    sink.close()
    assert hourly_files(tmp_path) == []
    df = pl.read_parquet(tmp_path / "monthly" / "2026-11.parquet")
    assert df.height == 2
    assert df.schema["battery_time_to_empty_h"] == pl.Float64
    assert df.schema["battery_time_to_full_h"] == pl.Float64
    assert df.schema["timestamp_utc"] == pl.Datetime("us")


def test_month_rollover_splits_files(tmp_path):
    t = datetime.datetime(2026, 11, 30, 23, 30)
    sink = ParquetSink(tmp_path, now=t)
    sink.add(row(t))
    sink.add(row(datetime.datetime(2026, 12, 1, 0, 30)))
    sink.close()
    assert monthly_files(tmp_path) == ["2026-11.parquet", "2026-12.parquet"]


def test_restart_appends_to_existing_monthly(tmp_path):
    sink = ParquetSink(tmp_path, now=T0)
    sink.add(row(T0))
    sink.close()
    sink = ParquetSink(tmp_path, now=T0 + datetime.timedelta(minutes=10))
    sink.add(row(T0 + datetime.timedelta(minutes=10)))
    sink.close()
    assert pl.read_parquet(tmp_path / "monthly" / "2026-11.parquet").height == 2


def test_startup_resumes_current_hour_after_crash(tmp_path):
    sink = ParquetSink(tmp_path, now=T0)
    sink.add(row(T0))
    sink.flush()  # simulate the hourly file existing, then a crash (no close)

    sink = ParquetSink(tmp_path, now=T0 + datetime.timedelta(minutes=5))
    sink.add(row(T0 + datetime.timedelta(minutes=5)))
    sink.add(row(T0 + datetime.timedelta(hours=1)))
    assert pl.read_parquet(tmp_path / "hourly" / "2026-11-12T10.parquet").height == 2


def test_startup_compacts_stale_hourly_files(tmp_path):
    sink = ParquetSink(tmp_path, now=T0)
    sink.add(row(T0))
    sink.flush()  # crash

    ParquetSink(tmp_path, now=T0 + datetime.timedelta(days=2))
    assert hourly_files(tmp_path) == []
    assert pl.read_parquet(tmp_path / "monthly" / "2026-11.parquet").height == 1


def test_compaction_deduplicates(tmp_path):
    sink = ParquetSink(tmp_path, now=T0)
    sink.add(row(T0))
    sink.flush()
    # Simulate a crash after the monthly write but before the hourly file was deleted.
    hourly = tmp_path / "hourly" / "2026-11-12T10.parquet"
    pl.read_parquet(hourly).write_parquet(tmp_path / "monthly" / "2026-11.parquet")
    ParquetSink(tmp_path, now=T0 + datetime.timedelta(days=1))
    assert pl.read_parquet(tmp_path / "monthly" / "2026-11.parquet").height == 1
