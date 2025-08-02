import asyncio
import json
import random
import traceback
from functools import reduce
from io import BytesIO
from pathlib import Path

import nonebot
import requests
import yt_dlp
from moviepy import VideoFileClip
from nonebot import get_bot, get_driver, on_command, require
from nonebot.adapters import Message
from nonebot.adapters.onebot.v11 import (
    Bot,
    Event,
    GroupMessageEvent,
    MessageEvent,
    MessageSegment,
)
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata, inherit_supported_adapters

from .follow import (
    check_timers,
    get_formatted_time_left,
    get_upcoming_bili_live,
    get_upcoming_youtube_live,
    timers,
    update_timers,
)
from .twits import get_tweets

require("nonebot_plugin_alconna")
require("nonebot_plugin_apscheduler")
require("nonebot_plugin_htmlrender")
require("nonebot_plugin_localstore")

import nonebot_plugin_localstore as store
from nonebot_plugin_alconna import UniMessage

from .config import Config
from .data_source import get_reply, load_json
from .llm import openai_completion

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
bind_file: Path = store.get_data_file("nonebot_plugin_ddcheck", "bind.json")
member_file: Path = store.get_data_file("nonebot_plugin_ddcheck", "member.json")

ydl_opts = {
    "flat_playlist": True,
    "skip_download": True,
    "playlistend": 1,
    "extract_flat": True,
    "format": "json",
    "quiet": True,
}

ban_words = ["sb", "母狗", "沐勾"]


