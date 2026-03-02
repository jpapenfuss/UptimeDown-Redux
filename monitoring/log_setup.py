import logging


def log_setup():
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

    # add the stream handler to the logger
    logger.addHandler(ch)
    return logger
