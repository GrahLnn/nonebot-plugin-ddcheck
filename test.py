import asyncio
from bilibili_api import user


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


if __name__ == "__main__":
    info = asyncio.run(get_upcoming_bili_live(5714273))
    print(info)
