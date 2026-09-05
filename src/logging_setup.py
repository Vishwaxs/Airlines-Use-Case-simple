import logging
from pathlib import Path


def configure_logging(log_dir: Path, run_id: str) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('asg_airlines')
    logger.setLevel(logging.INFO)
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    for handler in [logging.FileHandler(log_dir / f'{run_id}.log', encoding='utf-8'),
                    logging.StreamHandler()]:
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger
