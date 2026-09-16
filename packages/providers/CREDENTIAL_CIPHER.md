# Offline credential cipher (#327)

`CredentialCipher` uses the existing runtime's hash-locked cryptography
Fernet/MultiFernet library, imported only on construction. The standalone
protocol/mock package stays importable without cryptography installed. No
provider interfaces, environment settings, database, API or worker are changed.

Inject a list/tuple of 1–16 distinct Fernet keys as bytes, primary key first.
The caller obtains these from its approved deployment secret store outside the
database; this module neither provisions nor discovers keys. `seal(secret,
context)` returns bytes; `open(token, expected)` returns a sensitive plaintext
string; `rotate(token, expected)` validates identity then re-encrypts with the
primary key while preserving the original Fernet timestamp.

`CipherContext` requires canonical lowercase UUID strings for user, organization
and credential, positive integer credential version (at most 2^31−1), and purpose
and provider identifiers of 1–64 lowercase ASCII letters/digits/underscore/hyphen,
starting with a letter. Purpose is caller-defined and must match exactly. Secrets
are nonempty UTF-8 strings of at most 4096 bytes; tokens are bytes at most 45056
bytes. Serialized plaintext is bounded to 32768 bytes before encryption and
after decryption, accommodating JSON escaping of every allowed control byte
without reducing the documented 4096-byte UTF-8 secret limit. These are defensive primitive bounds, not public HTTP/financial policy.

The encrypted JSON has schema `credential-cipher/v1`, exact identity and secret.
Strict decoding rejects duplicate/unknown fields, malformed Unicode, unsupported
schema, invalid identity types, mismatched identity and oversized material. The
identity fields are authenticated plaintext inside encryption, not a custom AAD
or envelope scheme. Library authentication rejects tampering before decoding.
This identity comparison does **not** authorize the caller: custody code must
first establish database ownership, membership, live credential status and run
binding. It must not accept expected identity directly from untrusted requests.

New objects have redacted repr; fixed failure exceptions discard underlying
exception context. Returned plaintext is intentionally sensitive: never log it,
put it in queue payloads, expose a key-read endpoint, or enable traceback local
variable capture. The module cannot scrub Python memory or conceal arguments
from a debugger/process compromise. A database alone lacks the keyring, but a
compromised running authorized application can decrypt credentials. Fernet's
creation timestamp is visible in its token; token bytes still are not diagnostics.

Rotation procedure: deploy new primary plus retained old keys, rotate every
retained row through the custody service, verify all identity bindings and run
backup/restore tests, then retire old keys only when the retention policy's
required backups/material remain recoverable. Removing an old key too early
makes old ciphertext unreadable. This primitive performs no row updates, revocation,
retention enforcement or backup validation. Missing keys fail closed, never
fall back to a plaintext value or application-owner provider key.

Tests generate synthetic keys in memory and make no network calls. They cover
identity mismatch, tamper, strict payload/encoding bounds, multi-key rotation,
old-key retirement and hostile library exceptions. Passing them establishes
only the offline primitive, not a tenant-authorized production vault or hosted
BYOK acceptance. See accepted ADR-0026 for the narrower scope.
