from nonebot import get_plugin_config
from pydantic import BaseModel
from pathlib import Path
import jinja2

class Config(BaseModel):
    bilibili_cookie: str = ""


ddcheck_config = get_plugin_config(Config)
