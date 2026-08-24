import os

from app import create_app


def main():
    flask_app = create_app()
    flask_app.run(
        host=os.getenv("EVENTCRAWLER_HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5080")),
        debug=False,
    )


if __name__ == "__main__":
    main()
