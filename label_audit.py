"""
Find the Items that came out of the parser without an English label, and say
which of them can be repaired from data already on disk.

Why they are missing: Wikidata moved labels that read the same in every
language ("Leonardo da Vinci", "Mona Lisa") out of labels.en and into a single
labels.mul entry. wpars reads labels.en only, so for those Items it wrote an
empty label - while the English *description*, which was not migrated, came
through. In the 2025-09-22 dump Q762 had no labels.en at all, only
labels.mul; today it has both, and running wpars over today's version of that
Item produces the label correctly. So this is a schema change to follow, not a
parsing bug: labels.en, then labels.mul.

That fix needs another pass over the dump. This script is about what can be
done without one, and it sorts the damage into three buckets:

    enwiki   the Item has an English Wikipedia article, whose title is already
             in ItemSites.csv - repairable offline, right now. Small bucket,
             but it is where the well-known Items are (Barack Obama, Leonardo
             da Vinci, Michael Jackson), because the migration went through the
             most-linked Items first
    ru_only  a Russian label but no English article - needs labels.mul, so
             either a reparse or a lookup against the API
    bare     no label either way. Mostly Items that genuinely have no label in
             Wikidata (a sample of 20 held 16 of them) - not worth chasing

Reads the parser's own output rather than the database, so it says what wpars
emitted rather than what survived loading, and it does not contend with
anything else using the DuckDB file.

Run:
    python label_audit.py select --run-dir /home/denis/projects/wiki_data/run2
    python label_audit.py select --run-dir ... --out-dir /tmp/labels --min-sitelinks 5
"""

import argparse
import csv
import os
import sys


