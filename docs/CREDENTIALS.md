# Credential Management

> **Status:** Planned — not yet implemented

Tasks that require authentication (calendar sync, email, APIs with keys) need secure credential storage. This document describes the planned architecture.

## Architecture

### Master Keys (asymmetric, long-lived)

Located in `~/.outheis/human/keys/`:

```
keys/
├── signing.key        # Ed25519 private key — signs session keys
├── signing.pub        # Ed25519 public key
├── encryption.key     # X25519 private key — encrypts session keys  
├── encryption.pub     # X25519 public key
└── README.md          # This file (warning not to share)
```

Generated once during `outheis init` (or on first task requiring auth).

### Session Keys (symmetric, short-lived)

Located in `~/.outheis/human/keys/sessions/`:

```
sessions/
├── 2026-03.key.enc    # AES-256 key, encrypted with encryption.pub
├── 2026-03.key.sig    # Signature from signing.key
├── 2026-04.key.enc    # Next month's key (pre-generated)
└── 2026-04.key.sig
```

- Rotated monthly
- Old credentials re-encrypted with new session key during rotation
- Rotation runs as scheduled task (Pattern agent? Dedicated task?)

### Task Credentials

Each task with auth has:

```
tasks/<task-id>/
├── directive.md
├── config.json
└── credentials.enc    # Encrypted with current session key
```

## Key Operations

### Generation (outheis init)

```bash
# Signing key (Ed25519)
ssh-keygen -t ed25519 -f ~/.outheis/human/keys/signing -N ""

# Encryption key (X25519 via OpenSSL or age)
# Option A: Use age (simpler)
# Option B: Use OpenSSL + X25519
# Option C: Use Python cryptography library
```

### Encryption Flow

1. Load current session key
2. Decrypt session key using encryption.key
3. Verify session key signature using signing.pub
4. Encrypt credentials with session key (AES-256-GCM)
5. Store as credentials.enc

### Decryption Flow (task execution)

1. Load credentials.enc from task directory
2. Load current session key
3. Decrypt session key
4. Decrypt credentials
5. Use credentials for task
6. Clear from memory

## Rotation

Monthly scheduled task:

1. Generate new session key
2. Encrypt with encryption.pub
3. Sign with signing.key
4. Re-encrypt all credentials.enc files with new key
5. Keep previous month's key for rollback (delete after 2 months)

## Security Considerations

- Master keys never leave the machine
- Session keys limit exposure window
- Memory cleared after use
- No credentials in logs
- Permissions: 600 for all key files

## Workaround (until implemented)

For tasks requiring auth, use environment variables:

```bash
export CALENDAR_USER="markus"
export CALENDAR_PASS="secret"
```

Task reads from env if credentials.enc not present.

## Implementation Plan

1. [ ] Key generation in `outheis init`
2. [ ] Session key creation/rotation
3. [ ] Encrypt/decrypt module
4. [ ] Task credential storage
5. [ ] Rotation scheduler
6. [ ] Migration for existing tasks
