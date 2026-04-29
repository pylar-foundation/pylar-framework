# Encryption & Password Hashing

Pylar provides two distinct security primitives: **symmetric encryption** for data at rest (cookies, tokens, secrets) and **password hashing** for credential storage.

## Symmetric Encryption

The `Encrypter` uses AES-256-GCM authenticated encryption keyed by `APP_KEY`. Tampering is detected on decryption.

### Generating a Key

```bash
pylar key:generate
# Outputs: base64:A1B2C3...  (32-byte random key)
```

Set the result as `APP_KEY` in your `.env`. The `base64:` prefix is required.

### Using the Encrypter

```python
from pylar.encryption import Encrypter

# The container wires this automatically from APP_KEY:
encrypter: Encrypter  # declare in __init__

# Encrypt / decrypt raw bytes:
token = encrypter.encrypt(b"secret data")
assert encrypter.decrypt(token) == b"secret data"

# String convenience methods:
token = encrypter.encrypt_string("user-api-key-abc123")
plain = encrypter.decrypt_string(token)
```

Each call generates a fresh random nonce, so the same plaintext never produces the same ciphertext. The output is a URL-safe base64 string containing `nonce (12 bytes) || ciphertext || GCM tag (16 bytes)`.

### Decryption Errors

`DecryptionError` is raised for tampered tokens, wrong keys, or malformed input:

```python
from pylar.encryption import DecryptionError

try:
    encrypter.decrypt(user_supplied_token)
except DecryptionError:
    return JsonResponse({"error": "Invalid token"}, status_code=400)
```

## Password Hashing

Two hashers ship out of the box, both satisfying the `PasswordHasher` protocol:

### Pbkdf2PasswordHasher (default, no extra deps)

```python
from pylar.auth import Pbkdf2PasswordHasher

hasher = Pbkdf2PasswordHasher()  # 600,000 iterations (OWASP 2023)
hashed = hasher.hash("correct-horse-battery-staple")
assert hasher.verify("correct-horse-battery-staple", hashed)
assert not hasher.verify("wrong-password", hashed)
```

Hashes are self-describing strings: `pbkdf2_sha256$600000$salt$hash`. Verification uses constant-time comparison. The constructor refuses fewer than 100,000 iterations.

### Argon2PasswordHasher (opt-in)

```python
# pip install 'pylar[auth]'  -- pulls in argon2-cffi
from pylar.auth import Argon2PasswordHasher

hasher = Argon2PasswordHasher()  # Argon2id, OWASP defaults
hashed = hasher.hash("correct-horse-battery-staple")
assert hasher.verify("correct-horse-battery-staple", hashed)

# Check if stored hash needs re-hashing with updated parameters:
if hasher.needs_rehash(hashed):
    new_hash = hasher.hash(password)
```

Argon2id is the modern recommendation when you can accept a native dependency. Defaults: `time_cost=2`, `memory_cost=19456` KiB, `parallelism=1`. Tune via constructor kwargs.

### Swapping Hashers in the Container

```python
from pylar.auth import PasswordHasher, Argon2PasswordHasher

# In your AuthServiceProvider.register():
container.singleton(PasswordHasher, Argon2PasswordHasher)
```

Controllers and guards declare `hasher: PasswordHasher` and the container resolves the bound implementation.

## Cookie Encryption Middleware

`EncryptCookiesMiddleware` automatically encrypts outgoing cookie values and decrypts incoming ones using the `Encrypter`, so raw values are never visible in browser dev tools:

```python
from pylar.http.middlewares.encrypt_cookies import EncryptCookiesMiddleware

class AppEncryptCookies(EncryptCookiesMiddleware):
    except_cookies = ("analytics_consent",)  # skip these
```

Cookies that fail decryption (tampered or from a rotated key) are silently dropped.
