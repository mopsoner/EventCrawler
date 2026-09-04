import logging
import os

from app import create_app, ensure_booking_job_thread, scheduler_loop


def main():
    create_app()
    ensure_booking_job_thread()
    scheduler_loop()


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    main()
