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


def parse_data_tokens(class_name: str, prompt_type: str, file_path):
    f"""
    parse ..test_results.html to identify line/branch coverage
    :param file_path: 
    :param class_name
    :param prompt_type
    :return:
    """
    tokens = []
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

        if status == "INFO":
            token_count = int(columns[3].text.strip())
            tokens.append(token_count)

    return tokens


def any_larger_than(lst, n):
    return any(x > n for x in lst)


def count_larger_than(lst, n):
    return sum(1 for x in lst if x > n)

if __name__ == '__main__':
    subjects_file = "pass_rate_statistics.csv"
    header = ["project", 'class', "cogpath_basic", "cogpath_coverage", "cogpath", "symprompt"]
    create_csv_file(subjects_file, header)
    if __name__ == '__main__':
        defects4j_subjects = ["JacksonXml-5f", "Csv-16f", "Collections-28f", "Gson-16f", "Cli-40f", "JacksonCore-26f",
                              "JxPath-22f", "Jsoup-93f", "Codec-18f", "Compress-47f", "JacksonDatabind-112f",
                              "Time-13f", "Lang-4f", "Math-2f"]
        defects4j_subject_classes = get_d4j_subject_classes()
        for p_name in defects4j_subjects:
            class_subjects = defects4j_subject_classes[p_name]

            for class_name in class_subjects.keys():
                token_list = parse_data_tokens(class_name, "control", f"../../result-files/control_llama3-3")
                num = count_larger_than(token_list, 64000)
                if num:
                    print(p_name, class_name, num)