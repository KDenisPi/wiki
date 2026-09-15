#!/bin/bash
#
# Rebuild the whole extract from the dump with the fixed parser, into a new
# directory, leaving the current one untouched until the result is checked.
#
# Why re-read 2 TB at all: the attribute allowlist changed, and which
# attributes are kept is decided while the dump is parsed, so a new property
# cannot be backfilled from the CSVs of an earlier run.
#
# This run changes no property list at all. It re-reads the dump to keep two
# qualifiers the parser has always thrown away: P580 "start time" and P582
# "end time", on attribute claims.
#
# What that buys. Wikidata dates the STATEMENT, not the item. A reign is
# "position held: Tsar of All Russia" carrying P580 1682 and P582 1725; a
# citizenship that lapsed carries the years it was true. Until now the parser
# stored a claim's value and dropped everything qualifying it, so run6 knows
# Peter the Great held two offices and cannot say he reigned 1682-1725. His
# whole dated record is P569 1672 and P570 1725, birth and death.
#
# The 641,801 P580 rows already in the extract are a different thing: they are
# top-level claims on items that have a duration - 386,370 of them clinical
# trials, then badminton events and sports seasons. Only 348 people carry one.
#
# What it fixes, concretely. "Which rulers in Russia lived when Isaac Newton
# was alive?" answers 25 people, and the wrong ones are wrong for want of a
# date: Gustav Evertsson Horn was Governor-General of Finland while Finland was
# Swedish, and Baltic regents held Courland rather than Russia. Neither can be
# excluded today, because no office in the database has a time attached and
# P27 "Russia" sits undated on men who died in 1666 - Q159 is the modern
# Russian Federation, carried by 92,740 people.
#
# It is also the only route to "who ruled Russia in 1700", which needs the
# span of the office and not the lifespan of the person.
#
# Cost and shape of the change:
#
#   cpp/item_parser.h   parse_period() reads the two qualifiers; attribute
#                       claims are walked directly rather than through
#                       parse_property, so nothing about date parsing moves
#                       and every event row comes out identical
#   Attributes.csv      six columns now, key;property;value;item;starts;ends
#   the dedup key       gains the period. The dictionary keeps one row per
#                       key, and a second spell in the same office would
#                       otherwise overwrite the first: verified on Q1056,
#                       who holds one office in 1924-29, 1929-34 and 1934-39,
#                       and keeps all three
#   load_duckdb.py      attributes gains start_year and end_year, read with
#                       the same regex the event dates use. Four-column files
#                       from run6 and earlier still load, periods NULL
#
# Measured on the 1,000-item fixture: 453 of 4,880 attribute rows carry a
# period, 57 of them open-ended - an office still held, which is a start with
# no end and has to stay distinguishable from no dates at all.
#
# The run5 caveat still stands for P527/P361: they arrived, they are stored,
# and they remain unusable until a transitive closure over P361 and an intent
# relation exist. Eight of the eleven here are the same bet - real data waiting
# on schema work - and only P39 and P840 pay off the day the run lands.
#
# The previous run added P7937 "form of creative work" and seeded painting in
# build_class_closure.py. Both worked: P7937 went from 0 rows to 303,706, all
# nine Beethoven symphonies became findable by kind, and the art domain went
# from 3 items to 708,251.
#
# The previous run existed for a different reason, and its check survives in
# preflight: Wikidata moved labels that read the same in every language into
# labels.mul and dropped labels.en for those Items, which cost the run before
# it 1,609,929 English labels. cpp/item_parser.h falls back to labels.mul now,
# and the fixture probe below refuses to start a 21-hour run on a binary that
# has regressed.
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
#   OUT_DIR=/data/run6 ./rerun_extract.sh
#
# Unattended:
#   nohup ./rerun_extract.sh > ~/rerun.log 2>&1 &
#   tail -f ~/rerun.log
#
# Nothing here writes to the current run directory or its database, so the
# question pipeline keeps working off run5 while this runs.

set -uo pipefail

