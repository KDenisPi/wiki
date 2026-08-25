#!/bin/bash
#
# Rebuild the whole extract from the dump with the fixed parser, into a new
# directory, leaving the current one untouched until the result is checked.
#
# Why re-read 2 TB at all: Wikidata moved labels that read the same in every
# language into a single labels.mul entry and removed labels.en for those
# Items. The parser read labels.en only, so 1,609,929 Items came out of the
# last run with no English label - among them Barack Obama, Leonardo da Vinci,
# Michael Jackson, because the migration went through the most-linked Items
# first. cpp/item_parser.h now falls back to labels.mul, and labels.mul is only
# in the dump, so the fix needs a pass over it.
#
# What runs, in order:
#
#   preflight  the checks worth failing on in two seconds rather than after
#              twenty hours: the dump is readable, the binary really has the
#              mul fix (it is run against cpp/testdata/mul_label_item.json,
#              which is Q762 exactly as the dump holds it - mul label, no en),
#              the output directory is empty, and the disk has room
#   parse      run_wpars.sh over the dump, in chunks, resuming from run.pos.
#              ~21 hours for the 2025-09-22 dump
#   values     resolve_values.py, against this run's own ItemsExt.csv and
#              ItemsExtNotUsed.csv rather than the Item.csv from an older pass,
#              so attribute values (occupations, places, genres) get labels
#              from the fixed parser too - 40,345 of them are missing today
#   load       load_duckdb.py, which ends by filling any label still missing
#              from the English Wikipedia article title
#   verify     what changed against the previous run, and the Items that
#              prompted all this
#
# Every step is safe to run again. parse resumes where it stopped; the others
# rebuild their output from scratch and take minutes, not hours.
#
# Usage:
#   ./rerun_extract.sh                  # everything, in order
#   ./rerun_extract.sh preflight        # just the checks
#   ./rerun_extract.sh parse            # or values / load / verify
#   OUT_DIR=/data/run4 ./rerun_extract.sh
#
# Unattended:
#   nohup ./rerun_extract.sh > ~/rerun.log 2>&1 &
#   tail -f ~/rerun.log
#
# Nothing here writes to the current run directory or its database, so the
# question pipeline keeps working off run2 while this runs.

set -uo pipefail

WIKI=${WIKI:-/home/denis/projects/wiki}
OUT_DIR=${OUT_DIR:-/home/denis/projects/wiki_data/run3}
OLD_DIR=${OLD_DIR:-/home/denis/projects/wiki_data/run2}
DUMP=${DUMP:-/mnt/nfs/wiki/wikidata-20250922-all.json}
PROPS=${PROPS:-/home/denis/projects/wiki_data/properties.json}
CONFIG=${CONFIG:-/home/denis/projects/wiki_data/classes}
WPARS=${WPARS:-$WIKI/build/wpars}
PY=${PY:-/home/denis/projects/venv3.11/bin/python}
FIXTURE=$WIKI/cpp/testdata/mul_label_item.json
NEED_GB=${NEED_GB:-40}

step() { echo; echo "=== $(date '+%F %T')  $1"; }
die()  { echo "FAILED: $1" >&2; exit 1; }

