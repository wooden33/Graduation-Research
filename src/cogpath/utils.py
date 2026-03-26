import os

from .config_loader import get_settings


def _is_python_file(path_to_file) -> bool:
    return path_to_file.endswith(".py")


def _is_java_file(path_to_file) -> bool:
    return path_to_file.endswith(".py")


def read_file(file_path):
    try:
        with open(file_path, "r") as f:
            return f.read()
    except Exception as e:
        return f"Error reading {file_path}: {e}"


def get_class_name(file_path):
    """Extract class name from a file path."""
    return os.path.splitext(os.path.basename(file_path))[0]


def get_code_language(source_code_file):
    language_extensions_map = get_settings().language_extension

    extension_to_language = {}

    for language, extensions in language_extensions_map.items():
        for ext in extensions:
            extension_to_language[ext] = language

    extension_s = "." + source_code_file.rsplit(".")[-1]

    language_name = "unknown"

    # Check if the extracted file extension is in the dictionary
    if extension_s and (extension_s in extension_to_language):
        # Set the language name based on the file extension
        language_name = extension_to_language[extension_s]

    return language_name.lower()
