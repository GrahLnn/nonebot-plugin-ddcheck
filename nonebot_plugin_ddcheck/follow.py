import asyncio
import datetime
import json

import yt_dlp
from bilibili_api import user
from nonebot.log import logger

timers = {}


# 获取B站直播预约信息
async def get_upcoming_bili_live(uid):
    u = user.User(uid)
    data = await u.get_reservation()

    if data:
        space_info = await u.get_live_info()
        live_room_rul = space_info["live_room"]["url"]
        dt_object = data[0]["live_plan_start_time"]
        return {
            "url": live_room_rul,
            "release_time": dt_object,
        }
    else:
        return None


# 获取YouTube直播预约信息
async def get_upcoming_youtube_live(ytber):
    channel_url = f"https://www.youtube.com/{ytber}/streams"
    ydl_opts = {
        "flat_playlist": True,
        "skip_download": True,
        "playlistend": 5,
        "extract_flat": True,
        "format": "json",
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(channel_url, download=False)

    up_coming = None
    for entry in result["entries"]:
        if entry["release_timestamp"] is None:
            break
        url = entry["url"]
        if "schedule" in entry["title"].lower():
            continue
        release_time = entry["release_timestamp"]

        up_coming = {"url": url, "release_time": release_time}
    return up_coming


async def timer_task(nickname, delay, url, sub_groups, bot):
    await asyncio.sleep(delay)
    for group_id in sub_groups:
        await bot.send_group_msg(
            group_id=group_id, message=f"{nickname}开播啦！\n传送门: {url}"
        )


async def add_timer(nickname, uid_or_id, release_time, sub_groups, url, bot):
    if uid_or_id in timers:
        return

    delay = release_time - datetime.datetime.now().timestamp()
    if delay <= 0:
        return

    timers[uid_or_id] = asyncio.create_task(
        timer_task(nickname, delay, url, sub_groups, bot)
    )


async def check_timers(bot, vtb_data, ytb_data):
    while True:
        await update_timers(bot, vtb_data, ytb_data)

        await asyncio.sleep(3600)  # 每小时检查一次


async def update_timers(bot, vtb_data, ytb_data):
    for vtb in vtb_data:
        live_info = await get_upcoming_bili_live(vtb["uid"])
        if live_info:
            release_time = live_info["release_time"]
            delay = release_time - datetime.datetime.now().timestamp()
            time_left = datetime.timedelta(seconds=delay)
            formatted_time_left = str(time_left)
            logger.info(f"{vtb['nickname']}的直播时间还有: {formatted_time_left}")
            if vtb["uid"] not in timers:
                await add_timer(
                    vtb["nickname"],
                    vtb["uid"],
                    release_time,
                    vtb["sub_group"],
                    live_info["url"],
                    bot,
                )

    for ytb in ytb_data:
        live_info = await get_upcoming_youtube_live(ytb["id"])
        if live_info:
            release_time = live_info["release_time"]
            delay = release_time - datetime.datetime.now().timestamp()
            time_left = datetime.timedelta(seconds=delay)
            formatted_time_left = str(time_left)
            logger.info(f"{ytb['nickname']}的直播时间还有: {formatted_time_left}")
            if ytb["id"] not in timers:
                await add_timer(
                    ytb["nickname"],
                    ytb["id"],
                    release_time,
                    ytb["sub_group"],
                    live_info["url"],
                    bot,
                )
