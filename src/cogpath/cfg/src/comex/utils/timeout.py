import signal


class TimeoutException(Exception):
    pass


def timeout_handler(signum, frame):
    raise TimeoutException()


def timeout_function(seconds, func, *args, **kwargs):
    # Set the signal handler for the timeout
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(seconds)  # Trigger alarm after `seconds` seconds

    try:
        result = func(*args, **kwargs)
        signal.alarm(0)  # Disable the alarm
        return result
    except TimeoutException:
        print(f"Function timed out after {seconds} seconds")
        return []
    finally:
        signal.alarm(0)  # Ensure the alarm is disabled