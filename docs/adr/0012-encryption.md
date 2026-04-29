# ADR-0012: Symmetric encryption primitive

## Status

Accepted. The `pylar/encryption/` module has shipped; this ADR
documents the choice retrospectively so the rationale lives next to
the other foundational decisions.

## Context

Three parts of the framework need to symmetrically encrypt small
blobs of bytes at rest:

1. **Signed cookies** — `EncryptCookiesMiddleware` wraps every
   outgoing cookie (except session + CSRF, which are signed
   separately) in an AEAD envelope so a stolen cookie jar on a
   shared browser leaks nothing legible, and a tampered cookie is
   rejected on the way back in.
2. **Token storage at rest** — API tokens from ADR-0009 are stored
   hashed, but some adjacent data (e.g. push-notification
   credentials the app stores on behalf of users) legitimately
   needs to be recoverable. A symmetric primitive is the correct
   tool.
3. **Application secrets in config** — config files loaded from a
   deploy bundle sometimes need to carry encrypted values (S3
   secret keys, third-party API keys) rather than plaintext.

Laravel solves all three with one module
(`Illuminate\Encryption\Encrypter`) keyed on a single `APP_KEY`.
The operational story is: one `php artisan key:generate` at project
init, one env var to roll, nothing else to manage.

Pylar deliberately matched that story before this ADR was written
(see `pylar/encryption/` and `pylar-framework/docs/site/security/encryption.md`)
but never recorded *why* that shape was chosen. This ADR captures
the decision so the operational contract (key format, rotation
policy, algorithm choice) cannot silently drift.

## Decision

### Algorithm: AES-256-GCM

Authenticated encryption with associated data (AEAD). GCM gives us:

- **Confidentiality** via AES-256.
- **Integrity + authenticity** via the 16-byte tag appended to
  every ciphertext. A tampered byte fails the tag check and
  `decrypt()` raises `DecryptionError` before returning anything.
- **Nonce misuse resistance is not* a goal** — we rely on fresh
  random 12-byte nonces per encryption instead. That is the
  standard GCM envelope and matches Laravel's default (OpenSSL's
  `aes-256-gcm` cipher with random nonces).

Rejected alternatives:

- **Fernet / AES-256-CBC + HMAC**: historically safe but imposes
  two keys (encryption + MAC) or a key-derivation step, which
  complicates key rotation.
- **ChaCha20-Poly1305**: equally good cryptographically; we chose
  AES-GCM because it matches the Laravel key format precisely
  (`base64:<32 bytes>`), which means operators moving between
  frameworks do not have to relearn the env-var contract.
- **NaCl / libsodium**: extra C dependency; `cryptography` is
  already in the dependency tree for password hashing.

### Library: `cryptography` (pyca)

The `cryptography` package is already a transitive dependency via
`argon2-cffi` / `passlib` in the auth module. Reusing it avoids a
second C-extension install and keeps all crypto in one maintained
audited codebase. We use
`cryptography.hazmat.primitives.ciphers.aead.AESGCM` directly
because it:

- enforces the 12-byte nonce length via its constructor;
- handles the tag concatenation so there is one blob to persist;
- raises `InvalidTag` on tampered ciphertext rather than silently
  returning garbage.

### Key format: `base64:` prefix

Keys are represented as `base64:<44 ASCII chars>` where the base64
body decodes to exactly 32 bytes. The prefix:

- matches Laravel's convention pixel-for-pixel, so operators
  recognise the format;
- lets `Encrypter.key_from_string()` surface a helpful error when
  someone pastes a plain string by mistake (`"APP_KEY must be
  base64-encoded…"`);
- leaves room to add other prefixes later (`pem:`, `kms:`) without
  a breaking change.

### Envelope layout

`encrypt()` returns a URL-safe base64 string of:

```
nonce (12 bytes) || ciphertext || tag (16 bytes)
```

One blob, one base64 decode, one `AESGCM.decrypt()` call. The
12-byte nonce is generated via `os.urandom` on every call — the
same plaintext therefore never produces the same ciphertext, so an
attacker cannot correlate two encrypted cookies that happen to
hold the same session state.

### CLI surface: `pylar key:generate`

One command, zero arguments. Emits `base64:<fresh 32 bytes>` on
stdout. The operator copies the value into `.env` under the
`APP_KEY` variable. There is **no** `key:rotate` command in the
first iteration — rotation is a Phase 2 concern that needs a
documented dual-key window; see the Future section below.

### Failure mode: `DecryptionError`

Every decryption path raises `pylar.encryption.exceptions.DecryptionError`
on:

- malformed base64;
- ciphertext shorter than `nonce + tag` (12 + 16 = 28 bytes);
- tag mismatch (tampered or wrong key).

Callers catch that one class and treat it as "the value was not
written by us" without having to distinguish sub-reasons. The
error does *not* include the ciphertext in its string to avoid
leaking partial plaintext through logs.

## Consequences

### Positive

- One obvious primitive for every symmetric-at-rest use case; no
  two-library sprawl.
- Laravel-compatible key format means existing docs, blog posts,
  and operator muscle memory carry over.
- AEAD means the middleware and token-storage consumers never have
  to add their own integrity layer.

### Negative

- `cryptography` ships as a wheel per platform; on exotic targets
  (alpine ARM, old PPC) a source build is needed.
- No native kernel acceleration in pure-Python fallback; fine for
  cookie-sized blobs, not intended for bulk data encryption.

### Out of scope

- **Asymmetric encryption** (RSA, Ed25519). Use
  `cryptography.hazmat` directly — pylar does not wrap it because
  key management for asymmetric pairs is a different problem
  (provisioning, rotation, trust).
- **Key rotation via dual keys**. A future `APP_KEY_OLD` env var
  would let `decrypt()` try both keys and `encrypt()` always use
  the new one. Deferred until someone actually hits the operational
  need.
- **KMS / HSM integration**. A pluggable `KeyProvider` would let
  `Encrypter` pull its key from AWS KMS / GCP KMS / HashiCorp Vault
  rather than `APP_KEY`. Designed for a separate ADR when there is
  a real request.
- **Asymmetric JWT signing**. Out of scope; API tokens from
  ADR-0009 use opaque random strings with server-side lookup,
  which is simpler and revocable.

## References

- `pylar-framework/pylar/encryption/encrypter.py` — the 128-line
  implementation.
- `pylar-framework/pylar/encryption/commands.py` — `pylar key:generate`.
- `pylar-framework/pylar/http/middlewares/encrypt_cookies.py` — first
  consumer.
- `pylar-framework/docs/site/security/encryption.md` — end-user docs.
- [Laravel: Encryption](https://laravel.com/docs/11.x/encryption) —
  the ergonomic contract we match.
