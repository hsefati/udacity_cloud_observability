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
*TODO:* Create a dashboard to measure the uptime of the frontend and backend services We will also want to measure to measure 40x and 50x errors. Create a dashboard that show these values over a 24 hour period and take a screenshot.

## Tracing our Flask App
*TODO:*  We will create a Jaeger span to measure the processes on the backend. Once you fill in the span, provide a screenshot of it here. Also provide a (screenshot) sample Python file containing a trace and span code used to perform Jaeger traces on the backend service.

## Jaeger in Dashboards
*TODO:* Now that the trace is running, let's add the metric to our current Grafana dashboard. Once this is completed, provide a screenshot of it here.

## Report Error
*TODO:* Using the template below, write a trouble ticket for the developers, to explain the errors that you are seeing (400, 500, latency) and to let them know the file that is causing the issue also include a screenshot of the tracer span to demonstrate how we can user a tracer to locate errors easily.

TROUBLE TICKET

Name:

Date:

Subject:

Affected Area:

Severity:

Description:


## Creating SLIs and SLOs
*TODO:* We want to create an SLO guaranteeing that our application has a 99.95% uptime per month. Name four SLIs that you would use to measure the success of this SLO.

## Building KPIs for our plan
*TODO*: Now that we have our SLIs and SLOs, create a list of 2-3 KPIs to accurately measure these metrics as well as a description of why those KPIs were chosen. We will make a dashboard for this, but first write them down here.

## Final Dashboard
*TODO*: Create a Dashboard containing graphs that capture all the metrics of your KPIs and adequately representing your SLIs and SLOs. Include a screenshot of the dashboard here, and write a text description of what graphs are represented in the dashboard.  
