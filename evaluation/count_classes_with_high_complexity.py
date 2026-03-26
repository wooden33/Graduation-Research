import os
import numpy as np
import re
import sys
import json
import subprocess
import csv
import logging
import os


def get_d4j_subjects():
    d4j_subjects = []
    with open('d4j-fixed-version.csv', 'r') as file:
        reader = csv.reader(file)
        next(reader)

        for row in reader:
            # Append the first column value to the list
            d4j_subjects.append(row[0])
    return d4j_subjects


if __name__ == '__main__':
    defects4j_subjects = ["JacksonXml-5f", "Csv-16f", "Collections-28f", "Gson-16f", "Cli-40f", "JacksonCore-26f",
                          "JxPath-22f", "Jsoup-93f", "Codec-18f", "Compress-47f", "JacksonDatabind-112f",
                          "Time-13f", "Lang-4f", "Math-2f"]
    count_1 = 0
    count_2 = 0
    for p_name in defects4j_subjects:
        print(p_name)
        with open(os.path.join("defects4j-codefiles", f"{p_name}-codefiles.json"), 'r') as f:
            data = json.load(f)

        file_objects = data["src_test_exact_match"] + data["src_test_fuzz_match"] + data["src_without_tests"]
        for src_file in file_objects:
            if "methods_under_test" in src_file.keys():
                if "abstract" in src_file["class_declaration"]:
                    continue
                if src_file["methods_under_test"]["11-20"] and not src_file["methods_under_test"][">20"]:
                    max_cc = 0
                    valid = True
                    for key, value in src_file["methods_under_test"]["11-20"].items():
                        if value[0] == value[1] == value[2]:
                            if value[0] > max_cc:
                                max_cc = value[0]
                        else:
                            valid = False
                            break
                    if not valid:
                        #print("invalid", p_name, src_file["src_name"])
                        continue
                    #print(src_file["src_name"], max_cc)
                    count_1 +=1
                if src_file["methods_under_test"][">20"]:
                    max_cc = 0
                    valid = True
                    for key, value in src_file["methods_under_test"][">20"].items():
                        if value[0] == value[1] == value[2]:
                            if value[0] > max_cc:
                                max_cc = value[0]
                        else:
                            valid = False
                            break
                    if not valid:
                        #print("invalid", p_name, src_file["src_name"])
                        continue

                    if max_cc > 40:
                        continue
                    #print(src_file["src_name"], max_cc)
                    count_2 += 1

    print("total", count_1, count_2, count_1+count_2)
