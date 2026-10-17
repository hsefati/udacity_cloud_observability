# Observability Setup v2: Prometheus, Grafana, Jaeger (kind + ingress)

A clean, self-contained Kubernetes observability setup based on a local [kind](https://kind.sigs.k8s.io/) cluster with ingress routing.

---

### Component Summary

| Component | Version | Description |
|---|---|---|
| **kind node (Kubernetes)** | `v1.36.1` | Local Kubernetes cluster running in Docker containers |
| **kube-prometheus-stack** | chart `91.9.0` (app `v0.94.1`) | Full monitoring suite: Prometheus Operator, Alertmanager, Grafana, and node-exporter |
| **jaeger-operator** | chart `2.57.0` (app `1.61.0`) | Kubernetes operator managing Jaeger distributed tracing instances and sidecars |
| **Jaeger instance** | `simplest` (all-in-one) | Lightweight all-in-one tracing backend (query, collector, UI) with in-memory storage |
| **cert-manager** | latest (Jetstack chart) | Issues TLS certificates required by the Jaeger Operator admission webhook |
| **ingress-nginx** | kind provider manifest | Ingress controller routing host domain traffic to cluster services |

---

### Namespace Architecture

| Namespace | Contents | Purpose |
|---|---|---|
| `ingress-nginx` | Ingress NGINX controller | Terminates incoming traffic on ports 80/443 and routes to target services |
| `cert-manager` | cert-manager controller, webhook, cainjector | Manages internal CAs and TLS certificates for Kubernetes webhooks |
| `monitoring` | Prometheus, Alertmanager, Grafana | Metrics collection, evaluation, alerting, and visualization |
| `observability` | jaeger-operator, Jaeger `simplest` instance | Distributed trace ingestion, storage, search, and trace visualization UI |

---

### Exposed Endpoints

| URL | Service Name | Namespace | Internal Target Port | Description |
|---|---|---|---|---|
| `http://grafana.local` | `prometheus-grafana` | `monitoring` | `80` | Metrics dashboards and unified trace viewer |
| `http://prometheus.local` | `prometheus-kube-prometheus-prometheus` | `monitoring` | `9090` | Prometheus web UI, metrics browser, and targets |
| `http://jaeger.local` | `simplest-query` | `observability` | `16686` | Jaeger distributed tracing search and timeline UI |

> [!NOTE]
> The commands below provide a verified, reproducible environment. If any step encounters an issue, consult the **Troubleshooting** section at the bottom of this document.

---

## 0. Prerequisites

### What it does:
Verifies that all required local CLI utilities and free host networking ports are available before attempting cluster creation.

### Why it is needed:
- **`docker`**: Underpins `kind` by running Kubernetes nodes as local Linux containers.
- **`kind` (Kubernetes in Docker)**: Runs multi-node or single-node Kubernetes clusters locally without heavyweight virtual machines.
- **`kubectl`**: Standard command-line tool for controlling Kubernetes clusters and deploying resources.
- **`helm`**: The package manager for Kubernetes, used to deploy complex Helm charts (Prometheus stack, cert-manager, Jaeger operator).
- **Free host ports 80 & 443**: `kind` binds directly to ports 80 and 443 on your local machine so you can browse `http://*.local` domains without running temporary `kubectl port-forward` commands.

```bash
# Verify installed command-line tools
docker --version      # Container runtime engine
kind --version        # Local cluster management CLI
kubectl version --client --output=yaml  # Kubernetes control CLI
helm version --short  # Helm package manager CLI

# Check if ports 80 and 443 are free (should return empty output if free)
sudo ss -tulpn | grep -E ':(80|443)\b' || true
```

---

## 1. kind cluster

### What it does:
1. Writes a cluster configuration file (`kind-config.yaml`) defining a single control-plane node.
2. Applies a node label (`ingress-ready=true`) via `kubeadmConfigPatches`.
3. Binds host ports `80` and `443` directly to the `kind` control-plane container's ports `80` and `443`.
4. Creates the Kubernetes cluster named `kind-cloud-observ-project` and switches `kubectl` context to it.

### Why it is needed:
- **`node-labels: "ingress-ready=true"`**: The official NGINX Ingress manifest for `kind` uses a `nodeSelector` looking for this exact label. This guarantees that the ingress controller pod is scheduled on the node configured with the host port mappings.
- **`extraPortMappings`**: Standard Kubernetes containers inside `kind` run in an isolated Docker bridge network. Forwarding container ports 80 and 443 to the host machine allows your browser to reach ingress endpoints on `localhost:80` and `localhost:443` directly.

Save as `kind-config.yaml`:

```yaml
# kind-config.yaml
# Kind cluster configuration file for local ingress integration
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  # Custom kubeadm initialization patch applied during node bootstrapping
  kubeadmConfigPatches:
  - |
    kind: InitConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        # Label required by the kind NGINX Ingress controller nodeSelector
        node-labels: "ingress-ready=true"
  # Forward local host traffic directly into the kind node container
  extraPortMappings:
  # Map host port 80 -> kind node container port 80 (HTTP)
  - containerPort: 80
    hostPort: 80
    protocol: TCP
  # Map host port 443 -> kind node container port 443 (HTTPS)
  - containerPort: 443
    hostPort: 443
    protocol: TCP
```

Execute the cluster creation:

```bash
# 1. Spin up the kind cluster using our custom configuration
kind create cluster --name kind-cloud-observ-project --config kind-config.yaml

# 2. Confirm the active kubectl context points to our newly created kind cluster
kubectl config current-context    # Expected output: kind-kind-cloud-observ-project

# 3. Verify the control-plane node is ready and labeled correctly
kubectl get nodes --show-labels
```

---

## 2. Ingress controller

### What it does:
1. Deploys the official NGINX Ingress Controller using the kind-specific deployment manifest.
2. Waits until the ingress controller pod is fully initialized, running, and in the `Ready` condition.

### Why it is needed:
- Kubernetes does not provide an ingress routing daemon by default. `ingress-nginx` acts as the reverse proxy that reads `Ingress` resources, parses incoming HTTP `Host` headers (e.g. `grafana.local`), and routes requests to the correct internal ClusterIP services.
- The `wait` command ensures that the ingress admission webhooks and controller daemon are active before subsequent steps attempt to create ingress rules or send HTTP traffic.

```bash
# 1. Apply the kind-tailored ingress-nginx manifest (configures hostPorts and tolerations)
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml

# 2. Block until the ingress-nginx controller pod is fully Ready (or timeout after 3 minutes)
kubectl -n ingress-nginx wait --for=condition=ready pod \
  -l app.kubernetes.io/component=controller --timeout=180s
```

---

## 3. Helm repos

### What it does:
Registers the upstream Helm package repositories for Prometheus Community, Jaeger Tracing, and Jetstack (cert-manager), then pulls down the latest chart index metadata.

### Why it is needed:
- Helm requires repository registration to locate, fetch, and verify packaged Kubernetes applications and their dependencies.
- Running `helm repo update` ensures that your local Helm cache contains the latest index records for chart versions such as `kube-prometheus-stack` (`91.9.0`) and `jaeger-operator` (`2.57.0`).

```bash
# Add the Prometheus Community repository (kube-prometheus-stack, node-exporter, etc.)
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts

# Add the Jaeger Tracing repository (jaeger-operator, jaeger)
helm repo add jaegertracing https://jaegertracing.github.io/helm-charts

# Add the Jetstack repository (cert-manager for TLS and webhooks)
helm repo add jetstack https://charts.jetstack.io

# Synchronize and update local chart metadata caches from all configured repos
helm repo update
```

---

## 4. Prometheus and Grafana

### What it does:
1. Creates a `prometheus-values.yaml` file that pre-configures Grafana with an automated Jaeger data source.
2. Creates the dedicated `monitoring` namespace.
3. Installs `kube-prometheus-stack` (deploying Prometheus Operator, Prometheus server, Alertmanager, Grafana, and node-exporter).
4. Retrieves and base64-decodes the default Grafana administrator credentials.

### Why it is needed:
- **`kube-prometheus-stack`**: Provides an end-to-end monitoring solution pre-configured with Kubernetes cluster metric scrapers, default alerting rules, and Grafana dashboards.
- **`additionalDataSources`**: Automating the Jaeger data source definition within Grafana's values eliminates the need to manually log in and configure Jaeger endpoints in the Grafana UI every time the cluster is recreated.
- **Cluster-internal DNS (`http://simplest-query.observability.svc.cluster.local:16686`)**: Allows Grafana (in `monitoring`) to securely query the Jaeger Query service (in `observability`) over Kubernetes internal DNS.

Save as `prometheus-values.yaml`:

```yaml
# prometheus-values.yaml
# Custom Helm values overriding defaults for kube-prometheus-stack
grafana:
  # Automatically provision additional data sources inside Grafana on startup
  additionalDataSources:
  - name: Jaeger                                                          # Display name in Grafana UI
    type: jaeger                                                          # Data source plugin type
    access: proxy                                                         # Proxy queries through Grafana backend
    url: http://simplest-query.observability.svc.cluster.local:16686      # Cluster-internal DNS to Jaeger Query
```

Deploy the Prometheus & Grafana stack:

```bash
# 1. Create the dedicated monitoring namespace
kubectl create namespace monitoring

# 2. Install kube-prometheus-stack using our custom values file
helm install prometheus prometheus-community/kube-prometheus-stack \
  --version 91.9.0 \
  -n monitoring \
  -f prometheus-values.yaml

# 3. Check deployment status of all monitoring components
kubectl -n monitoring get pods

# 4. Extract and decode the auto-generated Grafana admin password
# Username: admin
echo -n "Grafana Admin Password: "
kubectl -n monitoring get secret prometheus-grafana \
  -o jsonpath='{.data.admin-password}' | base64 -d
echo ""
```

---

## 5. cert-manager

### What it does:
1. Installs `cert-manager` into the `cert-manager` namespace.
2. Automatically installs cert-manager Custom Resource Definitions (CRDs) via `--set crds.enabled=true`.
3. Waits for all cert-manager controller, webhook, and CA-injector pods to enter the `Ready` state.

### Why it is needed:
- The Jaeger Operator utilizes Kubernetes **Validating and Mutating Admission Webhooks** to validate `Jaeger` custom resources and automatically inject tracing sidecar containers into application pods.
- Admission webhooks in Kubernetes mandate valid TLS certificates trusted by the API server. `cert-manager` automates the provisioning, rotation, and CA injection of internal TLS certificates for the Jaeger webhook.
- **Must be installed and ready before the Jaeger operator**: If `cert-manager` is missing or not ready when the Jaeger operator starts, the operator webhook will fail, causing pod crash loops or preventing `Jaeger` resources from being created.

```bash
# 1. Install cert-manager with CRDs enabled in a new namespace
helm install cert-manager jetstack/cert-manager \
  -n cert-manager \
  --create-namespace \
  --set crds.enabled=true

# 2. Block until all cert-manager pods (controller, webhook, cainjector) are Ready
kubectl -n cert-manager wait --for=condition=ready pod --all --timeout=180s
```

---

## 6. Jaeger operator

### What it does:
1. Creates the `observability` namespace.
2. Deploys `jaeger-operator` Helm chart with cluster-wide role-based access control (`rbac.clusterRole=true`).
3. Waits until the Jaeger Operator controller pod is running and ready.

### Why it is needed:
- The **Jaeger Operator** extends the Kubernetes API with custom resources (`Jaeger`) and automates the lifecycle, deployment, and management of Jaeger tracing components.
- **`rbac.clusterRole=true`**: Grants the operator cluster-wide permissions so it can watch `Jaeger` resources and inject Jaeger agent sidecar containers into application pods residing in *any* namespace across the cluster.

```bash
# 1. Create the dedicated observability namespace
kubectl create namespace observability

# 2. Install the jaeger-operator Helm chart
helm install jaeger-operator jaegertracing/jaeger-operator \
  --version 2.57.0 \
  -n observability \
  --set rbac.clusterRole=true

# 3. Wait until the Jaeger operator pod is Ready
kubectl -n observability wait --for=condition=ready pod \
  -l app.kubernetes.io/name=jaeger-operator --timeout=180s
```

---

## 7. Jaeger instance

### What it does:
1. Applies a custom resource of `kind: Jaeger` named `simplest`.
2. Employs the `allInOne` deployment strategy with ephemeral in-memory storage.
3. Explicitly disables the operator's built-in automatic ingress generation (`spec.ingress.enabled: false`).
4. Creates three internal Kubernetes services: `simplest-query`, `simplest-collector`, and `simplest-agent`.

### Why it is needed:
- **`simplest` (all-in-one)**: Packages the collector, query engine, UI, and in-memory trace storage into a single lightweight pod. This is optimal for development, coursework, and local testing because it avoids the overhead of managing distributed databases (Elasticsearch/Cassandra).
- **`spec.ingress.enabled: false`**: The operator's default ingress generator may produce conflicts with our unified custom Ingress manifests or use incompatible annotations. Disabling it allows us to define a clean, explicit Ingress rule in Step 8.
- **Ephemeral Storage Notice**: Traces remain in memory and are discarded whenever the `simplest` pod restarts.

```bash
# Apply the Jaeger Custom Resource definition to the observability namespace
kubectl apply -n observability -f - <<EOF
apiVersion: jaegertracing.io/v1
kind: Jaeger
metadata:
  name: simplest
spec:
  # The default strategy is 'allInOne' (query + collector + in-memory store in one pod)
  strategy: allInOne
  # Disable automatic operator-managed ingress; we create our own custom ingress in Step 8
  ingress:
    enabled: false
EOF

# Verify that the Jaeger custom resource was accepted and processed
kubectl -n observability get jaegers

# Check the created Jaeger services and their ports
kubectl -n observability get svc -l app.kubernetes.io/instance=simplest
```

### Services Created by Jaeger:

| Service Name | Port(s) | Protocol | Purpose |
|---|---|---|---|
| `simplest-query` | `16686` | HTTP | Jaeger UI and Query API |
| `simplest-collector` | `4317` (gRPC), `4318` (HTTP)<br>`14268` (HTTP), `14250` (gRPC), `9411` (Zipkin) | OTLP / Jaeger | Ingests trace spans exported by instrumented applications |
| `simplest-agent` | `6831`, `6832` | UDP | Legacy Jaeger agent compact/binary Thrift protocol |

---

## 8. Ingress

### What it does:
1. Creates `ingress.yaml` defining HTTP routing rules for all three web interfaces:
   - `observability-ingress` in the `monitoring` namespace (routing `grafana.local` to Grafana and `prometheus.local` to Prometheus).
   - `jaeger-ingress` in the `observability` namespace (routing `jaeger.local` to the `simplest-query` UI).
2. Sets `nginx.ingress.kubernetes.io/ssl-redirect: "false"` to prevent unwanted HTTPS redirects on local HTTP connections.
3. Guides mapping local domain names in `/etc/hosts`.

### Why it is needed:
- **Namespace-scoped Ingress**: In Kubernetes, an `Ingress` resource can only route traffic to `Service` objects located within the **exact same namespace**. Therefore, two separate Ingress resources are created: one in `monitoring` and one in `observability`.
- **Host-based Routing**: Allows using clean, memorable local domain names (`grafana.local`, `prometheus.local`, `jaeger.local`) on standard HTTP port 80 instead of managing multiple non-standard port numbers.
- **`ssl-redirect: "false"`**: In local development environments without TLS certificates configured on ingress hosts, NGINX would otherwise return 308 redirects to HTTPS port 443.

Save as `ingress.yaml`:

```yaml
# ingress.yaml
# Ingress routing rules for Monitoring and Observability suites

# 1. Ingress for services in the 'monitoring' namespace
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: observability-ingress
  namespace: monitoring
  annotations:
    # Disable automatic redirect to HTTPS for local HTTP development
    nginx.ingress.kubernetes.io/ssl-redirect: "false"
spec:
  ingressClassName: nginx
  rules:
  # Route grafana.local -> prometheus-grafana:80
  - host: grafana.local
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: prometheus-grafana
            port:
              number: 80
  # Route prometheus.local -> prometheus-kube-prometheus-prometheus:9090
  - host: prometheus.local
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: prometheus-kube-prometheus-prometheus
            port:
              number: 9090
---
# 2. Ingress for services in the 'observability' namespace
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: jaeger-ingress
  namespace: observability
  annotations:
    # Disable automatic redirect to HTTPS for local HTTP development
    nginx.ingress.kubernetes.io/ssl-redirect: "false"
spec:
  ingressClassName: nginx
  rules:
  # Route jaeger.local -> simplest-query:16686 (Jaeger UI)
  - host: jaeger.local
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: simplest-query
            port:
              number: 16686
```

Apply the ingress rules:

```bash
# 1. Apply both Ingress resources to the cluster
kubectl apply -f ingress.yaml

# 2. Inspect Ingress resources across all namespaces to verify hosts and backends
kubectl get ingress -A
```

### Configure Local Hostnames (`/etc/hosts`)

### What it does:
Maps `grafana.local`, `prometheus.local`, and `jaeger.local` to loopback address `127.0.0.1` so that your web browser resolves these domains to your local host (where kind's port 80 mapping listens).

### Why it is needed:
Operating system DNS resolvers do not recognize `.local` domains out of the box. Adding static entries to `/etc/hosts` resolves requests locally without requiring an external DNS server.

Add the following line to `/etc/hosts` (Linux / macOS / WSL) or `C:\Windows\System32\drivers\etc\hosts` (Windows):

```text
127.0.0.1 grafana.local prometheus.local jaeger.local
```

Quick command for Linux / WSL:
```bash
# Append host entries to /etc/hosts (requires sudo)
echo "127.0.0.1 grafana.local prometheus.local jaeger.local" | sudo tee -a /etc/hosts
```

---

## 9. Verify

### What it does:
1. Verifies that all pods across the cluster are in the `Running` state.
2. Performs automated HTTP checks via `curl` simulating incoming HTTP `Host` headers.
3. Guides manual UI validation in your web browser.

### Why it is needed:
- `curl` testing with explicit `-H "Host: ..."` confirms that the NGINX Ingress controller and backend services are communicating properly independent of local browser caching or OS DNS configuration.

```bash
# 1. Check all pods across the entire cluster; all should show Running or Completed
kubectl get pods -A

# 2. Check pods specifically in monitoring and observability namespaces
kubectl -n monitoring get pods
kubectl -n observability get pods

# 3. Test Ingress endpoints via curl; expected response is HTTP 200 or 302
echo -n "grafana.local:    " && curl -s -o /dev/null -w "%{http_code}\n" -H "Host: grafana.local"    http://localhost/
echo -n "prometheus.local: " && curl -s -o /dev/null -w "%{http_code}\n" -H "Host: prometheus.local" http://localhost/
echo -n "jaeger.local:     " && curl -s -o /dev/null -w "%{http_code}\n" -H "Host: jaeger.local"     http://localhost/
```

### Browser Verification:
- **`http://grafana.local`**:
  - Log in using username `admin` and the password retrieved in **Step 4**.
  - Navigate to **Connections → Data sources** and confirm the **Jaeger** data source is listed and healthy.
- **`http://prometheus.local`**:
  - Navigate to **Status → Targets** to verify that Prometheus is actively scraping Kubernetes components and node metrics.
- **`http://jaeger.local`**:
  - The Jaeger UI will open. The *Service* dropdown will remain empty until an application begins exporting trace spans.

---

## 10. Sending traces from your apps

### What it does:
Explains how to connect application workloads to the Jaeger collector using either direct OpenTelemetry Protocol (OTLP) endpoints or automatic Jaeger agent sidecar injection.

### Why it is needed:
- **OpenTelemetry (OTLP)** is the vendor-neutral cloud standard for distributed tracing. Modern instrumented applications export spans over standard HTTP or gRPC endpoints.
- **Sidecar injection** is useful for applications instrumented with legacy Jaeger client libraries that expect a local agent listening on UDP `localhost:6831`.

### Option A: OpenTelemetry (OTLP) Direct Export (Recommended)

Configure your application's OpenTelemetry SDK with the internal cluster DNS endpoint of the `simplest-collector` service:

| Protocol | Cluster Internal Endpoint | SDK Environment Variable | Notes |
|---|---|---|---|
| **OTLP / HTTP** | `http://simplest-collector.observability.svc.cluster.local:4318` | `OTEL_EXPORTER_OTLP_ENDPOINT="http://simplest-collector.observability.svc.cluster.local:4318"` | Append `/v1/traces` if your SDK does not auto-append paths |
| **OTLP / gRPC** | `simplest-collector.observability.svc.cluster.local:4317` | `OTEL_EXPORTER_OTLP_ENDPOINT="http://simplest-collector.observability.svc.cluster.local:4317"` | Standard high-performance binary transport |

### Option B: Automatic Jaeger Agent Sidecar Injection

### What it does:
Instructs the Jaeger Operator admission webhook to automatically inject a Jaeger agent container into your application pod at deploy time.

### Why it is needed:
Applications using older Jaeger client libraries send traces via UDP to `localhost:6831`. The sidecar container receives these local UDP packets and batches/forwards them to the central collector over TCP.

Add the `sidecar.jaegertracing.io/inject` annotation to the **pod template** (`spec.template.metadata.annotations`):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sample-app
  namespace: observability  # Must be deployed in the same namespace as the Jaeger CR
spec:
  replicas: 1
  selector:
    matchLabels:
      app: sample-app
  template:
    metadata:
      labels:
        app: sample-app
      annotations:
        # Injects the Jaeger agent sidecar container targeting the 'simplest' Jaeger instance
        sidecar.jaegertracing.io/inject: "simplest"
    spec:
      containers:
      - name: sample-app
        image: your-app-image:latest
        env:
        # App sends spans to the local sidecar container over localhost UDP
        - name: JAEGER_AGENT_HOST
          value: "localhost"
        - name: JAEGER_AGENT_PORT
          value: "6831"
```

---

## Troubleshooting

| Symptom | Probable Cause | Diagnostic Command / Resolution |
|---|---|---|
| `*.local` cannot be resolved in browser | Host `/etc/hosts` missing entry or DNS cache stale | Verify `/etc/hosts` has `127.0.0.1 grafana.local prometheus.local jaeger.local`. Test with `ping -c 1 grafana.local`. |
| Ingress returns `404 Not Found` | Ingress resource backend service name or port mismatch | Run `kubectl get ingress -A` and `kubectl describe ingress <name> -n <namespace>` to verify target service name and port. |
| Ingress returns `503 Service Unavailable` | Backend pods are not running or endpoints are not ready | Run `kubectl -n monitoring get endpoints` and ensure backend pods have passed readiness probes. |
| Connection refused to `localhost:80` | `kind` cluster not running or port 80 was occupied on the host | Verify `docker ps` displays `0.0.0.0:80->80/tcp` on the control-plane container. |
| Jaeger Operator fails to start / crash loops | `cert-manager` webhook is not ready or CRDs missing | Cert-manager must be running first (Step 5). Run `kubectl -n cert-manager get pods` and check logs with `kubectl -n observability logs deploy/jaeger-operator`. |
| Grafana has no Jaeger data source | `prometheus-values.yaml` was not supplied during Helm install | Run `helm upgrade prometheus prometheus-community/kube-prometheus-stack -n monitoring -f prometheus-values.yaml`, or add the data source manually in Grafana UI. |
| Sidecar not injected into pod (`1/1` instead of `2/2`) | Annotation missing, placed under deployment metadata instead of pod template, or namespace mismatch | Ensure annotation is under `spec.template.metadata.annotations`, and the deployment is in the same namespace as the `Jaeger` custom resource (`observability`). |
| Ingress conflicts or unexpected routes | The operator's automatic ingress was not disabled | Verify `spec.ingress.enabled: false` is set in the `Jaeger` custom resource (Step 7). Run `kubectl -n observability get ingress` to inspect. |

---

## Cleanup

### What it does:
Deletes the local `kind` cluster along with all associated containers, volumes, namespaces, and configurations.

### Why it is needed:
Reclaims local host memory, CPU, and network ports (80 and 443) when you are finished testing or need to restart from a clean slate.

```bash
# Delete the entire kind cluster and associated Docker resources
kind delete cluster --name kind-cloud-observ-project

# (Optional) Remove the static host entries from /etc/hosts
sudo sed -i '/grafana.local prometheus.local jaeger.local/d' /etc/hosts
```
