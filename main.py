import os
import sys
from pathlib import Path


def main():
    app_dir = Path(__file__).resolve().parent / "EventCrawler"
    os.chdir(app_dir)
    sys.path.insert(0, str(app_dir))
    from app import create_app

    flask_app = create_app()
    flask_app.run(host=os.getenv("EVENTCRAWLER_HOST", "127.0.0.1"), port=int(os.getenv("PORT", "5080")), debug=False)


if __name__ == "__main__":
    main()
