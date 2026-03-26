from flask import Flask, render_template
from api import api
from db import init_db, get_db_stats, list_events, list_free_products, get_event, list_patterns, list_extraction_runs
from config import APP_HOST, APP_PORT

app = Flask(__name__)
app.register_blueprint(api)
init_db()


@app.route("/")
def dashboard():
    return render_template("dashboard.html", stats=get_db_stats())


@app.route("/events")
def events():
    return render_template("events.html", events=list_events())


@app.route("/free")
def free_products():
    return render_template("free_products.html", products=list_free_products())


@app.route("/patterns")
def patterns():
    return render_template("patterns.html", patterns=list_patterns())


@app.route("/runs")
def runs():
    return render_template("runs.html", runs=list_extraction_runs())


@app.route("/event/<int:event_id>")
def event_detail(event_id):
    return render_template("event_detail.html", event=get_event(event_id))


if __name__ == "__main__":
    app.run(host=APP_HOST, port=APP_PORT, debug=True)
