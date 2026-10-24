# Challenge 2 — Payment Idempotency

## Purpose
Demonstrate that the payment service handles repeated and concurrent requests using the same `Idempotency-Key`.

## Prerequisites
- MySQL is running and the `payment_db` schema is initialized.
- Mock payment gateway is running on port 8005.
- Payment service is running on port 8003.
- The repository virtual environment is activated.

## Run the evidence script

From the repository root:

```bash
python evidence/challenge-2-idempotency/challenge_2_idempotency.py
```

The script records responses, checks payment database rows, and writes the output and database snapshot to this directory.

## Scenarios and results

1. **Identical request replay:** Sending the same booking, amount, and idempotency key twice returned HTTP 201 both times with equivalent response bodies.
2. **Different request body:** Reusing an idempotency key with a different amount returned HTTP 422 with `IDEMPOTENCY_KEY_REUSED`.
3. **Concurrent duplicate requests:** Two simultaneous requests with the same key and body resulted in one HTTP 201 response and one HTTP 409 `REQUEST_IN_PROGRESS` response. The second request was rejected while the first was processing.

## Database verification

The captured database results show one payment row for each of the three test bookings. All three rows had status `CONFIRMED`.

## Evidence files

- `challenge_2_idempotency.py` — repeatable evidence script.
- `output.txt` — captured scenario responses and database verification.
- `database_dump.sql` — SQL snapshot of the relevant payment and idempotency records.
- `README.md` — instructions and results.

## Gateway-charge limitation

The script does not directly count calls made by the payment service to the separately running mock gateway. The observed replay behavior and database records support the idempotency result, but gateway logs or gateway-side request counting are needed to independently demonstrate the number of actual charge requests.