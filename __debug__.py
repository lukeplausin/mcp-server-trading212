from src.server import main
import os

# This file is a debugging entrypoint for IDE work

main.callback(
    api_key=os.environ["TRADING212_API_KEY"],
    environment="live",
    cache_ttl=300,
    sse=True,
    host="127.0.0.1",
    port=6677
)
