import asyncio
import datetime
import json

import yt_dlp
from bilibili_api import user
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot.log import logger
from retry import retry

timers = {}


# 获取B站直播预约信息
@retry(tries=3, delay=2)
async def get_upcoming_bili_live(uid):
    logger.info(f"Fetching upcoming live for UID: {uid}")
    try:
        u = user.User(uid)
        data = await u.get_reservation()
    except Exception as e:
        logger.error(f"Error fetching live info for UID: {uid} - {e}")
        raise
    
    if data:
        space_info = await u.get_live_info()
        live_room_url = space_info["live_room"]["url"]
        dt_object = data[0]["live_plan_start_time"]
        return {
            "url": live_room_url,
            "release_time": dt_object,
        }
    else:
        logger.info(f"No upcoming live found for UID: {uid}")
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
        up_coming = {"url": url, "release_time": release_time, "title": entry["title"]}
    return up_coming


async def timer_task(
    nickname, delay, url, sub_groups, bot, bind_data, uid_or_id, title=None
):
    await asyncio.sleep(delay)
    for group_id in sub_groups:
        message = ""
        for bind in bind_data:
            if bind["group_id"] == str(group_id):
                message += MessageSegment.at(bind["target_qq"]) + " "
        await bot.send_group_msg(
            group_id=group_id,
            message=message + f"{nickname}开播啦！gkd\n\n{title}\n{url}",
        )
    timers.pop(uid_or_id, None)


async def add_timer(
    nickname, uid_or_id, release_time, sub_groups, url, bot, bind_data, title=None
):
    if uid_or_id in timers:
        return

    delay = release_time - datetime.datetime.now().timestamp()
    if delay <= 0:
        return

    timers[uid_or_id] = asyncio.create_task(
        timer_task(nickname, delay, url, sub_groups, bot, bind_data, uid_or_id, title)
    )


async def check_timers(bot, vtb_data, ytb_data, bind_data):
    while True:
        try:
            await update_timers(bot, vtb_data, ytb_data, bind_data)
        except TimeoutError:
            logger.error("TimeoutError: Failed to update timers. Retrying...")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
        await asyncio.sleep(3600)  # 每小时检查一次


async def update_timers(bot, vtb_data, ytb_data, bind_data):
    # for vtb in vtb_data:
    #     logger.info("update bilibili live info")
    #     live_info = await get_upcoming_bili_live(vtb["uid"])

    #     if live_info:
    #         release_time = live_info["release_time"]
    #         logger.info(f"{vtb['nickname']}, {get_formatted_time_left(release_time)}")
    #         if vtb["uid"] not in timers:
    #             await add_timer(
    #                 vtb["nickname"],
    #                 vtb["uid"],
    #                 release_time,
    #                 vtb["sub_group"],
    #                 live_info["url"],
    #                 bot,
    #                 bind_data,
    #             )

    for ytb in ytb_data:
        logger.info("update youtube live info")
        live_info = await get_upcoming_youtube_live(ytb["id"])

        if live_info:
            release_time = live_info["release_time"]
            logger.info(f"{ytb['nickname']}, {get_formatted_time_left(release_time)}")
            if ytb["id"] not in timers:
                await add_timer(
                    ytb["nickname"],
                    ytb["id"],
                    release_time,
                    ytb["sub_group"],
                    live_info["url"],
                    bot,
                    bind_data,
                    live_info["title"],
                )
    logger.info("timers: ", timers)


def get_formatted_time_left(release_time):
    delay = release_time - datetime.datetime.now().timestamp()
    if delay <= 0:
        return "已经上机了，快去吧！"

    time_left = datetime.timedelta(seconds=int(delay))
    days, seconds = time_left.days, time_left.seconds
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)

    if days == 0 and hours == 0 and minutes == 0:
        return "马上就上机了，快去吧！"

    parts = []
    if days > 0:
        parts.append(f"{days}天")
    if hours > 0:
        parts.append(f"{hours}小时")
    if minutes > 0:
        parts.append(f"{minutes}分钟")

    if len(parts) < 1 and seconds > 0:
        parts.append(f"{seconds}秒")

    return "还有" + "".join(parts) + "配信"
