import logging


def log_setup():
    logger = logging.getLogger('monitoring')
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    # Channel - stdout/stderr
    ch = logging.StreamHandler()
    ch.setLevel(logging.ERROR)
    ch.setFormatter(formatter)

    # File handler - logfile.
    fh = logging.FileHandler('monitoring.log')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)

    # add the handlers to the logger
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger
