#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the P31 selection set for the parser from the seed classes in
description.txt (5.1 List of interesting instances).

The parser matches an item's P31 value against a fixed list of seed classes.
Wikidata models real items as instances of *subclasses* of those seeds
(a battle is P31=Q178561, and Q178561 is P279* of "event"), so the direct
match selects almost nothing outside Q5. This script expands every seed
through the P279 (subclass of) closure using the Wikidata Query Service and
writes the expanded set to a file the parser can load.

Seeds come in two shapes:
  SUBCLASS  - an ordinary class; its P279* descendants are the classes to match
  METACLASS - a class whose instances are themselves classes ("Wikidata
              metaclass"); those instances plus their P279* descendants
  OCCUPATION- a class whose instances are occupations. Occupations are not P31
              values of people, they are P106 values, so they go to a separate
              vocabulary file instead of the P31 selection set.

Outputs (into --out-dir):
  select_classes.csv  QID;label;description;root_seeds   - P31 selection set
  occupations.csv     QID;label;description;root_seeds   - P106 vocabulary
  closure_report.txt  per-seed counts and dump coverage

Labels are resolved offline from P31_out.csv (the distinct P31 values already
collected from the dump) rather than from WDQS, which also tells us how many
of the expanded classes actually occur in the dump.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from csv_utils import parse_csv_line, write_csv_line

WDQS_ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "wiki-class-closure/0.1 (https://github.com/KDenisPi/wiki; dkudja@gmail.com)"

SUBCLASS = "subclass"
METACLASS = "metaclass"
OCCUPATION = "occupation"

# Seeds from description.txt 5.1, with the expansion mode each one needs.
# The "domain" is carried through to the output so items can later be grouped
# by area (music / science / event / person / ...).
SEEDS = [
    # qid,          domain,      mode
    ("Q5",          "person",    SUBCLASS),

    ("Q13418847",   "event",     SUBCLASS),   # historical event
    ("Q1656682",    "event",     SUBCLASS),   # event
    ("Q58687420",   "event",     SUBCLASS),   # cultural event
    ("Q24336466",   "event",     SUBCLASS),   # mythical event
    ("Q30111082",   "event",     SUBCLASS),   # political event
    ("Q2680861",    "science",   SUBCLASS),   # transient astronomical event
    ("Q55814",      "science",   SUBCLASS),   # extinction event
    ("Q2245405",    "event",     SUBCLASS),   # key event
    ("Q113162275",  "music",     SUBCLASS),   # music event
    ("Q52260246",   "science",   SUBCLASS),   # scientific event
    ("Q110799181",  "event",     SUBCLASS),   # in-person event
    ("Q106518893",  "event",     SUBCLASS),   # entity in event
    ("Q463796",     "science",   SUBCLASS),   # impact event
    ("Q1568205",    "literature", SUBCLASS),  # literary event
    ("Q2136042",    "art",       SUBCLASS),   # arts event
    ("Q117769381",  "event",     SUBCLASS),   # social event
    ("Q109975697",  "science",   SUBCLASS),   # geological event
    ("Q108586636",  "event",     METACLASS),  # form of event (metaclass)

    ("Q105543609",  "music",     METACLASS),  # musical work/composition (metaclass)
    ("Q107487333",  "music",     METACLASS),  # type of musical work/composition (metaclass)
    ("Q2188189",    "music",     SUBCLASS),   # musical work
    ("Q207628",     "music",     SUBCLASS),   # composed musical work

    ("Q12737077",   "occupation", OCCUPATION),  # occupation
    ("Q135106813",  "music",      OCCUPATION),  # musical occupation
    ("Q15839299",   "art",        OCCUPATION),  # theatrical occupation
    ("Q63187345",   "religion",   OCCUPATION),  # religious occupation

    ("Q6256",       "place",     SUBCLASS),   # country
    ("Q5107",       "place",     SUBCLASS),   # continent

    ("Q93288",      "event",     SUBCLASS),   # contract
    ("Q11514315",   "event",     SUBCLASS),   # historical period
    ("Q103495",     "event",     SUBCLASS),   # world war
    ("Q47461344",   "literature", SUBCLASS),  # written work
    ("Q11344",      "science",   SUBCLASS),   # chemical element
]

# Seeds deliberately dropped from description.txt 5.1: these describe Wikidata
# properties and Wikimedia list pages, not items we can date.
#   Q22965078  Wikidata property for items about musical works
#   Q28146956  Wikidata property to identify musical works
#   Q66666236  Wikimedia list of persons by occupation

# The P279 graph is not clean: following it without a bound drags whole
# unrelated branches into the selection. These subtrees are subtracted again
# after the closure is built. The item counts are direct P31 usage measured
# with haswbstatement on the Wikidata search API - they are the reason each
# root is here. Comment a line out to let that branch back in.
EXCLUDE_SEEDS = [
    ("Q13442814",  "scholarly article"),        # 45,820,128 items, every one dated
    ("Q4167836",   "Wikimedia category"),       #  5,827,598
    ("Q4167410",   "Wikimedia disambiguation"), #  1,527,696
    ("Q3331189",   "version, edition or translation"),  # 842,123 - editions duplicate the work
    ("Q11266439",  "Wikimedia template"),       #    830,287
    ("Q13433827",  "encyclopedia article"),     #    688,488
    ("Q13406463",  "Wikimedia list article"),   #    382,597
    ("Q17442446",  "Wikimedia internal item"),  #      6,307 direct, root of the branches above
    ("Q7889",      "video game"),               #    175,509 - outside the target areas
    ("Q7397",      "software"),                 #     18,719 - outside the target areas
]

QUERIES = {
    SUBCLASS: "SELECT ?c WHERE {{ ?c wdt:P279* wd:{seed} }}",
    # instances of the metaclass are classes; take them and their descendants
    METACLASS: (
        "SELECT ?c WHERE {{"
        " {{ ?c wdt:P279* wd:{seed} }}"
        " UNION"
        " {{ ?x wdt:P31 wd:{seed} . ?c wdt:P279* ?x }}"
        " }}"
    ),
    OCCUPATION: (
        "SELECT ?c WHERE {{"
        " {{ ?c wdt:P279* wd:{seed} }}"
        " UNION"
        " {{ ?x wdt:P31 wd:{seed} . ?c wdt:P279* ?x }}"
        " }}"
    ),
}


def run_query(query: str, retries: int = 4, pause: float = 2.0) -> list:
    """POST a SPARQL query to WDQS and return the list of QIDs it selected."""
    data = urllib.parse.urlencode({"query": query, "format": "json"}).encode()
    req = urllib.request.Request(
        WDQS_ENDPOINT,
        data=data,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/sparql-results+json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )

    last_err = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                payload = json.load(resp)
            qids = []
            for row in payload["results"]["bindings"]:
                uri = row["c"]["value"]
                qid = uri.rsplit("/", 1)[-1]
                if qid.startswith("Q"):
                    qids.append(qid)
            return qids
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as err:
            last_err = err
            wait = pause * (2 ** attempt)
            print(f"    query failed ({err}); retry in {wait:.0f}s", file=sys.stderr)
            time.sleep(wait)

    raise RuntimeError(f"WDQS query failed after {retries} attempts: {last_err}")


def fetch_seed(seed: str, mode: str, cache_dir: str) -> list:
    """Fetch (or reuse the cached) closure for one seed."""
    cache_file = os.path.join(cache_dir, f"{seed}_{mode}.json")
    if os.path.exists(cache_file):
        with open(cache_file, "r") as fd:
            qids = json.load(fd)
        print(f"  {seed} [{mode}]: {len(qids)} classes (cached)")
        return qids

    qids = run_query(QUERIES[mode].format(seed=seed))
    with open(cache_file, "w") as fd:
        json.dump(qids, fd)
    print(f"  {seed} [{mode}]: {len(qids)} classes")
    time.sleep(1.0)  # be polite to a shared public endpoint
    return qids


def load_dump_classes(p31_file: str) -> dict:
    """Load QID -> (label, description) for every P31 value seen in the dump."""
    result = {}
    if not os.path.exists(p31_file):
        print(f"WARNING: {p31_file} not found, labels will be empty", file=sys.stderr)
        return result

    with open(p31_file, "r") as fd:
        for line in fd:
            info = parse_csv_line(line)
            if len(info) >= 4:
                result[info[0]] = (info[2], info[3])
            elif len(info) >= 3:
                result[info[0]] = (info[2], "")
    return result


def write_classes(out_file: str, qids: dict, dump_classes: dict, only_in_dump: bool) -> int:
    """Write QID;label;description;root_seeds, sorted by QID number."""
    count = 0
    with open(out_file, "w") as fd:
        for qid in sorted(qids, key=lambda q: int(q[1:])):
            label, descr = dump_classes.get(qid, ("", ""))
            if only_in_dump and qid not in dump_classes:
                continue
            roots = "|".join(sorted(qids[qid]))
            fd.write(write_csv_line([qid, label, descr, roots]) + "\n")
            count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", default="/home/denis/projects/wiki_data/classes",
                        help="where to write the selection files")
    parser.add_argument("--p31-file", default="/home/denis/projects/wiki_data/fstep/P31_out.csv",
                        help="distinct P31 values collected from the dump, used for labels")
    parser.add_argument("--only-in-dump", action="store_true",
                        help="keep only classes that actually occur as a P31 value in the dump")
    args = parser.parse_args()

    cache_dir = os.path.join(args.out_dir, "cache")
    os.makedirs(cache_dir, exist_ok=True)

    selection = {}    # qid -> set of domains, for the P31 selection set
    occupations = {}  # qid -> set of domains, for the P106 vocabulary
    report = []

    print(f"Expanding {len(SEEDS)} seeds through the P279 closure")
    for seed, domain, mode in SEEDS:
        qids = fetch_seed(seed, mode, cache_dir)
        target = occupations if mode == OCCUPATION else selection
        for qid in qids:
            target.setdefault(qid, set()).add(domain)
        report.append((seed, domain, mode, len(qids)))

    dump_classes = load_dump_classes(args.p31_file)
    print(f"\nDistinct P31 values seen in the dump: {len(dump_classes)}")

    print(f"\nSubtracting {len(EXCLUDE_SEEDS)} excluded subtrees")
    excluded = {}
    for seed, name in EXCLUDE_SEEDS:
        qids = fetch_seed(seed, SUBCLASS, cache_dir)
        hit = [q for q in qids if q in selection]
        in_dump_hit = [q for q in hit if q in dump_classes]
        for qid in hit:
            excluded.setdefault(qid, set()).add(name)
        print(f"    {seed} {name}: removes {len(hit)} classes"
              f" ({len(in_dump_hit)} of them seen in the dump)")
        report.append((seed, name, "exclude", -len(hit)))

    # keep an audit trail: what was dropped, and by which rule
    with open(os.path.join(args.out_dir, "excluded_classes.csv"), "w") as fd:
        for qid in sorted(excluded, key=lambda q: int(q[1:])):
            label, descr = dump_classes.get(qid, ("", ""))
            fd.write(write_csv_line([qid, label, descr,
                                     "|".join(sorted(selection[qid])),
                                     "|".join(sorted(excluded[qid]))]) + "\n")
        for qid in excluded:
            del selection[qid]
    print(f"  removed {len(excluded)} classes from the selection set")

    sel_file = os.path.join(args.out_dir, "select_classes.csv")
    occ_file = os.path.join(args.out_dir, "occupations.csv")
    sel_count = write_classes(sel_file, selection, dump_classes, args.only_in_dump)
    occ_count = write_classes(occ_file, occupations, dump_classes, args.only_in_dump)

    in_dump = sum(1 for q in selection if q in dump_classes)

    with open(os.path.join(args.out_dir, "closure_report.txt"), "w") as fd:
        fd.write("seed;domain;mode;classes\n")
        for row in report:
            fd.write(";".join(str(x) for x in row) + "\n")
        fd.write(f"\nP31 selection set: {len(selection)} classes"
                 f" ({in_dump} of them occur as a P31 value in the dump)\n")
        fd.write(f"occupation vocabulary: {len(occupations)} classes\n")
        fd.write(f"written to {sel_file}: {sel_count}\n")
        fd.write(f"written to {occ_file}: {occ_count}\n")

    print(f"\nP31 selection set : {len(selection)} classes"
          f" ({in_dump} occur in the dump) -> {sel_file} [{sel_count} written]")
    print(f"occupations       : {len(occupations)} classes -> {occ_file} [{occ_count} written]")


if __name__ == "__main__":
    main()
