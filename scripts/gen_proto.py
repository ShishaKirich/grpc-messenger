"""Пересобирает Python-код из proto/messenger.proto.

Запуск из корня репозитория:  python scripts/gen_proto.py
Сгенерированные файлы лежат в git, чтобы проект запускался без этого шага.
"""
import sys
from pathlib import Path

from grpc_tools import protoc

ROOT = Path(__file__).resolve().parent.parent

code = protoc.main([
    "grpc_tools.protoc",
    f"-I{ROOT}",
    f"--python_out={ROOT}",
    f"--pyi_out={ROOT}",
    f"--grpc_python_out={ROOT}",
    str(ROOT / "proto" / "messenger.proto"),
])
sys.exit(code)
