"""``svctl``: operaciones de administración.

    svctl migrate            # alembic upgrade head
    svctl bootstrap          # sincroniza roles/permisos y crea el primer admin (SV_BOOTSTRAP_ADMIN_*)
    svctl serve [--reload]   # arranca la API
    svctl gen-secrets        # genera valores para SV_JWT_SECRET y SV_SECRETS_KEY
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _migrate(revision: str = "head") -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "src/security_vision/infrastructure/database/migrations"))
    command.upgrade(cfg, revision)


async def _bootstrap() -> dict[str, object]:
    from security_vision.core.configuration.settings import get_settings
    from security_vision.infrastructure.database.session import create_engine, uow_factory
    from security_vision.infrastructure.security.adapters import Argon2PasswordHasher
    from security_vision.modules.users.services import bootstrap

    s = get_settings()
    engine = create_engine(s.database_url.get_secret_value(), pool_size=2)
    try:
        pwd = s.bootstrap_admin_password.get_secret_value() if s.bootstrap_admin_password else None
        return await bootstrap(uow_factory(engine), Argon2PasswordHasher(), s.bootstrap_admin_email, pwd)
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="svctl")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    sub.add_parser("bootstrap")
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--reload", action="store_true")
    sub.add_parser("gen-secrets")
    args = ap.parse_args(argv)

    if args.cmd == "migrate":
        _migrate()
    elif args.cmd == "bootstrap":
        print(json.dumps(asyncio.run(_bootstrap()), ensure_ascii=False))
    elif args.cmd == "serve":
        import uvicorn

        uvicorn.run("security_vision_api.main:app_factory", factory=True, host=args.host, port=args.port,
                    reload=args.reload, access_log=False)
    elif args.cmd == "gen-secrets":
        from security_vision.infrastructure.security.adapters import AesGcmCipher

        print(f"SV_JWT_SECRET={secrets.token_urlsafe(48)}")
        print(f"SV_SECRETS_KEY={AesGcmCipher.generate_key()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
