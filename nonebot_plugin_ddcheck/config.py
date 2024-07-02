from nonebot import get_plugin_config
from pydantic import BaseModel
from pathlib import Path
import jinja2

class Config(BaseModel):
    bilibili_cookie: str = ""


ddcheck_config = get_plugin_config(Config)

dir_path = Path(__file__).parent
template_path = dir_path / "template"
env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(template_path), enable_async=True
)