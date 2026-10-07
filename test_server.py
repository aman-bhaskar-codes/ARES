import uvicorn
import asyncio
from ares.api.app import app
async def main():
    config = uvicorn.Config(app, port=8001, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()
asyncio.run(main())
