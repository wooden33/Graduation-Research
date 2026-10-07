import json
import subprocess
import csv
import os
import configparser
import sys
import threading
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from collections import defaultdict

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]

# Thread-safe progress tracking
progress_lock = Lock()
completed_count = 0
project_locks = defaultdict(Lock)


def extract_config_data(src_file_obj, project_name, model):
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
            'test_file_output_path': '',
            'code_coverage_report_path': code_coverage_report_path,
            'test_execution_command': test_execution_command,
            'test_code_command_dir': test_code_command_dir,
            'junit_version': junit_version,
            'model': model,
            'coverage_type': 'jacoco',
            'prompt_type': 'symprompt',
            'run_symprompt': 'true',
            'report_filepath': f"{src_file_obj['src_name']}_symprompt_test_results.html",
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


def read_html_file(file_name, file_path):
    with open(f"{file_path}/{file_name}", 'r', encoding='utf-8') as file:
        return file.read()


def parse_line_branch_coverage(class_name: str, prompt_type: str, file_path, model="llama3"):
    f"""
    parse ../result-files/{prompt_type}_{model}/{class_name}_{prompt_type}_test_results.html to identify line/branch coverage
    :param file_path: 
    :param class_name
    :param prompt_type
    :return:
    """
    try:
        html_file = f"{class_name}_{prompt_type}_test_results.html"
        html_content = read_html_file(html_file, file_path)
        soup = BeautifulSoup(html_content, 'html.parser')
        # Find the table in the HTML content
        table = soup.find('table')

        if not table:
            raise ValueError("No table found in the provided HTML file.")

        # Iterate over the rows of the table (skip the header row)
        rows = table.find_all('tr')[1:]  # Skip the header row
        last_row = rows[-1]
        columns = last_row.find_all('td')
        line_coverage = float(columns[4].text.strip())
        branch_coverage = float(columns[5].text.strip())
        return True
    except Exception as e:
        #print(e)
        return False


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


def fill_config_and_execute(src_f, proj_name, model):
    """Original sequential execution function"""
    config_data = extract_config_data(src_f, proj_name, model)
    fill_config(config_data, filename="../src/cogpath/config.ini")
    cmd = ["python", "-m", "cogpath.main"]
    process = subprocess.Popen(cmd, cwd="../", stdout=subprocess.PIPE, text=True)
    for line in process.stdout:
        print(line, end='')

    exit_code = process.wait()
    print("Exit Code:", exit_code)


def fill_config_and_execute_parallel(src_f, proj_name, model, total_samples):
    """Parallel execution function with thread-safe config handling"""
    global completed_count
    proj_lock = project_locks[proj_name]

    thread_id = threading.current_thread().ident
    temp_config_file = f"../src/cogpath/config_{thread_id}_{uuid.uuid4().hex[:8]}.ini"
    backup_done = False
    backup_path = None
    test_dir_created = None

    try:
        config_data = extract_config_data(src_f, proj_name, model)
        project_dir = config_data['default']['project_directory']
        test_code_file = config_data['default']['test_code_file']
        test_dir = os.path.dirname(test_code_file)

        # Serialize per project to safely adjust test directories
        with proj_lock:
            original_test_dir = os.path.join(project_dir, 'src', 'test', 'java')
            if os.path.exists(original_test_dir):
                backup_path = original_test_dir + "_backup"
                if not os.path.exists(backup_path):
                    try:
                        os.rename(original_test_dir, backup_path)
                        backup_done = True
                    except Exception:
                        backup_done = False
                        backup_path = None
            os.makedirs(test_dir, exist_ok=True)
            test_dir_created = test_dir

        fill_config(config_data, filename=temp_config_file)

        with proj_lock:
            cmd = ["python", "-m", "cogpath.main", "--config", os.path.basename(temp_config_file)]
            process = subprocess.Popen(cmd, cwd="../", stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = process.communicate()
            exit_code = process.returncode

        with progress_lock:
            completed_count += 1
            current_progress = completed_count

        status = "SUCCESS" if exit_code == 0 else "FAILED"
        print(f"[{current_progress}/{total_samples}] {src_f['src_name']} ({proj_name}) - {status}")

        if exit_code != 0:
            print(f"  Error output: {stderr}")

        return {
            'src_name': src_f['src_name'],
            'project': proj_name,
            'exit_code': exit_code,
            'stdout': stdout,
            'stderr': stderr
        }

    except Exception as e:
        with progress_lock:
            completed_count += 1
            current_progress = completed_count

        print(f"[{current_progress}/{total_samples}] {src_f['src_name']} ({proj_name}) - EXCEPTION: {str(e)}")
        return {
            'src_name': src_f['src_name'],
            'project': proj_name,
            'exit_code': -1,
            'error': str(e)
        }

    finally:
        if os.path.exists(temp_config_file):
            try:
                os.remove(temp_config_file)
            except:
                pass
        if backup_done and backup_path:
            with proj_lock:
                try:
                    if test_dir_created and os.path.exists(test_dir_created):
                        try:
                            original_test_dir = os.path.join(project_dir, 'src', 'test', 'java')
                            if test_dir_created.startswith(original_test_dir):
                                import shutil
                                shutil.rmtree(original_test_dir, ignore_errors=True)
                        except Exception:
                            pass
                    original_test_dir = os.path.join(project_dir, 'src', 'test', 'java')
                    if os.path.exists(backup_path):
                        os.rename(backup_path, original_test_dir)
                except Exception:
                    pass


if __name__ == '__main__':
    defects4j_subject_classes = get_d4j_subject_classes()
    prompt = sys.argv[1]
    model = sys.argv[2]

    # Check for parallel execution flag
    use_parallel = len(sys.argv) > 3 and sys.argv[3].lower() in ['--parallel', '-p', 'parallel']
    max_workers = 13

    if use_parallel and len(sys.argv) > 4:
        try:
            max_workers = int(sys.argv[4])
        except ValueError:
            print(f"Warning: Invalid worker count '{sys.argv[4]}', using default {max_workers}")

    result_path = os.path.join(ROOT, f"result-files/{prompt}_{model}")
    defects4j_subjects = ["JacksonXml-5f", "Csv-16f", "Collections-28f", "Gson-16f", "Cli-40f", "JacksonCore-26f",
                          "JxPath-22f", "Jsoup-93f", "Codec-18f", "Compress-47f", "JacksonDatabind-112f",
                          "Time-13f", "Lang-4f", "Math-2f"]

    total_samples = 0
    project_sample_counts = {}
    tasks = []

    print("=" * 60)
    execution_mode = "PARALLEL" if use_parallel else "SEQUENTIAL"
    print(f"Starting Evaluation - Prompt Type: {prompt}, Model: {model}, Mode: {execution_mode}")
    if use_parallel:
        print(f"Max Workers: {max_workers}")
    print("=" * 60)

    for p_name in defects4j_subjects:
        with open(os.path.join("defects4j-codefiles", f"{p_name}-codefiles.json"), 'r') as f:
            data = json.load(f)

        file_objects = data["src_test_exact_match"] + data["src_test_fuzz_match"] + data["src_without_tests"]
        class_subjects = defects4j_subject_classes[p_name]

        valid_samples = 0
        for src_file in file_objects:
            if src_file["src_name"] in class_subjects.keys():
                html_file = f"{result_path}/{src_file['src_name']}_{prompt}_test_results.html"

                if not os.path.exists(html_file):
                    tasks.append((src_file, p_name, model))
                    valid_samples += 1
                else:
                    valid_samples += 1

        project_sample_counts[p_name] = valid_samples
        total_samples += valid_samples

    pending_tasks = len(tasks)
    completed_tasks = total_samples - pending_tasks

    print(f"Total Test Samples: {total_samples}")
    print(f"Already Completed: {completed_tasks}")
    print(f"Pending Tasks: {pending_tasks}")
    print("\nSample Distribution by Project:")
    for p_name, count in project_sample_counts.items():
        print(f"  {p_name}: {count} samples")
    print("=" * 60)
    print()

    if pending_tasks == 0:
        print("All tasks already completed!")
        sys.exit(0)

    if use_parallel:
        print(f"Starting parallel execution with {max_workers} workers...")
        print("=" * 60)

        completed_count = 0

        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_task = {
                executor.submit(fill_config_and_execute_parallel, *task, total_samples): task
                for task in tasks
            }

            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as exc:
                    src_file, p_name = task[0], task[1]
                    print(f"Task {src_file['src_name']} ({p_name}) generated an exception: {exc}")
                    results.append({
                        'src_name': src_file['src_name'],
                        'project': p_name,
                        'exit_code': -1,
                        'error': str(exc)
                    })

        print("\n" + "=" * 60)
        print("PARALLEL EXECUTION SUMMARY")
        print("=" * 60)

        success_count = sum(1 for r in results if r.get('exit_code') == 0)
        failed_count = len(results) - success_count

        print(f"Total Tasks Executed: {len(results)}")
        print(f"Successful: {success_count}")
        print(f"Failed: {failed_count}")

        if failed_count > 0:
            print("\nFailed Tasks:")
            for result in results:
                if result.get('exit_code') != 0:
                    error_msg = result.get('error', result.get('stderr', 'Unknown error'))
                    print(f"  - {result['src_name']} ({result['project']}): {error_msg}")

    else:
        print("Starting sequential execution...")
        print("=" * 60)

        executed_count = 0
        for task in tasks:
            src_file, p_name, model = task
            executed_count += 1
            print(f"Executing [{executed_count}/{pending_tasks}] {src_file['src_name']}")
            fill_config_and_execute(src_file, p_name, model)

    print("\n" + "=" * 60)
    print(f"Evaluation Complete! Processed {pending_tasks} new samples")
    print("=" * 60)