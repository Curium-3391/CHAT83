"""Write the public TI-83 Plus 0104 app-signing key for RabbitSign.

Usage: python tools/ti_0104_pubkey.py spasm-ng/export.cpp out.key

SPASM-ng signs .8xk files with the well-known 0104 key that it embeds in
export.cpp. Distribution packages of RabbitSign ship without key files, so
CI derives the public modulus from SPASM's copy to check the signature:
    rabbitsign -c -k out.key CHAT83.8xk
"""
import re
import sys


def key_bytes(source: str, name: str) -> bytes:
    match = re.search(r"%s\[\]\s*=\s*\{(.*?)\};" % name, source, re.S)
    if not match:
        raise SystemExit(f"{name} not found in SPASM source")
    return bytes(int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})", match.group(1)))


def main() -> None:
    source_path, out_path = sys.argv[1:3]
    source = open(source_path, encoding="utf-8").read()
    n = key_bytes(source, "nbuf")
    p = key_bytes(source, "pbuf")
    q = key_bytes(source, "qbuf")
    # SPASM stores the numbers little-endian (mpz_import order -1).
    if int.from_bytes(p, "little") * int.from_bytes(q, "little") != int.from_bytes(n, "little"):
        raise SystemExit("SPASM key material does not satisfy n = p * q")
    # TI key file: key ID, then length-prefixed little-endian hex modulus.
    with open(out_path, "w", encoding="ascii") as out:
        out.write("0104\n%02X%s\n" % (len(n), n.hex().upper()))


if __name__ == "__main__":
    main()
