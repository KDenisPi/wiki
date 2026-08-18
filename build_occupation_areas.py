#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Map the occupations that occur in the extract onto areas.

"Which scientists lived in Germany in the 1400s?" returns nothing when
"scientist" is matched literally: the century has 58,088 dated people and 2,213
with a German place, but only 50 carry the occupation "scientist". The rest are
astronomers, physicians, mathematicians and theologians. The question means an
area, and the data records a profession.

Wikidata already knows that an astronomer is a scientist - it is P279 all the
way up - so the mapping is fetched rather than invented: expand a few area
roots through the subclass closure, then keep only the occupations that
actually appear in the extract. The closure of "scientist" alone runs to
thousands of professions, most of which nobody in the data has.

Reuses the WDQS client in build_class_closure.py, including its on-disk cache,
so re-running costs nothing and the endpoint is queried once per root.

    python build_occupation_areas.py
    python build_occupation_areas.py --db ... --out ... --min-people 5

Writes occupation_areas.csv (qid;label;areas;people) next to the other
selection files, plus a coverage report naming the most common occupations that
no area claimed - that list is what to read before adding a root.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_class_closure import OCCUPATION, fetch_seed  # noqa: E402

#Roots per area, each expanded through P279* (and P31/P279* for the metaclass
#case, which is what OCCUPATION mode does). Kept short on purpose: a root is a
#claim about what belongs to an area, and every one added has to be defensible.
#Coverage is reported per run, so the uncovered list is the evidence for adding
#the next one rather than guesswork.
AREA_SEEDS = {
    "science": [
        ("Q901",     "scientist"),
        ("Q1650915", "researcher"),
        ("Q81096",   "engineer"),      # not under scientist, but asked for as science
        ("Q39631",   "physician"),     # medicine, likewise
    ],
    "music": [
        ("Q639669",  "musician"),
        ("Q36834",   "composer"),      # not every composer item is under musician
    ],
    "art": [
        #Q483501 is the "artist" the data actually uses - 60,148 people hold it,
        #against 19 for the other item of the same label
        ("Q483501",  "artist"),
        ("Q3391743", "artist (the other item of that name)"),
        ("Q33999",   "actor"),
    ],
    "literature": [
        ("Q36180",   "writer"),
        ("Q482980",  "author"),
    ],
}

#Subtracted from every area afterwards, the same way build_class_closure.py
#prunes its seeds. Wikidata puts teaching under researcher and scientist, which
#hands "science" its two largest occupations - 233,786 university teachers and
#81,252 teachers - and neither says anything about a scientific discipline.
#Removing the occupation does not remove the person: a physicist who also
#taught still arrives through "physicist", while someone who only ever taught
#no longer answers "which scientists".
EXCLUDE_SEEDS = [
    ("Q1622272", "university teacher"),   # 233,786 people
    ("Q37226",   "teacher"),              #  81,252
    ("Q1231865", "pedagogue"),            #  35,615
]

OCCUPATION_PROP = "P106"


def used_occupations(db_path: str) -> dict:
    """Every occupation in the extract, with how many people hold it."""
    import duckdb

    con = duckdb.connect(db_path, read_only=True)
    rows = con.execute(f"""
        SELECT a."value" AS qid, max(v."label") AS label, count(DISTINCT a.qid) AS people
        FROM attributes a
        JOIN value_items v ON v.qid = a."value"
        WHERE a.property = '{OCCUPATION_PROP}'
        GROUP BY a."value"
        ORDER BY people DESC""").fetchall()
    con.close()
    return {qid: (label, people) for qid, label, people in rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default="/home/denis/projects/wiki_data/run2/wiki.duckdb")
    parser.add_argument("--out", default="/home/denis/projects/wiki_data/classes/occupation_areas.csv")
    parser.add_argument("--cache", default="/home/denis/projects/wiki/cache")
    parser.add_argument("--min-people", type=int, default=1,
                        help="skip occupations held by fewer people than this")
    parser.add_argument("--report", type=int, default=25,
                        help="how many uncovered occupations to list")
    args = parser.parse_args()

    os.makedirs(args.cache, exist_ok=True)

    print(f"Reading the occupations used in {args.db}")
    used = used_occupations(args.db)
    total_people = sum(people for _, people in used.values())
    print(f"  {len(used):,} distinct occupations, {total_people:,} person-occupation pairs\n")

    #qid -> set of areas; an occupation can sit in two (a singer-songwriter is
    #music and literature), which is why this is a set and the file holds a
    #'|' separated list, like classes.domains
    areas = {}
    for area, seeds in AREA_SEEDS.items():
        print(f"{area}:")
        for seed, name in seeds:
            qids = fetch_seed(seed, OCCUPATION, args.cache)
            hits = [q for q in qids if q in used]
            for qid in hits:
                areas.setdefault(qid, set()).add(area)
            people = sum(used[q][1] for q in hits)
            print(f"    {seed} {name}: {len(qids):,} in the closure,"
                  f" {len(hits):,} used here, {people:,} people")
        print()

    print(f"Subtracting {len(EXCLUDE_SEEDS)} subtrees")
    for seed, name in EXCLUDE_SEEDS:
        #the closure can name the same class twice, hence the set
        qids = set(fetch_seed(seed, OCCUPATION, args.cache))
        gone = [q for q in qids if q in areas]
        people = sum(used[q][1] for q in gone)
        for qid in gone:
            del areas[qid]
        print(f"    {seed} {name}: dropped {len(gone):,} occupations, {people:,} people")
    print()

    rows = []
    for qid, tags in areas.items():
        label, people = used[qid]
        if people >= args.min_people and label:
            rows.append((qid, label, "|".join(sorted(tags)), people))
    rows.sort(key=lambda r: -r[3])

    with open(args.out, "w") as fd:
        fd.write("# occupation QID;label;areas;people - built by build_occupation_areas.py\n")
        fd.write("# areas are '|' separated, the same convention as classes.domains\n")
        for qid, label, tags, people in rows:
            fd.write(f"{qid};{label};{tags};{people}\n")

    covered = sum(r[3] for r in rows)
    print(f"Wrote {len(rows):,} occupations to {args.out}")
    print(f"  {covered:,} of {total_people:,} person-occupation pairs covered"
          f" ({100.0 * covered / total_people:.1f}%)")
    for area in AREA_SEEDS:
        n = sum(r[3] for r in rows if area in r[2].split("|"))
        print(f"  {area:12s} {n:>10,} people")

    uncovered = sorted(((people, label) for qid, (label, people) in used.items()
                        if qid not in areas and label),
                       reverse=True)[:args.report]
    print(f"\nMost common occupations no area claimed - add a root if one belongs:")
    for people, label in uncovered:
        print(f"  {people:>9,}  {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
