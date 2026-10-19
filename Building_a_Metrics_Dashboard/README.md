**Note:** For the screenshots, you can store all of your answer images in the `answer-img` directory.

## Verify the monitoring installation

All pods and services across all namespaces (`monitoring`, `observability`, `default`, `ingress-nginx`, and `cert-manager`) are running and verified:

```bash
kubectl get pods -A
kubectl get svc -A
```

### Running Pods across all namespaces:
![Running Pods](answer-img/all-pods.png)

### Running Services across all namespaces:
![Running Services](answer-img/all-services.png)

## Setup the Jaeger and Prometheus source
Grafana is exposed via NGINX Ingress at `http://grafana.local` with Prometheus and Jaeger configured as active data sources.

### Grafana Home Page after login:
![Grafana Home Page](answer-img/grafana-loggin.png)

## Create a Basic Dashboard
Basic dashboard created in Grafana with Prometheus as the data source, visualizing application HTTP requests (`flask_http_request_total`) over time using a Time Series panel:

### Basic Prometheus Dashboard (Time Series):
![Basic Dashboard](answer-img/grafana-promethues-dashboard.png)

## Describe SLO/SLI

In simple terms:
- **SLI (Service Level Indicator)**: What you **actually measure**. It tells you how your service is performing right now (like the speedometer in a car).
- **SLO (Service Level Objective)**: The **target or goal** you agree to meet (like keeping your speed under the speed limit).

### 1. Based on an SLO of *Monthly Uptime* (e.g., 99.9% uptime per month):
- **SLI (What we measure)**: The percentage of successful HTTP requests compared to total requests over the month.
  $$\text{Uptime SLI} = \frac{\text{Successful Requests (non-5xx)}}{\text{Total Requests}} \times 100\%$$
- If out of 10,000 requests, 10 fail with a 500 error, our uptime SLI is 99.9%.

### 2. Based on an SLO of *Request Response Time* (e.g., 95% of requests answered in under 200ms):
- **SLI (What we measure)**: The latency (how long a user waits for a reply). Specifically, we measure the proportion of requests that complete within our 200ms threshold:
  $$\text{Latency SLI} = \frac{\text{Requests completed in } \le 200\text{ms}}{\text{Total Requests}} \times 100\%$$

---

## Creating SLI metrics.

It is important to measure metrics from the customer's point of view: if the server is technically running but the user sees an error or waits 10 seconds, the service is broken for them.

Here are 5 key metrics to measure these SLIs:

1. **HTTP 5xx Server Error Rate (Availability SLI)**:
   - **What it is**: The rate of internal server errors (HTTP 500, 502, 503) where our backend fails or crashes.
   - **Why it matters**: A customer seeing a 500 error cannot use the service. A sudden spike in 5xx means an outage or bad deployment.
   - **Prometheus Metric**: `rate(flask_http_request_total{status=~"5.."}[5m]) / rate(flask_http_request_total[5m])`

2. **Request Response Time / Latency (Speed SLI)**:
   - **What it is**: The time (in seconds or milliseconds) from when a customer sends a request until they receive the response.
   - **Why it matters**: Slow websites feel broken. If pages take too long to load, customers leave. Tracking the 95th percentile (p95) ensures even slower users get an acceptable experience.
   - **Prometheus Metric**: `histogram_quantile(0.95, sum(rate(flask_http_request_duration_seconds_bucket[5m])) by (le))`

3. **HTTP 4xx Client Error Rate (Quality SLI)**:
   - **What it is**: The rate of requests returning 400 (Bad Request) or 404 (Not Found).
   - **Why it matters**: While 4xx errors usually mean bad input or missing pages, a high rate often signals broken links in the frontend or buggy API calls between frontend and backend.
   - **Prometheus Metric**: `rate(flask_http_request_total{status=~"4.."}[5m])`

4. **Service Health / Up Status (Pod Availability SLI)**:
   - **What it is**: A binary check (1 = alive, 0 = down) showing whether Prometheus can reach and scrape the application instance.
   - **Why it matters**: If all instances of a service report 0, the application has crashed completely and no traffic can be served.
   - **Prometheus Metric**: `up{job=~".*service.*"}`

5. **Request Throughput / Traffic Volume (RPS)**:
   - **What it is**: The total number of HTTP requests arriving per second.
   - **Why it matters**: It provides context for all other metrics. It helps us understand whether high latency is caused by a massive traffic surge or a backend bottleneck, and an unexpected drop to 0 requests indicates an upstream network failure.
   - **Prometheus Metric**: `sum(rate(flask_http_request_total[5m])) by (service)` 

