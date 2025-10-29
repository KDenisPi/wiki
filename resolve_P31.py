#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os

csv_delim = ";"
filename_P31_in = "P31.csv"
filename_P31_out = "P31_out.csv"

filename_items = "Item.csv"

log_size = 100

def load_P31(file_name:str) -> dict:
    """Load P31 file"""
    result = {}
    if not os.path.exists(file_name):
        return result

    with open(file_name, "r") as fd:
        line = fd.readline()
        while line:
            pos = line.find(csv_delim)
            q_idx = line[0:pos]
            result[q_idx] = line.strip()
            line = fd.readline()
        fd.close()
    return result

def save_p31(file_name:str, props:dict) -> int:
    """Write dictionaly to file"""
    with open(file_name, "w") as fd:
        for items in list(props.values()):
            fd.write(f"{items}\n")
        fd.close()
    return len(props)

def resolve_P31(file_name:str, props:dict) -> int:
    """Resolve P31 description"""

    processed = 0
    resolved = 0
    if not os.path.exists(file_name):
        return 0

    with open(file_name, "r") as fd:
        line = fd.readline()
        while line:
            pos = line.find(csv_delim)
            q_idx = line[0:pos]
            if q_idx in props:
                props[q_idx] = props[q_idx] + line[pos+1:].strip()
                print(props[q_idx])
                resolved += 1
            processed += 1

            if (processed % log_size) == 0:
                print("Processed: {}".format(processed))

            line = fd.readline()
        fd.close()
    return resolved

if __name__ == '__main__':

    p31 = load_P31(filename_P31_in)
    print("Loaded: {}".format(len(p31)))

    resv = resolve_P31(filename_items, p31)
    print("Resolved: {}".format(resv))

    res = save_p31(filename_P31_out, p31)
    print("Saved: {}".format(res))

