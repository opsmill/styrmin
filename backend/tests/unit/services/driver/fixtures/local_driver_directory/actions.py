from prefect import get_run_logger


def setup():
    logger = get_run_logger()
    logger.info("Executing setup user action...")


def update_password():
    pass
