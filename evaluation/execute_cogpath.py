import json
import subprocess
import csv
import os
import configparser
import sys
import threading
import tempfile
import uuid
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from collections import defaultdict

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
print(ROOT)

# Thread-safe progress tracking
progress_lock = Lock()
completed_count = 0
project_locks = defaultdict(Lock)

def extract_config_data(src_file_obj, project_name, max_complexity, prompt_type, model, solver_model):
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
    # Avoid using `clean` to prevent concurrent deletion conflicts; run tests directly
    test_execution_command = (
        f"mvn clean package -Dtest={test_file_name}"
    )
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
            'test_dependency_command': 'mvn dependency:list -DexcludeTransitive=true | grep ":test"',
            'test_code_command_dir': test_code_command_dir,
            'included_files': '',
            'junit_version': junit_version,
            'model': model,
            # 'solver_model': solver_model,
            'coverage_type': 'jacoco',
            'report_filepath': f"{src_file_obj['src_name']}_{prompt_type}_test_results.html",
            'target_coverage': '100',
            'maximum_iterations': str(max_complexity),
            'no_coverage_increase_iterations': '3',
            'enable_fixing': '3',
            'run_symprompt': 'false',
            'prompt_type': prompt_type,
            'use_backward_slice': 'true',
            'use_constraints': 'true',
            # Every ablation factor must be stated explicitly. `fix_type` used to be
            # commented out here, so it silently inherited whatever value the
            # previous run had left in config.ini.
            'fix_type': '',
            'pick_two_paths': 'true',
            'additional_instructions': ''
        }
    }
    return config_data


def fill_config(config_data, filename="config.ini"):
    """Write a config file from scratch.

    NOTE: this deliberately uses a *fresh* ConfigParser instead of reading and
    merging into the existing file.  Merging left every key the caller did not set
    at whatever value a previous run had written, which is how an ablation run
    could execute a different configuration than its directory name implied.

    New experiments should use ``experiment.py`` (manifest-driven) rather than this
    legacy driver.
    """
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


def fill_config_and_execute(src_f, proj_name, iter_num, prompt_type, model, solver_model):
    """Original sequential execution function"""
    config_data = extract_config_data(src_f, proj_name, iter_num, prompt_type, model, solver_model)
    fill_config(config_data, filename="../src/cogpath/config.ini")
    cmd = ["python", "-m", "cogpath.main"]  # Example: Python script execution
    process = subprocess.Popen(cmd, cwd="../", stdout=subprocess.PIPE, text=True)
    for line in process.stdout:
        print(line, end='')

    exit_code = process.wait()
    print("Exit Code:", exit_code)


