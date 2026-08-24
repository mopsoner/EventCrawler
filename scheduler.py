import logging
import os

from app import create_app, scheduler_loop


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    create_app()
    scheduler_loop()
