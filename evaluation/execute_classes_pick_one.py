import json
import subprocess
import csv
import os
import configparser


def extract_config_data(src_file_obj, project_name, max_complexity):
    if project_name == "Gson-16f":
        project_dir = "../../defects4j-subjects-reduced/" + project_name + "/gson"
    else:
        project_dir = "../../defects4j-subjects-reduced/" + project_name
    src_path = src_file_obj["src_path"].replace("defects4j-subjects", "defects4j-subjects-reduced")
    test_path = src_file_obj["test_path"].replace("defects4j-subjects", "defects4j-subjects-reduced")
    test_file_name = test_path.split('/')[-1].split('.')[0]
    code_coverage_report_path = project_dir + "/target/jacoco/jacoco.csv"
    test_execution_command = f"mvn clean package -Dtest={test_file_name}"
    test_code_command_dir = project_dir

    if project_name == "JxPath-22f" or project_name == "Time-13f":
        junit_version = '3'
    else:
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
            'prompt_type': 'control',
            'pick_two_paths': 'false',
            'enable_fixing': '3'
        }
    }
    return config_data


def fill_config(config_data, filename="config.ini"):
    # Initialize the ConfigParser
    config = configparser.ConfigParser()

    # Load existing configuration if the file exists
    config.read(filename)

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


def get_d4j_subjects():
    d4j_subjects = []
    with open('d4j-fixed-version.csv', 'r') as file:
        reader = csv.reader(file)
        next(reader)

        for row in reader:
            # Append the first column value to the list
            d4j_subjects.append(row[0])
    return d4j_subjects


def fill_config_and_execute(src_f, proj_name, iter_num):
    config_data = extract_config_data(src_f, proj_name, iter_num)
    fill_config(config_data, filename="../cogpath/config.ini")
    cmd = ["python", "main.py"]  # Example: Python script execution
    process = subprocess.Popen(cmd, cwd="../src", stdout=subprocess.PIPE, text=True)
    for line in process.stdout:
        print(line, end='')

    exit_code = process.wait()
    print("Exit Code:", exit_code)


if __name__ == '__main__':
    # defects4j_subjects = get_d4j_subjects()
    #defects4j_subjects = ["JxPath-22f", "Csv-16f", "Gson-16f", "Collections-28f", "Jsoup-93f", "Codec-18f",
    #                      "Compress-47f", "JacksonDatabind-112f"]
    defects4j_subjects = ["Csv-16f", "Gson-16f", "Collections-28f"]
    for p_name in defects4j_subjects:
        print(p_name)
        with open(os.path.join("defects4j-codefiles", f"{p_name}-codefiles.json"), 'r') as f:
            data = json.load(f)
        count_1 = 0
        count_2 = 0
        for src_file in data["src_test_exact_match"]:
            if "methods_under_test" in src_file.keys():
                if src_file["methods_under_test"]["11-20"] and not src_file["methods_under_test"][">20"]:
                    count_1 += 1
                    max_cc = 0
                    for key, value in src_file["methods_under_test"]["11-20"].items():
                        if value[0] > max_cc:
                            max_cc = value[0]
                    print("max cc between 11~20",  src_file["src_path"], max_cc)
                    fill_config_and_execute(src_file, p_name, max_cc)
                if src_file["methods_under_test"][">20"]:
                    count_2 += 1
                    max_cc = 0
                    for key, value in src_file["methods_under_test"][">20"].items():
                        if value[0] > max_cc:
                            max_cc = value[0]
                    print("max cc larger than 20", src_file["src_path"], max_cc)
                    fill_config_and_execute(src_file, p_name, max_cc)
        # print("total", count_1, count_2, count_1 + count_2)