def save_json(file: Path, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


# 尝试从 localstore 加载 dd.json 的数据，如果不存在则初始化为空列表
alias_data = load_json(dd_file)
vtb_data = load_json(vtb_file)
ytb_data = load_json(ytb_file)
bind_data = load_json(bind_file)
member_data = load_json(member_file)

driver = nonebot.get_driver()


# 用于追踪任务状态
_task_running = {"check_timers": False, "watch_tweets": False}


async def run_with_retry(coro_factory, name):
    while True:
        coro = coro_factory()  # 每次循环都创建一个新的协程对象
        try:
            await coro
        except Exception as e:
            logger.error(f"{name} task crashed: {e}")
            logger.error(traceback.format_exc())
            await asyncio.sleep(10)
            logger.info(f"Restarting {name} task...")


@driver.on_bot_connect
async def _():
    bot = get_bot()

    if not _task_running["check_timers"]:
        _task_running["check_timers"] = True
        asyncio.create_task(
            run_with_retry(
                lambda: check_timers(
                    bot, vtb_data, ytb_data, bind_data
                ),  # 用lambda“包装”一下
                "check_timers",
            )
        )
        logger.info("Created check_timers task")

    # if not _task_running["watch_tweets"]:
    #     _task_running["watch_tweets"] = True
    #     asyncio.create_task(
    #         run_with_retry(
    #             lambda: watch_tweets(bot, vtb_data, bind_data), "watch_tweets"
    #         )
    #     )
    #     logger.info("Created watch_tweets task")


# ddcheck = on_command("查成分", aliases={"ccf"}, block=True, priority=12)
ddadd = on_command("adddd", block=True, priority=12)
vtbadd = on_command("vtbadd", block=True, priority=12)
ytbadd = on_command("ytbadd", block=True, priority=12)
vtbrm = on_command("vtbrm", block=True, priority=12)
ytbrm = on_command("ytbrm", block=True, priority=12)
alldd = on_command("alldd", block=True, priority=12)
rmdd = on_command("rmdd", block=True, priority=12)
whenlive = on_command(
    "主包什么时候播",
    aliases={
        "maririn~",
        "maririn～",
        "又是想maririn的一天",
        "我要看maririn",
        "我要看maria",
        "等不及了",
        "什么时候播",
        "什么时候开播",
        "什么时候直播",
        "主播什么时候播",
        "when streaming",
    },
    block=True,
    priority=12,
)
binddd = on_command("bind", block=True, priority=12)
bindrm = on_command("bindrm", block=True, priority=12)
bindall = on_command("bindall", block=True, priority=12)
ask_llm = on_command("", block=True, priority=12)

member = on_command("member", block=True, priority=12)
quickat = on_command("", block=True, priority=12)
randomat = on_command("", block=True, priority=12)
rmmember = on_command("rmm", block=True, priority=12)

invalid_words = [
    "mll",
    "maririn",
    "maria",
    "maria",
    "maria ",
    "马力力",
    "玛丽亚",
]


@randomat.handle()
async def handle_randomat(
    matcher: Matcher, event: GroupMessageEvent, msg: Message = CommandArg()
):
    text = msg.extract_plain_text().strip()
    group_id = str(event.group_id)
    msg_user_id = str(event.user_id)
    msg_user_name = event.sender.card or event.sender.nickname
    bot_qq = str(event.self_id)
    if msg_user_id == bot_qq:
        return
    val = reduce(lambda x, y: x or y, [keyword in text for keyword in invalid_words])

    if any(
        keyword in text
        for keyword in [
            "召唤一条狗",
            "来条",
            "随机召唤",
            "随机一条狗",
            "来条山里灵活的狗",
            "来条山里灵活的似狗",
            "来条山里不灵活的狗",
            "来条山里不灵活的似狗",
            "谁是",
        ]
    ):
        if val:
            await matcher.finish("诶，你没资格~杂古~杂古~~")
        else:
            qq_list = [
                item["qq"]
                for item in member_data
                if item["group_id"] == group_id
                # and str(item["qq"]) != msg_user_id
                and str(item["qq"]) not in superusers
            ]
            if qq_list:
                qq_list = list(set(qq_list))
                qq = random.choice(qq_list)
                msg_user_name = msg_user_name + "："
                if str(qq) == msg_user_id:
                    text = (
                        text.replace("谁是", "不用召唤，你就是")
                        .replace("随机召唤", "不用召唤，你就是")
                        .replace("召唤一条狗", "狗来咯")
                        .replace("来条", "")
                    )
                else:
                    text = (
                        text.replace("谁是", "这是")
                        .replace("随机召唤", "来力")
                        .replace("召唤一条狗", "狗")
                        .replace("来条", "")
                    )
                text = text + " "
                await matcher.finish(text + MessageSegment.at(qq))
            else:
                await matcher.finish("没有可召唤的狗")


@quickat.handle()
async def handle_quickat(
    matcher: Matcher, event: GroupMessageEvent, msg: Message = CommandArg()
):
    text = msg.extract_plain_text().strip()
    group_id = str(event.group_id)
    msg_user_id = str(event.user_id)
    bot_qq = str(event.self_id)
    if msg_user_id == bot_qq:
        await matcher.finish()

    if any(
        keyword in text
        for keyword in [
            "来康康",
            "都来康",
            "来吹逼",
            "大召唤术",
            "召唤一群狗",
            "群狗召唤",
            "大召唤兽",
            "都来猎",
            "都来裂",
        ]
    ):
        qq_list = [
            item["qq"]
            for item in member_data
            if item["group_id"] == group_id and str(item["qq"]) != msg_user_id
        ]
    elif any(
        kw not in text
        for kw in [
            "召唤一条狗",
            "来条狗",
            "随机召唤",
            "随机一条狗",
            "来条山里灵活的狗",
            "来条山里灵活的似狗",
            "来条山里不灵活的狗",
            "来条山里不灵活的似狗",
            "谁是",
        ]
    ):
        qq_list = [
            item["qq"]
            for item in member_data
            if item["nickname"] in text and item["group_id"] == group_id
        ]

    if qq_list:
        qq_list = list(set(qq_list))
        msgs = f"{text} "
        for qq in qq_list:
            msgs += MessageSegment.at(qq) + " "
        await matcher.finish(msgs)


@rmmember.handle()
async def handle_rmmember(
    matcher: Matcher, event: GroupMessageEvent, msg: Message = CommandArg()
):
    if str(event.user_id) not in superusers:
        await matcher.finish("你不是管理员，离开")

    group_id = str(event.group_id)
    info = msg.extract_plain_text().strip().split()
    if not info:
        await matcher.finish("请提供要解绑的昵称")

    nicknames = info[0].split(",")

    failed = []
    for nickname in nicknames:
        qq = {
            m["qq"]
            for m in member_data
            if m["nickname"] == nickname and m["group_id"] == group_id
        }
        before_len = len(member_data)
        member_data[:] = [
            m for m in member_data if not (m["qq"] in qq and m["group_id"] == group_id)
        ]
        if len(member_data) == before_len:
            failed.append(nickname)

    save_json(member_file, member_data)

    if failed:
        await matcher.finish(f"以下昵称没有绑定记录：{', '.join(failed)}")
    else:
        await matcher.finish("解绑成功")


@member.handle()  # member nickname1,nickname2,nickname3 @msg
async def handle_member(
    matcher: Matcher, event: GroupMessageEvent, msg: Message = CommandArg()
):
    if str(event.user_id) not in superusers:
        await matcher.finish("你不是管理员，离开")

    at_segment = msg["at"]
    if not at_segment:
        await matcher.finish("请@要绑定的用户")

    # 获取被@用户的QQ号
    target_qq = at_segment[0].data["qq"]

    # 获取当前群号
    group_id = str(event.group_id)
    info = msg.extract_plain_text().strip().split()
    nicknames = info[0].split(",")
    for nickname in nicknames:
        if nickname in ban_words:
            # await matcher.finish("你骂谁呢？")
            continue
        data = {
            "nickname": nickname,
            "qq": target_qq,
            "group_id": group_id,
        }
        if data not in member_data:
            member_data.append(data)
        else:
            await matcher.finish(f"{nickname}已经绑定过了")
    save_json(member_file, member_data)
    await matcher.finish("更新成功")


@ask_llm.handle()
async def handle_message(
    matcher: Matcher, event: GroupMessageEvent, msg: Message = CommandArg()
):
    if event.is_tome():
        sys_prompt = """你会用可爱的语气回答并喜爱在句子结束加入"喵~"的衬词，你当前的身份是「maririn的狗」，仅使用中文回复。
        指南：
        - 若用户询问意图���得鼓励的问题，以正面肯定的态度支持"""
        text = msg.extract_plain_text()
        result = openai_completion(text, sys_prompt)
        sender_id = event.user_id
        at_message = MessageSegment.at(sender_id)
        await matcher.finish(at_message + " " + result)


@binddd.handle()
async def handle_binddd(
    bot: Bot, matcher: Matcher, event: GroupMessageEvent, msg: Message = CommandArg()
):
    # 检查消息中是否包含@
    at_segment = msg["at"]
    if not at_segment:
        await matcher.finish("请@要绑定的用户")

    # 获取被@用户的QQ号
    target_qq = at_segment[0].data["qq"]

    # 获取当前群号
    group_id = str(event.group_id)

    # 更新bind_data
    targets = [item["target_qq"] for item in bind_data if item["group_id"] == group_id]
    at_message = MessageSegment.at(target_qq)
    if target_qq not in targets:
        targets.append(target_qq)
        bind_data.append({"group_id": group_id, "target_qq": str(target_qq)})

        # 保存到bind.json
        save_json(bind_file, bind_data)
        await update_timers(bot, vtb_data, ytb_data, bind_data)
        await matcher.finish(at_message + " 绑定成功，回复TD不退订")
    else:
        await matcher.finish(at_message + " 已经绑定了")


@bindrm.handle()
async def handle_bindrm(
    bot: Bot, matcher: Matcher, event: GroupMessageEvent, msg: Message = CommandArg()
):
    if str(event.user_id) not in superusers:
        await matcher.finish("你不是管理员，离开")
    at_segment = msg["at"]
    if not at_segment:
        await matcher.finish("请@要解绑的用户")

    target_qq = at_segment[0].data["qq"]
    group_id = str(event.group_id)
    global bind_data

    at_message = MessageSegment.at(target_qq)

    # 只删除特定群内的特定QQ绑定
    for item in bind_data:
        if item["group_id"] == group_id and item["target_qq"] == target_qq:
            bind_data.remove(item)
            save_json(bind_file, bind_data)
            await update_timers(bot, vtb_data, ytb_data, bind_data)
            await matcher.finish(at_message + "解绑成功")

    await matcher.finish(at_message + "并没有绑定")


@bindall.handle()
async def handle_bindall(
    bot: Bot, matcher: Matcher, event: GroupMessageEvent, msg: Message = CommandArg()
):
    await matcher.finish(str(bind_data))


# @ddcheck.handle()
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
    await update_timers(bot, vtb_data, ytb_data, bind_data)

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


@whenlive.handle()
async def handle_whenlive(bot: Bot, matcher: Matcher, msg: Message = CommandArg()):
    records = []
    # for item in vtb_data:
    #     live_info = await get_upcoming_bili_live(item["uid"])
    #     logger.info(live_info)
    #     if live_info:
    #         records.append(
    #             f"{item['nickname']}{get_formatted_time_left(live_info['release_time'])}(bilibili)"
    #         )
    #     else:
    #         records.append(f"{item['nickname']}还没有发布bilibili的直播预告")
    for item in ytb_data:
        live_info = await get_upcoming_youtube_live(item["id"])
        logger.info(live_info)
        if live_info:
            records.append(
                f"{item['nickname']}{get_formatted_time_left(live_info['release_time'])}(youtube)\n{live_info['title']}"
            )
        else:
            records.append(f"{item['nickname']}还没有发布youtube的直播预告")
    logger.info(records)
    await update_timers(bot, vtb_data, ytb_data, bind_data)
    if not records:
        await matcher.finish("还没有关注任何人呢，杂古")
    await matcher.finish("\n".join(records))


async def watch_tweets(bot, vtb_data, bind_data):
    interval = 2
    error_count = 0
    error_msg = ""
    while True:
        if error_count >= 3:
            for group in vtb_data[0]["sub_group"]:
                await bot.send_group_msg(
                    group_id=group,
                    message=f"retry too many times, now stop: {error_msg}",
                )
            raise Exception("retry too many times")
        try:
            tweets = await get_tweets(interval)
            error_count = 0
        except Exception as e:
            exc = traceback.format_exc()
            error_count += 1
            msg = f"58是狗，retry， error: {e}\n\n{exc}"
            error_msg = msg
            continue

        unique_tweets = {tweet["text"]: tweet for tweet in tweets}.values()
        tweets = list(unique_tweets)
        logger.info(f"valid tweets: {len(tweets)}")
        for vtb in vtb_data:
            await send_tweets(bot, vtb["sub_group"], bind_data, tweets)
        await asyncio.sleep(interval * 60)


async def send_tweets(bot, groups, bind_data, tweets: list):
    if not tweets:
        return
    for tweet in tweets:
        if tweet.get("text"):
            sys_prompt = """You are a professional translation engine, please translate the text into a colloquial, professional, elegant and fluent content, without the style of machine translation. You must only translate the text content, never interpret it."""
            prompt = f"""Translate into zh-hans: \n---\n{tweet["text"]}"""
            result = openai_completion(prompt, sys_prompt)
        for group in groups:
            message = ""
            for bind in bind_data:
                if bind["group_id"] == str(group):
                    message += MessageSegment.at(bind["target_qq"]) + " "
            message += "\nMaria发推：\n" + tweet["text"]
            if tweet.get("medias"):
                for media in tweet["medias"]:
                    if media.get("type") == "photo":
                        image = media["url"]
                        img_bytes = requests.get(image).content
                        message += MessageSegment.image(img_bytes)
                    elif media.get("type") == "animated_gif":
                        video = media["url"]
                        video_bytes = requests.get(video).content
                        # 将视频内容保存到内存中
                        video_buffer = BytesIO(video_bytes)

                        # 使用 moviepy 将视频转换为 GIF
                        with VideoFileClip(video_buffer) as clip:
                            # 转换为 GIF 并保存到内存
                            gif_buffer = BytesIO()
                            clip.write_gif(gif_buffer)  # fps 可调，影响大小和流畅度
                            gif_buffer.seek(0)

                        # 将 GIF 发送为图片
                        message += MessageSegment.image(gif_buffer)

            if q := tweet.get("quote"):
                message += "\n==========\n" + q.get("text", "")
                if q.get("medias"):
                    for media in q["medias"]:
                        if media.get("type") == "photo":
                            image = media["url"]
                            img_bytes = requests.get(image).content
                            message += MessageSegment.image(img_bytes)
                        elif media.get("type") == "animated_gif":
                            video = media["url"]
                            video_bytes = requests.get(video).content
                            # 将视频内容保存到内存中
                            video_buffer = BytesIO(video_bytes)

                            # 使用 moviepy 将视频转换为 GIF
                            with VideoFileClip(video_buffer) as clip:
                                # 转换为 GIF 并保存到内存
                                gif_buffer = BytesIO()
                                clip.write_gif(gif_buffer)
                                gif_buffer.seek(0)

                            # 将 GIF 发送为图片
                            message += MessageSegment.image(gif_buffer)
                message += "\n==========\n"

            message += "\n\n翻译：\n" + result
            await bot.send_group_msg(group_id=group, message=message)