def read_missing(items_ext: str) -> dict:
    """qid -> whether an English description came through, for every Item the
    parser wrote without an English label.

    A description without a label is the signature of the mul migration: the
    Item's English block was there and only the label had moved. An Item with
    neither is more likely to be one Wikidata never labelled.

    Only the first three fields are read. Descriptions can contain the ';'
    delimiter in files written before the escaping fix, but qid and label sit
    in front of any description, so splitting off the first three is safe."""
    missing = {}
    total = 0
    with open(items_ext, encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line or line.startswith("#"):
                continue
            total += 1
            parts = line.rstrip("\n").split(";", 3)
            if len(parts) < 2 or not parts[0]:
                continue
            if parts[1] == "":
                missing[parts[0]] = len(parts) > 2 and parts[2] != ""
    print(f"  {items_ext}: {total} item(s), {len(missing)} without an English label")
    return missing


def read_sites(item_sites: str, wanted: dict) -> dict:
    """qid -> (sitelinks, enwiki title, ruwiki title) for the Items we care
    about. Format is qid;sitelinks;enwiki;ruwiki - the English article title is
    the label these Items are missing, near enough: it carries a disambiguator
    now and then ("Mercury (planet)"), which the composer's ILIKE match steps
    over."""
    sites = {}
    with open(item_sites, encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.rstrip("\n").split(";")
            if not parts or parts[0] not in wanted:
                continue
            count = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            sites[parts[0]] = (count,
                               parts[2] if len(parts) > 2 else "",
                               parts[3] if len(parts) > 3 else "")
    print(f"  {item_sites}: matched {len(sites)} of them")
    return sites


def read_ru_labels(items_ext: str, wanted: dict) -> dict:
    """qid -> Russian label, for Items that have one. Second pass over the same
    file: the Russian block is what tells a mul-migrated Item apart from one
    that was never labelled at all."""
    ru = {}
    with open(items_ext, encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.rstrip("\n").split(";")
            if not parts or parts[0] not in wanted:
                continue
            #...;ru;<label_ru>;<description_ru> - find the language marker
            for i, field in enumerate(parts):
                if field == "ru" and i + 1 < len(parts) and parts[i + 1]:
                    ru[parts[0]] = parts[i + 1]
                    break
    return ru


def select(args: argparse.Namespace) -> None:
    items_ext = os.path.join(args.run_dir, "ItemsExt.csv")
    item_sites = os.path.join(args.run_dir, "ItemSites.csv")
    for path in (items_ext, item_sites):
        if not os.path.exists(path):
            sys.exit(f"Missing: {path}")

    os.makedirs(args.out_dir, exist_ok=True)
    print("Reading parser output:")
    missing = read_missing(items_ext)
    sites = read_sites(item_sites, missing)
    ru_labels = read_ru_labels(items_ext, missing)

    buckets = {"enwiki": [], "ru_only": [], "bare": []}
    for qid, had_en_description in missing.items():
        sitelinks, enwiki, _ruwiki = sites.get(qid, (0, "", ""))
        if sitelinks < args.min_sitelinks:
            continue
        row = (qid, sitelinks, enwiki, ru_labels.get(qid, ""), int(had_en_description))
        if enwiki:
            buckets["enwiki"].append(row)
        elif row[3]:
            buckets["ru_only"].append(row)
        else:
            buckets["bare"].append(row)

    print("\nBuckets (most-linked first):")
    for name, rows in buckets.items():
        rows.sort(key=lambda r: -r[1])
        path = os.path.join(args.out_dir, f"missing_label_{name}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["qid", "sitelinks", "enwiki_title", "label_ru", "had_en_description"])
            writer.writerows(rows)
        print(f"  {name:<8} {len(rows):>9} -> {path}")
        for row in rows[:5]:
            print(f"      {row[0]:<12} sitelinks={row[1]:<4} {row[2] or row[3]}")


def apply_enwiki(args: argparse.Namespace) -> None:
    """Repair an already-built database in place, without reloading it.

    load_duckdb.py does this at the end of a load, so a rebuild needs nothing
    from here; this is for the database on disk right now.

    Every row it is about to change is written out first (qid;enwiki title), so
    the repair can be undone - UPDATE items SET "label" = NULL WHERE qid IN
    (that list) - and so there is a record of which labels are article titles
    rather than labels proper.

    DuckDB gives one writer the whole file, so this fails while anything else
    has the database open, including a read-only reader."""
    import duckdb

    try:
        con = duckdb.connect(args.db)
    except Exception as e:
        sys.exit(f"Cannot open {args.db} for writing: {e}\n"
                 "Something else has the database open - close it and run this again.")

    rows = con.execute("""
        SELECT i.qid, s.enwiki, s.sitelinks FROM items i JOIN sites s ON s.qid = i.qid
        WHERE i."label" IS NULL AND s.enwiki IS NOT NULL
        ORDER BY s.sitelinks DESC""").fetchall()
    print(f"{len(rows)} Item(s) can take an English Wikipedia title as their label")
    for qid, title, sitelinks in rows[:5]:
        print(f"   {qid:<12} sitelinks={sitelinks:<4} {title}")

    if not rows:
        return
    if args.dry_run:
        print("--dry-run: nothing written")
        return

    with open(args.record, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["qid", "enwiki_title", "sitelinks"])
        writer.writerows(rows)
    print(f"recorded the rows about to change -> {args.record}")

    repaired = con.execute("""
        UPDATE items SET "label" = s.enwiki FROM sites s
        WHERE s.qid = items.qid AND items."label" IS NULL AND s.enwiki IS NOT NULL
        """).fetchone()[0]
    con.close()
    print(f"backfilled {repaired} label(s) in {args.db}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    select_parser = sub.add_parser(
        "select", help="list the Items with no English label, bucketed by what can repair them")
    select_parser.add_argument("--run-dir", default="/home/denis/projects/wiki_data/run2",
                               help="directory holding ItemsExt.csv and ItemSites.csv")
    select_parser.add_argument("--out-dir", default="/home/denis/projects/wiki_data/run2/labels",
                               help="where to write the three CSV lists")
    select_parser.add_argument("--min-sitelinks", type=int, default=0,
                               help="skip Items with fewer Wikipedia articles than this. An Item "
                               "no Wikipedia covers is one no question in the test base will ask "
                               "about, so this is how to cut the list down to what matters")
    select_parser.set_defaults(func=select)

    apply_parser = sub.add_parser(
        "apply", help="backfill missing labels from enwiki titles in an existing database")
    apply_parser.add_argument("--db", default="/home/denis/projects/wiki_data/run2/wiki.duckdb",
                              help="DuckDB file to repair, opened for writing")
    apply_parser.add_argument("--record",
                              default="/home/denis/projects/wiki_data/run2/labels/backfilled.csv",
                              help="where to write the rows that were changed, so the repair can "
                              "be undone and so it stays visible which labels are article titles")
    apply_parser.add_argument("--dry-run", action="store_true",
                              help="report what would change and write nothing")
    apply_parser.set_defaults(func=apply_enwiki)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
