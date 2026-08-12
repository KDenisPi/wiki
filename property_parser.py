#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os

from csv_utils import parse_csv_line, write_csv_line

file_name_src = 'prop_list.log'
file_name_csv = "properties.csv"

def prop_loader(file_name:str) -> dict:
    """Load file content to dictionary"""
    result = {}
    if not os.path.exists(file_name):
        return result

    with open(file_name, "r") as fd:
        line = fd.readline()
        while line:
            prop_info = parse_csv_line(line)
            result[prop_info[0]] = prop_info
            line = fd.readline()
        fd.close()
    return result

def prop_write(file_name:str, props:dict) -> int:
    """Write dictionaly to file"""
    with open(file_name, "w") as fd:
        for items in list(props.values()):
            fd.write(f"{write_csv_line(items)}\n")
        fd.close()
    return len(props)

props = prop_loader(file_name_csv)

def collect_properties():
    """Collect properties information"""
    cnt = 0
    with open(file_name_src, "r") as fd:
        line = fd.readline()
        while line:
            off_beg = line.find('">P')
            if off_beg > 0:
                """Start a new property processing"""
                off_beg = off_beg + 2
                off_end = line.find('<', off_beg)
                prop_id = line[off_beg:off_end]
                """Label"""
                label = fd.readline()[4:-6]
                description = fd.readline()[4:-6]

                if prop_id not in props:
                    props[prop_id] = [prop_id, label, description]

                cnt = cnt + 1
                if cnt%10 == 0:
                    print(f"Processed {cnt}")

            line = fd.readline()
        fd.close()

    if len(props)>0:
        pr_cnt = prop_write(file_name_csv, props)
        print(f"\nNUmber of properties {pr_cnt}")

if __name__ == '__main__':
    collect_properties()
