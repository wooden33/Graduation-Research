import json
import os
import re

from .command_executor import CommandExecutor
from .coverage.jacoco_coverage import JacocoCoverage
from .coverage.pycov_coverage import PycovCoverage
from .error_message_parser import extract_error_message, extract_compilation_error_message_java
from .file_preprocessor import FilePreprocessor
from .logger import cogpathLogger
from .model_invocation.llm_invocation import LLMInvocation, AzureOpenAIInvocation
from .prompt_builder import PromptBuilder
from .utils import get_code_language
from .yaml_parser_utils import load_yaml
from .cfg.src.comex.codeviews.combined_graph.combined_driver import line_number_to_node_id_mapping
from .cfg.src.comex.codeviews.CFG.CFG_driver import CFGDriver
from .utils import read_file
from .config_loader import get_settings
from .llm_constraint_solver import LLMConstraintSolver
from .llm_backward_slicer import LLMBackwardSlicer


def count_leading_spaces(text):
    match = re.match(r'^ +', text)
    if match:
        return len(match.group(0))
    return 0


def failed_test_to_string(failed_test: dict):
    failed_test_str = ""
    failed_test_dict = failed_test.get("code", {})
    error_message = failed_test.get("error_message", "")
    if failed_test_dict:
        failed_test_code = failed_test_dict.get("test_code", "").rstrip()
        failed_test_imports = (failed_test_dict.get("new_imports_code", "") or "").strip()
        failed_test_name = failed_test_dict.get("test_name", "").rstrip()
        failed_test_str += f"=========The failed test case is : {failed_test_name}=======\n"
        failed_test_str += f"{failed_test_code}\n"
        failed_test_str += f"additional imports: {failed_test_imports}\n"

        if error_message:
            failed_test_str += f"Failed with error message:\n{error_message}\n\n"
        else:
            failed_test_str += "\n\n"
    return failed_test_str


