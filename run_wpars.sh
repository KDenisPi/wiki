#!/bin/bash
#
# Run wpars over and over until the whole dump is processed.
#
# wpars stops after a chunk of items instead of reading the dump in one go, so
# that a failure costs one chunk and not the whole run. It reports what to do
# next through its exit code:
#
#   0  chunk done, the dump still has items    -> run it again
#   1  something failed                        -> stop and look at the log
#   2  the dump was read to the end            -> finished
#
# Usage:  ./run_wpars.sh [output_dir] [items_per_pass]
#
# Everything lands in the output directory: the CSV files, run.log and the
# position file the next pass resumes from. Start with an empty directory - the
# CSV files are appended to, so a leftover file from an older run stays in.

set -u

# any of these can be overridden from the environment, which is handy for a
# dry run against one of the sample files:
#   DUMP=/home/denis/projects/wiki_data/wiki_1000.json ./run_wpars.sh /tmp/try 300
WPARS=${WPARS:-/home/denis/projects/wiki/build/wpars}
DUMP=${DUMP:-/mnt/nfs/wiki/wikidata-20250922-all.json}
PROPS=${PROPS:-/home/denis/projects/wiki_data/properties.json}
CONFIG=${CONFIG:-/home/denis/projects/wiki_data/classes}

OUT_DIR=${1:-/home/denis/projects/wiki_data/run2}
LIMIT=${2:-15000000}

for f in "$WPARS" "$DUMP" "$PROPS" \
         "$CONFIG/select_classes.csv" "$CONFIG/date_properties.csv" \
         "$CONFIG/attribute_properties.csv"; do
    if [ ! -f "$f" ]; then
        echo "Missing: $f"
        exit 1
    fi
done

mkdir -p "$OUT_DIR"
cd "$OUT_DIR" || exit 1

# The CSV files are opened in append mode, so output left over from an older
# run would silently blend into the new data. CSV files next to a position
# file are a different case: that is an interrupted run being picked up again,
# which is what the loop is here for. Set FORCE=1 to start anyway.
shopt -s nullglob
existing=(./*.csv)
shopt -u nullglob

if [ ${#existing[@]} -gt 0 ] && [ ! -f run.pos ] && [ "${FORCE:-0}" != "1" ]; then
    echo "Refusing to start: $OUT_DIR already holds ${#existing[@]} CSV file(s) but no"
    echo "position file, so this is output from an earlier run rather than one to resume."
    echo "Every row would be written a second time."
    echo
    echo "Either use an empty directory, or remove the old output:"
    echo "  rm -f $OUT_DIR/*.csv $OUT_DIR/*.log"
    echo "Set FORCE=1 to start anyway."
    exit 1
fi

if [ -f run.pos ]; then
    echo "Resuming  : position $(cat run.pos 2>/dev/null)"
fi

echo "Output    : $OUT_DIR"
echo "Per pass  : $LIMIT items"
echo "Log       : $OUT_DIR/run.log"

pass=0
while true; do
    pass=$((pass + 1))
    echo "$(date '+%F %T')  pass $pass started"

    "$WPARS" "$DUMP" "$PROPS" run.pos \
        --classes "$CONFIG/select_classes.csv" \
        --dates   "$CONFIG/date_properties.csv" \
        --attrs   "$CONFIG/attribute_properties.csv" \
        --limit   "$LIMIT" >> run.log 2>&1

    code=$?
    case $code in
        0)
            echo "$(date '+%F %T')  pass $pass done, more data left"
            ;;
        2)
            echo "$(date '+%F %T')  pass $pass done, dump fully processed"
            break
            ;;
        *)
            echo "$(date '+%F %T')  pass $pass FAILED (exit code $code), see $OUT_DIR/run.log"
            exit "$code"
            ;;
    esac
done

echo
echo "Finished after $pass passes. Output:"
ls -la ./*.csv

echo
echo "Next: resolve the attribute values, then load the database"
echo "  python3 /home/denis/projects/wiki/resolve_values.py"
echo "  python3 /home/denis/projects/wiki/load_duckdb.py --data-dir . --db wiki.duckdb"
