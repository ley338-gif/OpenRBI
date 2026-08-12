import { createHmac } from "node:crypto";

// Minimal RFC 6238 TOTP generator (SHA-1, 6 digits, 30s step) — no extra
// dependency, since we only ever need this for e2e_admin's own real
// enrollment flow (its otpauth_uri, extracted from the app's own API
// response, not a secret we invented).
function base32Decode(input: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const clean = input.replace(/=+$/, "").toUpperCase();
  let bits = "";
  for (const char of clean) {
    const val = alphabet.indexOf(char);
    if (val === -1) continue;
    bits += val.toString(2).padStart(5, "0");
  }
  const bytes: number[] = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) {
    bytes.push(parseInt(bits.slice(i, i + 8), 2));
  }
  return Buffer.from(bytes);
}

export function secretFromOtpauthUri(otpauthUri: string): string {
  const url = new URL(otpauthUri);
  const secret = url.searchParams.get("secret");
  if (!secret) throw new Error(`otpauth URI has no secret: ${otpauthUri}`);
  return secret;
}

export function totpNow(base32Secret: string, stepSeconds = 30, digits = 6): string {
  const key = base32Decode(base32Secret);
  const counter = Math.floor(Date.now() / 1000 / stepSeconds);
  const counterBuf = Buffer.alloc(8);
  counterBuf.writeBigUInt64BE(BigInt(counter));
  const hmac = createHmac("sha1", key).update(counterBuf).digest();
  const offset = hmac[hmac.length - 1] & 0x0f;
  const binCode =
    ((hmac[offset] & 0x7f) << 24) |
    ((hmac[offset + 1] & 0xff) << 16) |
    ((hmac[offset + 2] & 0xff) << 8) |
    (hmac[offset + 3] & 0xff);
  return (binCode % 10 ** digits).toString().padStart(digits, "0");
}
