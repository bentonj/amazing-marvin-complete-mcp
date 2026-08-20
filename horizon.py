from marvin_mcp import server
from marvin_mcp.config import load_settings

server.init(load_settings())

mcp = server.mcp
