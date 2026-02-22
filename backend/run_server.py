import asyncio
import sys

import uvicorn


def main() -> None:
    # On Windows, Playwright requires a loop that supports subprocesses.
    # Uvicorn's default asyncio loop setup switches to SelectorEventLoop,
    # which breaks playwright.async_api with NotImplementedError.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    config = uvicorn.Config(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        loop="none",
    )
    server = uvicorn.Server(config)
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
