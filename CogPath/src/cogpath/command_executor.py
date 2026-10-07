import subprocess
import time
import os
import signal

class CommandExecutor:
    @staticmethod
    def run_command(command, cwd=None, timeout=60):
        """
        Returns:
            tuple: A tuple containing the standard output ('stdout'), standard error ('stderr'),
            exit code ('exit_code'), and the time of the executed command ('command_start_time').
        """
        p = None
        try:
            command_start_time = int(round(time.time() * 1000))
            p = subprocess.Popen(command, shell=True, cwd=cwd, text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            stdout, stderr = p.communicate(timeout=timeout)
            exit_code = p.returncode
            command_duration = int(round(time.time() * 1000)) - command_start_time
            return stdout, stderr, exit_code, command_start_time, command_duration
        except subprocess.TimeoutExpired:
            print(f'Timeout for {command} ({timeout}s) expired')
            print('Terminating the whole process group...')
            if p:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            return "Timeout", None, -1, None, None