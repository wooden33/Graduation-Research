import json
import re
import os
import yaml
from jinja2 import Environment, StrictUndefined
from .command_executor import CommandExecutor
from .logger import cogpathLogger
from .config_loader import get_settings
from .templates import TEST_CLASS_JUNIT_5_IMPORTS, TEST_CLASS_JUNIT_4_IMPORTS, TEST_CLASS_JUNIT_3_IMPORTS
from .utils import read_file, get_code_language
from .cfg.src.comex.codeviews.combined_graph.combined_driver import CombinedDriver
from .cfg.src.comex.tree_parser.parser_driver import pre_process_src_code
from .model_invocation.llm_invocation import LLMInvocation


def get_class_name(file_path):
    file_name = os.path.basename(file_path)
    class_name = os.path.splitext(file_name)[0]
    return class_name


class HITS:
    """
    HITS: High-coverage LLM-based Unit Test Generation via Method Slicing

    This class implements the HITS methodology which:
    1. Decomposes the focal method into slices (problem-solving steps)
    2. Generates unit tests for each slice separately
    3. Combines all tests into a complete test suite
    4. Repairs any failed tests using self-debugging
    """

    def __init__(self, project_dir: str, source_code_file: str, llm_model: str, junit_version: int):
        """
        Initialize the HITS test generator.

        Args:
            project_dir: Directory of the project under test
            source_code_file: Path to the source file containing the method to test
            llm_model:LM model to use Name of the L
            junit_version: JUnit version (3, 4, or 5)
        """
        self.project_dir = project_dir
        self.source_code_file = source_code_file
        self.source_file_name = source_code_file.split("/")[-1]
        self.language = get_code_language(source_code_file)
        self.source_file = read_file(source_code_file)
        self.junit_version = junit_version
        self.logger = cogpathLogger.initialize_logger(__name__)

        # Initialize CFG driver to extract methods
        cfg_driver = CombinedDriver(
            src_language=self.language, src_code=self.source_file)
        self.cfg_obj = cfg_driver.file_obj

        # Extract all methods under test from the class
        self.methods_under_test = self._extract_methods_under_test()
        
        self.focal_class_name = get_class_name(source_code_file)
        self.cfg_node_to_line = cfg_driver.node_id_to_line_number

        # Generate test context based on JUnit version
        if junit_version == 3:
            self.test_context = self.extract_test_dependency() + \
                f"\n{TEST_CLASS_JUNIT_3_IMPORTS}"
        elif junit_version == 5:
            self.test_context = self.extract_test_dependency() + \
                f"\n{TEST_CLASS_JUNIT_5_IMPORTS}"
        else:
            self.test_context = self.extract_test_dependency() + \
                f"\n{TEST_CLASS_JUNIT_4_IMPORTS}"

        # Dependencies (to be populated)
        self.c_deps = {}  # Class dependencies
        self.m_deps = {}  # Method dependencies

        # Generated tests and slices storage
        self.generated_tests = {}
        self.slices = {}

        self.llm_invoker = LLMInvocation(model=llm_model, component="hits")

        self.logger.info(
            f"Initialized HITS for {self.source_file_name} with JUnit {junit_version}")
        self.logger.info(
            f"Found {len(self.methods_under_test)} methods under test")

    def extract_test_dependency(self):
        try:
            stdout, stderr, exit_code, time_of_command, command_duration = CommandExecutor.run_command(
                command="mvn dependency:list -DexcludeTransitive=true | grep ':test'", cwd=self.project_dir
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

    def generate_focal_class_context(self):
        src_code_lines = self.source_file.split('\n')
        clz_obj = self.cfg_obj["class_objects"][0]
        first_method = clz_obj['methods_under_test'][0]
        first_method_start_id = first_method['method_declaration']['id']
        first_method_start_line = self.cfg_node_to_line[first_method_start_id][0] - 1
        focal_context_lines = "\n".join(src_code_lines[:first_method_start_line])
        focal_context_lines = pre_process_src_code(self.language, focal_context_lines)
        return focal_context_lines

    def generate_focal_method_context(self, method):
        src_code_lines = self.source_file.split('\n')
        paths = method["paths"]
        method_calls_in_class = set()
        for index, path in enumerate(paths):
            for m in path['method_calls_within_class']:
                method_calls_in_class.add(m)

        methods_in_class = ""
        for method_call in method_calls_in_class:
            values = method_call.rsplit(',', 2)
            start_id = values[1].strip()
            end_id = values[2].strip()
            start_line = self.cfg_node_to_line[int(start_id)][0] - 1

            if end_id == "None":
                method_lines = "\n".join(src_code_lines[start_line:])
            else:
                end_line = self.cfg_node_to_line[int(end_id)][-1] - 1
                method_lines = "\n".join(src_code_lines[start_line:end_line])
            method_lines = pre_process_src_code(self.language, method_lines)

            methods_in_class += method_lines

        focal_method_nodes = method['method_declaration']['nodes']

        focal_start_line = self.cfg_node_to_line[focal_method_nodes[0]][0] - 1
        focal_end_line = self.cfg_node_to_line[focal_method_nodes[-1]][-1] - 1

        focal_method_lines = "\n".join(src_code_lines[focal_start_line:focal_end_line + 1])
        focal_method_lines = pre_process_src_code(self.language, focal_method_lines)
        return methods_in_class, focal_method_lines



    def _extract_methods_under_test(self) -> list:
        """
        Extract all methods under test from the focal class using CFG analysis.

        Returns:
            List of method dictionaries with 'name', 'id', 'complexity', 'value', and 'nodes' keys.
        """
        try:
            clz_obj = self.cfg_obj["class_objects"][0]
            methods = clz_obj.get("methods_under_test", [])

            methods_info = []
            for method in methods:
                method_decl = method.get("method_declaration", {})
                method_info = {
                    "name": method_decl.get("name", ""),
                    "id": method_decl.get("id", ""),
                    "signature": method_decl['value'].strip(),
                    "complexity": method_decl.get("complexity", 1),
                    "nodes": method_decl.get("nodes", [])
                }
                methods_info.append(method_info)

            return methods_info

        except (KeyError, IndexError) as e:
            self.logger.error(f"Error extracting methods under test: {e}")
            return []

    def _get_method_source_code(self, method_info: dict) -> str:
        try:
            nodes = method_info.get("nodes", [])
            if not nodes:
                return ""

            start_node = nodes[0]
            end_node = nodes[-1]

            start_line = self.cfg_node_to_line[start_node][0] - 1
            end_line = self.cfg_node_to_line[end_node][-1]

            lines = self.source_file.split('\n')
            return '\n'.join(lines[start_line:end_line])
        except (KeyError, IndexError) as e:
            self.logger.error(f"Error getting method source code: {e}")
            return ""

    def set_dependencies(self, c_deps: dict = None, m_deps: dict = None):
        if c_deps:
            self.c_deps = c_deps
        if m_deps:
            self.m_deps = m_deps
        self.logger.info(
            f"Set dependencies: {len(self.c_deps)} classes, {len(self.m_deps)} methods")

    def _build_prompt(self, template_key: str, **kwargs) -> dict:
        try:
            environment = Environment(undefined=StrictUndefined)

            # Get template based on template_key
            if template_key == 'slice':
                settings_key = get_settings().hits_gen_slice
            elif template_key == 'code':
                settings_key = get_settings().hits_gen_code
            elif template_key == 'repair':
                settings_key = get_settings().hits_repair
            else:
                raise ValueError(f"Unknown template key: {template_key}")
            
            kwargs['junit_version'] = self.junit_version

            # Render system prompt
            system_template = environment.from_string(settings_key.system)
            system_prompt = system_template.render(**kwargs)

            # Render user prompt
            user_template = environment.from_string(settings_key.user)
            user_prompt = user_template.render(**kwargs)

            return {"system": system_prompt, "user": user_prompt}

        except Exception as e:
            self.logger.error(f"Error building prompt for {template_key}: {e}")
            return {"system": "", "user": ""}

    def _call_llm(self, prompt: dict, max_tokens: int = 4096) -> tuple:
        """
        Call the LLM with the given prompt.

        Args:
            prompt: Dictionary with 'system' and 'user' prompts
            max_tokens: Maximum tokens to generate

        Returns:
            Tuple of (response_text, prompt_token_count, response_token_count)
        """
        response, prompt_token_count, response_token_count = (
            self.llm_invoker.call_model(prompt=prompt, max_tokens=max_tokens)
        )
        total_tokens = prompt_token_count + response_token_count
        self.logger.info(f"LLM call completed: {total_tokens} total tokens")
        return response, prompt_token_count, response_token_count

    def _parse_slice_response(self, response: str) -> list:
        """
        Parse the LLM response for slice generation using JSON.

        Args:
            response: LLM response text

        Returns:
            List of slice dictionaries with 'desp' and 'code' keys
        """
        try:
            # Extract JSON from code block if present
            json_text = response
            json_match = re.search(
                r'```(?:json|JSON)?\s*\n?([\s\S]*?)\n?\s*```', response, re.IGNORECASE)
            if json_match:
                json_text = json_match.group(1).strip()

            # Parse as JSON
            slices_data = json.loads(json_text)

            if slices_data and 'steps' in slices_data:
                return slices_data['steps']

            self.logger.warning(
                "Failed to parse slice response, returning empty list")
            return []

        except json.JSONDecodeError as e:
            self.logger.error(f"JSON decode error: {e}")
            # Try fallback: extract the steps array directly
            try:
                steps_match = re.search(
                    r'"steps"\s*:\s*(\[.*?\])', response, re.DOTALL)
                if steps_match:
                    steps_data = json.loads(steps_match.group(1))
                    return steps_data
            except Exception:
                pass
            return []
        except Exception as e:
            self.logger.error(f"Error parsing slice response: {e}")
            return []

    def _parse_test_code(self, response: str) -> str:
        try:
            # Extract YAML content from code block
            yaml_match = re.search(r'```yaml\s*\n([\s\S]*?)\n```', response, re.IGNORECASE)
            if not yaml_match:
                yaml_match = re.search(r'```\s*yaml\s*\n([\s\S]*?)\n```', response, re.IGNORECASE)

            if yaml_match:
                yaml_content = yaml_match.group(1).strip()
            else:
                # Fallback: strip markdown code block markers if present
                yaml_content = response.strip()
                yaml_content = re.sub(r'^```yaml\s*\n?', '', yaml_content, flags=re.IGNORECASE)
                yaml_content = re.sub(r'\n?```\s*$', '', yaml_content)

            # Parse YAML
            yaml_data = yaml.safe_load(yaml_content)

            if not yaml_data or 'single_test' not in yaml_data:
                # Fallback: try to find any yaml content
                self.logger.warning("Failed to find 'single_test' in YAML response")
                return {'single_test': []}

            return yaml_data
        except yaml.YAMLError as e:
            self.logger.error(f"YAML parse error: {e}")
            return {'single_test': []}
        except Exception as e:
            self.logger.error(f"Error parsing test code: {e}")
            return {'single_test': []}

    def gen_slices(self):
        # Build the prompt for slice generation
        for method in self.methods_under_test:
            prompt = self._build_prompt(
                template_key='slice',
                focal_method=method['name'],
                class_name=self.focal_class_name,
                full_fm=self._get_method_source_code(method),
                c_deps=self.c_deps,
                m_deps=self.m_deps
            )

            response, _, _ = self._call_llm(prompt)
            slices = self._parse_slice_response(response)

            self.slices[method['signature']] = slices

    def gen_tests(self, max_slices_per_method=5):
        """
        Generate tests for each slice.

        Args:
            max_slices_per_method: Maximum number of slices to process per method.
                                   Set to None to process all slices (unlimited).
        """
        for method in self.methods_under_test:
            generated_tests = []
            slices = self.slices[method['signature']]
            # Limit number of slices if max_slices_per_method is set
            if max_slices_per_method is not None:
                slices = slices[:max_slices_per_method]

            for slice in slices:
                prompt = self._build_prompt(
                    template_key='code',
                    focal_method=method['signature'],
                    simple_class_name=self.focal_class_name,
                    class_name=self.focal_class_name,
                    full_fm=self._get_method_source_code(method),
                    c_deps=self.c_deps,
                    m_deps=self.m_deps,
                    slice=slice
                )

                response, _, _ = self._call_llm(prompt)
                test_obj = self._parse_test_code(response)
                generated_tests.extend(test_obj['single_test'])

            self.generated_tests[method['signature']] = generated_tests

    def generate_tests(self, max_slices_per_method=5):
        # Step 1: Generate slices
        self.gen_slices()

        # Step 2: Generate tests for each slice
        self.gen_tests(max_slices_per_method=max_slices_per_method)


if __name__ == "__main__":
    hits = HITS(project_dir="defects4j-subjects-notests/Math-2f",
                source_code_file="defects4j-subjects-notests/Math-2f/src/main/java/org/apache/commons/math3/stat/descriptive/SummaryStatistics.java",
                llm_model="ollama/qwen3-coder:30b-a3b-q8_0",
                junit_version=4)

    hits.generate_tests()
    print(hits.generated_tests)
