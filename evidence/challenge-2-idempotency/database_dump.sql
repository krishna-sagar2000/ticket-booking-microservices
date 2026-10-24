-- Challenge 2 idempotency evidence database snapshot
-- Snapshot of rows whose booking/key starts with challenge2-.

-- payments rows
INSERT INTO payments (id, booking_id, amount, status, created_at) VALUES ('4', 'challenge2-replay-001', '500.00', 'CONFIRMED', '2026-10-24 14:51:43');
INSERT INTO payments (id, booking_id, amount, status, created_at) VALUES ('5', 'challenge2-different-001', '500.00', 'CONFIRMED', '2026-10-24 14:51:43');
INSERT INTO payments (id, booking_id, amount, status, created_at) VALUES ('6', 'challenge2-race-001', '700.00', 'CONFIRMED', '2026-10-24 14:51:43');

-- idempotency_keys rows
INSERT INTO idempotency_keys (idem_key, request_hash, status, response_code, response_body, created_at) VALUES ('challenge2-different-key', '094cfd19760f2d3ae44fbd1c8d13be9e8792edee26e12396dc7cc133edfaac5f', 'DONE', '201', '{"amount": "500.00", "status": "APPROVED", "bookingId": "challenge2-different-001"}', '2026-10-24 14:51:43');
INSERT INTO idempotency_keys (idem_key, request_hash, status, response_code, response_body, created_at) VALUES ('challenge2-race-key', 'e07822823456fd365d47e88abdaf36f69ff6f47e6787660fdadcaef5ff4e4dce', 'DONE', '201', '{"amount": "700.00", "status": "APPROVED", "bookingId": "challenge2-race-001"}', '2026-10-24 14:51:43');
INSERT INTO idempotency_keys (idem_key, request_hash, status, response_code, response_body, created_at) VALUES ('challenge2-replay-key', 'd18c22d3d3fa7ec7a4181796549ab1057bd56a6fc2ae8f89614c38e8648c6a61', 'DONE', '201', '{"amount": "500.00", "status": "APPROVED", "bookingId": "challenge2-replay-001"}', '2026-10-24 14:51:43');
