# Ticket Booking - Microservices (SEZG583 Assignments 1 & 2)

Four services + a mock payment gateway. Python 3.11+ / FastAPI / MySQL 8. Database per service.

Assignment 1 covers the application itself (see below for local, non-containerised setup).
Assignment 2 covers containerising and deploying the same application with Docker and
Kubernetes (see "Assignment 2: Containerised Deployment" further down).

| Service | Port | Database | Owner |
|---|---|---|---|
| booking-service | 8001 | booking_db | Aishwarya |
| seat-service | 8002 | seat_db | Anwesa |
| payment-service | 8003 | payment_db | Aarzoo |
| notification-service | 8004 | notification_db | Krishna Sagar |
| mock-gateway | 8005 | none | Krishna Sagar |

## First-time setup (everyone)
1. Install Python 3.11+, Git, Docker Desktop.
2. Clone the repo and open it in VS Code.
3. Start the database (once per day):
   ```
   cd scripts/db
   docker compose up -d
   cd ../..
   ```
4. Check the databases: `pip install sqlalchemy pymysql cryptography` then `python scripts/db/check_db.py` (expect 4 x OK).
5. Go to your service folder and follow its README.

## Working rules
- Work on your own branch: `git checkout -b <yourname>/<service>`; small commits under your own name.
- Open a pull request into `main`; your review partner approves it.
- `git pull origin main` every morning.
- Never commit `.env` or real passwords (the passwords here are fake, local only).
- Everything the team agreed is in `docs/shared-contracts.md` and `docs/business-rules.md`.

---

## Assignment 2: Containerised Deployment

Every service has its own `Dockerfile`. All configuration (database URLs, inter-service
URLs, ports, timeouts) is supplied through environment variables at run time - nothing
is hard-coded in any image, and no `.env` file or password is ever copied into an image
(see each service's `.dockerignore`).

### Run everything with Docker Compose (single command)

From the repository root:
```
cp .env.example .env
docker compose up --build
```
This builds all five application images and starts them together with one MySQL
instance (four databases, four users - see `scripts/db/init.sql`). Startup order is
enforced with `depends_on: condition: service_healthy`, so, for example,
booking-service only starts once Seat, Payment, Notification and MySQL are already
healthy.

Useful commands:
```
docker compose ps                       # status/health of every container
docker compose logs -f booking-service  # logs for one service
docker compose down                     # stop everything
docker compose down -v                  # stop everything AND wipe the database volume
```

### Verify the main workflow through the deployed containers

```
curl http://localhost:8002/api/v1/events/1/seats
curl -X POST http://localhost:8001/api/v1/bookings -H "Content-Type: application/json" -d "{\"eventId\":1,\"seats\":[\"A1\"],\"customerEmail\":\"demo@example.com\"}"
curl -X POST http://localhost:8001/api/v1/bookings/<bookingId>/pay -H "Idempotency-Key: demo-1"
```
A `201 HELD` followed by a `200 CONFIRMED` proves booking, seat, payment, the mock
gateway, and notification are all communicating correctly through the deployed
containers.

### Kubernetes / Minikube deployment (optional advanced task)

The same system is also deployable to Kubernetes via Minikube. Manifests, full
install steps, and verification commands (including scaling and self-healing) are
in [`k8s/README.md`](k8s/README.md).

Quick summary once Minikube is installed and running (`minikube start --driver=docker`
on Windows - see `k8s/README.md` if virtualisation/BIOS errors appear):
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

kubectl apply -f k8s/
kubectl get pods -n ticket-booking
```
(`minikube image load` is used instead of `minikube docker-env` because the latter
fails on Windows with the containerd runtime - see `k8s/README.md` for details.)

See `k8s/README.md` for how to reach the services and prove the main workflow works
through the Kubernetes deployment, not just that pods are Running.
