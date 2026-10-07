#!/usr/bin/env python3
"""
LLM-based Backward Slicer for identifying prerequisites to reach uncovered code.
"""

import json
from typing import Dict, Any, Optional
from jinja2 import Environment, StrictUndefined
from .model_invocation.llm_invocation import LLMInvocation
from .config_loader import get_settings
from .logger import cogpathLogger


class LLMBackwardSlicer:
    """
    LLM-based backward slicer to analyze uncovered code and determine
    the conditions, inputs, and method calls required to reach it.
    """

    def __init__(self, llm_invoker: LLMInvocation):
        """
        Initialize the backward slicer.

        Args:
            llm_invoker: LLM invocation instance
        """
        self.logger = cogpathLogger.initialize_logger(__name__)
        self.llm_invoker = llm_invoker
        self.template = self._load_prompt_template()
        self.jinja_env = Environment(undefined=StrictUndefined)

    def _load_prompt_template(self) -> Dict[str, str]:
        """
        Load the backward slice prompt template.

        Returns:
            Dict[str, str]: System and user prompt templates
        """
        try:
            settings = get_settings()
            backward_slice_prompt = settings.get("backward_slice_prompt")

            if backward_slice_prompt:
                return {
                    "system": backward_slice_prompt.system,
                    "user": backward_slice_prompt.user
                }
            else:
                self.logger.warning("Backward slice prompt template not found")
                return self._get_default_template()

        except Exception as e:
            self.logger.error(f"Failed to load backward slice template: {str(e)}")
            return self._get_default_template()

    def _get_default_template(self) -> Dict[str, str]:
        """
        Get default prompt template as fallback.

        Returns:
            Dict[str, str]: Default system and user prompts
        """
        return {
            "system": "You are a code analysis expert specializing in backward slicing.",
            "user": """Analyze this uncovered code and determine what is required to reach it:
Uncovered Code:
{{ uncovered_code }}

Source:
{{ full_fm }}

Generate a backward slice analysis:
"""
        }

    def _render_prompt(self, uncovered_code: str, full_fm: str,
                       c_deps: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """
        Render the backward slice prompt using Jinja2.

        Args:
            uncovered_code: The code statement(s) that are not covered
            full_fm: Full source code of the focal method/class
            c_deps: Dependent classes information

        Returns:
            Dict[str, str]: Rendered system and user prompts
        """
        variables = {
            "uncovered_code": uncovered_code,
            "full_fm": full_fm,
            "c_deps": c_deps if c_deps else ""
        }

        try:
            user_prompt = self.jinja_env.from_string(self.template["user"]).render(**variables)
            return {
                "system": self.template["system"],
                "user": user_prompt
            }
        except Exception as e:
            self.logger.error(f"Failed to render backward slice prompt: {str(e)}")
            return {
                "system": self.template["system"],
                "user": f"Analyze uncovered code:\n{uncovered_code}\n\nSource:\n{full_fm}\n\nGenerate backward slice analysis:"
            }

    def slice(self, uncovered_code: str, full_fm: str,
              c_deps: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Perform backward slicing analysis on uncovered code.

        Args:
            uncovered_code: The code statement(s) that are not covered
            full_fm: Full source code of the focal method/class
            c_deps: Dependent classes information (optional)

        Returns:
            Dict containing:
                - backward_slice_code: List of statements forming the slice
                - prerequisites: Dict with input_values, object_states, method_mocks, control_flow_logic
                - test_hint: Guidance for test construction
        """
        if not self.llm_invoker:
            self.logger.error("LLM invoker not initialized, cannot perform backward slicing")
            return {}

        try:
            prompt = self._render_prompt(uncovered_code, full_fm, c_deps)
            self.logger.debug(f"Backward slice prompt: {prompt}")

            response, prompt_tokens, completion_tokens = self.llm_invoker.call_model(prompt)
            self.logger.info(f"Backward slice generated, prompt tokens: {prompt_tokens}, completion tokens: {completion_tokens}")

            # Parse JSON response
            result = self._parse_response(response)
            return result

        except Exception as e:
            self.logger.error(f"Error in backward slicing: {str(e)}")
            return {}

    def _parse_response(self, response: str) -> Dict[str, Any]:
        """
        Parse the LLM response into a structured dictionary.

        Args:
            response: Raw LLM response string

        Returns:
            Dict: Parsed backward slice result
        """
        try:
            # Try to extract JSON from the response
            response = response.strip()

            # Handle cases where response might have markdown code blocks
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]

            result = json.loads(response.strip())
            self.logger.debug(f"Parsed backward slice result: {result}")
            return result

        except json.JSONDecodeError as e:
            self.logger.warning(f"Failed to parse JSON response: {str(e)}, returning raw response")
            return {
                "raw_response": response,
                "error": "Failed to parse JSON"
            }


if __name__ == "__main__":
    # Simple test with mock LLM
    class MockLLM:
        def call_model(self, prompt):
            print("LLM Prompt:")
            print("=" * 50)
            print(prompt["system"])
            print(prompt["user"])
            print("=" * 50)
            print("Mock LLM Response:")
            mock_response = '''```json
{
    "backward_slice_code": [
        "if (index < 0) {",
        "    throw new IndexOutOfBoundsException(message);",
        "}"
    ],
    "prerequisites": {
        "input_values": [
            {"name": "index", "type": "int", "required_value": "< 0", "reason": "The condition index < 0 must be true"}
        ],
        "object_states": [
            {"object": "this", "field": "size", "type": "int", "required_value": ">= 0", "reason": "Used in error message"}
        ],
        "method_mocks": [],
        "control_flow_logic": "index < 0 must evaluate to true"
    },
    "test_hint": "Call list.get(-1)"
}
```'''
            return mock_response, 100, 200

    # Test inputs
    test_uncovered_code = """if (index < 0) {
    throw new IndexOutOfBoundsException("Index: " + index + ", Size: " + size);
}"""

    test_full_fm = """
public class ArrayList<E> {
    private int size;

    public E get(int index) {
        if (index < 0) {
            throw new IndexOutOfBoundsException("Index: " + index + ", Size: " + size);
        }
        return null;
    }
}
"""

    print("Testing LLMBackwardSlicer")
    print("=" * 70)

    try:
        slicer = LLMBackwardSlicer(MockLLM())
        result = slicer.slice(test_uncovered_code, test_full_fm)
        print(f"\nBackward Slice Result:")
        print(json.dumps(result, indent=2))
        print("\nTest completed successfully!")
    except Exception as e:
        print(f"\nError: {str(e)}")
        import traceback
        traceback.print_exc()
