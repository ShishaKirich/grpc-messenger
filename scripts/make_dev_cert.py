"""Создаёт сертификаты для локального запуска: свой центр сертификации (CA) и сертификат сервера.

    python scripts/make_dev_cert.py

certs/ca.crt     — клиент доверяет только этому CA (а не всем CA системы)
certs/server.crt — сертификат сервера для localhost и 127.0.0.1, подписан CA
certs/server.key — закрытый ключ сервера
certs/ca.key     — закрытый ключ CA; после создания сертификатов его можно удалить

Папка certs/ в .gitignore: закрытые ключи в репозиторий не попадают.
Для настоящего сервера используйте сертификат от Let's Encrypt.
"""
import datetime
import ipaddress
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

OUT = Path(__file__).resolve().parent.parent / "certs"


def write_key(path: Path, key) -> None:
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    path.chmod(0o600)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    if (OUT / "server.crt").exists() and "--force" not in sys.argv:
        print(f"Сертификаты уже есть в {OUT}. Пересоздать: --force")
        return
    now = datetime.datetime.now(datetime.timezone.utc)

    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Les iz Shishek dev CA")])
    ca_cert = (x509.CertificateBuilder()
               .subject_name(ca_name).issuer_name(ca_name)
               .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
               .not_valid_before(now).not_valid_after(now + datetime.timedelta(days=825))
               .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
               .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                            data_encipherment=False, key_agreement=False, key_cert_sign=True,
                                            crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
               .sign(ca_key, hashes.SHA256()))

    key = ec.generate_private_key(ec.SECP256R1())
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
            .issuer_name(ca_name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now).not_valid_after(now + datetime.timedelta(days=397))
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            ]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))

    (OUT / "ca.crt").write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    (OUT / "server.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    write_key(OUT / "ca.key", ca_key)
    write_key(OUT / "server.key", key)
    print(f"Готово: {OUT}")


if __name__ == "__main__":
    main()
