import json
import subprocess
import csv
import os
import configparser
import sys
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
print(ROOT)

def extract_config_data(src_file_obj, project_name, max_complexity, prompt_type, model):
    if project_name == "Gson-16f":
        project_dir = "defects4j-subjects-notests/" + project_name + "/gson"
    else:
        project_dir = "defects4j-subjects-notests/" + project_name

    src_path = src_file_obj["src_path"].replace("defects4j-subjects", "defects4j-subjects-notests")
    src_path = src_path.lstrip("../")
    # test_path = src_file_obj["test_path"].replace("defects4j-subjects", "defects4j-subjects-notests")
    file_name = os.path.basename(src_path)
    dir_name = os.path.dirname(src_path)
    if project_name == "JxPath-22f":
        test_dir = dir_name.replace("src/java", "src/test")
    else:
        test_dir = dir_name.replace("src/main/java", "src/test/java")

    test_name = file_name.replace(f"{src_file_obj['src_name']}.java", f"{src_file_obj['src_name']}Test.java")
    test_path = os.path.join(test_dir, test_name)

    if os.path.exists(test_path):
        os.remove(test_path)
    test_file_name = os.path.splitext(test_name)[0]
    code_coverage_report_path = project_dir + "/target/jacoco/jacoco.csv"
    test_execution_command = f"mvn clean package -Dtest={test_file_name}"
    test_code_command_dir = project_dir
    junit_version = '4'

    config_data = {
        'default': {
            'project_directory': project_dir,
            'source_code_file': src_path,
            'test_code_file': test_path,
            'code_coverage_report_path': code_coverage_report_path,
            'test_execution_command': test_execution_command,
            'test_code_command_dir': test_code_command_dir,
            'maximum_iterations': str(max_complexity),
            'no_coverage_increase_iterations': '3',
            'junit_version': junit_version,
            'prompt_type': prompt_type,
            'model': model,
            'enable_fixing': '3',
            # These were previously omitted, so they silently inherited whatever
            # the previous run had left in config.ini. This driver can no longer
            # produce ablations; use experiment.py with a study manifest for that.
            'use_constraints': 'true',
            'use_backward_slice': 'true',
            'fix_type': '',
            'pick_two_paths': 'true',
            'additional_instructions': ''
        }
    }
    return config_data


def fill_config(config_data, filename="config.ini"):
    """Write a config file from scratch (see execute_cogpath.fill_config)."""
    config = configparser.ConfigParser()

    # Update config with provided data
    for section, settings in config_data.items():
        if not config.has_section(section):
            config.add_section(section)
        for key, value in settings.items():
            config.set(section, key, value)

    # Write the config to the file
    with open(filename, 'w') as configfile:
        config.write(configfile)
    print(f"Configuration written to {filename}")


def get_d4j_subject_classes():
    d4j_subjects = {}
    with open('data/class_list.csv', 'r') as file:
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


def fill_config_and_execute(src_f, proj_name, iter_num, prompt_type, model):
    config_data = extract_config_data(src_f, proj_name, iter_num, prompt_type, model)
    fill_config(config_data, filename="../src/cogpath/config.ini")
    cmd = ["python", "-m", "cogpath.main"]  # Example: Python script execution
    process = subprocess.Popen(cmd, cwd="../", stdout=subprocess.PIPE, text=True)
    for line in process.stdout:
        print(line, end='')

    exit_code = process.wait()
    print("Exit Code:", exit_code)


if __name__ == '__main__':
    defects4j_subject_classes = get_d4j_subject_classes()
    prompt = sys.argv[1]
    model = sys.argv[2]
    result_path = os.path.join(ROOT, f"result-files/{prompt}_{model}")
    defects4j_subjects = ["JacksonXml-5f", "Csv-16f", "Collections-28f", "Gson-16f", "Cli-40f", "JacksonCore-26f",
                          "JxPath-22f", "Jsoup-93f", "Codec-18f", "Compress-47f", "JacksonDatabind-112f",
                          "Time-13f", "Lang-4f", "Math-2f"]
    for p_name in defects4j_subjects:
        #print(p_name)
        with open(os.path.join("defects4j-codefiles", f"{p_name}-codefiles.json"), 'r') as f:
            data = json.load(f)

        file_objects = data["src_test_exact_match"] + data["src_test_fuzz_match"] + data["src_without_tests"]
        class_subjects = defects4j_subject_classes[p_name]
        for src_file in file_objects:
            html_file = f"{result_path}/{src_file['src_name']}_{prompt}_test_results.html"
            if src_file["src_name"] in class_subjects.keys():
                max_cc = class_subjects[src_file["src_name"]]
                if not os.path.exists(html_file):
                    print("execute", src_file["src_name"], max_cc)
                    fill_config_and_execute(src_file, p_name, max_cc, prompt, model)

