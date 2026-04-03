---
title: API Authentication Patterns
tags: [reference, technical, security]
created: 2025-03-15
---

# API Authentication Patterns

Quick reference for common auth patterns.

## JWT (JSON Web Tokens)

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

- Stateless
- Contains claims (user id, roles, expiry)
- Verify signature, check expiry
- Refresh tokens for long sessions

## API Keys

```
X-API-Key: sk_live_abc123...
```

- Simple, good for server-to-server
- Store hashed, never log
- Rotate regularly

## OAuth 2.0 Flows

| Flow | Use Case |
|------|----------|
| Authorization Code | Web apps with backend |
| PKCE | Mobile/SPA |
| Client Credentials | Service-to-service |

## Best Practices

- Always HTTPS
- Rate limiting
- Audit logging
- Key rotation policy
