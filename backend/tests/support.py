"""Accounts that exist only while the tests run. Nothing here is used by the app."""
ADMIN_EMAIL = "admin@test.local"
PASSWORD = "Test-pass-12345"


def officer_email(authority_id):
    return f"{authority_id.lower()}@officers.test.local"


_phone = [9000000000]


def next_phone():
    """A fresh 10-digit mobile number. One counter for every test file, so registrations never collide."""
    _phone[0] += 1
    return str(_phone[0])
