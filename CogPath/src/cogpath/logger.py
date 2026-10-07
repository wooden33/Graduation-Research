import logging
import os


class cogpathLogger:
    log_file = "cogpath.log"
    log_directory = None

    @classmethod
    def set_log_path(cls, prompt_type, llm_model, project_name, use_constraints=False, fix_type=None):
        current_file = os.path.abspath(__file__)
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))

        # Build directory name with think and mcts flags
        directory_parts = [prompt_type, llm_model]

        # Add think flag if enabled
        if use_constraints:
            directory_parts.append("constraints")

        # Add mcts flag if fix_type is MCTS
        if fix_type == "MCTS":
            directory_parts.append("mcts")

        directory_name = "_".join(directory_parts)

        # Create full log directory path
        cls.log_directory = os.path.join(project_root, "logs", directory_name)

        # Ensure directory exists
        os.makedirs(cls.log_directory, exist_ok=True)

        # Use project name as log filename to avoid multi-threading conflicts
        log_filename = f"{project_name}.log"
        cls.log_file = os.path.join(cls.log_directory, log_filename)

    @classmethod
    def initialize_logger(cls, name):
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        # Only add handlers if log_directory has been set via set_log_path
        if cls.log_directory is None:
            # Add stream handler only for console output
            if not logger.handlers:
                stream_handler = logging.StreamHandler()
                stream_handler.setLevel(logging.INFO)
                stream_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
                stream_handler.setFormatter(stream_formatter)
                logger.addHandler(stream_handler)
            return logger

        if not logger.handlers:
            file_handler = logging.FileHandler(cls.log_file, mode="w")
            file_handler.setLevel(logging.DEBUG)
            file_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)

            # Stream handler for console output
            stream_handler = logging.StreamHandler()
            stream_handler.setLevel(logging.INFO)
            stream_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            stream_handler.setFormatter(stream_formatter)
            logger.addHandler(stream_handler)

        return logger
