from marvin_mcp import server
from marvin_mcp.config import load_settings

def create_server():
    server.init(load_settings())
    return server.mcp
