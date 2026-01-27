#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os

def detect_instances(filename : str) -> list:
    """
    Docstring for detect_instances
    
    :param filename: Description
    :type filename: str
    :return: Description
    :rtype: list
    """
    result = []
    counter = 0

    if not os.path.exists(filename):
        return result

    with open(filename, "r") as fd:
        line = fd.readline()
        while line:
            counter += 1
            info = line.strip().split(";")
            for itm in info[8:]:
                if itm in result:
                    continue
                result.append(itm)
            
            if counter%100000 == 0:
                print("{} {}".format(counter, result))

            line = fd.readline()

        fd.close()
        return result
    
if __name__ == '__main__':
    res = detect_instances('/home/denis/projects/wiki_data/attempt/DataEvents.csv')

