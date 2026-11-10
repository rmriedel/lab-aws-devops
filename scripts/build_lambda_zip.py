"""
Arma el zip de un Lambda de apps/ de forma DETERMINISTICA: orden de archivos,
fecha y permisos fijos. Mismo codigo => mismos bytes => mismo CodeSha256 en
Lambda, lo que deja al job deploy de CI saltear el update cuando no hay
cambios reales.

Uso: python scripts/build_lambda_zip.py apps/price_alert /tmp/price_alert.zip
Imprime el sha256 en base64 (el mismo formato que Lambda.CodeSha256).
"""
import base64
import hashlib
import sys
import zipfile
from pathlib import Path

FIXED_DATE = (2000, 1, 1, 0, 0, 0)
FILE_MODE = 0o100644  # archivo regular, rw-r--r--


def build(src_dir: Path, out_path: Path) -> str:
    files = sorted(
        p for p in src_dir.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    )
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(src_dir).as_posix(), date_time=FIXED_DATE)
            info.external_attr = FILE_MODE << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, path.read_bytes())
    return base64.b64encode(hashlib.sha256(out_path.read_bytes()).digest()).decode()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    print(build(Path(sys.argv[1]), Path(sys.argv[2])))
