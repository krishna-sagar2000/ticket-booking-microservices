-- booking_db has no seed data: bookings are created only through POST /api/v1/bookings,
-- because every booking must have a matching hold in the Seat service.
-- Seats and events are seeded by the Seat service (seat-service/seed.sql).
SELECT 'booking_db: nothing to seed' AS info;
