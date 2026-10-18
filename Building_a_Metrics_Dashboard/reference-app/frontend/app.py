from flask import Flask, render_template, request
from prometheus_flask_exporter import PrometheusMetrics

app = Flask(__name__)

# Prometheus Metrics
metrics = PrometheusMetrics(app)
metrics.info("app_info", "Application info", version="1.0.0")


@app.route("/")
def homepage():
    return render_template("main.html")


if __name__ == "__main__":
    app.run()
