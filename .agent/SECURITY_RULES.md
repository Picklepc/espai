# Security Rules

## Device Security
- View-only discovery is allowed.
- Control requires pairing.
- OTA requires pairing, checksum, compatibility, confirmation, and audit log.
- Dangerous actions require confirmation.

## Worker Security
Worker lifecycle:
1. imported
2. quarantined
3. reviewed
4. trusted locally
5. enabled per project

Workers declare filesystem, network, secret, runtime, memory, and disk permissions.

## Recipe Security
Sanitize exports to remove MACs, serials, Wi-Fi names, GPS data, pairing pins, API keys, owner notes, and private captures.
