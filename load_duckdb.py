#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Load the parser output into a DuckDB database.

The workload is analytical - group by century, filter by occupation, country
or genre, join events to items to attributes - over roughly 100M rows on one
machine, so every table is rebuilt from the CSVs instead of being updated in
place. Re-running the loader is therefore safe and idempotent, which is also
why no table carries a primary key: the CSVs are the source of truth and
constraints would only slow the bulk load down.

Input (produced by wpars, plus resolve_values.py and build_class_closure.py):
    DataEvents.csv   key;property;time;type;timezone;qual_prop;qual_value;item;class
    ItemsExt.csv     qid;label;description[;lng;label_lng;description_lng]
    Attributes.csv   key;property;value;item
    ItemClasses.csv  key;item;class
    values.csv       qid;label;description
    select_classes.csv / date_properties.csv / attribute_properties.csv
    properties.json

Files that are missing are skipped with a notice, so the database can be built
before a full run has produced everything.

Wikidata time strings are parsed here: "+1991-02-12T00:00:00Z" and also
"-0044-00-00T00:00:00Z" (BC) or "+1500-00-00T00:00:00Z" (year known, month and
day not). Month and day are 0 when the source has no such precision.

Year is signed and BIGINT. Not SMALLINT: 40 rows in the January extract are
outside 16 bits already. Not even INTEGER: the Big Bang is stored as
-13800000000, which overflows 32 bits.
"""

import argparse
import json
import os
import sys

TIME_RE = r'^([+-])0*(\d+)-(\d{2})-(\d{2})T'


def parse_time_cols(col: str) -> str:
    """SQL fragment turning a Wikidata time string into year/month/day/bc."""
    return f"""
        CASE WHEN regexp_extract({col}, '{TIME_RE}', 1) = '-' THEN -1 ELSE 1 END
            * TRY_CAST(regexp_extract({col}, '{TIME_RE}', 2) AS BIGINT) AS year,
        TRY_CAST(regexp_extract({col}, '{TIME_RE}', 3) AS UTINYINT) AS month,
        TRY_CAST(regexp_extract({col}, '{TIME_RE}', 4) AS UTINYINT) AS day,
        regexp_extract({col}, '{TIME_RE}', 1) = '-' AS bc"""


def csv(path: str, columns: dict, tolerant_ok: bool = False) -> str:
    """SQL fragment reading one of the ';'-delimited output files."""
    cols = ", ".join(f"'{n}':'{t}'" for n, t in columns.items())
    return (f"read_csv('{path}', delim=';', quote='\"', escape='\"', header=false,"
            f" auto_detect=false, null_padding=true, columns={{{cols}}})")


def items_tolerant(path: str) -> str:
    """Read ItemsExt.csv written before the CSV escaping fix (commit d0c19b5).

    In those files an unescaped ';' inside a description spills into extra
    fields. The language block always starts with a literal ';<lng>;', so the
    line can still be split reliably: id, then label, then everything left is
    the description.
    """
    return f"""
        WITH raw AS (
            SELECT line FROM read_csv('{path}', delim='\x07', header=false,
                                      auto_detect=false, columns={{'line':'VARCHAR'}})
        ), split_id AS (
            SELECT regexp_extract(line, '^([^;]*);(.*)$', 1) AS qid,
                   regexp_extract(line, '^([^;]*);(.*)$', 2) AS rest
            FROM raw
        ), split_lng AS (
            SELECT qid,
                   CASE WHEN contains(rest, ';ru;') THEN split_part(rest, ';ru;', 1) ELSE rest END AS en,
                   CASE WHEN contains(rest, ';ru;') THEN split_part(rest, ';ru;', 2) END AS ru
            FROM split_id
        )
        SELECT qid,
               split_part(en, ';', 1) AS label,
               CASE WHEN contains(en, ';') THEN substr(en, strpos(en, ';') + 1) END AS description,
               split_part(ru, ';', 1) AS label_ru,
               CASE WHEN contains(ru, ';') THEN substr(ru, strpos(ru, ';') + 1) END AS description_ru
        FROM split_lng
        WHERE qid <> ''"""


def load_properties(con, props_file, date_file, attr_file):
    """Property dictionary, tagged with the role each property plays here."""
    if not os.path.exists(props_file):
        print(f"  skip properties: no {props_file}")
        return

    with open(props_file) as fd:
        props = json.load(fd)

    def ids(path):
        if not os.path.exists(path):
            return set()
        with open(path) as fd:
            return {line.split(";", 1)[0].strip() for line in fd
                    if line.strip() and not line.startswith("#")}

    dates, attrs = ids(date_file), ids(attr_file)

    rows = [(pid, info[0], info[1] if len(info) > 1 else None,
             "date" if pid in dates else "attribute" if pid in attrs else "other")
            for pid, info in props.items()]

    con.execute("CREATE OR REPLACE TABLE properties"
                " (pid VARCHAR, label VARCHAR, description VARCHAR, kind VARCHAR)")
    con.executemany("INSERT INTO properties VALUES (?, ?, ?, ?)", rows)
    print(f"  properties: {len(rows):,}"
          f" ({len(dates)} date, {len(attrs)} attribute)")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", default=".", help="directory holding the wpars output")
    parser.add_argument("--config-dir", default="/home/denis/projects/wiki_data/classes",
                        help="directory holding the selection files")
    parser.add_argument("--properties", default="/home/denis/projects/wiki_data/properties.json")
    parser.add_argument("--db", default="wiki.duckdb")
    parser.add_argument("--tolerant", action="store_true",
                        help="repair ItemsExt.csv files written before the CSV escaping fix")
    args = parser.parse_args()

    try:
        import duckdb
    except ImportError:
        print("duckdb is not available in this interpreter", file=sys.stderr)
        return 1

    d = lambda name: os.path.join(args.data_dir, name)
    c = lambda name: os.path.join(args.config_dir, name)

    con = duckdb.connect(args.db)
    print(f"Building {args.db}")

    # ---- items -----------------------------------------------------------
    if os.path.exists(d("ItemsExt.csv")):
        if args.tolerant:
            src = items_tolerant(d("ItemsExt.csv"))
        else:
            src = "SELECT qid, label, description, label_ru, description_ru FROM " + csv(
                d("ItemsExt.csv"),
                {"qid": "VARCHAR", "label": "VARCHAR", "description": "VARCHAR",
                 "lng": "VARCHAR", "label_ru": "VARCHAR", "description_ru": "VARCHAR"})
        con.execute(f"CREATE OR REPLACE TABLE items AS {src}")
        print(f"  items: {con.sql('SELECT count(*) FROM items').fetchone()[0]:,}")
    else:
        print(f"  skip items: no {d('ItemsExt.csv')}")

    # ---- events ----------------------------------------------------------
    if os.path.exists(d("DataEvents.csv")):
        src = csv(d("DataEvents.csv"),
                  {"key": "VARCHAR", "property": "VARCHAR", "time_raw": "VARCHAR",
                   "type": "VARCHAR", "timezone": "VARCHAR", "qual_property": "VARCHAR",
                   "qual_value": "VARCHAR", "qid": "VARCHAR", "class": "VARCHAR"})
        con.execute(f"""CREATE OR REPLACE TABLE events AS
            SELECT DISTINCT qid, property, "class", time_raw,
                   {parse_time_cols('time_raw')},
                   TRY_CAST(timezone AS INTEGER) AS timezone,
                   nullif(qual_property, '0') AS qual_property,
                   nullif(qual_value, '0') AS qual_value
            FROM {src}""")
        print(f"  events: {con.sql('SELECT count(*) FROM events').fetchone()[0]:,}")
    else:
        print(f"  skip events: no {d('DataEvents.csv')}")

    # ---- attributes, class links, value labels ---------------------------
    optional = [
        ("attributes", d("Attributes.csv"),
         {"key": "VARCHAR", "property": "VARCHAR", "value": "VARCHAR", "qid": "VARCHAR"},
         'SELECT DISTINCT qid, property, value FROM'),
        ("item_classes", d("ItemClasses.csv"),
         {"key": "VARCHAR", "qid": "VARCHAR", "class": "VARCHAR"},
         'SELECT DISTINCT qid, "class" FROM'),
        ("value_items", d("values.csv"),
         {"qid": "VARCHAR", "label": "VARCHAR", "description": "VARCHAR"},
         "SELECT qid, label, description FROM"),
        ("classes", c("select_classes.csv"),
         {"qid": "VARCHAR", "label": "VARCHAR", "description": "VARCHAR", "domains": "VARCHAR"},
         "SELECT qid, label, description, domains FROM"),
    ]

    for table, path, columns, select in optional:
        if not os.path.exists(path):
            print(f"  skip {table}: no {path}")
            continue
        con.execute(f"CREATE OR REPLACE TABLE {table} AS {select} {csv(path, columns)}")
        print(f"  {table}: {con.sql(f'SELECT count(*) FROM {table}').fetchone()[0]:,}")

    load_properties(con, args.properties, c("date_properties.csv"), c("attribute_properties.csv"))

    con.close()
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