preflight() {
    step "preflight"

    [ -x "$WPARS" ] || die "no parser binary at $WPARS (build it: cd $WIKI/build && ninja wpars)"
    [ -f "$FIXTURE" ] || die "no fixture at $FIXTURE"
    [ -f "$PROPS" ] || die "no properties file at $PROPS"
    for f in select_classes.csv date_properties.csv attribute_properties.csv; do
        [ -f "$CONFIG/$f" ] || die "no $CONFIG/$f"
    done
    [ -x "$PY" ] || die "no python at $PY"

    # the dump lives on an NFS mount that is automounted on first use, so this
    # doubles as waking it up
    [ -r "$DUMP" ] || die "cannot read the dump at $DUMP"
    echo "  dump: $(du -h --apparent-size "$DUMP" 2>/dev/null | cut -f1) $DUMP"

    # Does this binary have the mul fix? The fixture is Q762 as the dump holds
    # it: labels.mul only, no labels.en. A parser without the fix writes an
    # empty label for it, which is the whole bug, so this catches a stale
    # binary before twenty hours are spent reproducing the same broken output.
    local probe
    probe=$(mktemp -d)
    ( cd "$probe" && "$WPARS" "$FIXTURE" "$PROPS" run.pos \
        --classes "$CONFIG/select_classes.csv" \
        --dates   "$CONFIG/date_properties.csv" \
        --attrs   "$CONFIG/attribute_properties.csv" --limit 5 >/dev/null 2>&1 )
    local line
    line=$(head -1 "$probe/ItemsExt.csv" 2>/dev/null)
    rm -rf "$probe"
    case "$line" in
        "Q762;Leonardo da Vinci;"*)
            echo "  parser: reads labels.mul (fixture ok)" ;;
        "Q762;;"*)
            die "the parser at $WPARS has no mul fallback - it wrote an empty label for the
       fixture, which is the bug this run exists to fix. Rebuild it:
           cd $WIKI/build && ninja wpars" ;;
        *)
            die "the fixture produced no usable output (got: ${line:-<nothing>})" ;;
    esac

    if [ -d "$OUT_DIR" ]; then
        shopt -s nullglob
        local existing=("$OUT_DIR"/*.csv)
        shopt -u nullglob
        if [ ${#existing[@]} -gt 0 ] && [ ! -f "$OUT_DIR/run.pos" ]; then
            die "$OUT_DIR already holds CSV files but no run.pos, so that is finished output
       from an earlier run. wpars appends, so every row would be written twice.
       Use an empty directory, or remove the old output first."
        fi
        [ -f "$OUT_DIR/run.pos" ] && echo "  resuming a run at position $(cat "$OUT_DIR/run.pos")"
    fi
    mkdir -p "$OUT_DIR" || die "cannot create $OUT_DIR"

    local free_gb
    free_gb=$(df -BG --output=avail "$OUT_DIR" | tail -1 | tr -dc '0-9')
    echo "  free space: ${free_gb}G (CSV output ~14G, database ~15G)"
    [ "$free_gb" -ge "$NEED_GB" ] || die "less than ${NEED_GB}G free on $OUT_DIR"

    echo "  output: $OUT_DIR"
    echo "  preflight ok"
}

parse() {
    step "parse (~21 hours; resumable, progress in $OUT_DIR/run.log)"
    WPARS="$WPARS" DUMP="$DUMP" PROPS="$PROPS" CONFIG="$CONFIG" \
        "$WIKI/run_wpars.sh" "$OUT_DIR" || die "wpars stopped early - see $OUT_DIR/run.log"
    for f in ItemsExt.csv ItemSites.csv Attributes.csv DataEvents.csv ItemClasses.csv; do
        [ -s "$OUT_DIR/$f" ] || die "no $f in $OUT_DIR"
    done
    wc -l "$OUT_DIR"/ItemsExt.csv
}

values() {
    step "values (resolve attribute values against this run's own items)"
    "$PY" "$WIKI/resolve_values.py" \
        --attributes "$OUT_DIR/Attributes.csv" \
        --classes    "$OUT_DIR/ItemClasses.csv" \
        --items      "$OUT_DIR/ItemsExt.csv" "$OUT_DIR/ItemsExtNotUsed.csv" \
        --out        "$OUT_DIR/values.csv" || die "resolve_values.py failed"
}

load() {
    step "load (build the database)"
    "$PY" "$WIKI/load_duckdb.py" \
        --data-dir "$OUT_DIR" \
        --config-dir "$CONFIG" \
        --properties "$PROPS" \
        --db "$OUT_DIR/wiki.duckdb" || die "load_duckdb.py failed"
}

verify() {
    step "verify"
    OUT_DIR="$OUT_DIR" OLD_DIR="$OLD_DIR" "$PY" - <<'PYCODE'
import os
import duckdb

new = os.path.join(os.environ["OUT_DIR"], "wiki.duckdb")
old = os.path.join(os.environ["OLD_DIR"], "wiki.duckdb")

def counts(path):
    if not os.path.exists(path):
        return None
    con = duckdb.connect(path, read_only=True)
    row = con.execute('''
        SELECT count(*),
               count(*) FILTER (WHERE "label" IS NULL OR "label" = ''),
               (SELECT count(*) FROM value_items WHERE "label" IS NULL OR "label" = '')
        FROM items''').fetchone()
    spot = {q: con.execute('SELECT "label" FROM items WHERE qid = ?', [q]).fetchone()
            for q in ("Q762", "Q76", "Q2831", "Q12418")}
    con.close()
    return row, spot

new_counts = counts(new)
if new_counts is None:
    raise SystemExit(f"no database at {new}")
(items, no_label, values_no_label), spot = new_counts
print(f"  items                     {items:,}")
print(f"  items with no label       {no_label:,}  ({no_label / items:.1%})")
print(f"  attribute values no label {values_no_label:,}")

old_counts = counts(old)
if old_counts:
    (o_items, o_no_label, o_values), _ = old_counts
    print(f"  previous run              {o_items:,} items, {o_no_label:,} unlabelled,"
          f" {o_values:,} values unlabelled")
    print(f"  labels recovered          {o_no_label - no_label:,}")

print("  spot checks (label in the new database):")
for qid, name in (("Q762", "Leonardo da Vinci"), ("Q76", "Barack Obama"),
                  ("Q2831", "Michael Jackson"), ("Q12418", "Mona Lisa")):
    row = spot.get(qid)
    if row is None:
        #no row at all is the class filter, not the labels: Mona Lisa parses
        #fine and goes to ItemsExtNotUsed because painting is not a selected class
        print(f"    -- {qid:<8} {name:<20} no row - not selected by the class filter")
    elif row[0] is None:
        print(f"    !! {qid:<8} {name:<20} row present, label still missing")
    else:
        print(f"    ok {qid:<8} {name:<20} {row[0]!r}")
PYCODE
    echo
    echo "  Nothing points at the new database yet. When the numbers look right,"
    echo "  switch the pipeline over by passing --db $OUT_DIR/wiki.duckdb, or by"
    echo "  changing the default in agent/sentence_to_sql.py and agent/compare_models.py."
}

case "${1:-all}" in
    preflight) preflight ;;
    parse)     parse ;;
    values)    values ;;
    load)      load ;;
    verify)    verify ;;
    all)       preflight && parse && values && load && verify ;;
    *)         echo "Usage: $0 [all|preflight|parse|values|load|verify]"; exit 1 ;;
esac

step "done"
