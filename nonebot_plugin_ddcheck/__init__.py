import asyncio
import datetime
import json
import os
import traceback
from pathlib import Path
import nonebot

import yt_dlp
from nonebot import get_driver, on_command, require, get_bot
from nonebot.adapters import Message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata, inherit_supported_adapters


from .follow import check_timers, update_timers

require("nonebot_plugin_alconna")
require("nonebot_plugin_apscheduler")
require("nonebot_plugin_htmlrender")
require("nonebot_plugin_localstore")

import nonebot_plugin_localstore as store
from nonebot_plugin_alconna import UniMessage

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
config = get_driver().config
superusers = list(config.superusers)

# 获取插件的数据目录路径
dd_file: Path = store.get_data_file("nonebot_plugin_ddcheck", "dd.json")
vtb_file: Path = store.get_data_file("nonebot_plugin_ddcheck", "vtb.json")
ytb_file: Path = store.get_data_file("nonebot_plugin_ddcheck", "ytb.json")

ydl_opts = {
    "flat_playlist": True,
    "skip_download": True,
    "playlistend": 1,
    "extract_flat": True,
    "format": "json",
    "quiet": True,
}

# 尝试从 localstore 加载 dd.json 的数据，如果不存在则初始化为空列表
try:
    with open(dd_file, encoding="utf-8") as f:
        alias_data = json.load(f)
except FileNotFoundError:
    alias_data = []

try:
    with open(vtb_file, encoding="utf-8") as f:
        vtb_data = json.load(f)
except FileNotFoundError:
    vtb_data = []

try:
    with open(ytb_file, encoding="utf-8") as f:
        ytb_data = json.load(f)
except FileNotFoundError:
    ytb_data = []

driver = nonebot.get_driver()
@driver.on_bot_connect
async def _():
    bot = get_bot()
    await check_timers(bot, vtb_data, ytb_data)



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
        await matcher.finish("查谁的成分？听不见！重来！！")

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


vtbadd = on_command("vtbadd", block=True, priority=12)


@vtbadd.handle()
async def _(
    bot: Bot,
    event: MessageEvent,
    matcher: Matcher,
    msg: Message = CommandArg(),
):
    if str(event.user_id) not in superusers:
        await matcher.finish("你不是管理员，离开")
    text = msg.extract_plain_text().strip()
    if not isinstance(event, GroupMessageEvent):
        await matcher.finish("请在群内使用命令")
    group_id = event.group_id
    if not text:
        matcher.block = False
        await matcher.finish("加谁的频道？听不见！重来！！")
    try:
        nickname, uid = text.split(" ")
        updated = False
        for item in vtb_data:
            if item["uid"] == uid:
                if group_id not in item["sub_group"]:
                    item["sub_group"].append(group_id)
                else:
                    await matcher.finish(f"{nickname}已经在关注了喵")
                updated = True
                break
        if not updated:
            vtb_data.append({"nickname": nickname, "uid": uid, "sub_group": [group_id]})
        with open(vtb_file, "w", encoding="utf-8") as f:
            json.dump(vtb_data, f, ensure_ascii=False, indent=4)
        await update_timers(bot, vtb_data, ytb_data)
        await matcher.finish(f"关注{nickname}成功喵~")
    except ValueError:
        await matcher.finish("参数错误")


ytbadd = on_command("ytbadd", block=True, priority=12)


@ytbadd.handle()
async def _(
    bot: Bot,
    event: MessageEvent,
    matcher: Matcher,
    msg: Message = CommandArg(),
):
    if str(event.user_id) not in superusers:
        await matcher.finish("你不是管理员，离开")
    text = msg.extract_plain_text().strip()
    if not text:
        matcher.block = False
        await matcher.finish("加谁的频道？听不见！重来！！")
    try:
        nickname, id = text.split(" ")
        if not isinstance(event, GroupMessageEvent):
            await matcher.finish("请在群内使用命令")
        group_id = event.group_id
        if not id:
            matcher.block = False
            await matcher.finish("加谁的频道？格式错误！重来！！")
        if not id.startswith("@"):
            id = "@" + id

        updated = False
        for item in ytb_data:
            if item["id"] == id:
                if group_id not in item["sub_group"]:
                    item["sub_group"].append(group_id)
                else:
                    await matcher.finish(f"{nickname}已经在关注了喵")
                updated = True
                break
        if not updated:
            url = f"https://www.youtube.com/{id}/streams"
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                result = ydl.extract_info(url, download=False)
            if result:
                ytb_data.append(
                    {"nickname": nickname, "id": id, "sub_group": [group_id]}
                )
                await update_timers(bot, vtb_data, ytb_data)
                await matcher.finish(f"关注{nickname}成功喵~")
            else:
                await matcher.finish("频道不存在")
        with open(ytb_file, "w", encoding="utf-8") as f:
            json.dump(ytb_data, f, ensure_ascii=False, indent=4)

    except Exception:
        logger.warning(traceback.format_exc())
        await matcher.finish("出错了，请稍后再试")


alldd = on_command("alldd", block=True, priority=12)


@alldd.handle()
async def _(
    matcher: Matcher,
):
    text = ""
    for item in alias_data:
        text += f"{item['nickname']} -> {item['uid']}\n"
    await matcher.finish(text)


rmdd = on_command("rmdd", block=True, priority=12)


@rmdd.handle()
async def _(
    matcher: Matcher,
    msg: Message = CommandArg(),
):
    text = msg.extract_plain_text().strip()
    if not text:
        matcher.block = False
        await matcher.finish()

    for item in alias_data:
        if item["nickname"] == text:
            alias_data.remove(item)
            with open(dd_file, "w", encoding="utf-8") as f:
                json.dump(alias_data, f, ensure_ascii=False, indent=4)
            await matcher.finish("删除成功")
            break
