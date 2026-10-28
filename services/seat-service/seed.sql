-- Sample data: event 1 with seats A1-A5 and B1-B5, all AVAILABLE.
-- Applied on startup after schema.sql. INSERT IGNORE skips rows that already exist, so a
-- restart never resets seats. To start fresh, see "Reset the seats" in README.md.

INSERT IGNORE INTO events (id, name, starts_at) VALUES
    (1, 'Demo Concert', '2026-11-01 19:00:00');

INSERT IGNORE INTO seats (event_id, seat_no, status) VALUES
    (1, 'A1', 'AVAILABLE'), (1, 'A2', 'AVAILABLE'), (1, 'A3', 'AVAILABLE'), (1, 'A4', 'AVAILABLE'), (1, 'A5', 'AVAILABLE'),
    (1, 'B1', 'AVAILABLE'), (1, 'B2', 'AVAILABLE'), (1, 'B3', 'AVAILABLE'), (1, 'B4', 'AVAILABLE'), (1, 'B5', 'AVAILABLE');
