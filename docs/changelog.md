# Changelog

Project changes are recorded here in reverse chronological order. Entries under **Unreleased** describe work on the current development branch and are not a release announcement. Release numbers and dates will be added when a release is cut.

## Unreleased

### Added

- Authenticated identity and role-scoped API support for landlord, property, unit, and tenant workflows.
- Invoice and ledger read APIs, payment allocation and credit details, and landlord workflows for reviewing and resolving unassigned payments.
- M-Pesa STK request tracking and operator endpoints for querying unresolved request status.
- Durable webhook inbox retry scheduling and replay support for callback processing.
- Outbox event claim handling for worker processing.

### Changed

- M-Pesa callbacks are correlated against an STK request recorded by KodiLedger before they enter the durable webhook inbox.
- Payment and outbox database access is scoped to the permissions required by the application workflows.

### Security

- M-Pesa callback requests support shared-token verification and source-IP allowlisting outside development and test environments.
- Authenticated identity and landlord scope are derived from verified authorization context rather than caller-supplied landlord identifiers.

### Validation status

- The sandbox STK callback flow is still being validated end to end. A successful STK initiation response alone does not confirm payment or callback delivery. See [roadmap.md](roadmap.md) for the current verification steps.

## Changelog conventions

- Keep entries concise and focused on changes that affect users, operators, or integrators.
- Group entries under **Added**, **Changed**, **Fixed**, **Removed**, or **Security** as appropriate.
- Move completed entries from **Unreleased** into a dated, versioned section when a release is published.
