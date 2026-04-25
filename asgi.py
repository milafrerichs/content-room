import os

from dotenv import load_dotenv

load_dotenv()

from cli import load_config
from content_agent.web.app import create_app

config_path = os.getenv("CONFIG_PATH", "config.yaml")
config = load_config(config_path)
app = create_app(config)
