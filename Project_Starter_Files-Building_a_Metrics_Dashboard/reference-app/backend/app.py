import logging
import os
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import pymongo
from flask_pymongo import PyMongo
from prometheus_flask_exporter import PrometheusMetrics
from jaeger_client import Config
from flask_opentracing import FlaskTracing

app = Flask(__name__)
CORS(app)

# Prometheus Metrics
metrics = PrometheusMetrics(app)
metrics.info("app_info", "Application info", version="1.0.0")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Jaeger Tracer Initialization
def init_tracer(service):
    config = Config(
        config={
            "sampler": {"type": "const", "param": 1},
            "logging": True,
            "reporter_batch_size": 1,
            "local_agent": {
                "reporting_host": os.getenv("JAEGER_AGENT_HOST", "localhost"),
                "reporting_port": int(os.getenv("JAEGER_AGENT_PORT", 6831)),
            },
        },
        service_name=service,
        validate=True,
    )
    return config.initialize_tracer()

tracer = init_tracer("backend")
flask_tracer = FlaskTracing(tracer, True, app)

# MongoDB Configuration
app.config["MONGO_DBNAME"] = "example-mongodb"
app.config[
    "MONGO_URI"
] = "mongodb://example-mongodb-svc.default.svc.cluster.local:27017/example-mongodb"

mongo = PyMongo(app)


@app.route("/")
def homepage():
    with tracer.start_span("homepage-backend") as span:
        span.set_tag("message", "hello-world")
        return "Hello World"


@app.route("/api")
def my_api():
    with tracer.start_span("api-processing") as span:
        answer = "something"
        span.set_tag("api.response", answer)
        return jsonify(repsonse=answer)


@app.route("/star", methods=["POST"])
def add_star():
    with tracer.start_span("mongo-insert-star") as span:
        try:
            star = mongo.db.stars
            name = request.json["name"]
            distance = request.json["distance"]
            span.set_tag("star.name", name)
            span.set_tag("star.distance", distance)

            star_id = star.insert({"name": name, "distance": distance})
            new_star = star.find_one({"_id": star_id})
            output = {"name": new_star["name"], "distance": new_star["distance"]}
            return jsonify({"result": output})
        except Exception as e:
            span.set_tag("error", True)
            span.log_kv({"event": "error", "message": str(e)})
            return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run()
