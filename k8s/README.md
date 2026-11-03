# Kubernetes / Minikube deployment (Assignment 2, Part B)

This folder deploys the exact same system as the root `docker-compose.yml`, translated
to Kubernetes: one Namespace, a MySQL StatefulSet (with a PersistentVolumeClaim and the
same `init.sql` the Docker Compose setup uses), and one Deployment + Service per
microservice.

Docker Compose's `depends_on: condition: service_healthy` has no direct Kubernetes
equivalent, so each service that needs something else to be ready first uses an
`initContainer` that loops until the dependency answers, then exits - only then does
the real application container start. Booking-service (the orchestrator) waits on
MySQL and on Seat, Payment and Notification being ready, the same ordering the
Compose file expresses.

## Files, in the order they should be applied

| File | What it creates |
|---|---|
| `00-namespace.yaml` | the `ticket-booking` namespace everything else lives in |
| `01-mysql-configmap.yaml` | `init.sql` as a ConfigMap, mounted into MySQL's init directory |
| `02-mysql.yaml` | MySQL StatefulSet + PVC + headless Service |
| `03-mock-gateway.yaml` | mock-gateway Deployment + Service (no DB dependency) |
| `04-seat-service.yaml` | seat-service Deployment (waits for MySQL) + Service (NodePort) |
| `05-payment-service.yaml` | payment-service Deployment (waits for MySQL) + Service |
| `06-notification-service.yaml` | notification-service Deployment (waits for MySQL) + Service |
| `07-booking-service.yaml` | booking-service Deployment (waits for MySQL + Seat + Payment + Notification) + Service (NodePort) |

## One-time setup

### 1. Install Minikube
Windows (with Chocolatey):
```
choco install minikube
```
Or download the installer directly from https://minikube.sigs.k8s.io/docs/start/

`kubectl` may already be installed separately; if not:
```
choco install kubernetes-cli
```

### 2. Start Minikube
On Windows, the default driver Minikube picks (VirtualBox) needs hardware
virtualisation (VT-x/AMD-V) enabled in the BIOS, which is often off on laptops by
default and gives a `HOST_VIRT_UNAVAILABLE` error. Since Docker Desktop is already
required for this project, use the `docker` driver instead - no BIOS changes needed:
```
minikube start --driver=docker
```
Make sure Docker Desktop is running first. First start downloads a ~500 MB base
image and can take a few minutes; this only happens once.

### 3. Build the five application images, then load them into Minikube
Minikube runs its own internal container runtime, separate from your normal `docker`
command, so images built normally are not automatically visible to it. The
officially documented way to bridge this is `minikube docker-env`, but **on Windows
with Minikube's containerd runtime this currently fails** with
`SSH_AGENT_START: starting an SSH agent on Windows is not yet supported`. Use
`minikube image load` instead, which works reliably: build normally with your usual
Docker daemon, then explicitly copy each image into Minikube.

```
docker build -t ticket-booking/mock-gateway:1.0 services/mock-gateway
docker build -t ticket-booking/seat-service:1.0 services/seat-service
docker build -t ticket-booking/payment-service:1.0 services/payment-service
docker build -t ticket-booking/notification-service:1.0 services/notification-service
docker build -t ticket-booking/booking-service:1.0 services/booking-service

minikube image load ticket-booking/mock-gateway:1.0
minikube image load ticket-booking/seat-service:1.0
minikube image load ticket-booking/payment-service:1.0
minikube image load ticket-booking/notification-service:1.0
minikube image load ticket-booking/booking-service:1.0
```
Verify they landed inside Minikube:
```
minikube image ls | findstr ticket-booking
```

## Deploy

Apply every manifest in this folder, in order:
```
kubectl apply -f k8s/00-namespace.yaml
kubectl apply -f k8s/01-mysql-configmap.yaml
kubectl apply -f k8s/02-mysql.yaml
kubectl apply -f k8s/03-mock-gateway.yaml
kubectl apply -f k8s/04-seat-service.yaml
kubectl apply -f k8s/05-payment-service.yaml
kubectl apply -f k8s/06-notification-service.yaml
kubectl apply -f k8s/07-booking-service.yaml
```
Or apply the whole folder in one command (Kubernetes still creates them in a sensible
order based on dependencies expressed via the init containers):
```
kubectl apply -f k8s/
```

## Verify everything is running

```
kubectl get pods -n ticket-booking
```
Every pod should eventually show `1/1 Running`. The ones with init containers will
show `Init:0/1` or similar for a short while first - that is the wait-for-dependency
loop, not a failure.

```
kubectl get svc -n ticket-booking
```

## Prove the main workflow actually works (not just "pods Running")

`minikube service <name> --url` needs its own long-running terminal window on
Windows with the Docker driver (it prints "the terminal needs to be open to run
it"), which is inconvenient for scripted checks. `kubectl port-forward` is simpler
and works the same way regardless of driver - run each of these in the background
(or in its own terminal window):
```
kubectl port-forward -n ticket-booking svc/booking-service 18001:8001
kubectl port-forward -n ticket-booking svc/seat-service 18002:8002
```
Then, from another terminal:
```
curl http://localhost:18001/health
curl http://localhost:18002/api/v1/events/1/seats
curl -X POST http://localhost:18001/api/v1/bookings -H "Content-Type: application/json" -d "{\"eventId\":1,\"seats\":[\"A1\"],\"customerEmail\":\"k8s-test@example.com\"}"
curl -X POST http://localhost:18001/api/v1/bookings/<bookingId>/pay -H "Idempotency-Key: k8s-test-1"
```
A `201 HELD` followed by a `200 CONFIRMED` proves the whole chain - booking, seat,
payment, mock-gateway, notification - is working through the real Kubernetes
deployment, not just that pods are Running. This exact sequence was run and
verified while building this deployment.

## Logs and troubleshooting

```
kubectl logs -n ticket-booking deployment/booking-service
kubectl describe pod -n ticket-booking <pod-name>
kubectl get events -n ticket-booking --sort-by=.lastTimestamp
```

## Tear down

```
kubectl delete namespace ticket-booking
```
This removes everything created above, including the PersistentVolumeClaim (MySQL
data is lost - re-apply from scratch for a fresh demo).

## Scaling and self-healing (1 more Part B mark - already verified working)

Scale seat-service to 3 replicas and show it still works (seat-service holds no
state in the pod itself, it is all in MySQL, so this is safe):
```
kubectl scale deployment seat-service -n ticket-booking --replicas=3
kubectl get pods -n ticket-booking -l app=seat-service
```

Self-healing: delete a pod and show Kubernetes recreates it automatically:
```
kubectl get pods -n ticket-booking -l app=seat-service
kubectl delete pod -n ticket-booking <one-of-the-seat-service-pod-names>
kubectl get pods -n ticket-booking -l app=seat-service --watch
```
A new pod with a new name appears within seconds, replacing the deleted one.
