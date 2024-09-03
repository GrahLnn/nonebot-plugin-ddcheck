import asyncio
from bilibili_api import user

async def get_upcoming_bili_live(uid):
    u = user.User(uid)
    data = await u.get_reservation()

    if data:
        space_info = await u.get_live_info()
        live_room_url = space_info["live_room"]["url"]
        dt_object = data[0]["live_plan_start_time"]
        return {
            "url": live_room_url,
            "release_time": dt_object,
        }
    else:
        return None

async def task_one():
    print("Task one started")
    info = await get_upcoming_bili_live(1217057066)
    print(f"Task one result: {info}")
    print("Task one finished")

async def task_two():
    print("Task two started")
    info = await get_upcoming_bili_live(5714273)
    print(f"Task two result: {info}")
    print("Task two finished")

async def main():
    task1 = asyncio.create_task(task_one())
    task2 = asyncio.create_task(task_two())

    await asyncio.gather(task1, task2)

if __name__ == "__main__":
    asyncio.run(main())
