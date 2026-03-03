"""Logging configuration for the monitoring package.

Sets up the 'monitoring' logger with two handlers:
  - File handler (monitoring.log, DEBUG level): written only if the current
    directory is writable; silently skipped otherwise.
  - Stream handler (stderr, ERROR level): always active.

Call log_setup() once from __main__.py before any other code runs.
"""
import logging


def log_setup():
    """Configure and return the 'monitoring' logger.

    Attempts to attach a DEBUG-level FileHandler writing to monitoring.log in
    the current directory. If the directory is not writable (e.g. read-only NFS
    mount), the file handler is silently skipped and only stderr is used.

    Returns:
        logging.Logger: the configured 'monitoring' logger instance.
    """
    logger = logging.getLogger('monitoring')
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    # Channel - stdout/stderr
    ch = logging.StreamHandler()
    ch.setLevel(logging.ERROR)
    ch.setFormatter(formatter)

    # File handler - logfile. Only add if we can write to current directory.
    try:
        fh = logging.FileHandler('monitoring.log')
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except (IOError, OSError):
        # Can't write to current directory; skip file logging
        pass

    logger.addHandler(ch)
    return logger
