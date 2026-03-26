import os
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import csv
import re
import json

def read_html_file(file_name, file_path):
    with open(f"{file_path}/{file_name}", 'r', encoding='utf-8') as file:
        return file.read()


def append_to_csv_file(filename, row):
    with open(filename, mode='a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(row)


def create_csv_file(filename, header):
    with open(filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(header)


def get_d4j_subject_classes():
    d4j_subjects = {}
    with open('class_list.csv', 'r') as file:
        reader = csv.reader(file)
        next(reader)

        for row in reader:
            # Append the first column value to the list
            project_name = row[0]
            class_name = row[1]
            max_cc = row[2]
            if d4j_subjects.get(project_name):
                d4j_subjects.get(project_name)[class_name] = max_cc
            else:
                d4j_subjects[project_name] = {class_name: max_cc}
    return d4j_subjects


def parse_data(class_name: str, prompt_type: str, file_path):
    f"""
    parse ..test_results.html to identify line/branch coverage
    :param file_path: 
    :param class_name
    :param prompt_type
    :return:
    """
    coverage = []
    html_file = f"{class_name}_{prompt_type}_test_results.html"
    html_content = read_html_file(html_file, file_path)
    soup = BeautifulSoup(html_content, 'html.parser')
    # Find the table in the HTML content
    table = soup.find('table')

    if not table:
        raise ValueError("No table found in the provided HTML file.")

    # Iterate over the rows of the table (skip the header row)
    rows = table.find_all('tr')[1:]  # Skip the header row
    row_id = 0
    for row in rows:
        columns = row.find_all('td')
        row_id += 1
        if len(columns) < 6:
            continue  # Skip rows that do not have enough columns

        # Extract details
        status = columns[0].text.strip()
        label = columns[1].text.strip()
        reason = columns[2].text.strip()
        line_coverage = float(columns[4].text.strip())
        branch_coverage = float(columns[5].text.strip())

        if status == "INFO":
            continue

        # Store coverage data in the dictionary
        coverage.append({
            "label": label,
            "status": status,
            "reason": reason,
            "line_coverage": line_coverage,
            "branch_coverage": branch_coverage
        })
    return coverage


def extract_gen_iter_number(label):
    match = re.search(r'_(\d+)', label)
    return match.group(1) if match else None

def extract_repair_iter_number(label):
    matches = re.findall(r'_(\d+)', label)
    return matches[1] if len(matches) > 1 else None

def extract_path_rate(data_list):
    count_dict = {}
    pass_dict = {}
    for item in data_list:
        label = item["label"]
        status = item["status"]
        count_dict[label] = count_dict.get(label, 0) + 1
        if status == "PASS":
            pass_dict[label] = pass_dict.get(label, 0) + 1
    return count_dict, pass_dict


def calculate_pass_rate_symprompt(clz_name, prompt_type, path):
    try:
        data_list = parse_data(clz_name, prompt_type, path)
        total = 0
        passed = 0
        for item in data_list:
            status = item["status"]
            total += 1
            if status == "PASS":
                passed += 1
        return passed/total
    except Exception as e:
        return None


def calculate_pass_rate(class_name, prompt_type, path):
    try:
        data_list = parse_data(class_name, prompt_type, path)

        if data_list[0]['line_coverage'] == data_list[-1]['line_coverage'] and data_list[0]['branch_coverage'] == \
                data_list[-1]['branch_coverage']:
            return 0

        count_num, pass_count = extract_path_rate(data_list)
        iter_count = {}
        iter_pass_count = {}
        for label, num in count_num.items():
            if label.startswith('g'):
                gen_iter = extract_gen_iter_number(label)
                iter_count[gen_iter] = {'0': num}
                pass_num = pass_count.get(label, 0)
                iter_pass_count[gen_iter] = {'0': pass_num}
                #print(f"total generation test for {gen_iter} is {num}, {pass_num} of them are passed")
            if label.startswith('f'):
                gen_iter = extract_gen_iter_number(label)
                repair_iter = extract_repair_iter_number(label)
                pass_num_f = pass_count.get(label, 0)
                iter_count[gen_iter][repair_iter] = num
                iter_pass_count[gen_iter][repair_iter] = pass_num_f
        # print(iter_count)
        # print(iter_pass_count)
        statistics = []
        total_tests = 0
        passed_tests = 0
        for iter_num, data in iter_count.items():
            total_generated_tests = data['0']
            pass_iter = iter_pass_count[iter_num]
            pass_num = 0
            for key, value in pass_iter.items():
                pass_num += value
            total_tests += total_generated_tests
            passed_tests += pass_num
            statistics.append((iter_num, total_generated_tests, pass_num))

        pass_rate = passed_tests / total_tests
        return pass_rate

    except Exception as e:
        return None


def calculate_baseline_pass_rate(class_name, prompt_type, path):
    try:
        data_list = parse_data(class_name, prompt_type, path)

        if data_list[0]['line_coverage'] == data_list[-1]['line_coverage'] and data_list[0]['branch_coverage'] == \
                data_list[-1]['branch_coverage']:
            return 0

        count_num, pass_count = extract_path_rate(data_list)
        pass_num = pass_count.get("g_0", 0)
        total_num = count_num.get("g_0")
        pass_rate = pass_num/total_num
        return pass_rate

    except Exception as e:
        return None

if __name__ == '__main__':
    subjects_file = "pass_rate_statistics.csv"
    header = ["project", 'class', "baseline", "cogpath_basic", "cogpath_coverage", "cogpath", "symprompt", "cogpath-gpt",
              "cogpath-claude", "cogpath-mistral"]
    create_csv_file(subjects_file, header)
    if __name__ == '__main__':
        defects4j_subjects = ["JacksonXml-5f", "Csv-16f", "Collections-28f", "Gson-16f", "Cli-40f", "JacksonCore-26f",
                              "JxPath-22f", "Jsoup-93f", "Codec-18f", "Compress-47f", "JacksonDatabind-112f",
                              "Time-13f", "Lang-4f", "Math-2f"]
        defects4j_subject_classes = get_d4j_subject_classes()
        for p_name in defects4j_subjects:
            print(p_name)
            class_subjects = defects4j_subject_classes[p_name]

            for class_name in class_subjects.keys():
                pass_rate_baseline = calculate_baseline_pass_rate(class_name, "baseline", f"../../result-files/baseline_llama3-3")
                pass_rate_basic = calculate_pass_rate(class_name, "baseline", f"../../result-files/baseline_llama3-3")
                pass_rate_coverage = calculate_pass_rate(class_name, "coverage", f"../../result-files/coverage_llama3-3")
                pass_rate_cogpath = calculate_pass_rate(class_name, "control", f"../../result-files/control_llama3-3")
                pass_rate_cogpath_gpt = calculate_pass_rate(class_name, "control", f"../../result-files/control_gpt-4o-mini")
                pass_rate_symprompt = calculate_pass_rate_symprompt(class_name, "symprompt", f"../../result-files/symprompt_llama3-3")
                pass_rate_cogpath_claude = calculate_pass_rate(class_name, "control",
                                                          f"../../result-files/control_claude3-5")
                pass_rate_cogpath_mistral = calculate_pass_rate(class_name, "control",
                                                             f"../../result-files/control_mistral-large")
                row = [p_name, class_name, pass_rate_baseline, pass_rate_basic, pass_rate_coverage, pass_rate_cogpath,
                       pass_rate_symprompt, pass_rate_cogpath_gpt, pass_rate_cogpath_claude, pass_rate_cogpath_mistral]
                append_to_csv_file(subjects_file, row)

# if __name__ == '__main__':
#     path = f"../../result-files/control_gpt-4o-mini"
#     dir_list = os.listdir(path)
#     effective_repair_round = [0, 0, 0, 0, 0, 0]
#     total_repair_round = [0, 0, 0, 0, 0, 0]
#     for file in dir_list:
#         class_name = file.split("_")[0]
#         prompt_type = "control"
#         data_list = parse_data(class_name, prompt_type, path)
#         if data_list[0]['line_coverage'] == data_list[-1]['line_coverage'] and data_list[0]['branch_coverage'] == data_list[-1]['branch_coverage']:
#             continue
#
#         count_num, pass_count = extract_path_rate(data_list)
#         iter_count = {}
#         iter_pass_count = {}
#         for label, num in count_num.items():
#             if label.startswith('g'):
#                 gen_iter = extract_gen_iter_number(label)
#                 iter_count[gen_iter] = {'0': num}
#                 pass_num = pass_count.get(label, 0)
#                 iter_pass_count[gen_iter] = {'0': pass_num}
#                 print(f"total generation test for {gen_iter} is {num}, {pass_num} of them are passed")
#             if label.startswith('f'):
#                 gen_iter = extract_gen_iter_number(label)
#                 repair_iter = extract_repair_iter_number(label)
#                 pass_num_f = pass_count.get(label, 0)
#                 iter_count[gen_iter][repair_iter] = num
#                 iter_pass_count[gen_iter][repair_iter] = pass_num_f
#         # print(iter_count)
#         # print(iter_pass_count)
#         statistics = []
#         total_tests = 0
#         passed_tests = 0
#         for iter_num, data in iter_count.items():
#             total_generated_tests = data['0']
#             pass_iter = iter_pass_count[iter_num]
#             pass_num = 0
#             for key, value in pass_iter.items():
#                 pass_num += value
#             # failed_test_before = data.get(str(1), 0)
#             # failed_test_after = data.get(str(1), 0)
#             # effective_repair = 0
#             # total_repair_round[len(data) - 1] += 1
#             # for i in range(1, 6):
#             #     if data.get(str(i)) is None:
#             #         failed_test_after = 0
#             #         effective_repair = i-1
#             #         break
#             #     else:
#             #         if data.get(str(i)) < failed_test_after:
#             #             effective_repair = i
#             #         failed_test_after = data.get(str(i))
#             # effective_repair_round[effective_repair] += 1
#             total_tests += total_generated_tests
#             passed_tests += pass_num
#             statistics.append((iter_num, total_generated_tests, pass_num))
#
#         pass_rate = passed_tests/total_tests
#         print(class_name, pass_rate)
#     #print(effective_repair_round, total_repair_round)