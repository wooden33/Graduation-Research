import logging
import re
from .constants_config import MAX_DISPLAY_LINES


def extract_error_message(fail_message, language):
    fail_message = strip_ansi(fail_message)
    if language == "java":
        return extract_error_message_java(fail_message)

    if language == "python":
        return extract_error_message_python(fail_message)


def extract_error_message_python(fail_message):
    try:
        pattern = r"={3,} FAILURES ={3,}(.*?)(={3,}|$)"
        match = re.search(pattern, fail_message, re.DOTALL)
        if match:
            err_str = match.group(1).strip("\n")
            error_lines = err_str.split("\n")
            if len(error_lines) > MAX_DISPLAY_LINES:
                # limit the number of lines to display so that we do not exceed the context window limit
                err_str = "...\n" + "\n".join(error_lines[-MAX_DISPLAY_LINES:])
            return err_str
        return ""
    except Exception as e:
        logging.error(f"Error extracting error message: {e}")
        return ""


def extract_error_message_java(fail_message):
    try:
        pattern = r"<<< FAILURE!([\s\S]+?)(?:\n{2}|\Z)"
        matches = re.findall(pattern, fail_message)
        if matches:
            return "\n".join(matches)

        pattern = r".*FAILED\n(?!\n$).+"
        matches = re.findall(pattern, fail_message)
        if matches:
            return "\n".join(matches)

        return "Test failures"
    except Exception as e:
        logging.error(f"Error extracting error message: {e}")
        return ""


def extract_compilation_error_message_java(fail_message):
    fail_message = strip_ansi(fail_message)
    # right now only support maven projects
    try:
        pattern = r"COMPILATION ERROR\s*:\s*\[INFO\]\s*-+\s*([\s\S]*?)\[INFO\] \d+ error"
        matches = re.findall(pattern, fail_message)
        if matches:
            return "\n".join(matches)
        pattern = r"\[ERROR\].*?\n"
        matches = re.findall(pattern, fail_message)
        if matches:
            return "\n".join(matches)
        return "Compilation error"
    except Exception as e:
        logging.error(f"Error extracting error message: {e}")
        return ""


def strip_ansi(text):
    ansi_escape = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')
    return ansi_escape.sub('', text)