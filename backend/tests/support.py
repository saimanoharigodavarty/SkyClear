"""Accounts that exist only while the tests run. Nothing here is used by the app."""
ADMIN_EMAIL = "admin@test.local"
PASSWORD = "Test-pass-12345"


def officer_email(authority_id):
    return f"{authority_id.lower()}@officers.test.local"
