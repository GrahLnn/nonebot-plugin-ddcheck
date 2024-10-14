import time
from datetime import datetime, timezone, timedelta
from nonebot.log import logger
from DrissionPage import ChromiumOptions, ChromiumPage

from .config import ddcheck_config

auth_token = ddcheck_config.x_auth_token

cookie = {"domain": ".x.com", "name": "auth_token", "value": auth_token}

url = "https://x.com/MariaMari0nette"
# cookie = json.load(open("twitter_cookies.json"))

opt = ChromiumOptions().headless()
driver = ChromiumPage(opt)
driver.set.cookies(cookie)
driver.set.window.max()
driver.get(url)


def format_time_diff(seconds):
    td = timedelta(seconds=seconds)
    days, remainder = divmod(td.seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if td.days:
        parts.append(f"{td.days}天")
    if hours:
        parts.append(f"{hours}小时")
    if minutes:
        parts.append(f"{minutes}分钟")
    if seconds:
        parts.append(f"{seconds}秒")
    return "".join(parts)


def tw_content(tweet_ele):
    text_ele = tweet_ele.ele("@data-testid=tweetText", timeout=0)
    if not text_ele:
        return ""
    text_content = []
    for child in text_ele.children():
        if child.tag == "img":
            text_content.append(child.attr("alt"))
        elif child.tag == "a":
            text_content.append(child.raw_text.strip("…"))
        else:
            text_content.append(child.raw_text)
    return "".join(filter(None, text_content))


async def get_tweets(interval: int = 2):
    tweets_data = []
    driver.refresh()
    driver.scroll.to_bottom()
    time.sleep(3)
    # driver.scroll.to_bottom()
    # time.sleep(3)
    # 使用XPath查找推文的根元素，并按新到旧的顺序进行抓取
    tweet_elements = driver.eles('xpath://article[@data-testid="tweet"]')
    logger.info(f"find {len(tweet_elements)} tweets")
    # 逆序遍历推文元素列表，从最新的推文开始
    for tweet in tweet_elements:
        tweet_data = {}

        # 获取推文的文本内容
        tweet_data["text"] = tw_content(tweet)

        # 获取推文的日期
        date_element = tweet.ele("xpath:.//time")
        tweet_data["date"] = date_element.attr("datetime") if date_element else None
        if not tweet_data["date"]:
            continue
        dt = datetime.strptime(tweet_data["date"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc
        )

        # 将 datetime 对象转换为 Unix 时间戳
        timestamp = int(dt.timestamp())
        tweet_data["timestamp"] = timestamp

        current_dt = datetime.now(timezone.utc)
        current_timestamp = int(current_dt.timestamp())
        time_diff = current_timestamp - timestamp
        formatted_time_diff = format_time_diff(time_diff)
        logger.info(
            f"{tweet_data['date']}-{formatted_time_diff}前:\n{tweet_data['text']}"
        )
        # 检查时间差，跳过太旧的推文
        if time_diff > interval * 60:
            continue

        # 获取作者名称和用户名
        author_element = tweet.ele('xpath:.//div[@data-testid="User-Name"]')
        author_details = author_element.text.split("\n")
        tweet_data["author_name"] = author_details[0] if len(author_details) > 0 else ""
        tweet_data["author_handle"] = (
            author_details[1] if len(author_details) > 1 else ""
        )
        if tweet_data["author_handle"] != "@MariaMari0nette":
            continue
        # 获取推文链接
        tweet_link = tweet.ele('xpath:.//a[contains(@href, "/status/")]').attr("href")
        tweet_data["url"] = tweet_link

        # 获取推文中的图片链接
        image_elements = tweet.eles("xpath:.//img[@src]")
        image_urls = [
            img.attr("src").replace("?format=jpg&name=small", "?format=jpg&name=large")
            for img in image_elements
            if "pbs.twimg.com/media" in img.attr("src")
        ]
        tweet_data["images"] = image_urls if image_urls else None

        # 添加推文信息到列表中
        tweets_data.append(tweet_data)

    return tweets_data
