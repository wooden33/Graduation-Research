import os
import shutil
import time
import json

from .logger import cogpathLogger
from .model_invocation.models import validate_and_map_model
from .command_executor import CommandExecutor
from .report_generator import ReportGenerator
from .unit_test_generator import UnitTestGenerator
from .symprompt import SymPrompt
from .hits import HITS
from .templates import TEST_CLASS_JUNIT_3, TEST_CLASS_JUNIT_4, TEST_CLASS_JUNIT_5
from .cfg.src.comex.codeviews.combined_graph.combined_driver import line_number_to_node_id_mapping
from .cfg.src.comex.codeviews.CFG.CFG_driver import CFGDriver
from .utils import read_file, get_code_language, get_class_name


class Cogpath:
    def __init__(self, args):
        self.args = args

        # Extract project name from project directory path
        project_name = os.path.basename(args.project_directory.rstrip('/'))


        cogpathLogger.set_log_path(
            prompt_type=args.prompt_type,
            llm_model=args.model,
            project_name=project_name,
            fix_type=args.fix_type,
            use_constraints=args.use_constraints
        )

        self.logger = cogpathLogger.initialize_logger(__name__)
        self.logger.info(f"Project name: {project_name}")
        self.logger.info(f"Log file path: {cogpathLogger.log_file}")

        # Build report label with think and mcts flags
        if args.run_symprompt:
            report_parts = ['symprompt', args.model]
        elif args.run_hits:
            report_parts = ['hits', args.model]
        else:
            report_parts = [args.prompt_type, args.model]

        # Add think flag if enabled
        if args.use_constraints:
            report_parts.append("constraints")

        self.beta = 0.6

        # Add mcts flag if fix_type is MCTS
        if args.fix_type == "MCTS":
            report_parts.append("mcts")
            
        if args.use_backward_slice:
            report_parts.append("bs")

        if args.solver_model:
            report_parts.append(args.solver_model)

        self.report_label = "_".join(report_parts)

        # Validate and map the model argument before passing it to UnitTestGenerator
        try:
            self.args.model = validate_and_map_model(args.model)
            if args.solver_model:
                self.args.solver_model = validate_and_map_model(args.solver_model)
            else:
                self.args.solver_model = self.args.model
        except ValueError as e:
            self.logger.error(str(e))
            raise
        self.test_dependencies = self.extract_test_dependency()
        self.validate_paths()
        self.duplicate_test_file()

        self.test_gen = UnitTestGenerator(
            project_dir=args.project_directory,
            source_code_file=args.source_code_file,
            test_code_file=args.test_file_output_path,
            code_coverage_report_path=args.code_coverage_report_path,
            test_execution_command=args.test_execution_command,
            test_code_command_dir=args.test_code_command_dir,
            test_dependencies=self.test_dependencies,
            included_files=args.included_files,
            coverage_type=args.coverage_type,
            target_coverage=args.target_coverage,
            prompt_type=args.prompt_type,
            additional_instructions=args.additional_instructions,
            use_constraints=args.use_constraints,
            use_backward_slice=args.use_backward_slice,
            fix_type=args.fix_type,
            llm_model=args.model,
            solver_model=args.solver_model)

    def extract_test_dependency(self):
        """
        Extract test dependencies by running the test dependency command.

        Returns:
            str: The output of the test dependency command, or empty string if failed.
        """
        try:
            stdout, stderr, exit_code, time_of_command, command_duration = (
                CommandExecutor.run_command(
                    command=self.args.test_dependency_command,
                    cwd=self.args.test_code_command_dir
                )
            )
            output = ""
            if exit_code == 0:
                output = '\n'.join(
                    line.replace("[INFO]", "").replace(":test", "").strip()
                    for line in stdout.strip().splitlines()
                )
            return output
        except Exception as e:
            self.logger.error(str(e))
            return ""

    def validate_paths(self):
        """
        Validate that the source code file exists and create test file if needed.

        Raises:
            FileNotFoundError: If the source code file is not found.
        """
        if not os.path.isfile(self.args.source_code_file):
            raise FileNotFoundError(f"Source file not found at {self.args.source_code_file}")

        test_file_dir = os.path.dirname(self.args.test_code_file)
        test_class_name = get_class_name(self.args.test_code_file)
        # Ensure the directory for the test file exists
        if test_file_dir and not os.path.exists(test_file_dir):
            os.makedirs(test_file_dir, exist_ok=True)

        # Create an empty test file if it does not exist
        if (not os.path.isfile(self.args.test_code_file) or
            os.path.getsize(self.args.test_code_file) == 0):
            self.initial_test_class_skeleton(test_class_name)

    def initial_test_class_skeleton(self, test_class_name):
        """Create a test class skeleton with basic package, imports and dummy test."""
        language = get_code_language(self.args.source_code_file)
        src_code = read_file(self.args.source_code_file)
        cfg_driver = CFGDriver(language, src_code)
        line_number_to_node_id_mapping(src_code, cfg_driver.CFG_nodes)

        # Only write the package declaration from source file
        package_line = next((line for line in src_code.split('\n')
                           if line.strip().startswith('package ')), None)

        if self.args.junit_version == 3:
            test_class_template = TEST_CLASS_JUNIT_3.format(test_class_name=test_class_name)
        elif self.args.junit_version == 5:
            test_class_template = TEST_CLASS_JUNIT_5.format(test_class_name=test_class_name)
        else:
            test_class_template = TEST_CLASS_JUNIT_4.format(test_class_name=test_class_name)

        with open(self.args.test_code_file, 'a') as f:
            if package_line:
                f.writelines(package_line + "\n\n")
            f.writelines(test_class_template)

    def duplicate_test_file(self):
        if self.args.test_file_output_path != "":
            shutil.copy(self.args.test_code_file, self.args.test_file_output_path)
        else:
            self.args.test_file_output_path = self.args.test_code_file

    def cleanup_test_file(self):
        """Remove the generated/used test file after run completes."""
        try:
            path = self.args.test_file_output_path if self.args.test_file_output_path else self.args.test_code_file
            if path and os.path.isfile(path):
                os.remove(path)
                self.logger.info(f"Cleaned up test file: {path}")
            else:
                self.logger.info(f"No test file to clean: {path}")
        except Exception as e:
            self.logger.error(f"Failed to cleanup test file: {str(e)}")

    def run(self):
        iteration_count = 0
        test_results_list = []
        no_coverage_increase = 0
        detailed_path_history = []

        self.test_gen.initial_test_suite_analysis_AST()
        try:
            while (
                    self.test_gen.current_coverage[0] < (self.test_gen.target_coverage / 100)
                    and iteration_count < self.args.maximum_iterations
                    and no_coverage_increase < self.args.no_coverage_increase_iterations
            ):
                cur_line_cov = round(self.test_gen.current_coverage[0] * 100, 2)
                cur_branch_cov = round(self.test_gen.current_coverage[1] * 100, 2)
                self.logger.info(f"Current line Coverage: {cur_line_cov}%, branch coverage: {cur_branch_cov}%")
                g_label = f"g_{iteration_count}"
                f_label = f"f_{iteration_count}"
                s_label = f"s_{iteration_count}"

                time_start = time.time()
                token_count = 0
                if int(cur_line_cov) == 0 and int(cur_branch_cov) == 0 or iteration_count == 0:
                    self.logger.info(f"initial tests generation using baseline type of prompt")
                    generated_tests_dict, gen_token_count = self.test_gen.generate_init_tests(g_label, max_tokens=4096)              
                else:
                    generated_tests_dict, gen_token_count = self.test_gen.generate_tests(g_label, max_tokens=4096,
                                                                        pick_two_paths=self.args.pick_two_paths)
                    
                if self.args.use_backward_slice and no_coverage_increase >= self.beta * self.args.no_coverage_increase_iterations:
                    backward_results = self.test_gen.generate_tests_by_slice(method_threshold=10, max_tokens=4096)
                    generated_tests_dict["slice_tests"] = []
                    for result in backward_results:
                        generated_tests_dict["slice_tests"].extend(result.get("generated_tests", []))
                    gen_token_count = 0  
                
                token_count += gen_token_count

                for generated_test in (generated_tests_dict.get("new_tests") or []):
                    test_result = self.test_gen.validate_test(generated_test)
                    test_result["label"] = g_label
                    test_results_list.append(test_result)
                    
                for generated_test in (generated_tests_dict.get("slice_tests") or []):
                    test_result = self.test_gen.validate_test(generated_test)
                    test_result["label"] = s_label
                    test_results_list.append(test_result)

                # collect code coverage after generation phase
                self.test_gen.run_coverage()
                info_dict_gen = {
                    "status": "INFO",
                    "label": g_label,
                    "reason": time.time() - time_start,
                    "exit_code": token_count,
                    "stderr": "",
                    "stdout": "",
                    "test": "",
                    "line_coverage": round(self.test_gen.current_coverage[0] * 100, 2),
                    "branch_coverage": round(self.test_gen.current_coverage[1] * 100, 2)
                }
                test_results_list.append(info_dict_gen)

                if self.args.enable_fixing:
                    # a separate phase to fix the failed tests in current generation iteration
                    iter_num = self.args.enable_fixing
                    fix_results_list, fix_token_count = self.test_gen.fix_failed_tests(f_label, iter_num, max_tokens=8192)
                    token_count += fix_token_count
                    for fix_result in fix_results_list:
                        test_results_list.append(fix_result)

                    # collect coverage after fixing phase
                    self.test_gen.run_coverage()
                    info_dict_fix = {
                        "status": "INFO",
                        "label": f_label,
                        "reason": time.time() - time_start,
                        "exit_code": token_count,
                        "stderr": "",
                        "stdout": "",
                        "test": "",
                        "line_coverage": round(self.test_gen.current_coverage[0] * 100, 2),
                        "branch_coverage": round(self.test_gen.current_coverage[1] * 100, 2)
                    }
                    test_results_list.append(info_dict_fix)
                else:
                    self.logger.info("fixing phase is disabled.")

                if self.test_gen.current_coverage[0] < (self.test_gen.target_coverage / 100):
                    new_line_cov = round(self.test_gen.current_coverage[0] * 100, 2)
                    new_branch_cov = round(self.test_gen.current_coverage[1] * 100, 2)
                    if new_line_cov > cur_line_cov or new_branch_cov > cur_branch_cov:
                        line_cov_increase = new_line_cov - cur_line_cov
                        branch_cov_increase = new_branch_cov - cur_branch_cov
                        self.logger.info(f"Iteration {iteration_count} increased "
                                         f"line coverage {round(line_cov_increase, 2)}%, "
                                         f"branch coverage {round(branch_cov_increase, 2)}%")
                        no_coverage_increase = 0
                    else:
                        self.logger.info(
                            f"Iteration {iteration_count} cannot increase coverage.")
                        no_coverage_increase += 1

                # Record detailed path history for this iteration
                iteration_path_data = {
                    "iteration": iteration_count,
                    "line_coverage": round(self.test_gen.current_coverage[0] * 100, 2),
                    "branch_coverage": round(self.test_gen.current_coverage[1] * 100, 2),
                    "path_history": dict(self.test_gen.path_history),  # Create a copy of the current path history
                    "lines_missed": list(self.test_gen.lines_missed),  # Copy of missed lines
                    "branches_missed": list(self.test_gen.branch_missed),  # Copy of missed branches
                    "timestamp": time.time()
                }
                detailed_path_history.append(iteration_path_data)

                iteration_count += 1              
        except Exception as e:
            self.logger.error("iteration stops due to error: %s", e)

        if self.test_gen.current_coverage[0] >= (self.test_gen.target_coverage / 100):
            self.logger.info(
                f"Reached above target coverage of {self.test_gen.target_coverage}% "
                f"(Current Coverage: ({round(self.test_gen.current_coverage[0] * 100, 2)}%, "
                f"{round(self.test_gen.current_coverage[1] * 100, 2)}%)) "
                f"in {iteration_count} iterations."
            )
        elif iteration_count == self.args.maximum_iterations:
            failure_message = (f"Reached maximum iteration limit without achieving desired coverage. "
                               f"Current Coverage: ({round(self.test_gen.current_coverage[0] * 100, 2)}%, "
                               f"{round(self.test_gen.current_coverage[1] * 100, 2)}%)")
            self.logger.error(failure_message)
        elif no_coverage_increase == self.args.no_coverage_increase_iterations:
            failure_message = (f"Reached maximum iteration limit without improving coverage. "
                               f"Current Coverage: ({round(self.test_gen.current_coverage[0] * 100, 2)}%, "
                               f"{round(self.test_gen.current_coverage[1] * 100, 2)}%)")
            self.logger.error(failure_message)

        report_file = self.args.report_filepath

        current_file = os.path.abspath(__file__)
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
        report_path = os.path.join(project_root, "result-files", self.report_label)
        info_dict = {
            "status": "INFO",
            "reason": "",
            "exit_code": 0,
            "stderr": "",
            "stdout": self.test_gen.prompt_builder.path_history,
            "test": "",
            "line_coverage": round(self.test_gen.current_coverage[0] * 100, 2),
            "branch_coverage": round(self.test_gen.current_coverage[1] * 100, 2)
        }
        test_results_list.append(info_dict)
        if not os.path.exists(report_path):
            os.makedirs(report_path)
        ReportGenerator.generate_report(test_results_list, os.path.join(report_path, report_file))
        self.logger.info(f"Report generated successfully at: {os.path.join(report_path, report_file)}")

        # Save detailed path history for comparison purposes (first occurrence)
        if detailed_path_history:
            # Generate final missed paths information
            final_line_coverage = round(self.test_gen.current_coverage[0] * 100, 2)
            final_branch_coverage = round(self.test_gen.current_coverage[1] * 100, 2)
            final_missed_data = {
                "final_line_coverage": final_line_coverage,
                "final_branch_coverage": final_branch_coverage,
                "final_lines_missed": list(self.test_gen.lines_missed),
                "final_branches_missed": list(self.test_gen.branch_missed),
                "detailed_path_history": detailed_path_history
            }

            path_history_file = os.path.splitext(report_file)[0] + "_path_history.json"
            path_history_path = os.path.join(report_path, path_history_file)

            with open(path_history_path, "w") as f:
                json.dump(final_missed_data, f, indent=2)

            self.logger.info(f"Detailed path history saved at: {path_history_path}")

            # Log the final coverage status
            self.logger.info(f"\n=== Final Coverage Status ===")
            self.logger.info(f"Line Coverage: {final_line_coverage}%")
            self.logger.info(f"Branch Coverage: {final_branch_coverage}%")
            self.logger.info(f"Final Missed Lines: {list(self.test_gen.lines_missed)}")
            self.logger.info(f"Final Missed Branches: {list(self.test_gen.branch_missed)}")
            self.logger.info(f"Paths Explored: {len(detailed_path_history[-1]['path_history']) if detailed_path_history else 0}")
        # Cleanup test file after run
        self.cleanup_test_file()

    def run_symprompt(self):
        test_results_list = []

        self.test_gen.initial_test_suite_analysis_AST()

        symprompt = SymPrompt(project_dir=self.args.project_directory, source_code_file=self.args.source_code_file,
                              llm_model=self.args.model, junit_version=self.args.junit_version)
        symprompt.generate_test()
        generated_tests = symprompt.generated_tests

        print('generated_tests', generated_tests)

        for method in generated_tests.keys():
            for index, g_test in enumerate(generated_tests[method]):
                test_result = self.test_gen.validate_test(g_test)
                test_result["label"] = f"{method}_{index}"
                test_results_list.append(test_result)
        self.test_gen.run_coverage()
        info_dict = {
            "status": "INFO",
            "reason": "",
            "exit_code": 0,
            "stderr": "",
            "stdout": "",
            "test": "",
            "line_coverage": round(self.test_gen.current_coverage[0] * 100, 2),
            "branch_coverage": round(self.test_gen.current_coverage[1] * 100, 2)
        }
        test_results_list.append(info_dict)
        file_name = self.args.source_code_file.split("/")[-1]
        file_name = file_name.split(".")[0]
        name_list = [file_name, "symprompt", self.args.report_filepath]
        if self.args.report_filepath:
            report_file = self.args.report_filepath
        else:
            report_file = "_".join(name_list) + ".html"

        current_file = os.path.abspath(__file__)
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
        report_path = os.path.join(project_root, "result-files", self.report_label)
        if not os.path.exists(report_path):
            os.makedirs(report_path)
        ReportGenerator.generate_report(test_results_list, os.path.join(report_path, report_file))
        self.logger.info(f"Report generated successfully at: {os.path.join(report_path, report_file)}")
        # Cleanup test file after run
        self.cleanup_test_file()

    def run_hits(self):
        test_results_list = []

        self.test_gen.initial_test_suite_analysis_AST()

        hits = HITS(project_dir=self.args.project_directory, source_code_file=self.args.source_code_file,
                              llm_model=self.args.model, junit_version=self.args.junit_version)

        # Limit slices per method to control token consumption
        max_slices = getattr(self.args, 'max_slices_per_method', 5)
        hits.generate_tests(max_slices_per_method=max_slices)
        generated_tests = hits.generated_tests

        for method_signature in generated_tests.keys():
            for index, g_test in enumerate(generated_tests[method_signature]):
                test_result = self.test_gen.validate_test(g_test)
                test_result["label"] = f"{method_signature}_{index}"
                test_results_list.append(test_result)
        self.test_gen.run_coverage()
        info_dict = {
            "status": "INFO",
            "reason": "",
            "exit_code": 0,
            "stderr": "",
            "stdout": "",
            "test": "",
            "line_coverage": round(self.test_gen.current_coverage[0] * 100, 2),
            "branch_coverage": round(self.test_gen.current_coverage[1] * 100, 2)
        }


        test_results_list.append(info_dict)
        file_name = self.args.source_code_file.split("/")[-1]
        file_name = file_name.split(".")[0]
        name_list = [file_name, "hits", self.args.report_filepath]
        if self.args.report_filepath:
            report_file = self.args.report_filepath
        else:
            report_file = "_".join(name_list) + ".html"

        current_file = os.path.abspath(__file__)
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
        report_path = os.path.join(project_root, "result-files", self.report_label)
        if not os.path.exists(report_path):
            os.makedirs(report_path)
        ReportGenerator.generate_report(test_results_list, os.path.join(report_path, report_file))
        self.logger.info(f"Report generated successfully at: {os.path.join(report_path, report_file)}")
        # Cleanup test file after run
        self.cleanup_test_file()
