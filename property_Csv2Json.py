#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os

from csv_utils import parse_csv_line

file_name_csv = "properties.csv"
file_name_json = "properties.json"

csv_delim = ";"


if not os.path.exists(file_name_csv):
    print("No file {}".format(file_name_csv))
    exit()

fd_w = open(file_name_json, "w")
fd_w.write("{\n")
with open(file_name_csv, "r") as fd:
    line = fd.readline()

    while line:
        prop_info = parse_csv_line(line)
        fd_w.write("\"{0}\" : {1}\"{2}\",\"{3}\"{4}".format(prop_info[0], '[',
                            prop_info[1].replace('"', '\\"'),
                            prop_info[2].replace("\\", "").replace('"', '\\"'), ']'))

        line = fd.readline()
        if line:
            fd_w.write(",\n")
    fd.close()
fd_w.write("}\n")
fd_w.close()