## Create a Dashboard to measure our SLIs

Dashboard created in Grafana measuring the uptime of frontend and backend services, alongside real-time 40x client errors and 50x server errors tracked over a 24-hour window:

### SLI & Error Dashboard (24 Hours):
![SLI Dashboard](answer-img/sli-dashboard.png)

## Tracing our Flask App

We instrumented the backend Flask service with the Jaeger Python client (`jaeger-client`) and OpenTracing (`FlaskTracing`) to measure and trace internal operations across routes:

### Jaeger Trace Span for Backend Service:
![Backend Trace Span](answer-img/backend-trace.png)

### Sample Python Code for Tracing and Custom Spans (`backend/app.py`):
```python
import os
import logging
from flask import Flask, jsonify, request
from jaeger_client import Config
from flask_opentracing import FlaskTracing

app = Flask(__name__)


# Initialize Jaeger Tracer
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


# Custom Trace Span Example on /api endpoint
@app.route("/api")
def my_api():
    with tracer.start_span("api-processing") as span:
        answer = "something"
        span.set_tag("api.response", answer)
        return jsonify(repsonse=answer)


# Custom Trace Span Example with Database Operations
@app.route("/star", methods=["POST"])
def add_star():
    with tracer.start_span("mongo-insert-star") as span:
        star = mongo.db.stars
        name = request.json["name"]
        distance = request.json["distance"]
        span.set_tag("star.name", name)
        span.set_tag("star.distance", distance)

        star_id = star.insert({"name": name, "distance": distance})
        new_star = star.find_one({"_id": star_id})
        output = {"name": new_star["name"], "distance": new_star["distance"]}
        return jsonify({"result": output})
```

## Jaeger in Dashboards

Jaeger tracing is integrated directly into Grafana using the pre-configured Jaeger data source (`http://simplest-query.observability.svc.cluster.local:16686`), allowing developers to query, inspect, and analyze distributed traces and latency spans within the Grafana interface:

### Jaeger Traces Integrated in Grafana:
![Jaeger in Grafana](answer-img/grafana-jaeger.png)

## Report Error

Using distributed tracing in Jaeger, we quickly located and diagnosed an unhandled HTTP 500 error on the `/trace` endpoint:

### Jaeger Tracer Error Span:
![Tracer Error Span](answer-img/error-trace.png)

### TROUBLE TICKET

**Name**: SRE / Observability Engineer  
**Date**: October 19, 2026  
**Subject**: HTTP 500 Internal Server Error & Failure on `/trace` Endpoint  
**Affected Area**: Trial Service (`reference-app/trial/app.py`, endpoint `/trace`, span `get-python-jobs`)  
**Severity**: High (Service endpoint unavailable / broken transaction)  

**Description**:
- **Symptom**: Requests sent to `http://trial.local/trace` consistently return an HTTP 500 Internal Server Error with elevated response latency.
- **Root Cause Identified via Jaeger**:
  Inspection of the Jaeger distributed trace immediately pinpointed the root cause to the child span labeled **`get-python-jobs`**. In `reference-app/trial/app.py` (lines 60–64), the application performs a synchronous HTTP request:
  ```python
  res = requests.get("https://jobs.github.com/positions.json?description=python")
  span.log_kv({"event": "get jobs count", "count": len(res.json())})
  ```
  The external endpoint `jobs.github.com` was decommissioned by GitHub and no longer serves JSON payloads. Consequently, `res.json()` fails with an uncaught `JSONDecodeError`, terminating the Flask request with an unhandled 500 error.
- **Value of Tracing**:
  The Jaeger tracer highlighted the failing sub-process in red, tagged the HTTP 500 status, and revealed that the failure was not in the database or server runtime, but in an external outbound HTTP dependency.


## Creating SLIs and SLOs

To guarantee our application meets the **SLO of 99.95% monthly uptime** (which allows a maximum of **~21.6 minutes of downtime** or 5 failed requests per 10,000 requests in a 30-day month), we use the following four SLIs:

1. **HTTP Success Rate SLI (Non-5xx Error Rate)**:
   - **What it measures**: The percentage of incoming HTTP requests that return a successful status code (anything other than a 5xx server error).
   - **Formula**:
     $$\text{SLI}_1 = \frac{\text{Total Requests} - \text{HTTP 5xx Requests}}{\text{Total Requests}} \times 100\% \ge 99.95\%$$
   - **Why it matters**: A direct measure of user success: whenever a 5xx error occurs, the user's transaction fails.

