# upower-logger
A time series logger for upower to track a laptop battery's health over the duration of its ownership

## Description
The main Python script can be started on boot in userspace (no superuser permissions required).

It logs the battery info, provided by the `upower` command, to a SQLite database.

## License
This project is licensed under the [The Unlicense](https://unlicense.org/), a public domain equivalent license for software.
