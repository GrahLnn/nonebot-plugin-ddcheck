import asyncio
import datetime
import json
import os
import traceback
from pathlib import Path

import nonebot
import yt_dlp
from nonebot import get_bot, get_driver, on_command, require
from nonebot.adapters import Message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata, inherit_supported_adapters

from .follow import (
    check_timers,
    get_formatted_time_left,
    get_upcoming_bili_live,
    get_upcoming_youtube_live,
    update_timers,
)

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


def load_json(file: Path, default=[]):
    try:
        with open(file, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(file: Path, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


# 尝试从 localstore 加载 dd.json 的数据，如果不存在则初始化为空列表
alias_data = load_json(dd_file)
vtb_data = load_json(vtb_file)
ytb_data = load_json(ytb_file)

driver = nonebot.get_driver()
ddcheck = on_command("查成分", block=True, priority=12)
ddadd = on_command("adddd", block=True, priority=12)
vtbadd = on_command("vtbadd", block=True, priority=12)
ytbadd = on_command("ytbadd", block=True, priority=12)
alldd = on_command("alldd", block=True, priority=12)
rmdd = on_command("rmdd", block=True, priority=12)


@driver.on_bot_connect
async def _():
    bot = get_bot()
    asyncio.create_task(check_timers(bot, vtb_data, ytb_data))


@ddcheck.handle()
async def handle_ddcheck(matcher: Matcher, msg: Message = CommandArg()):
    text = msg.extract_plain_text().strip()
    text = next((item["uid"] for item in alias_data if item["nickname"] == text), text)

    if not text:
        matcher.block = False
        await matcher.finish()

    try:
        result = await get_reply(text)
        if isinstance(result, str):
            await matcher.finish(result)
        await UniMessage.image(raw=result).send()
    except Exception:
        logger.warning(traceback.format_exc())
        await matcher.finish("出错了，请稍后再试")


@ddadd.handle()
async def handle_ddadd(matcher: Matcher, msg: Message = CommandArg()):
    text = msg.extract_plain_text().strip()
    if not text:
        matcher.block = False
        await matcher.finish("查谁的成分？听不见！重来！！")

    try:
        nickname, uid = text.split(" ")
        for item in alias_data:
            if item["nickname"] == nickname:
                item["uid"] = uid
                break
        else:
            alias_data.append({"nickname": nickname, "uid": uid})

        save_json(dd_file, alias_data)
        await matcher.finish("更新成功")
    except ValueError:
        await matcher.finish("参数错误")


async def handle_add(
    matcher: Matcher, event: MessageEvent, msg: Message, is_youtube: bool
):
    async def handle_live_info(live_info):
        if live_info:
            formatted_time_left = get_formatted_time_left(live_info["release_time"])
            await matcher.finish(f"关注{nickname}成功喵~，{formatted_time_left}")
        else:
            await matcher.finish(
                f"关注{nickname}成功喵~, {nickname}还没开始播噢，别担心，时间到了我会提醒你的"
            )

    if str(event.user_id) not in superusers:
        await matcher.finish("你不是管理员，离开")
    if not isinstance(event, GroupMessageEvent):
        await matcher.finish("请在群内使用命令")

    text = msg.extract_plain_text().strip()
    if not text:
        matcher.block = False
        await matcher.finish("加谁的频道？听不见！重来！！")

    try:
        nickname, id = text.split(" ")
        if is_youtube and not id.startswith("@"):
            id = "@" + id
    except ValueError:
        await matcher.finish("参数错误")

    group_id = event.group_id
    data = ytb_data if is_youtube else vtb_data
    file = ytb_file if is_youtube else vtb_file

    for item in data:
        if item["id" if is_youtube else "uid"] == id:
            if group_id not in item["sub_group"]:
                item["sub_group"].append(group_id)
                save_json(file, data)
                live_info = await (
                    get_upcoming_youtube_live if is_youtube else get_upcoming_bili_live
                )(id)
                await handle_live_info(live_info)
            else:
                live_info = await (
                    get_upcoming_youtube_live if is_youtube else get_upcoming_bili_live
                )(id)
                if live_info:
                    formatted_time_left = get_formatted_time_left(
                        live_info["release_time"]
                    )
                    await matcher.finish(
                        f"{nickname}已经在关注了喵，{formatted_time_left}"
                    )
                else:
                    await matcher.finish(
                        f"{nickname}已经在关注了喵，{nickname}还没开始播噢，别担心，时间到了我会提醒你的"
                    )
            return

    if is_youtube:
        url = f"https://www.youtube.com/{id}/streams"
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(url, download=False)
        if not result:
            await matcher.finish("频道不存在")

    data.append(
        {
            "nickname": nickname,
            "id" if is_youtube else "uid": id,
            "sub_group": [group_id],
        }
    )
    save_json(file, data)

    bot = get_bot()
    await update_timers(bot, vtb_data, ytb_data)

    live_info = await (
        get_upcoming_youtube_live if is_youtube else get_upcoming_bili_live
    )(id)
    await handle_live_info(live_info)


@vtbadd.handle()
async def handle_vtbadd(
    matcher: Matcher, event: MessageEvent, msg: Message = CommandArg()
):
    await handle_add(matcher, event, msg, is_youtube=False)


@ytbadd.handle()
async def handle_ytbadd(
    matcher: Matcher, event: MessageEvent, msg: Message = CommandArg()
):
    await handle_add(matcher, event, msg, is_youtube=True)


@alldd.handle()
async def handle_alldd(matcher: Matcher):
    text = "\n".join(f"{item['nickname']} -> {item['uid']}" for item in alias_data)
    await matcher.finish(text)


@rmdd.handle()
async def handle_rmdd(matcher: Matcher, msg: Message = CommandArg()):
    text = msg.extract_plain_text().strip()
    if not text:
        matcher.block = False
        await matcher.finish()

    for item in alias_data:
        if item["nickname"] == text:
            alias_data.remove(item)
            save_json(dd_file, alias_data)
            await matcher.finish("删除成功")
            break