2. **Pod Availability SLI (Kubernetes Health Probes)**:
   - **What it measures**: The percentage of minutes in the month where at least one healthy, ready replica of each service (`frontend`, `backend`) is running and reachable by Prometheus.
   - **Formula**:
     $$\text{SLI}_2 = \frac{\text{Minutes where } \text{up} == 1}{\text{Total minutes in month (43,200 min)}} \times 100\% \ge 99.95\%$$
   - **Why it matters**: Measures infrastructure availability. If all backend or frontend pods crash, 100% of user traffic is dropped.

3. **Latency-Bounded Success SLI (Speed Quality)**:
   - **What it measures**: The percentage of valid requests completed in under an acceptable latency threshold (e.g., $\le 500\text{ms}$).
   - **Formula**:
     $$\text{SLI}_3 = \frac{\text{Successful requests completed in } \le 500\text{ms}}{\text{Total Requests}} \times 100\% \ge 99.0\%$$
   - **Why it matters**: A page that takes 30 seconds to load or times out feels completely down to the user, even if it eventually returns an HTTP 200.

4. **Database Dependency SLI (MongoDB Query Success Rate)**:
   - **What it measures**: The ratio of successful database operations (reads/writes on MongoDB `example-mongodb-svc`) compared to total attempted operations.
   - **Formula**:
     $$\text{SLI}_4 = \frac{\text{Successful MongoDB Read/Write Operations}}{\text{Total Attempted MongoDB Operations}} \times 100\% \ge 99.95\%$$
   - **Why it matters**: The backend API depends directly on MongoDB for critical operations like `/star`. If the database fails, the backend immediately begins failing user requests.

---

## Building KPIs for our plan

To effectively track and protect our 99.95% monthly uptime SLO, we track the following 3 Key Performance Indicators (KPIs):

1. **Error Budget Burn Rate (or Error Budget Remaining)**:
   - **Description**: Tracks how quickly the allowed 0.05% monthly error budget is being consumed over time.
   - **Why chosen**: A 99.95% SLO permits only 0.05% errors per month (~21.6 minutes of downtime). Rather than discovering a breached SLO at the end of the month, tracking the burn rate triggers automated alerts during sudden spikes, allowing engineers to mitigate issues before the monthly budget is exhausted.

2. **Mean Time to Recovery (MTTR)**:
   - **Description**: The average time elapsed from when an outage or performance degradation begins until service is fully restored.
   - **Why chosen**: Outages are inevitable in complex systems. High uptime depends heavily on how rapidly the team detects an incident (via Prometheus alerts), isolates the root cause (using Jaeger distributed tracing), and resolves it. Keeping MTTR under 10 minutes ensures single incidents do not blow the monthly uptime SLO.

3. **95th Percentile Response Latency (p95)**:
   - **Description**: The maximum response time experienced by 95% of users (excluding the slowest 5% outliers).
   - **Why chosen**: Average latency can be deceptive by hiding severe bottlenecks. Measuring p95 ensures that the vast majority of real users receive fast, responsive performance even during peak traffic loads.

---

## Final Dashboard

A comprehensive Grafana dashboard was created to capture all KPI and SLI metrics representing service health, error rates, throughput, and latency:

### Final Observability Dashboard:
![Final Dashboard](answer-img/sli-dashboard.png)

### Description of Dashboard Panels:
1. **Frontend Service Uptime (Stat Gauge)**: Displays real-time uptime percentage for the frontend UI service based on Prometheus health probes.
2. **Backend Service Uptime (Stat Gauge)**: Displays real-time uptime percentage for the backend API service, verifying continuous container and pod availability.
3. **Trial Service Uptime (Stat Gauge)**: Displays uptime for the testing sandbox service.
4. **40x Client Error Rate (Time Series)**: Tracks the rate of 4xx errors (e.g. 404 Not Found) per second over time, alerting to broken frontend links or faulty client calls.
5. **50x Server Error Rate (Time Series)**: Tracks the rate of 5xx errors (e.g. 500 Internal Server Error) per second, directly monitoring our availability SLI and error budget.
6. **Request Latency p95 (Time Series)**: Graphs the 95th percentile latency in seconds across services to ensure requests respond within user satisfaction thresholds.
7. **Total Requests by Service & Status (Time Series / Stacked Bars)**: Shows overall request traffic volume grouped by service name and HTTP response code, providing full operational visibility.  
