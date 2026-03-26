import shutil
import tempfile
from tree_sitter import Language
import os
import subprocess


def get_language_map():
    clone_directory = os.path.join(tempfile.gettempdir(), "comex")
    shared_languages = os.path.join(clone_directory, "languages.so")

    # ("https://github.com/tree-sitter/tree-sitter-c-sharp", "3ef3f7f99e16e528e6689eae44dff35150993307")
    grammar_repos = [
        ("https://github.com/tree-sitter/tree-sitter-java", "09d650def6cdf7f479f4b78f595e9ef5b58ce31e"),
        ("https://github.com/tree-sitter/tree-sitter-python", "c01fb4e38587e959b9058b8cd34b9e6a3068c827")
    ]
    vendor_languages = []

    for url, commit in grammar_repos:
        grammar = url.rstrip("/").split("/")[-1]
        vendor_language = os.path.join(clone_directory, grammar)
        vendor_parser = os.path.join(vendor_language, "src", "parser.c")
        vendor_languages.append(vendor_language)
        if os.path.isfile(shared_languages) and not os.path.isfile(vendor_parser):
            os.remove(shared_languages)
            print(f"{vendor_parser} does not exist...")
        elif not os.path.isfile(shared_languages) and os.path.isfile(vendor_parser):
            shutil.rmtree(vendor_language)
            print(f"{shared_languages} does not exist...")
        elif not os.path.isfile(shared_languages) and not os.path.isfile(vendor_parser):
            print(f"{shared_languages} and {vendor_parser} do not exist...")
        else:
            continue
        print(f"Intial Setup: First time running COMEX on {grammar}")
        os.makedirs(vendor_language, exist_ok=True)

        commands = [["git", "init"],
                    ["git", "remote", "add", "origin", url],
                    ["git", "fetch", "--depth=1", "origin", commit],
                    ["git", "checkout", commit]]
        for command in commands:
            try:
                subprocess.check_call(command, cwd=vendor_language, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.STDOUT)
                print(f"Command '{' '.join(command)}' succeeded.")
            except subprocess.CalledProcessError as e:
                print(f"Command '{' '.join(command)}' failed with exit code {e.returncode}.")

    # build_id = ""
    # for vendor_language in vendor_languages:
    #     commit_hash = get_commit_hash(vendor_language)
    #     if commit_hash:
    #         build_id += commit_hash
    #     else:
    #         build_id += "ERROR"
    # build_id_file = os.path.join(clone_directory, "build_id")
    #
    # # check if the build_id is the same as the one stored in the file
    # # if not, rebuild the shared library
    # if os.path.exists(build_id_file):
    #     with open(build_id_file, "r") as f:
    #         stored_build_id = f.read()
    #     if build_id != stored_build_id:
    #         os.remove(shared_languages)
    # else:
    #     if os.path.exists(shared_languages):
    #         os.remove(shared_languages)

    Language.build_library(
        # Store the library in the `build` directory
        shared_languages,
        vendor_languages,
    )
    PYTHON_LANGUAGE = Language(shared_languages, "python")
    JAVA_LANGUAGE = Language(shared_languages, "java")
    # C_SHARP_LANGUAGE = Language(shared_languages, "c_sharp")
    # RUBY_LANGUAGE = Language("build/my-languages.so", "ruby")
    # GO_LANGUAGE = Language("build/my-languages.so", "go")
    # PHP_LANGUAGE = Language("build/my-languages.so", "php")
    # JAVASCRIPT_LANGUAGE = Language("build/my-languages.so", "javascript")

    # with open(build_id_file, "w") as f:
    #     f.write(build_id)

    return {
        "python": PYTHON_LANGUAGE,
        "java": JAVA_LANGUAGE,
        # "cs": C_SHARP_LANGUAGE,
        # "ruby": RUBY_LANGUAGE,
        # "go": GO_LANGUAGE,
        # "php": PHP_LANGUAGE,
        # "javascript": JAVASCRIPT_LANGUAGE,
    }