WIKI=${WIKI:-/home/denis/projects/wiki}
OUT_DIR=${OUT_DIR:-/home/denis/projects/wiki_data/run7}
OLD_DIR=${OLD_DIR:-/home/denis/projects/wiki_data/run6}
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
    #what this run is for: the share of each property's claims that now say
    #when they were true. P39 should be the highest by far - an office is
    #dated far more often than a citizenship - and P106 near zero, because an
    #occupation is rarely given a span
    #the previous run has no period columns at all - that is the baseline this
    #one has to rise from, so read it as zero rather than falling over
    dated_cols = {r[0] for r in con.execute("DESCRIBE attributes").fetchall()}
    has_period = "start_year" in dated_cols

    added = {}
    for pid in ("P39", "P27", "P106", "P551", "P26", "P19"):
        dated = con.execute("SELECT count(*) FROM attributes WHERE property = ?"
                            " AND (start_year IS NOT NULL OR end_year IS NOT NULL)",
                            [pid]).fetchone()[0] if has_period else 0
        total = con.execute("SELECT count(*) FROM attributes"
                            " WHERE property = ?", [pid]).fetchone()[0]
        added[pid] = (dated, total)
    #"What novels exist in French literature?" and the Russian version of the
    #same sentence returned identical rows before this: nothing said which
    french = con.execute("""
        SELECT count(*) FROM items i
        WHERE EXISTS (SELECT 1 FROM attributes a JOIN value_items v ON v.qid = a."value"
                      WHERE a.qid = i.qid AND a.property = 'P407'
                        AND regexp_matches(v."label", '(?i)^French$'))
          AND EXISTS (SELECT 1 FROM attributes a JOIN value_items v ON v.qid = a."value"
                      WHERE a.qid = i.qid AND a.property IN ('P921','P136','P7937')
                        AND regexp_matches(v."label", '(?i)\\bnovel'))""").fetchone()[0]
    #Ivan the Terrible is the item that prompted this run. P106 files him as
    #"politician" and nothing else that says he ruled; P39 should say "Tsar of
    #All Russia" outright, which is what LEADER_OCCUPATIONS is working around.
    lived = con.execute("""
        SELECT count(*) FROM attributes a JOIN value_items v ON v.qid = a."value"
        WHERE a.qid = 'Q7996' AND a.property = 'P39'
          AND regexp_matches(v."label", '(?i)tsar')
          AND a.start_year IS NOT NULL""").fetchone()[0] if has_period else 0
    #and the question that could not be asked in any phrasing before: a person
    #with a father the extract can name
    #the case the dedup key had to be widened for: one person, one office,
    #two separate spells. On item_property_value alone the second would
    #overwrite the first and a broken reign would read as one unbroken one
    parents = con.execute("""
        SELECT count(*) FROM (
            SELECT qid, property, "value" FROM attributes
            WHERE property = 'P39' AND start_year IS NOT NULL
            GROUP BY 1, 2, 3 HAVING count(*) > 1)""").fetchone()[0] if has_period else 0
    forms = con.execute("SELECT count(*) FROM attributes"
                        " WHERE property = 'P7937'").fetchone()[0]
    symphonies = con.execute("""
        SELECT count(*) FROM items i
        WHERE EXISTS (SELECT 1 FROM attributes a JOIN value_items v ON v.qid = a."value"
                      WHERE a.qid = i.qid AND a.property IN ('P921','P136','P7937')
                        AND regexp_matches(v."label", '(?i)\\bsymphony'))
          AND EXISTS (SELECT 1 FROM attributes a JOIN value_items v ON v.qid = a."value"
                      WHERE a.qid = i.qid AND a.property = 'P86'
                        AND regexp_matches(v."label", '(?i)\\bBeethoven'))""").fetchone()[0]
    con.close()
    return row, spot, forms, symphonies, added, french, lived, parents

new_counts = counts(new)
if new_counts is None:
    raise SystemExit(f"no database at {new}")
((items, no_label, values_no_label), spot, forms, symphonies,
 added, french, lived, parents) = new_counts
print(f"  items                     {items:,}")
print(f"  items with no label       {no_label:,}  ({no_label / items:.1%})")
print(f"  attribute values no label {values_no_label:,}")

print("  claims that now carry a period:")
for pid, (dated, total) in added.items():
    share = f"{dated / total:.1%}" if total else "-"
    note = "OK" if (pid != "P39" or dated) else "EMPTY - qualifiers not read?"
    print(f"    {pid:<8} {dated:>10,} dated of {total:>12,}  {share:>6}   {note}")
print(f"  French-language novels    {french:,}"
      f"   {'OK' if french else 'LOW - P407 not reaching works'}")
print(f"  Ivan the Terrible reign   {lived} dated tsar statement(s)"
      f"   {'OK' if lived else 'LOW - expected a P580 on Tsar of All Russia'}")
print(f"  offices held twice over   {parents:,}"
      f"   {'OK' if parents else 'EMPTY - the period is not in the dedup key'}")
print(f"  P7937 rows                {forms:,}")
print(f"  Beethoven symphonies      {symphonies} findable by kind"
      f"   {'OK' if symphonies >= 9 else 'LOW - expected 9'}")

old_counts = counts(old)
if old_counts:
    (o_items, o_no_label, o_values), _, o_forms, o_symphonies, _, _, _, _ = old_counts
    print(f"  previous run              {o_items:,} items, {o_no_label:,} unlabelled,"
          f" {o_values:,} values unlabelled")
    print(f"  labels recovered          {o_no_label - no_label:,}")
    print(f"  previous run P7937        {o_forms:,} rows,"
          f" {o_symphonies} Beethoven symphonies findable")

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
