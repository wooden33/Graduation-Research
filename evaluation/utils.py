import os
import re
from thefuzz import fuzz, process
import glob


def get_all_code_files(project_directory, language):
    files = []
    if language == "java":
        files = glob.glob(os.path.join(project_directory, '**', '*.java'), recursive=True)
    if language == "python":
        files = glob.glob(os.path.join(project_directory, '**', '*.py'), recursive=True)
    return files


def separate_test_code_files(code_files):
    test_file_paths = set()
    code_file_paths = set()
    for filepath in code_files:
        filename = os.path.basename(filepath)  # get only the filename
        if 'test' in filename.lower():
            test_file_paths.add(filepath)
        else:
            code_file_paths.add(filepath)

    return test_file_paths, code_file_paths


def get_all_file_paths(project_path, pl):
    """ Get all file paths from the project"""
    all_file_paths = []
    pl_file_paths = None
    for (dirpath, _, filenames) in os.walk(project_path):
        all_file_paths += [os.path.join(dirpath, file) for file in filenames]
    if pl == 'python':
        pl_file_paths = [path for path in all_file_paths if path.endswith('.py')]
    elif pl == 'java':
        pl_file_paths = [path for path in all_file_paths if path.endswith('.java')]
    return pl_file_paths, all_file_paths


def heuristic_name_check_python(test_file_path, code_file_paths, test_file, code_file_names):
    candidates = []
    for i in range(len(code_file_names)):
        code_file = code_file_names[i]
        if test_file == code_file + "_test":
            candidates.append(code_file_paths[i])
        if test_file == "test_" + code_file:
            candidates.append(code_file_paths[i])

    # no heuristic, match, return None
    if len(candidates) == 0:
        return None, -1

    # want to pick code file path with closest match to test file path
    code_file, score = process.extractOne(test_file_path, candidates, scorer=fuzz.partial_ratio)
    return code_file, score


def get_code_test_file_mapping_python(files_changed):
    """Align python code and test files based on fuzzy string match."""
    files_changed = [filename for filename in files_changed if filename.endswith('.py')]
    test_file_paths, code_file_paths = separate_test_code_files(files_changed)

    if not code_file_paths or not test_file_paths:
        return {}, list(code_file_paths), list(test_file_paths)

    mapping = {}
    code_file_paths_list = list(code_file_paths)
    code_file_names = [get_filename_from_path(path) for path in code_file_paths_list]
    for test_file_path in test_file_paths:
        # extract filename from path and remove .py
        test_file = get_filename_from_path(test_file_path)
        # do exact heuristic (<CLASS>_test or test_<CLASS>)
        code_filepath, score = heuristic_name_check_python(test_file_path, code_file_paths_list, test_file,
                                                           code_file_names)
        if code_filepath is not None:
            # we always want heuristic to be prioritized above fuzzy match in one to many mapping
            if code_filepath not in mapping:
                mapping[code_filepath] = []
            mapping[code_filepath].append((test_file_path, 100 + score))
            continue
        # the fuzzy match returns non-deterministic results
        code_file, test_score = process.extractOne(test_file, code_file_names, scorer=fuzz.partial_ratio)
        if test_score > 85:
            # retrieve path from filename
            code_filepath, score = process.extractOne(code_file + '.py', code_file_paths, scorer=fuzz.partial_ratio)
            if code_filepath not in mapping:
                mapping[code_filepath] = []
            mapping[code_filepath].append((test_file_path, test_score))

    single_mapping = {}
    # select highest scoring test file in case one code file matches to multiple test files
    for key in mapping:
        single_mapping[key] = max(mapping[key], key=lambda item: item[1])

    return single_mapping, code_file_paths, test_file_paths


def heuristic_name_check_java(test_file_path, code_file_paths, test_file, code_file_names):
    candidates = []
    suffixes = ["TestCase", "Tests", "Test"]
    # loop through code files to get all candidate paths with Test<CLASS> or <CLASS>Test
    for i in range(len(code_file_names)):
        code_file = code_file_names[i]
        if any(test_file == code_file + suffix for suffix in suffixes) or test_file == "Test" + code_file:
            candidates.append(code_file_paths[i])

    # no heuristic, match, return None
    if len(candidates) == 0:
        return None, -1

    # want to pick code file path with closest match to test file path
    code_file, score = process.extractOne(test_file_path, candidates, scorer=fuzz.partial_ratio)
    return code_file, score


def get_code_test_file_mapping_java(files_changed):
    """Align java code and test files based on fuzzy string match."""
    files_changed = [filename for filename in files_changed if filename.endswith('.java')]
    test_file_paths, code_file_paths = separate_test_code_files(files_changed)
    if not code_file_paths or not test_file_paths:
        return {}, list(code_file_paths), list(test_file_paths)

    mapping = {}
    code_file_paths_list = list(code_file_paths)
    code_file_names = [get_filename_from_path(path) for path in code_file_paths_list]
    for test_file_path in test_file_paths:
        # extract filename from path and remove .java
        test_file = get_filename_from_path(test_file_path)
        # do exact heuristic (<CLASS>Test or Test<CLASS>)
        code_filepath, score = heuristic_name_check_java(test_file_path, code_file_paths_list, test_file,
                                                         code_file_names)
        if code_filepath is not None:
            # we always want heuristic to be prioritized above fuzzy match in one to many mapping
            if code_filepath not in mapping:
                mapping[code_filepath] = []
            mapping[code_filepath].append((test_file_path, 100 + score))
            continue
        # the fuzzy match returns non-deterministic results
        code_file, test_score = process.extractOne(test_file, code_file_names, scorer=fuzz.partial_ratio)
        if test_score > 85:
            # retrieve path from filename
            code_filepath, score = process.extractOne(code_file + '.java', code_file_paths, scorer=fuzz.partial_ratio)
            if code_filepath not in mapping:
                mapping[code_filepath] = []
            mapping[code_filepath].append((test_file_path, test_score))

    single_mapping = {}
    # select highest scoring test file in case one code file matches to multiple test files
    for key in mapping:
        single_mapping[key] = max(mapping[key], key=lambda item: item[1])

    return single_mapping, code_file_paths, test_file_paths


def get_code_test_file_mapping(files_changed, pl):
    if pl == 'python':
        mapping, code_file_paths, test_file_paths = get_code_test_file_mapping_python(files_changed)
    elif pl == 'java':
        mapping, code_file_paths, test_file_paths = get_code_test_file_mapping_java(files_changed)
    return mapping, code_file_paths, test_file_paths


def get_filename_from_path(f_path):
    _, fname = os.path.split(f_path)
    return fname.split('.')[0]


def remove_unpaired_files(all_files, paired_files):
    count_files_removed = 0
    for file in all_files:
        if file not in paired_files:
            count_files_removed += 1
            os.remove(file)
    return count_files_removed


def remove_non_pl_files(all_files, pl):
    count_files_removed = 0
    if pl == 'python':
        for file in all_files:
            if not file.endswith('.py'):
                count_files_removed += 1
                os.remove(file)

    elif pl == 'java':
        for file in all_files:
            if not file.endswith('.java'):
                count_files_removed += 1
                os.remove(file)

    return count_files_removed


def get_num_tokens(filename):
    num_tokens = -1
    with open(filename, errors='ignore') as f:
        file_content = f.read()
        num_tokens = len(re.split('\s+', file_content.strip()))
        if num_tokens < 10:
            print(f'filename: {filename}')
            print(f'file_content:s\n{file_content}')
    return num_tokens


