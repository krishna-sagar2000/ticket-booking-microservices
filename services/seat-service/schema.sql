-- seat_db schema. Applied by the service on startup (app/db.py: init_db), safe to run again.
-- Manual: docker exec -i ticket-mysql mysql -u seat_user -pseat_pass seat_db < schema.sql

CREATE TABLE IF NOT EXISTS events (
    id        INT          NOT NULL PRIMARY KEY,
    name      VARCHAR(100) NOT NULL,
    starts_at DATETIME     NOT NULL
);

-- One row per seat of an event. (event_id, seat_no) is the seat's identity, so the same
-- seat can never exist twice. booking_id is Booking's id, stored as a plain value: no
-- foreign key across services.
CREATE TABLE IF NOT EXISTS seats (
    event_id        INT         NOT NULL,
    seat_no         VARCHAR(10) NOT NULL,
    status          VARCHAR(10) NOT NULL DEFAULT 'AVAILABLE',
    booking_id      VARCHAR(64) NULL,
    hold_expires_at DATETIME    NULL,
    PRIMARY KEY (event_id, seat_no),
    CONSTRAINT fk_seats_event FOREIGN KEY (event_id) REFERENCES events (id),
    CONSTRAINT ck_seats_status CHECK (status IN ('AVAILABLE', 'HELD', 'SOLD'))
);