class UnitTestGenerator:
    def __init__(self, project_dir: str,
                 source_code_file: str,
                 test_code_file: str,
                 code_coverage_report_path: str,
                 test_execution_command: str,
                 llm_model: str,
                 solver_model: str,
                 test_code_command_dir: str = os.getcwd(),
                 test_dependencies: str = "",
                 included_files: list = None,
                 coverage_type="jacoco",
                 target_coverage: int = 100,
                 prompt_type: str = "baseline",
                 additional_instructions: str = "",
                 use_constraints: bool = False,
                 use_backward_slice: bool = False,
                 fix_type: str = None):

        self.relevant_line_number_to_insert_tests_after = None
        self.relevant_line_number_to_insert_imports_after = None
        self.relevant_line_number_to_insert_tests_before = None
        self.test_headers_indentation = None
        self.lines_missed = None
        self.branch_missed = None
        self.current_coverage = None
        self.code_coverage_report = None
        self.constraint_solver = None
        self.project_dir = project_dir
        self.source_code_file = source_code_file
        self.test_code_file = test_code_file
        self.code_coverage_report_path = code_coverage_report_path
        self.test_execution_command = test_execution_command
        self.test_code_command_dir = test_code_command_dir
        self.test_dependencies = test_dependencies
        self.included_files = self.get_included_files(included_files)
        self.coverage_type = coverage_type
        self.target_coverage = target_coverage
        self.additional_instructions = additional_instructions
        self.language = get_code_language(source_code_file)
        self.use_constraints = use_constraints
        self.use_backward_slice = use_backward_slice
        self.fix_type = fix_type

        self.llm_invoker = LLMInvocation(model=llm_model, component="test_generator")

        # Both optional analysers must exist as attributes regardless of the
        # configuration: `build_prompt` and `_init_prompt_builder` read them
        # unconditionally, so leaving `backward_slicer` unset made
        # `use_backward_slice=false` raise AttributeError on the first prompt
        # build -- which the run loop swallowed, producing a silent 0% run.
        # That combination is exactly the "w/o BS" ablation, so it has to work.
        self.constraint_solver = None
        self.backward_slicer = None

        if self.use_constraints:
            # `solver_model` may legitimately be empty ("use the main model"), and
            # config validation deliberately leaves it empty rather than resolving
            # it, because the result-directory label includes it only when set.
            self.constraint_solver = LLMConstraintSolver(
                LLMInvocation(model=solver_model or llm_model, component="constraint_solver")
            )

        if self.use_backward_slice:
            self.backward_slicer = LLMBackwardSlicer(
                llm_invoker=LLMInvocation(model=llm_model, component="backward_slicer")
            )

        self.logger = cogpathLogger.initialize_logger(__name__)
        self.logger.info(f"Using fix type: {self.fix_type}")
        
        # self.preprocessor = FilePreprocessor(self.test_code_file)
        self.failed_test_runs = []
        self.coverage_invalid_tests = []
        self.branch_miss_count = {}
        self.run_coverage()
        self.prompt_type = prompt_type
        self.path_history = {}
        # self.prompt = self.build_prompt(self.prompt_type)  # Commented out for now
        self.prompt = ""

    def run_coverage(self):
        """
        run the build/test command and get the baseline coverage
        """
        self.logger.info(f'generate baseline coverage report: "{self.test_execution_command}"')
        try:
            stdout, stderr, exit_code, time_of_test_execution_command, command_duration = (
                CommandExecutor.run_command(
                    command=self.test_execution_command, 
                    cwd=self.test_code_command_dir
                )
            )

            if exit_code != 0:
                raise RuntimeError(
                    f'Fatal: Error running test command. '
                    f'make sure this build command is correct: "{self.test_execution_command}"\n'
                    f'Exit code: {exit_code}'
                    f'\nStdout: {stdout}'
                    f'\nStderr: {stderr}'
                )

            # Instantiate Coverage and process the coverage report
            if self.coverage_type == "jacoco":
                coverage_processor = JacocoCoverage(
                    project_dir=self.project_dir,
                    file_path=self.code_coverage_report_path,
                    src_file_path=self.source_code_file)
            elif self.coverage_type == "pycov":
                coverage_processor = PycovCoverage(
                    file_path=self.code_coverage_report_path,
                    src_file_path=self.source_code_file)
            else:
                raise ValueError(f"Unsupported coverage type: {self.coverage_type}")

            # Use the process_coverage_report method of Coverage, 
            # passing in the time the test command was executed
            try:
                self.lines_missed, self.branch_missed, line_percentage, branch_percentage = (
                    coverage_processor.process_coverage_report(
                        time_of_test_execution_command=time_of_test_execution_command
                    )
                )

                # Process the extracted coverage metrics
                self.current_coverage = (line_percentage, branch_percentage)

                # Update branch miss count for tracking frequent missed branches
                if self.branch_missed:
                    for branch_line in self.branch_missed:
                        self.branch_miss_count[branch_line] = self.branch_miss_count.get(branch_line, 0) + 1
                    self.logger.debug(f"Branch miss count: {self.branch_miss_count}")

                self.code_coverage_report = (
                    f"Lines missed: {self.lines_missed}\n"
                    f"Branches missed: {self.branch_missed}\n"
                    f"Line coverage: {round(line_percentage * 100, 2)}%\n"
                    f"Branch coverage: {round(branch_percentage * 100, 2)}%"
                )
            except AssertionError as error:
                self.logger.error(f"Error in coverage processing: {error}")
                raise
            except (ValueError, NotImplementedError) as e:
                self.logger.warning(f"Error parsing coverage report: {e}")
                with open(self.code_coverage_report_path, "r") as f:
                    self.code_coverage_report = f.read()
        except Exception as e:
            self.logger.error(str(e))
            raise

    @staticmethod
    def get_included_files(included_files):
        """
        Process included files and return their content as a formatted string.
        
        Args:
            included_files: List of file paths to include, or None.
            
        Returns:
            str: Formatted string containing file contents, or empty string if no files.
        """
        if included_files:
            included_files_content = []
            file_names = []
            for file_path in included_files:
                try:
                    with open(file_path, "r") as file:
                        included_files_content.append(file.read())
                        file_names.append(file_path)
                except IOError as e:
                    print(f"Error reading file {file_path}: {str(e)}")

            out_str = ""
            if included_files_content:
                for i, content in enumerate(included_files_content):
                    out_str += f"file_path: `{file_names[i]}`\ncontent:\n```\n{content}\n```\n"

            return out_str.strip()
        return ""

    def build_prompt(self, prompt_type, pick_two_paths=True) -> dict:
        """
        Returns:
            str: prompt that will be used for generating new tests
        """

        failed_test_runs_value = ""
        try:
            # Check for existence of failed tests:
            for failed_test in self.failed_test_runs:
                failed_test_str = failed_test_to_string(failed_test)
                failed_test_runs_value += failed_test_str
        except Exception as e:
            self.logger.error(f"Error processing failed test runs: {e}")
        self.failed_test_runs = []

        no_coverage_increase_tests_value = ""

        self.prompt_builder = PromptBuilder(
            project_dir=self.project_dir,
            source_code_file=self.source_code_file,
            test_code_file=self.test_code_file,
            code_coverage_report=self.code_coverage_report,
            included_files=self.included_files,
            additional_instructions=self.additional_instructions,
            failed_test_runs=failed_test_runs_value,
            coverage_invalid_tests=no_coverage_increase_tests_value,
            language=self.language,
            lines_missed=self.lines_missed,
            branch_missed=self.branch_missed,
            path_history=self.path_history,
            test_dependencies=self.test_dependencies,
            constraint_solver=self.constraint_solver,
            backward_slicer=self.backward_slicer
        )
        
        # CFG guided test generation strategy
        if prompt_type == "control":
            prompt = self.prompt_builder.build_prompt_cfa_guided(pick_two_paths, use_constraints=self.use_constraints)
            self.path_history = self.prompt_builder.get_current_path_history()
            return prompt
        elif prompt_type == "coverage":
            return self.prompt_builder.build_prompt(coverage_enabled=True)
        else:
            return self.prompt_builder.build_prompt(coverage_enabled=False)


    def initial_test_suite_analysis(self):
        """
        Simple implementation for initial test suite analysis.
        We can move to an approach using AST or string parsing, instead of just using LLM for everything.
        Specifically, when we can use AST to extract the test headers indentation and the relevant line number to insert new tests.
        :return:
        """
        try:
            test_headers_indentation = None
            allowed_attempts = 3
            counter_attempts = 0
            while test_headers_indentation is None and counter_attempts < allowed_attempts:
                prompt_headers_indentation = (
                    self.prompt_builder.build_prompt_custom(
                        file="test_headers_indentation_prompt"
                    )
                )
                response, prompt_token_count, response_token_count = (
                    self.llm_invoker.call_model(prompt=prompt_headers_indentation)
                )
                tests_dict = load_yaml(response)
                test_headers_indentation = tests_dict.get(
                    "test_headers_indentation", None
                )
                counter_attempts += 1

            if test_headers_indentation is None:
                raise Exception("Failed to analyze the test headers indentation")

            relevant_line_number_to_insert_tests_after = None
            relevant_line_number_to_insert_imports_after = None
            allowed_attempts = 3
            counter_attempts = 0
            while not relevant_line_number_to_insert_tests_after and counter_attempts < allowed_attempts:
                prompt_test_insert_line = (
                    self.prompt_builder.build_prompt_custom(
                        file="analyze_suite_test_insert_line"
                    )
                )
                response, prompt_token_count, response_token_count = (
                    self.llm_invoker.call_model(prompt=prompt_test_insert_line)
                )
                tests_dict = load_yaml(response)
                relevant_line_number_to_insert_tests_after = tests_dict.get(
                    "relevant_line_number_to_insert_tests_after", None
                )
                relevant_line_number_to_insert_imports_after = tests_dict.get(
                    "relevant_line_number_to_insert_imports_after", None
                )
                counter_attempts += 1

            if not relevant_line_number_to_insert_tests_after:
                raise Exception(
                    "Failed to analyze the relevant line number to insert new tests"
                )

            self.test_headers_indentation = test_headers_indentation
            self.relevant_line_number_to_insert_tests_after = relevant_line_number_to_insert_tests_after
            self.relevant_line_number_to_insert_imports_after = relevant_line_number_to_insert_imports_after
        except Exception as e:
            self.logger.error(f"Error during initial test suite analysis: {e}")
            raise Exception("Error during initial test suite analysis")

    def initial_test_suite_analysis_AST(self):
        """
        Specifically, when we can use AST to extract the test headers indentation
        and the relevant line number to insert new tests.

        In the case, each test class has at least one existing test method.
        :return:
        """

        test_code = read_file(self.test_code_file)
        cfg_driver = CFGDriver(self.language, test_code, {"test_code": True})
        _, node_id_to_line_numbers_mapping = line_number_to_node_id_mapping(test_code, cfg_driver.CFG_nodes)
        last_import_id = cfg_driver.file_obj["imports"][-1]["id"]
        last_line_for_imports = node_id_to_line_numbers_mapping[last_import_id][-1]

        class_obj = cfg_driver.file_obj["class_objects"][0]
        class_declaration_id = class_obj["class_declaration"]["id"]
        class_declaration_start_line = node_id_to_line_numbers_mapping[class_declaration_id][0]

        last_method_declaration = class_obj["methods_under_test"][-1]
        last_method_start_id = last_method_declaration["method_declaration"]["id"]
        last_method_start_line = node_id_to_line_numbers_mapping[last_method_start_id][0]
        test_code_lines = test_code.split('\n')
        method_line_str = test_code_lines[last_method_start_line - 1]
        indents = count_leading_spaces(method_line_str)

        self.test_headers_indentation = indents
        self.relevant_line_number_to_insert_tests_before = last_method_start_line
        self.relevant_line_number_to_insert_imports_after = last_line_for_imports

    def generate_tests_by_slice(self, method_threshold: int = 3, max_tokens: int = 4096) -> list:
        """
        Analyze low-coverage methods using backward slicing and generate tests.

        This method identifies methods with low coverage and complexity above threshold,
        then uses backward slicing to determine what inputs/conditions are needed to
        reach the uncovered code, and generates targeted tests.

        Returns:
            list: List of method analysis results with backward slices and generated tests
        """
        self.logger.info(f"Analyzing methods by backward slicing (threshold={method_threshold})")

        # Check if backward slicing is properly enabled
        if not getattr(self, 'use_backward_slice', False):
            self.logger.warning("Backward slicing is not enabled")
            return []

        if not hasattr(self, 'backward_slicer') or self.backward_slicer is None:
            self.logger.warning("Backward slicer not initialized")
            return []

        if not hasattr(self, 'prompt_builder') or self.prompt_builder is None:
            self._init_prompt_builder()

        low_coverage_methods = self.prompt_builder.get_lowest_coverage_methods_sorted(
            cc_threshold=method_threshold,
            limit=5
        )

        if not low_coverage_methods:
            self.logger.info("No low coverage methods found")
            return []

        analyzed_results = []
        for method in low_coverage_methods:
            method_name, coverage, complexity, missed_lines, missed_branches, total_lines = method
            uncovered_segments = self.prompt_builder.get_longest_uncovered_segments(missed_lines)

            longest_segment = uncovered_segments[0] if uncovered_segments else None
            if longest_segment:
                start_line, end_line, length = longest_segment
                uncovered_code = self._extract_code_segment_for_slicing(start_line, end_line)
            else:
                uncovered_code = ""

            backward_slice = None
            generated_tests = []
            slice_tokens = 0
            self.logger.info(f"Processing method {method_name}: uncovered_code={bool(uncovered_code)}, backward_slicer={bool(self.backward_slicer)}")
            if uncovered_code and self.backward_slicer:
                try:
                    backward_slice = self.backward_slicer.slice(
                        uncovered_code=uncovered_code,
                        full_fm=self.prompt_builder.source_file
                    )
                    self.logger.info(f"Backward slice result for {method_name}: {backward_slice}")

                    # Generate tests using backward slice info
                    if backward_slice:
                        generated_tests, slice_tokens = self._generate_tests_from_slice(
                            backward_slice, max_tokens
                        )
                        self.logger.info(f"Generated {len(generated_tests)} tests for {method_name}")
                    else:
                        self.logger.warning(f"Backward slice returned empty for {method_name}")

                except Exception as e:
                    self.logger.error(f"Backward slice failed for {method_name}: {e}")

            analyzed_results.append({
                "method_name": method_name,
                "coverage": coverage,
                "complexity": complexity,
                "missed_lines": missed_lines,
                "missed_branches": missed_branches,
                "total_lines": total_lines,
                "longest_segment": longest_segment,
                "backward_slice": backward_slice,
                "generated_tests": generated_tests,
                # Reported so the caller can account for tokens spent on the
                # slice phase; they used to be dropped on the floor.
                "tokens": slice_tokens,
            })

        self.logger.info(f"Analyzed {len(analyzed_results)} methods, generated {sum(len(r.get('generated_tests', [])) for r in analyzed_results)} tests")
        return analyzed_results

    def _extract_tests_from_response(self, tests_response) -> list:
        """
        Extract tests from LLM response, handling both dict and list formats.

        The LLM sometimes returns a list directly instead of a dict with 'new_tests' key.
        """
        if isinstance(tests_response, list):
            return tests_response
        elif isinstance(tests_response, dict):
            return tests_response.get("new_tests", [])
        return []

    def _generate_tests_from_slice(self, backward_slice: dict, max_tokens: int = 4096) -> tuple:
        """
        Generate tests using backward slice information.

        Parameters:
            backward_slice: The backward slice result containing prerequisites and test hints
            max_tokens: Maximum tokens for LLM response

        Returns:
            tuple: ``(generated_tests, token_count)``.  The token count used to be
            discarded, which made the token totals wrong for every iteration that
            triggered the slicing phase.
        """
        from jinja2 import Environment, StrictUndefined

        # Build slice_info for template
        slice_info = []
        prerequisites = backward_slice.get("prerequisites", {})

        slice_info.append({
            "index": 1,
            "slice_code": backward_slice.get("backward_slice_code", []),
            "input_values": prerequisites.get("input_values", []),
            "object_states": prerequisites.get("object_states", []),
            "method_mocks": prerequisites.get("method_mocks", []),
            "control_flow_logic": prerequisites.get("control_flow_logic", ""),
            "test_hint": backward_slice.get("test_hint", "")
        })

        # Prepare variables for template
        variables = {
            "slice_info": slice_info,
            "processed_source_code": self.prompt_builder.processed_source_code if hasattr(self.prompt_builder, 'processed_source_code') else self.prompt_builder.source_file,
            "test_file_numbered": self.prompt_builder.test_file_numbered,
            "test_dependencies": self.test_dependencies,
            "language": self.language
        }

        try:
            # Render prompt using template
            environment = Environment(undefined=StrictUndefined)
            prompt_config = get_settings().backward_slice_test_generation_prompt

            system_prompt = environment.from_string(prompt_config.system).render()
            user_prompt = environment.from_string(prompt_config.user).render(variables)

            prompt = {"system": system_prompt, "user": user_prompt}

            # Call LLM to generate tests
            tests_dict, token_count = self.generate_test_by_prompt_llm(prompt, max_tokens)
            self.logger.info(f"Parsed tests_dict: {tests_dict}")

            # Handle different return formats
            tests = []
            if "new_tests" in tests_dict and tests_dict["new_tests"]:
                tests = tests_dict["new_tests"]
            elif "test_code" in tests_dict:
                # Backward slice template returns a single test object
                tests = [tests_dict]

            return tests, token_count

        except Exception as e:
            self.logger.error(f"Failed to generate tests from slice: {e}")
            return [], 0

    def _extract_code_segment_for_slicing(self, start_line: int, end_line: int) -> str:
        if not hasattr(self, 'prompt_builder'):
            return ""
        lines = self.prompt_builder.source_file.split("\n")
        start_idx = max(0, start_line - 1)
        end_idx = min(len(lines), end_line)
        if start_idx >= end_idx:
            return ""
        selected_lines = lines[start_idx:end_idx]
        return "\n".join([f"{start_idx + i + 1} {line}" for i, line in enumerate(selected_lines)])

    def _init_prompt_builder(self):
        from .prompt_builder import PromptBuilder
        self.prompt_builder = PromptBuilder(
            project_dir=self.project_dir,
            source_code_file=self.source_code_file,
            test_code_file=self.test_code_file,
            code_coverage_report=self.code_coverage_report,
            included_files=self.included_files,
            additional_instructions=self.additional_instructions,
            failed_test_runs="",
            coverage_invalid_tests="",
            language=self.language,
            lines_missed=self.lines_missed,
            branch_missed=self.branch_missed,
            path_history=self.path_history,
            test_dependencies=self.test_dependencies,
            constraint_solver=self.constraint_solver if self.use_constraints else None,
            backward_slicer=self.backward_slicer
        )

    def generate_tests(self, g_label, max_tokens=4096, pick_two_paths=True):
        self.prompt = self.build_prompt(self.prompt_type, pick_two_paths)
        # self.logger.info(f"{g_label}: {self.path_history}")
        tests_dict, token_count = self.generate_test_by_prompt_llm(self.prompt, max_tokens)

        # If we have constraints solving capability and tests aren't good enough,
        # we can enhance them further. However, in our current implementation,
        # the constraint solving is already integrated into the prompt.

        return tests_dict, token_count

    def generate_init_tests(self, prompt_type='baseline', max_tokens=4096):
        prompt = self.build_prompt(prompt_type)
        tests_dict, token_count = self.generate_test_by_prompt_llm(prompt, max_tokens)
        return tests_dict, token_count

    def generate_test_by_prompt_llm(self, prompt, max_tokens=4096):
        response, prompt_token_count, response_token_count = (
            self.llm_invoker.call_model(prompt=prompt,
                                        max_tokens=max_tokens))
        self.logger.info(f"Total token count for LLM {self.llm_invoker.model}: "
                         f"{prompt_token_count + response_token_count}")
        token_count = prompt_token_count + response_token_count

        # Check if the response is irrelevant to test generation
        irrelevant_keywords = ["Congress", "government", "policy", "politics"]
        for keyword in irrelevant_keywords:
            if keyword in response:
                self.logger.error(f"LLM returned irrelevant response containing: {keyword}")
                self.logger.error(f"Response: {response[:100]}...")  # Log first 100 chars
                return {"new_tests": []}, token_count

        try:
            tests_dict = load_yaml(response, keys_fix_yaml=["test_code",
                                                            "test_name",
                                                            "test_behavior"], )
            # Ensure tests_dict is a dictionary
            if tests_dict is None:
                return {"new_tests": []}, token_count
            if isinstance(tests_dict, list):
                # LLM returned a list directly instead of dict with 'new_tests' key
                return {"new_tests": tests_dict}, token_count
            if not isinstance(tests_dict, dict):
                return {"new_tests": []}, token_count
        except Exception as e:
            self.logger.error(f"Error during test generation: {e}")
            fail_details = {
                "status": "FAIL",
                "reason": f"Parsing error: {e}",
                "exit_code": None,  # No exit code as it's a parsing issue
                "stderr": str(e),
                "stdout": "",  # No output expected from a parsing error
                "test": response,  # Use the response that led to the error
            }
            # self.failed_test_runs.append(fail_details)
            tests_dict = {"new_tests": []}

        return tests_dict, token_count

    def validate_test(self, generated_test: dict):
        # Try to add the generated test to the relevant section in the original test file
        with open(self.test_code_file, "r") as test_file:
            original_content = test_file.read()  # Store original content
        try:
            processed_test, relevant_line_number_to_insert_imports_after, \
            relevant_line_number_to_insert_tests_before = self.add_new_test_to_test_file(generated_test, original_content)
            if processed_test:
                with open(self.test_code_file, "w") as test_file:
                    test_file.write(processed_test)
                self.logger.info(f"Test added to the test file: {self.test_code_file}")
                test_name = generated_test.get("test_name")

                self.logger.info(f'Run test with the command: "{self.test_execution_command}"')
                stdout, stderr, exit_code, time_of_command, command_duration = CommandExecutor.run_command(
                    command=self.test_execution_command, cwd=self.test_code_command_dir, timeout=60
                )

                # Now we need to check if we were able to run the test successfully or not
                if exit_code != 0:
                    # As the test failed, we go back to the test file with the original content
                    with open(self.test_code_file, "w") as test_file:
                        test_file.write(original_content)
                    if "COMPILATION ERROR" in stdout or "Compilation failed" in stdout:
                        self.logger.info(f"Test generated with compilation error.")
                        error_message = extract_compilation_error_message_java(stdout)
                        failure_details = {
                            "status": "FAIL",
                            "reason": "Compilation failure",
                            "exit_code": exit_code,
                            "stderr": stderr,
                            "stdout": error_message,
                            "test": generated_test,
                            "line_coverage": round(self.current_coverage[0] * 100, 2),
                            "branch_coverage": round(self.current_coverage[1] * 100, 2)
                        }
                        self.failed_test_runs.append({
                            "code": generated_test,
                            "error_message": error_message
                        })
                    elif "Timeout" in stdout:
                        self.logger.info(f"Test generated failed due to timeout.")
                        failure_details = {
                            "status": "FAIL",
                            "reason": "Timeout",
                            "exit_code": exit_code,
                            "stderr": stderr,
                            "stdout": "Timeout",
                            "test": generated_test,
                            "line_coverage": round(self.current_coverage[0] * 100, 2),
                            "branch_coverage": round(self.current_coverage[1] * 100, 2)
                        }
                        self.failed_test_runs.append({
                            "code": generated_test,
                            "error_message": "Timeout"
                        })
                    else:
                        self.logger.info(f"Test generated failed due to runtime error.")
                        error_message = extract_error_message(stdout, self.language)
                        failure_details = {
                            "status": "FAIL",
                            "reason": "Test failures",
                            "exit_code": exit_code,
                            "stderr": stderr,
                            "stdout": error_message,
                            "test": generated_test,
                            "line_coverage": round(self.current_coverage[0] * 100, 2),
                            "branch_coverage": round(self.current_coverage[1] * 100, 2)
                        }
                        self.failed_test_runs.append(
                            {
                                "code": generated_test,
                                "error_message": error_message
                            }
                        )

                    return failure_details

                self.logger.info(f"Generated test has passed: {test_name}")
                pass_details = {
                    "status": "PASS",
                    "reason": "",
                    "exit_code": exit_code,
                    "stderr": stderr,
                    "stdout": "",
                    "test": generated_test,
                    "line_coverage": round(self.current_coverage[0] * 100, 2),
                    "branch_coverage": round(self.current_coverage[1] * 100, 2)
                }

                self.relevant_line_number_to_insert_tests_before = relevant_line_number_to_insert_tests_before
                self.relevant_line_number_to_insert_imports_after = relevant_line_number_to_insert_imports_after
                return pass_details
        except Exception as e:
            self.logger.error(f"Error validating test: {e}")
            with open(self.test_code_file, "w") as test_file:
                test_file.write(original_content)
            return {
                "status": "FAIL",
                "reason": f"Error validating test: {e}",
                "exit_code": None,
                "stderr": str(e),
                "stdout": "",
                "test": generated_test,
                "line_coverage": round(self.current_coverage[0] * 100, 2),
                "branch_coverage": round(self.current_coverage[1] * 100, 2)
            }

    def add_new_test_to_test_file(self, generated_test: dict, original_content):
        processed_test = ""
        test_code = generated_test.get("test_code", "").rstrip()
        additional_imports = (generated_test.get("new_imports_code", "") or "").strip()
        if additional_imports and additional_imports[0] == '"' and additional_imports[-1] == '"':
            additional_imports = additional_imports.strip('"')

        # check if additional_imports only contains '"':
        if additional_imports and additional_imports == '""':
            additional_imports = ""

        relevant_line_number_to_insert_tests_before = self.relevant_line_number_to_insert_tests_before
        relevant_line_number_to_insert_imports_after = self.relevant_line_number_to_insert_imports_after

        needed_indent = self.test_headers_indentation

        # now we will remove the initial indent of test code, and insert the needed indent
        test_code_indented = test_code
        if needed_indent:
            initial_indent = len(test_code) - len(test_code.lstrip())
            delta_indent = int(needed_indent) - initial_indent
            if delta_indent > 0:
                test_code_indented = "\n".join(
                    [delta_indent * " " + line for line in test_code.split("\n")]
                )
        test_code_indented = "\n" + test_code_indented.strip("\n") + "\n"

        if test_code_indented and relevant_line_number_to_insert_tests_before:
            original_content_lines = original_content.split("\n")
            test_code_lines = test_code_indented.split("\n")
            processed_test_lines = (
                    original_content_lines[:relevant_line_number_to_insert_tests_before - 1]
                    + test_code_lines
                    + original_content_lines[relevant_line_number_to_insert_tests_before - 1:]
            )
            relevant_line_number_to_insert_tests_before += len(test_code_lines)

            # additional imports for line 'relevant_line_number_to_insert_imports_after
            processed_test = "\n".join(processed_test_lines)
            if relevant_line_number_to_insert_imports_after and additional_imports and additional_imports not in processed_test:
                additional_imports_lines = additional_imports.split("\n")
                processed_test_lines = (
                        processed_test_lines[:relevant_line_number_to_insert_imports_after]
                        + additional_imports_lines
                        + processed_test_lines[relevant_line_number_to_insert_imports_after:]
                )
                relevant_line_number_to_insert_imports_after += len(additional_imports_lines)
                relevant_line_number_to_insert_tests_before += len(additional_imports_lines)

            processed_test = "\n".join(processed_test_lines)
        return processed_test, relevant_line_number_to_insert_imports_after, relevant_line_number_to_insert_tests_before

    def build_prompt_for_fixing(self) -> dict:
        """
        Returns:
            str: prompt that will be used for fixing the failed test case
        """
        failed_test_runs_value = ""
        # Check for existence of failed tests:
        for failed_test in self.failed_test_runs:
            failed_test_str = failed_test_to_string(failed_test)
            failed_test_runs_value += failed_test_str

        prompt_builder = PromptBuilder(
            project_dir=self.project_dir,
            source_code_file=self.source_code_file,
            test_code_file=self.test_code_file,
            failed_test_runs=failed_test_runs_value,
            language=self.language
        )
        # reset failed tests
        self.failed_test_runs = []
        return prompt_builder.build_prompt_for_fixing(self.fix_type)

    def fix_failed_tests(self, f_label, iter_num, max_tokens=8192):
        # Check for existence of failed tests, fix until failed tests are empty or at most 5 iterations
        fix_results_list = []
        iter_count = 0
        token_count = 0

        # MCTS repair process
        if self.fix_type == 'MCTS':
            self.logger.info(f"Using MCTS repair strategy with {iter_num} iterations")
            while self.failed_test_runs and iter_count < iter_num:
                try:
                    fixing_prompt = self.build_prompt_for_fixing()
                    fixed_tests, tokens = self.generate_test_by_prompt_llm(fixing_prompt, max_tokens)
                    iter_count += 1
                    token_count += tokens
                    for fixed_test in self._extract_tests_from_response(fixed_tests):
                        test_result = self.validate_test(fixed_test)
                        test_result['label'] = f"{f_label}_{iter_count}"
                        fix_results_list.append(test_result)

                except Exception as e:
                    self.logger.error(f"Error in MCTS repair process: {e}")
                    # Fall back to traditional repair process
                    self.fix_type = 'traditional'

        # Traditional repair process
        if self.fix_type != 'MCTS' and self.failed_test_runs:
            while self.failed_test_runs and iter_count < iter_num:
                try:
                    fixing_prompt = self.build_prompt_for_fixing()
                    fixed_tests, tokens = self.generate_test_by_prompt_llm(fixing_prompt, max_tokens)
                    iter_count += 1
                    token_count += tokens
                    for fixed_test in self._extract_tests_from_response(fixed_tests):
                        test_result = self.validate_test(fixed_test)
                        test_result['label'] = f"{f_label}_{iter_count}"
                        fix_results_list.append(test_result)
                except Exception as e:
                    self.logger.error(f"Error processing failed test runs: {e}")

        return fix_results_list, token_count
