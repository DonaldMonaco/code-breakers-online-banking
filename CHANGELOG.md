# Changelog

## v1.0-uat (baseline for User Acceptance Testing)

- Customer sign-in with password and one-time code; lockout after 5 wrong passwords for 15 minutes
- Accounts page with masked account numbers and balances
- Transaction history filtered by date range
- Transfers between a customer's own accounts: review, confirm, receipt; safe against double submits
- Staff transfer lookup with a required reason and an access log
- Sign-out after 5 minutes without activity; CSRF protection on every form
- Code split into modules (`bank/`), database password read from the environment instead of the code
- 10 automated tests (`tests/`)

### Known limitations for UAT
- The one-time code is shown on screen (demo mode) instead of being sent by text message
- Runs on Flask's built-in development server, for local testing only