def fill_config_and_execute_parallel(src_f, proj_name, iter_num, prompt_type, model, solver_model, total_samples):
    """Parallel execution function with thread-safe config handling"""
    global completed_count
    # Per-project serialization to avoid test directory conflicts
    proj_lock = project_locks[proj_name]

    # Create a unique temporary config file for this thread
    thread_id = threading.current_thread().ident
    temp_config_file = f"../src/cogpath/config_{thread_id}_{uuid.uuid4().hex[:8]}.ini"
    backup_done = False
    backup_path = None
    test_dir_created = None

    try:
        # Extract and fill config data
        config_data = extract_config_data(src_f, proj_name, iter_num, prompt_type, model, solver_model)
        project_dir = config_data['default']['project_directory']
        test_code_file = config_data['default']['test_code_file']
        test_dir = os.path.dirname(test_code_file)

        # Serialize per project to safely adjust test directories
        with proj_lock:
            # Backup existing test sources to avoid Maven compiling unrelated tests
            original_test_dir = os.path.join(project_dir, 'src', 'test', 'java')
            if os.path.exists(original_test_dir):
                backup_path = original_test_dir + "_backup"
                if not os.path.exists(backup_path):
                    try:
                        os.rename(original_test_dir, backup_path)
                        backup_done = True
                    except Exception:
                        # If rename fails, proceed without backup
                        backup_done = False
                        backup_path = None
            # Ensure our test directory exists (clean)
            os.makedirs(test_dir, exist_ok=True)
            test_dir_created = test_dir

        # Write config after directory is prepared
        fill_config(config_data, filename=temp_config_file)

        # Execute with the temporary config file under project-level lock to serialize Maven operations
        with proj_lock:
            cmd = ["python", "-m", "cogpath.main", "--config", os.path.basename(temp_config_file)]
            process = subprocess.Popen(cmd, cwd="../", stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            # Capture output
            stdout, stderr = process.communicate()
            exit_code = process.returncode
        
        # Thread-safe progress update
        with progress_lock:
            completed_count += 1
            current_progress = completed_count
            
        # Print progress and results
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
        # Clean up temporary config file
        if os.path.exists(temp_config_file):
            try:
                os.remove(temp_config_file)
            except:
                pass  # Ignore cleanup errors
        # Restore original test directory if we backed it up
        if backup_done and backup_path:
            with proj_lock:
                try:
                    # Remove any test directories we created (may contain generated tests)
                    if test_dir_created and os.path.exists(test_dir_created):
                        try:
                            # Only remove if it's under src/test/java
                            original_test_dir = os.path.join(project_dir, 'src', 'test', 'java')
                            if test_dir_created.startswith(original_test_dir):
                                # Remove created test dir tree
                                import shutil
                                shutil.rmtree(original_test_dir, ignore_errors=True)
                        except Exception:
                            pass
                    # Restore backup
                    original_test_dir = os.path.join(project_dir, 'src', 'test', 'java')
                    if os.path.exists(backup_path):
                        os.rename(backup_path, original_test_dir)
                except Exception:
                    pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Execute cogpath evaluation')
    parser.add_argument('prompt', type=str, help='Prompt type')
    parser.add_argument('model', type=str, help='Main model name')
    parser.add_argument('--solver-model', type=str, default=None,
                        help='Solver model name (optional)')
    parser.add_argument('--parallel', '-p', action='store_true',
                        help='Enable parallel execution')
    parser.add_argument('--workers', '-w', type=int, default=4,
                        help='Number of parallel workers (default: 4)')

    args = parser.parse_args()

    prompt = args.prompt
    model = args.model
    solver_model = args.solver_model
    use_parallel = args.parallel
    max_workers = args.workers

    defects4j_subject_classes = get_d4j_subject_classes()

    # Build result path - include solver_model if specified
    result_path = os.path.join(ROOT, f"result-files/{prompt}_{model}_constraints_bs")
    # result_path = os.path.join(ROOT, f"result-files/{prompt}_{model}_mcts")
    if solver_model:
        result_path += f"_{solver_model}"
        
    defects4j_subjects = ["JacksonXml-5f", "Csv-16f", "Collections-28f", "Gson-16f", "Cli-40f", "JacksonCore-26f",
                          "JxPath-22f", "Jsoup-93f", "Codec-18f", "Compress-47f", "JacksonDatabind-112f",
                          "Time-13f", "Lang-4f", "Math-2f"]
    
    # Count all test samples and prepare task list
    total_samples = 0
    project_sample_counts = {}
    tasks = []  # For parallel execution
    
    print("=" * 60)
    execution_mode = "PARALLEL" if use_parallel else "SEQUENTIAL"
    solver_info = f", Solver Model: {solver_model}" if solver_model else ""
    print(f"Starting Evaluation - Prompt Type: {prompt}, Model: {model}{solver_info}, Mode: {execution_mode}")
    if use_parallel:
        print(f"Max Workers: {max_workers}")
    print("=" * 60)
    
    # First, count all samples and prepare tasks
    for p_name in defects4j_subjects:
        with open(os.path.join("defects4j-codefiles", f"{p_name}-codefiles.json"), 'r') as f:
            data = json.load(f)
        
        file_objects = data["src_test_exact_match"] + data["src_test_fuzz_match"] + data["src_without_tests"]
        class_subjects = defects4j_subject_classes[p_name]
        
        # Count valid samples and prepare tasks for this project
        valid_samples = 0
        for src_file in file_objects:
            if src_file["src_name"] in class_subjects.keys():
                html_file = f"{result_path}/{src_file['src_name']}_{prompt}_test_results.html"
                max_cc = class_subjects[src_file["src_name"]]
                
                # Only add to tasks if not already completed
                if not os.path.exists(html_file):
                    tasks.append((src_file, p_name, max_cc, prompt, model, solver_model))
                    valid_samples += 1
                else:
                    # Still count completed ones for statistics
                    valid_samples += 1
        
        project_sample_counts[p_name] = valid_samples
        total_samples += valid_samples
    
    # Display statistics
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
    
    # Group tasks by project for better scheduling
    project_tasks = defaultdict(list)
    for task in tasks:
        src_file, p_name = task[0], task[1]
        project_tasks[p_name].append(task)

    # Interleave tasks from different projects for better parallelism
    # This ensures tasks from different projects run together
    interleaved_tasks = []
    max_project_tasks = max(len(t) for t in project_tasks.values()) if project_tasks else 0

    for i in range(max_project_tasks):
        for p_name in project_tasks.keys():
            if i < len(project_tasks[p_name]):
                interleaved_tasks.append(project_tasks[p_name][i])

    # Execute tasks
    if use_parallel:
        print(f"Starting parallel execution with {max_workers} workers...")
        print(f"Using interleaved scheduling: {len(interleaved_tasks)} tasks from {len(project_tasks)} projects")
        print("=" * 60)

        # Reset global counter for parallel execution
        completed_count = 0

        # Execute tasks in parallel with interleaved scheduling
        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit interleaved tasks to maximize parallelism
            future_to_task = {
                executor.submit(fill_config_and_execute_parallel, *task, total_samples): task
                for task in interleaved_tasks
            }

            # Process completed tasks
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
        
        # Summary of parallel execution
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

        # Sequential execution (original logic)
        executed_count = 0
        for task in tasks:
            src_file, p_name, max_cc, prompt, model, solver_model = task
            executed_count += 1
            print(f"Executing [{executed_count}/{pending_tasks}] {src_file['src_name']} (Complexity: {max_cc})")
            fill_config_and_execute(src_file, p_name, max_cc, prompt, model, solver_model)
    
    print("\n" + "=" * 60)
    print(f"Evaluation Complete! Processed {pending_tasks} new samples")
    print("=" * 60)

