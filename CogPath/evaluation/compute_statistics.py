import os
import numpy as np
import re
import sys
import json
import subprocess
import csv
import logging
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cogpath.cfg.src.comex.codeviews.CFG.CFG_driver import CFGDriver
from utils import get_all_code_files, get_code_test_file_mapping, get_filename_from_path


def generate_cfg(code_file):
    file_handle = open(code_file, "r", encoding="utf-8", errors="ignore")
    src_code = file_handle.read()
    file_handle.close()
    cfg_driver = CFGDriver(language, src_code, {"statistics": code_file})
    testable_methods = cfg_driver.testable_methods
    class_obj = cfg_driver.file_obj["class_objects"][0]
    class_dec = class_obj["class_declaration"]["value"]
    return class_dec, testable_methods


# Function to create a CSV file and write header
def create_csv_file(filename, header):
    with open(filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(header)


# Function to append new lines to the CSV file
def append_to_csv_file(filename, row):
    with open(filename, mode='a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(row)


def calculate_statistics(data):
    data = np.array(data)
    min_val = np.min(data)
    max_val = np.max(data)
    median = np.median(data)
    q1 = np.percentile(data, 25)
    q3 = np.percentile(data, 75)
    count_1 = np.sum(data == 1)
    count_2_10 = np.sum((data > 1) & (data <= 10))
    count_11_20 = np.sum((data > 10) & (data <= 20))
    count_20_more = np.sum(data > 20)
    return min_val, q1, median, q3, max_val, count_1, count_2_10, count_11_20, count_20_more


def run_test_coverage(repo_dir_path):
    coverage_process = subprocess.run(['../../defects4j/framework/bin/defects4j', 'coverage'],
                                      capture_output=True, cwd=repo_dir_path)
    captured_stdout = coverage_process.stdout.decode()
    captured_stderr = coverage_process.stderr.decode()

    if len(captured_stdout) == 0:
        logging.error(f"No coverage output for repo {repo_dir_path}")
        return {}
    else:
        stdout_lines = captured_stdout.split('\n')
        coverage = {}
        for line in stdout_lines:
            if line:
                key = line.split(":")[0].strip()
                value = line.split(":")[1].strip()
                coverage[key] = value

        return coverage


def get_d4j_subjects():
    d4j_subjects = []
    with open('data/d4j-fixed-version.csv', 'r') as file:
        reader = csv.reader(file)
        next(reader)

        for row in reader:
            # Append the first column value to the list
            d4j_subjects.append(row[0])
    return d4j_subjects


def analyze_code_files_at_project_level(proj_path, lang):
    code_files = get_all_code_files(proj_path, lang)
    src_test_mapping, src_file_paths, test_file_paths = get_code_test_file_mapping(code_files, lang)

    files_obj = {"src_test_exact_match": [], "src_test_fuzz_match": [], "src_without_tests": [], "test_unpaired": []}
    num_of_testable = 0
    cyc_complexity = []
    for f_path in src_file_paths:
        fname = get_filename_from_path(f_path)
        print(f_path)
        try:
            class_dec, methods_under_test = generate_cfg(code_file=f_path)
            for key in methods_under_test:
                if key == "to_be_determined":
                    continue
                num_of_testable += len(methods_under_test[key])
                for m, c in methods_under_test[key].items():
                    cyc_complexity.append(c[0])
            f_obj = {"src_name": fname, "src_path": f_path, "class_declaration": class_dec, "methods_under_test": methods_under_test}
        except Exception as error:
            f_obj = {"src_name": fname, "src_path": f_path, "error": str(error)}

        if f_path in src_test_mapping:
            test_path = src_test_mapping[f_path][0]
            matching_score = src_test_mapping[f_path][1]
            test_file_paths.remove(test_path)
            f_obj["test_path"] = test_path
            if matching_score > 100:
                files_obj["src_test_exact_match"].append(f_obj)
            else:
                files_obj["src_test_fuzz_match"].append(f_obj)
        else:
            files_obj["src_without_tests"].append(f_obj)
    for t_path in test_file_paths:
        t_name = get_filename_from_path(t_path)
        files_obj["test_unpaired"].append({t_name: t_path})

    return files_obj, cyc_complexity, num_of_testable


if __name__ == '__main__':
    language = sys.argv[1]
    defects4j_subjects = get_d4j_subjects()

    subjects_file = "subject_statistics.csv"
    header = ['ID', 'subject', "testable methods", "cyclomatic complexity"]
    create_csv_file(subjects_file, header)

    count = 0
    for p_name in defects4j_subjects[:1]:
        print(p_name)
        proj_dir = os.path.join("../defects4j-subjects-notests", p_name)
        files_object, cyc_complexity, num_of_testable = analyze_code_files_at_project_level(proj_dir, language)

        with open(os.path.join("defects4j-codefiles", f"{p_name}-codefiles.json"), 'w') as f:
            json.dump(files_object, f)

        count += 1

        min_val, q1, median, q3, max_val, count_1, count_2_10, count_11_20, count_20_more = calculate_statistics(cyc_complexity)
        # coverage = run_test_coverage(proj_dir)
        # lines = [int(coverage["Lines total"]), int(coverage["Lines covered"]), coverage["Line coverage"]]
        # conditions = [int(coverage["Conditions total"]), int(coverage["Conditions covered"]),
        #               coverage["Condition coverage"]]
        row = [count, p_name, [num_of_testable, count_1, count_2_10, count_11_20, count_20_more], [min_val, q1, median, q3, max_val]]
        append_to_csv_file(subjects_file, row)
