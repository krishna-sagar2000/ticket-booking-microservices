# Business rules

| Id | Rule | Service | Error | Test |
|---|---|---|---|---|
| BR1 | A seat belongs to one booking at a time | Seat | 409 SEAT_UNAVAILABLE | test_BR1_seat_cannot_be_held_twice |
| BR2 | A hold expires after 30 s; a paid seat is never released | Seat | - | test_BR2_expired_hold_is_released, test_BR2_paid_seat_is_not_released |
| BR3 | A booking can be paid only while HELD and not expired | Booking | 409 BOOKING_NOT_PAYABLE / HOLD_EXPIRED | test_BR3_cannot_pay_expired_booking |
| BR4 | A payment is applied once per booking | Booking + Payment | 422 / 409 | test_BR4_same_key_returns_same_result, test_BR4_same_key_different_body_rejected |
