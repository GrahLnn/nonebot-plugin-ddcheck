import traceback
import json
from pathlib import Path

from nonebot import on_command, require
from nonebot.adapters import Message
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata, inherit_supported_adapters

require("nonebot_plugin_alconna")
require("nonebot_plugin_apscheduler")
require("nonebot_plugin_htmlrender")
require("nonebot_plugin_localstore")

from nonebot_plugin_alconna import UniMessage
import nonebot_plugin_localstore as store

from .config import Config
from .data_source import get_reply

__plugin_meta__ = PluginMetadata(
    name="成分姬",
    description="查询B站用户关注的VTuber成分",
    usage="查成分 B站用户名/UID",
    type="application",
    homepage="https://github.com/noneplugin/nonebot-plugin-ddcheck",
    config=Config,
    supported_adapters=inherit_supported_adapters("nonebot_plugin_alconna"),
    extra={
        "example": "查成分 小南莓Official",
    },
)

# 获取插件的数据目录路径
dd_file: Path = store.get_data_file("nonebot_plugin_ddcheck", "dd.json")

# 尝试从 localstore 加载 dd.json 的数据，如果不存在则初始化为空列表
try:
    with open(dd_file, "r", encoding="utf-8") as f:
        alias_data = json.load(f)
except FileNotFoundError:
    alias_data = []

ddcheck = on_command("查成分", block=True, priority=12)


@ddcheck.handle()
async def _(
    matcher: Matcher,
    msg: Message = CommandArg(),
):
    text = msg.extract_plain_text().strip()
    nickname_list = [item["nickname"] for item in alias_data]
    if text in nickname_list:
        text = alias_data[nickname_list.index(text)]["uid"]
    if not text:
        matcher.block = False
        await matcher.finish()

    try:
        result = await get_reply(text)
    except Exception:
        logger.warning(traceback.format_exc())
        await matcher.finish("出错了，请稍后再试")

    if isinstance(result, str):
        await matcher.finish(result)

    await UniMessage.image(raw=result).send()


ddadd = on_command("adddd", block=True, priority=12)


@ddadd.handle()
async def _(
    matcher: Matcher,
    msg: Message = CommandArg(),
):
    text = msg.extract_plain_text().strip()

    if not text:
        matcher.block = False
        await matcher.finish()

    try:
        nickname, uid = text.split(" ")
        # 检查是否存在相同的 nickname
        updated = False
        for item in alias_data:
            if item["nickname"] == nickname:
                item["uid"] = uid
                updated = True
                break

        # 如果不存在相同的 nickname，则添加新条目
        if not updated:
            alias_data.append({"nickname": nickname, "uid": uid})

        # 保存更新后的数据到 localstore
        with open(dd_file, "w", encoding="utf-8") as f:
            json.dump(alias_data, f, ensure_ascii=False, indent=4)

        await matcher.finish("更新成功")
    except ValueError:
        await matcher.finish("参数错误")


alldd = on_command("alldd", block=True, priority=12)

@alldd.handle()
async def _(
    matcher: Matcher,
):
    text = ""
    for item in alias_data:
        text += f"{item['nickname']} -> {item['uid']}\n"
    await matcher.finish(text)