import logging
from .logger import cogpathLogger
from .config_loader import get_settings
from .templates import ADDITIONAL_INCLUDES_TEXT, ADDITIONAL_INSTRUCTIONS_TEXT, FAILED_TESTS_TEXT
from jinja2 import Environment, StrictUndefined
from .cfg.src.comex.codeviews.combined_graph.combined_driver import CombinedDriver
from .llm_constraint_solver import LLMConstraintSolver
from .llm_backward_slicer import LLMBackwardSlicer
import random

from .utils import read_file

MAX_TESTS_PER_RUN = 4


class PromptBuilder:

    def __init__(self,
                 project_dir: str,
                 source_code_file: str,
                 test_code_file: str,
                 code_coverage_report: str = "",
                 included_files: str = "",
                 additional_instructions: str = "",
                 failed_test_runs: str = "",
                 coverage_invalid_tests: str = "",
                 language: str = "python",
                 lines_missed=None,
                 branch_missed=None,
                 path_history=None,
                 test_dependencies="",
                 constraint_solver: LLMConstraintSolver = None,
                 backward_slicer: LLMBackwardSlicer = None):
        if lines_missed is None:
            lines_missed = []
        if branch_missed is None:
            branch_missed = []
        if path_history is None:
            path_history = {}

        self.project_dir = project_dir
        self.source_file_name = source_code_file.split("/")[-1]
        self.test_file_name = test_code_file.split("/")[-1]
        self.source_file = read_file(source_code_file)
        self.test_file = read_file(test_code_file)
        self.code_coverage_report = code_coverage_report
        self.language = language

        cfg_driver = CombinedDriver(src_language=self.language, src_code=self.source_file)
        self.processed_source_code = cfg_driver.preprocessed_src_code
        self.cfg_obj = cfg_driver.file_obj
        self.cfg_node_to_line = cfg_driver.node_id_to_line_number
        self.line_to_cfg_node = cfg_driver.line_number_to_node_id
        self.lines_missed = lines_missed
        self.branch_missed = branch_missed
        self.path_history = path_history
        self.test_dependencies = test_dependencies

        # Initialize CFG branch analyzer
        self.cfa_guided_methods_under_test = self.extract_cfa_info_for_each_method_under_test()

        self.logger = cogpathLogger.initialize_logger(__name__)
        self.constraint_solver = constraint_solver
        self.backward_slicer = backward_slicer

        # add line numbers to each line in 'source_file'. start from 1
        self.source_file_numbered = "\n".join(
            [f"{i + 1} {line}" for i, line in enumerate(self.source_file.split("\n"))]
        )
        self.test_file_numbered = "\n".join(
            [f"{i + 1} {line}" for i, line in enumerate(self.test_file.split("\n"))]
        )

        # Conditionally fill in optional sections
        self.included_files = (
            ADDITIONAL_INCLUDES_TEXT.format(included_files=included_files)
            if included_files
            else ""
        )
        self.additional_instructions = (
            ADDITIONAL_INSTRUCTIONS_TEXT.format(
                additional_instructions=additional_instructions
            )
            if additional_instructions
            else ""
        )
        self.failed_test_runs_feedback = (
            FAILED_TESTS_TEXT.format(failed_test_runs=failed_test_runs)
            if failed_test_runs
            else ""
        )
        self.coverage_invalid_tests = coverage_invalid_tests
        self.failed_test_runs = failed_test_runs

    def identify_method_under_tests_with_missed_lines(self, method):
        lines = [
            line for node_id in method["method_declaration"]["nodes"] 
            for line in self.cfg_node_to_line[node_id]
        ]
        method_name = method["method_declaration"]["name"]
        cyc_complexity = method["method_declaration"]["complexity"]
        method_missed_lines = []
        method_missed_branches = []
        for line in self.lines_missed:
            if line in lines:
                method_missed_lines.append(line)
        for branch_line in self.branch_missed:
            if branch_line in lines:
                method_missed_branches.append(branch_line)
        return method_name, cyc_complexity, lines, method_missed_lines, method_missed_branches

    def generate_paths_to_be_covered(self, method, missed_lines, missed_branches):
        paths = method["paths"]
        candidate_paths = []
        method_label = (
            f"{method['method_declaration']['name']}_"
            f"{method['method_declaration']['id']}"
        )
        for index, path in enumerate(paths):
            path_label = f"{method_label}_{index}"
            path_node_ids = [node['id'] for node in path["path"]]
            path_lines = [
                line for node_id in path_node_ids 
                for line in self.cfg_node_to_line[node_id]
            ]
            path_covered_missed_lines = [value for value in missed_lines if value in path_lines]
            path_covered_missed_branches = [
                value for value in missed_branches if value in path_lines
            ]
            path_nodes = [
                (self.cfg_node_to_line[node['id']], node['statement'], node['conditional']) 
                for node in path["path"]
            ]
            if len(path_covered_missed_lines) or len(path_covered_missed_branches):
                path_conditions_str = ""

                for node in path_nodes:
                    node_lines = node[1].split("\n")
                    for i, line in enumerate(node[0]):
                        path_conditions_str += f"\n{line}: {node_lines[i]}"
                    if node[2] is not None:
                        path_conditions_str += f" is {node[2]}"
                missed_value = len(path_covered_missed_lines) + len(path_covered_missed_branches)
                candidate_paths.append((missed_value, path_lines, path_nodes, path_conditions_str, path_label))
                random.shuffle(candidate_paths)
        return candidate_paths

    def get_first_uncovered_branch(self, path_nodes, missed_branches):
        """
        Get the first uncovered branch node in a path.
        Path nodes are ordered by CFG topology, so the first uncovered branch
        can be found by iterating through nodes in order.
        """
        for node_index, node in enumerate(path_nodes):
            node_lines = node[0]
            statement = node[1]
            conditional = node[2]

            if conditional is None:
                continue

            for line in node_lines:
                if line in missed_branches:
                    return {
                        'line': line,
                        'statement': statement,
                        'condition': conditional,
                        'node_index': node_index
                    }

        return None

    def extract_cfa_info_for_each_method_under_test(self):
        # there may be multiple classes defined in the file, we focus on the outer class for now
        clz_obj = self.cfg_obj["class_objects"][0]
        methods_under_test = clz_obj["methods_under_test"]
        cfa_guided_methods = []
        for method in methods_under_test:
            name, complexity, lines, missed_lines, missed_branches = self.identify_method_under_tests_with_missed_lines(
                method)
            if complexity > 1:
                candidate_paths = self.generate_paths_to_be_covered(method, missed_lines, missed_branches)
            else:
                candidate_paths = []
            cfa_guided_methods.append((name, complexity, lines, missed_lines, missed_branches, candidate_paths))

        return sorted(cfa_guided_methods, key=lambda x: x[1], reverse=True)

    def pick_two_paths(self, candidate_paths, path_history, max_visit=10):

        if not candidate_paths:
            return None, None  # Handle empty input safely

        # Add visit count to each candidate path for comparison
        paths_with_visits = [
            (path, path_history.get(path[4], 0))  # path[4] is path_label
            for path in candidate_paths
        ]

        filtered_paths = [path for path in paths_with_visits if path[1] < max_visit]

        # Handle case where all paths are over-visited
        if not filtered_paths:
            return None, None

        # Exploitation: Pick highest-missed-value path
        highest_missed_path = max(filtered_paths, key=lambda x: x[0][0])[0]

        # Exploration: Pick least-visited path
        least_visited_path = max(filtered_paths, key=lambda x: -x[1])[0]  # Extract the path

        return highest_missed_path, least_visited_path

    def pick_path(self, candidate_paths, path_history, alpha=0.7):
        # candidate_paths: [(missed_value, path_lines, path_nodes, path_conditions_str, path_label)]
        # Add visit count to each candidate path for comparison
        if not candidate_paths:
            return None

        paths_with_visits = [
            (path, path_history.get(path[4], 0))  # path[4] is path_label
            for path in candidate_paths
        ]
        # Normalize missed_value for stable scoring
        max_missed_value = max((p[0] for p in candidate_paths), default=1)

        # Compute priority score
        prioritized_path = max(
            paths_with_visits,
            key=lambda x: (
                alpha * (x[0][0] / max_missed_value) + (1 - alpha) / (x[1] + 1),
                x[0][0]   # Tie-breaker
            )
        )[0]  # Extract the path

        return prioritized_path

    def build_prompt_backward(self, method_threshold: int = 3, max_methods: int = 3) -> dict:
        """
        Build prompts using backward slicing analysis for low-coverage methods.

        This method identifies methods with low coverage and complexity above threshold,
        then uses backward slicing to determine what inputs/conditions are needed to
        reach the uncovered code, generating targeted test generation prompts.

        Parameters:
            method_threshold: Minimum cyclomatic complexity threshold (default 3)
            max_methods: Maximum number of methods to analyze (default 3)

        Returns:
            dict: Contains:
                - system: System prompt
                - user: User prompt with backward slice analysis
                - methods: List of analyzed method info with slices
        """
        # Get low coverage methods with their uncovered segments
        low_coverage_methods = self.get_all_low_coverage_methods_with_segments(
            cc_threshold=method_threshold,
            limit=max_methods
        )

        if not low_coverage_methods:
            self.logger.info("No low coverage methods found meeting the complexity threshold")
            return {"system": "", "user": "", "methods": []}

        # Build variables for template rendering
        variables = {
            "source_file_name": self.source_file_name,
            "test_file_name": self.test_file_name,
            "source_file_numbered": self.source_file_numbered,
            "test_file_numbered": self.test_file_numbered,
            "source_file": self.source_file,
            "test_file": self.test_file,
            "test_dependencies": self.test_dependencies,
            "code_coverage_report": self.code_coverage_report,
            "coverage_invalid_tests_section": self.coverage_invalid_tests,
            "failed_tests_section": self.failed_test_runs_feedback,
            "additional_includes_section": self.included_files,
            "additional_instructions_text": self.additional_instructions,
            "language": self.language,
            "max_tests": MAX_TESTS_PER_RUN,
        }

        # Analyze each method using backward slicing
        analyzed_methods = []
        for method_info in low_coverage_methods:
            method_name = method_info[0]
            coverage = method_info[1]
            complexity = method_info[2]
            missed_lines = method_info[3]
            missed_branches = method_info[4]
            total_lines = method_info[5]
            uncovered_segments = method_info[6]

            self.logger.info(f"Analyzing method {method_name}: coverage={coverage:.2%}, complexity={complexity}")

            # Get the longest uncovered segment for backward slicing
            if uncovered_segments:
                longest_segment = uncovered_segments[0]  # Already sorted by length
                start_line, end_line, length = longest_segment

                # Extract the uncovered code from source
                uncovered_code = self._extract_code_segment(start_line, end_line)
            else:
                uncovered_code = ""
                start_line, end_line = None, None

            # Perform backward slicing if we have uncovered code and a backward slicer
            backward_slice = None
            if uncovered_code and self.backward_slicer:
                try:
                    backward_slice = self.backward_slicer.slice(
                        uncovered_code=uncovered_code,
                        full_fm=self.source_file
                    )
                    self.logger.info(f"Backward slice generated for {method_name}")
                except Exception as e:
                    self.logger.error(f"Failed to generate backward slice for {method_name}: {e}")

            analyzed_methods.append({
                "method_name": method_name,
                "coverage": coverage,
                "complexity": complexity,
                "missed_lines": missed_lines,
                "missed_branches": missed_branches,
                "total_lines": total_lines,
                "uncovered_segments": uncovered_segments,
                "longest_segment": {
                    "start_line": start_line,
                    "end_line": end_line,
                    "length": length,
                    "code": uncovered_code
                } if start_line else None,
                "backward_slice": backward_slice
            })

        # Render prompts using templates
        environment = Environment(undefined=StrictUndefined)
        try:
            system_prompt = environment.from_string(
                get_settings().test_generation_prompt.system
            ).render(variables)

            # Build user prompt with backward slice analysis
            backward_analysis_text = self._format_backward_analysis(analyzed_methods)
            user_prompt = environment.from_string(
                get_settings().test_generation_prompt.user
            ).render(variables, backward_analysis=backward_analysis_text)

            self.logger.debug(f"build_prompt_backward - system_prompt: {system_prompt[:200]}...")
            self.logger.debug(f"build_prompt_backward - user_prompt: {user_prompt[:200]}...")

        except Exception as e:
            self.logger.error(f"Error rendering backward prompt: {e}")
            return {"system": "", "user": "", "methods": analyzed_methods}

        return {
            "system": system_prompt,
            "user": user_prompt,
            "methods": analyzed_methods
        }

    def _extract_code_segment(self, start_line: int, end_line: int) -> str:
        """
        Extract code lines from source file.

        Parameters:
            start_line: Starting line number (1-indexed)
            end_line: Ending line number (1-indexed)

        Returns:
            str: The extracted code segment
        """
        lines = self.source_file.split("\n")
        # Handle 1-indexed line numbers
        start_idx = max(0, start_line - 1)
        end_idx = min(len(lines), end_line)

        if start_idx >= end_idx:
            return ""

        selected_lines = lines[start_idx:end_idx]
        # Add line numbers back
        numbered_lines = [f"{start_idx + i + 1} {line}" for i, line in enumerate(selected_lines)]
        return "\n".join(numbered_lines)

    def _format_backward_analysis(self, analyzed_methods: list) -> str:
        """
        Format backward slice analysis for inclusion in prompts.

        Parameters:
            analyzed_methods: List of method analysis results

        Returns:
            str: Formatted analysis text
        """
        if not analyzed_methods:
            return ""

        lines = ["", "=" * 60, "BACKWARD SLICE ANALYSIS FOR TEST GENERATION", "=" * 60, ""]

        for method in analyzed_methods:
            method_name = method["method_name"]
            coverage = method["coverage"]
            complexity = method["complexity"]
            longest_segment = method["longest_segment"]
            backward_slice = method["backward_slice"]

            lines.append(f"Method: {method_name}")
            lines.append(f"Coverage: {coverage:.2%} (complexity: {complexity})")
            lines.append("-" * 40)

            if longest_segment:
                lines.append(f"Longest uncovered segment (lines {longest_segment['start_line']}-{longest_segment['end_line']}):")
                lines.append(longest_segment['code'][:200] + "..." if len(longest_segment['code']) > 200 else longest_segment['code'])

            if backward_slice:
                lines.append("")
                lines.append("Backward Slice Analysis:")
                prerequisites = backward_slice.get("prerequisites", {})
                if prerequisites.get("input_values"):
                    lines.append("  Required Inputs:")
                    for inp in prerequisites["input_values"]:
                        lines.append(f"    - {inp.get('name', '?')} ({inp.get('type', '?')}): {inp.get('required_value', '?')}")
                        lines.append(f"      Reason: {inp.get('reason', '?')}")

                if prerequisites.get("object_states"):
                    lines.append("  Required Object States:")
                    for state in prerequisites["object_states"]:
                        lines.append(f"    - {state.get('object', '?')}.{state.get('field', '?')} = {state.get('required_value', '?')}")

                if prerequisites.get("control_flow_logic"):
                    lines.append(f"  Control Flow: {prerequisites['control_flow_logic']}")

                test_hint = backward_slice.get("test_hint", "")
                if test_hint:
                    lines.append(f"  Test Hint: {test_hint}")

            lines.append("")
            lines.append("=" * 60)

        return "\n".join(lines)

    def build_prompt_cfa_guided(self, pick_two_paths=True, use_constraints=True) -> dict:
        """
        Replaces placeholders with the actual content of files read during initialization, and returns the formatted prompt.

        Parameters:
            None

        Returns:
            str: The formatted prompt string.
        """
        variables = {
            "source_file_name": self.source_file_name,
            "test_file_name": self.test_file_name,
            "source_file_numbered": self.source_file_numbered,
            "test_file_numbered": self.test_file_numbered,
            "source_file": self.source_file,
            "test_file": self.test_file,
            "test_dependencies": self.test_dependencies,
            "code_coverage_report": self.code_coverage_report,
            "coverage_invalid_tests_section": self.coverage_invalid_tests,
            "failed_tests_section": self.failed_test_runs_feedback,
            "additional_includes_section": self.included_files,
            "additional_instructions_text": self.additional_instructions,
            "language": self.language,
            "max_tests": MAX_TESTS_PER_RUN,
            "processed_source_code": self.processed_source_code,
        }

        environment = Environment(undefined=StrictUndefined)
        try:
            if use_constraints:
                system_prompt = environment.from_string(
                    get_settings().test_generation_cfg_guided_with_constraint_solver_prompt.system
                ).render(variables)
            else:
                system_prompt = environment.from_string(
                    get_settings().test_generation_cfg_guided_prompt.system
                ).render(variables)

            rendered_templates = ""
            selected_paths = []

            for method in self.cfa_guided_methods_under_test:
                method_name = method[0]
                method_complexity = method[1]
                missed_lines = method[3]
                missed_branches = method[4]
                # print(method_name, missed_lines)
                # candidate_paths: [(missed_value, path_lines, path_nodes, path_conditions_str, path_label)]
                candidate_paths = method[5]
                
                if method_complexity > 1:
                    template_str = "\n=========\nPlease generate test case for method `{{ method_name }}` " \
                                   "to cover the path: {{ candidate_path }}"
                    if pick_two_paths:
                        highest_missed_path, least_visited_path = self.pick_two_paths(candidate_paths,
                                                                                      self.path_history)
                        if highest_missed_path and least_visited_path:
                            self.logger.info(
                                f"select the candidate path that covers the most missed lines for method {method_name}: {highest_missed_path[3]}")
                            highest_path_label = highest_missed_path[4]
                            least_path_label = least_visited_path[4]
                            self.path_history[highest_path_label] = self.path_history.get(highest_path_label, 0) + 1
                            path_str = highest_missed_path[3]
                            selected_paths.append(path_str)
                            
                            rendered_template = environment.from_string(template_str).render(method_name=method_name,
                                                                                             candidate_path=path_str)
                            rendered_templates += rendered_template
                            
                            if least_path_label != highest_path_label:
                                # self.logger.info(
                                #     f"select another candidate path with the least time of visits for method {method_name}: {least_visited_path[3]}")
                                self.path_history[least_path_label] = self.path_history.get(least_path_label, 0) + 1
                                path_str = least_visited_path[3]
                                selected_paths.append(path_str)

                                rendered_template = environment.from_string(template_str).render(method_name=method_name,
                                                                                                  candidate_path=path_str)
                                rendered_templates += rendered_template

                                if use_constraints and self.constraint_solver:
                                    # Get first uncovered branch info
                                    first_branch = self.get_first_uncovered_branch(
                                        least_visited_path[2], missed_branches)
                                    # Generate constraints for the selected path
                                    constraints = self.constraint_solver.generate_constraints(
                                        variables['source_file'], path_str, first_branch)
                                    rendered_template += f"\nConstraints: {constraints}"
                                
                    else:
                        prioritized_path = self.pick_path(candidate_paths, self.path_history)
                        if prioritized_path:
                            self.logger.info(
                                f"select the path that has highest priority score for method {method_name}: {prioritized_path[3]}")
                            path_label = prioritized_path[4]
                            self.path_history[path_label] = self.path_history.get(path_label, 0) + 1
                            path_str = prioritized_path[3]
                            selected_paths.append(path_str)
                            
                            rendered_template = environment.from_string(template_str).render(method_name=method_name,
                                                                                             candidate_path=path_str)
                            rendered_templates += rendered_template
                else:
                    if missed_lines:
                        template_str_missed_lines = "\n=========\nPlease generate test case for method `{{ method_name }}` " \
                                                    "to cover missed lines: {{ missed_lines }}"

                        rendered_template = environment.from_string(template_str_missed_lines).render(
                            method_name=method_name, missed_lines=missed_lines)
                        rendered_templates += rendered_template

            if use_constraints:
                user_prompt = environment.from_string(
                    get_settings().test_generation_cfg_guided_with_constraint_solver_prompt.user
                ).render(variables, method_under_test=rendered_templates)
            else:
                user_prompt = environment.from_string(
                    get_settings().test_generation_cfg_guided_prompt.user
                ).render(variables, method_under_test=rendered_templates)

            self.logger.debug(f"system_prompt: {system_prompt}")
            self.logger.debug(f"user_prompt: {user_prompt}")
        except Exception as e:
            logging.error(f"Error rendering prompt: {e}")
            return {"system": "", "user": ""}

        # print(f"#### user_prompt:\n\n{user_prompt}")
        return {"system": system_prompt, "user": user_prompt}

    def get_current_path_history(self):
        return self.path_history

    def get_lowest_coverage_method(self, cc_threshold: int = 3):
        """
        Find the method with the lowest coverage that has complexity greater than cc_threshold.

        Parameters:
            cc_threshold: Minimum cyclomatic complexity threshold (default 1)

        Returns:
            tuple: (method_name, coverage, complexity, missed_lines, missed_branches, total_lines)
                   or None if no method meets the criteria
        """
        best_method = None
        best_coverage = float('inf')  # Lower coverage is better (we want lowest)

        for method in self.cfa_guided_methods_under_test:
            method_name = method[0]
            complexity = method[1]
            lines = method[2]
            missed_lines = method[3]

            # Skip methods with complexity below threshold
            if complexity <= cc_threshold:
                continue

            total_lines = len(lines)
            if total_lines == 0:
                continue

            # Calculate coverage
            covered_lines = total_lines - len(missed_lines)
            coverage = covered_lines / total_lines

            # Track method with lowest coverage
            if coverage < best_coverage:
                best_coverage = coverage
                missed_branches = [
                    branch_line for branch_line in self.branch_missed
                    if branch_line in lines
                ]
                best_method = (method_name, coverage, complexity, missed_lines, missed_branches, total_lines)

        return best_method

    def get_lowest_coverage_methods_sorted(self, cc_threshold: int = 3, limit: int = 5):
        """
        Get a sorted list of methods with lowest coverage, filtered by complexity threshold.

        Parameters:
            cc_threshold: Minimum cyclomatic complexity threshold (default 1)
            limit: Maximum number of methods to return (default 5)

        Returns:
            list: List of tuples sorted by coverage (lowest first):
                  [(method_name, coverage, complexity, missed_lines, missed_branches, total_lines), ...]
        """
        qualified_methods = []

        for method in self.cfa_guided_methods_under_test:
            method_name = method[0]
            complexity = method[1]
            lines = method[2]
            missed_lines = method[3]

            # Skip methods with complexity below threshold
            if complexity <= cc_threshold:
                continue

            total_lines = len(lines)
            if total_lines == 0:
                continue

            # Calculate coverage
            covered_lines = total_lines - len(missed_lines)
            coverage = covered_lines / total_lines

            missed_branches = [
                branch_line for branch_line in self.branch_missed
                if branch_line in lines
            ]

            qualified_methods.append((method_name, coverage, complexity, missed_lines, missed_branches, total_lines))

        # Sort by coverage (lowest first)
        qualified_methods.sort(key=lambda x: x[1])

        return qualified_methods[:limit]

    def get_longest_uncovered_segments(self, missed_lines: list) -> list:
        """
        Find the longest consecutive uncovered line segments from a list of missed lines.

        Parameters:
            missed_lines: List of uncovered line numbers

        Returns:
            list: List of tuples (start_line, end_line, length) sorted by length (longest first)
        """
        if not missed_lines:
            return []

        # Sort the missed lines
        sorted_lines = sorted(set(missed_lines))
        segments = []
        start = sorted_lines[0]
        end = sorted_lines[0]

        for line in sorted_lines[1:]:
            if line == end + 1:
                # Consecutive line, extend the segment
                end = line
            else:
                # Gap found, save current segment and start new one
                segments.append((start, end, end - start + 1))
                start = line
                end = line

        # Don't forget the last segment
        segments.append((start, end, end - start + 1))

        # Sort by length (longest first)
        segments.sort(key=lambda x: x[2], reverse=True)

        return segments

    def get_lowest_coverage_method_with_segments(self, cc_threshold: int = 3):
        """
        Find the method with lowest coverage (complexity > cc_threshold) and its longest uncovered segments.

        Returns:
            tuple: (method_name, coverage, complexity, missed_lines, missed_branches, total_lines, longest_segments)
                   where longest_segments is a list of (start_line, end_line, length) tuples
        """
        method_info = self.get_lowest_coverage_method(cc_threshold)

        if method_info is None:
            return None

        method_name, coverage, complexity, missed_lines, missed_branches, total_lines = method_info
        longest_segments = self.get_longest_uncovered_segments(missed_lines)

        return (method_name, coverage, complexity, missed_lines, missed_branches, total_lines, longest_segments)

    def get_all_low_coverage_methods_with_segments(self, cc_threshold: int = 3, limit: int = 5):
        """
        Get low coverage methods with their longest uncovered segments.

        Parameters:
            cc_threshold: Minimum cyclomatic complexity threshold
            limit: Maximum number of methods to return

        Returns:
            list: List of method info tuples with longest_segments included
        """
        methods = self.get_lowest_coverage_methods_sorted(cc_threshold, limit)

        result = []
        for method in methods:
            method_name, coverage, complexity, missed_lines, missed_branches, total_lines = method
            longest_segments = self.get_longest_uncovered_segments(missed_lines)
            result.append((method_name, coverage, complexity, missed_lines, missed_branches, total_lines, longest_segments))

        return result


    def build_prompt(self, coverage_enabled=False) -> dict:
        """
        Replaces placeholders with the actual content of files read during initialization, and returns the formatted prompt.

        Parameters:
            coverage_enabled

        Returns:
            str: The formatted prompt string.
        """
        variables = {
            "source_file_name": self.source_file_name,
            "test_file_name": self.test_file_name,
            "source_file_numbered": self.source_file_numbered,
            "test_file_numbered": self.test_file_numbered,
            "source_file": self.source_file,
            "test_file": self.test_file,
            "test_dependencies": self.test_dependencies,
            "code_coverage_report": self.code_coverage_report,
            "coverage_invalid_tests_section": self.coverage_invalid_tests,
            "failed_tests_section": self.failed_test_runs_feedback,
            "additional_includes_section": self.included_files,
            "additional_instructions_text": self.additional_instructions,
            "language": self.language,
            "max_tests": MAX_TESTS_PER_RUN,
        }
        environment = Environment(undefined=StrictUndefined)
        try:
            if coverage_enabled:
                system_prompt = environment.from_string(
                    get_settings().test_generation_prompt_with_code_coverage_report.system
                ).render(variables)
                user_prompt = environment.from_string(
                    get_settings().test_generation_prompt_with_code_coverage_report.user
                ).render(variables)
            else:
                system_prompt = environment.from_string(
                    get_settings().test_generation_prompt.system
                ).render(variables)
                user_prompt = environment.from_string(
                    get_settings().test_generation_prompt.user
                ).render(variables)

            self.logger.debug(f"system_prompt: {system_prompt}")
            self.logger.debug(f"user_prompt: {user_prompt}")
        except Exception as e:
            logging.error(f"Error rendering prompt: {e}")
            return {"system": "", "user": ""}

        # print(f"#### user_prompt:\n\n{user_prompt}")
        return {"system": system_prompt, "user": user_prompt}

    def build_prompt_custom(self, file) -> dict:
        variables = {
            "source_file_name": self.source_file_name,
            "test_file_name": self.test_file_name,
            "source_file_numbered": self.source_file_numbered,
            "test_file_numbered": self.test_file_numbered,
            "source_file": self.source_file,
            "test_file": self.test_file,
            "test_dependencies": self.test_dependencies,
            "code_coverage_report": self.code_coverage_report,
            "coverage_invalid_tests_section": self.coverage_invalid_tests,
            "additional_includes_section": self.included_files,
            "failed_tests_section": self.failed_test_runs_feedback,
            "additional_instructions_text": self.additional_instructions,
            "language": self.language,
            "max_tests": MAX_TESTS_PER_RUN,
        }
        environment = Environment(undefined=StrictUndefined)
        try:
            system_prompt = environment.from_string(
                get_settings().get(file).system
            ).render(variables)
            user_prompt = environment.from_string(get_settings().get(file).user).render(
                variables
            )
        except Exception as e:
            logging.error(f"Error rendering prompt: {e}")
            return {"system": "", "user": ""}

        return {"system": system_prompt, "user": user_prompt}

    def build_prompt_for_fixing(self, fix_type: str) -> dict:
        variables = {
            "source_file_name": self.source_file_name,
            "test_file_name": self.test_file_name,
            "source_file": self.source_file,
            "test_file": self.test_file,
            "test_dependencies": self.test_dependencies,
            "failed_test_runs": self.failed_test_runs,
            "language": self.language
        }
        environment = Environment(undefined=StrictUndefined)
        try:
            if fix_type == 'MCTS':
                system_prompt = environment.from_string(
                    get_settings().failed_test_prompt_with_MCTS.system
                ).render(variables)
                user_prompt = environment.from_string(get_settings().failed_test_prompt_with_MCTS.user).render(
                    variables
                )
            else:
                system_prompt = environment.from_string(
                    get_settings().failed_test_prompt.system
                ).render(variables)
                user_prompt = environment.from_string(get_settings().failed_test_prompt.user).render(
                    variables
                )
            self.logger.debug(f"system_prompt: {system_prompt}")
            self.logger.debug(f"user_prompt: {user_prompt}")
        except Exception as e:
            logging.error(f"Error rendering prompt: {e}")
            return {"system": "", "user": ""}

        return {"system": system_prompt, "user": user_prompt}
