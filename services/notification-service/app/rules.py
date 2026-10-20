"""Business rules for this service live here (one function per rule).

Tag every rule with its id, for example:
    # BR1: a seat belongs to one booking at a time
and write a test named test_BR1_... so the report can trace rule -> code -> test.

notification-service does not own any of BR1-BR4 (those belong to seat,
booking and payment services). This service only validates the shape of
incoming notification requests before they are persisted.
"""

KNOWN_TYPES = {
    "BOOKING_CONFIRMED",
    "BOOKING_CANCELLED",
    "BOOKING_EXPIRED",
}


def validate_type(notification_type: str) -> bool:
    """Returns True if notification_type is a non-empty, reasonably short
    string. We intentionally do NOT hard-reject unknown values outside
    KNOWN_TYPES, because booking-service (owned by another team member) may
    introduce new notification types later - we only guard against empty or
    malformed input here. KNOWN_TYPES documents the types we expect today.
    """
    return isinstance(notification_type, str) and 0 < len(notification_type) <= 64
