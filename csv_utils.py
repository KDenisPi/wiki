#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared reader/writer for the ';'-delimited CSV files produced by
cpp/dict_class.h.

Fields are unquoted unless they contain the delimiter, a double quote, or a
newline, in which case they are wrapped in double quotes with embedded quotes
doubled (RFC4180-style, with ';' standing in for ','). This matches
write_csv_field() in cpp/dict_class.h.
"""

import csv
import io

CSV_DELIM = ";"


def parse_csv_line(line: str, delim: str = CSV_DELIM) -> list:
    """Parse a single CSV-formatted line into a list of fields, honoring
    double-quoted fields that may contain the delimiter itself."""
    line = line.rstrip("\r\n")
    if not line:
        return []
    reader = csv.reader([line], delimiter=delim, quotechar='"')
    return next(reader)


def write_csv_line(fields: list, delim: str = CSV_DELIM) -> str:
    """Format fields into a single CSV line (no trailing newline), quoting
    any field that contains the delimiter, a quote, or a newline."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=delim, quotechar='"', lineterminator="")
    writer.writerow(fields)
    return buf.getvalue()
