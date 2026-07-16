from __future__ import annotations

import uvicorn

from grokgw.config import Settings
from grokgw.grok_runner import GrokRunner
from grokgw.proxy_runner import ProxyRunner
from grokgw.server import create_app


def build_runner(settings: Settings):
    if settings.backend == "cli":
        return GrokRunner(settings)
    return ProxyRunner(settings)


def main():
    settings = Settings.from_env()
    runner = build_runner(settings)
    app = create_app(
        runner=runner,
        api_key=settings.api_key,
        max_concurrent=settings.max_concurrent,
    )
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
