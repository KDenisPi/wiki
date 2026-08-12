#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resolve the item IDs used as attribute values into labels.

Attributes.csv stores what an item is linked to, not what that link says:

    Q103_P136_Q492264;P136;Q492264;Q103

Q492264 is only meaningful once it is known to be "progressive rock". The
labels live in Item.csv, the id;label;description dump of every item produced
by the earlier full pass, so one scan over it resolves every value at once.

Values are collected from the attribute file (and optionally the class links),
which keeps the lookup table down to the ids actually referenced instead of
all 129M items.

Output: values.csv - qid;label;description - the dictionary table the
attribute values point at.
"""

import argparse
import os
import sys

from csv_utils import parse_csv_line, write_csv_line

LOG_EVERY = 10_000_000


def collect_ids(attributes_file: str, classes_file: str) -> set:
    """Collect every item ID referenced as an attribute value or a class."""
    wanted = set()

    with open(attributes_file, "r") as fd:
        for line in fd:
            # key;property;value;item
            info = parse_csv_line(line)
            if len(info) >= 3 and info[2]:
                wanted.add(info[2])

    if classes_file and os.path.exists(classes_file):
        with open(classes_file, "r") as fd:
            for line in fd:
                # key;item;class
                info = parse_csv_line(line)
                if len(info) >= 3 and info[2]:
                    wanted.add(info[2])

    return wanted


def resolve(items_file: str, wanted: set, out_file: str) -> int:
    """Scan Item.csv once and write out the label of every wanted ID."""
    found = 0
    processed = 0

    with open(items_file, "r") as fd, open(out_file, "w") as out:
        for line in fd:
            processed += 1

            # the id is everything up to the first delimiter, check it before
            # paying for a full CSV parse of a 129M line file
            off = line.find(";")
            qid = line[:off] if off > 0 else line.strip()
            if qid in wanted:
                info = parse_csv_line(line)
                label = info[1] if len(info) > 1 else ""
                descr = info[2] if len(info) > 2 else ""
                out.write(write_csv_line([qid, label, descr]) + "\n")
                found += 1
                wanted.discard(qid)
                if not wanted:
                    print("  all values resolved, stopping early")
                    break

            if processed % LOG_EVERY == 0:
                print(f"  scanned {processed:,} items, resolved {found:,},"
                      f" {len(wanted):,} left")

    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--attributes", default="Attributes.csv")
    parser.add_argument("--classes", default="ItemClasses.csv",
                        help="class links, so class ids get labels too")
    parser.add_argument("--items", default="/home/denis/projects/wiki_data/fstep/Item.csv",
                        help="id;label;description for every item in the dump")
    parser.add_argument("--out", default="values.csv")
    args = parser.parse_args()

    if not os.path.exists(args.attributes):
        print(f"No attribute file: {args.attributes}", file=sys.stderr)
        return 1
    if not os.path.exists(args.items):
        print(f"No items file: {args.items}", file=sys.stderr)
        return 1

    wanted = collect_ids(args.attributes, args.classes)
    print(f"Distinct ids referenced as a value: {len(wanted):,}")

    total = len(wanted)
    found = resolve(args.items, wanted, args.out)
    print(f"Resolved {found:,} of {total:,} -> {args.out}")
    if wanted:
        print(f"Unresolved: {len(wanted):,} (first few: {sorted(wanted)[:5]})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
