import base64
import html
import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Union
from urllib.parse import urlparse

import httpx

# from DrissionPage import ChromiumOptions, ChromiumPage
from nonebot.log import logger
from poolctrl import Pool, RateLimitRule
from requests import RequestException
from retry import retry as lretry
from returns.maybe import Maybe, Nothing, Some
from tenacity import retry, stop_after_attempt, wait_fixed

from .config import ddcheck_config


def parse_cookie_string(cookie_str) -> Maybe[Dict[str, Any]]:
    cookie_dict = {}
    pairs = cookie_str.split(";")
    for pair in pairs:
        pair = pair.strip()
        if "=" in pair:
            key, value = pair.split("=", 1)
            cookie_dict[key.strip()] = value.strip()
    return Some(cookie_dict)


# auth_token = ""
tweet_api_key_rows = ddcheck_config.tweet_api_key
cookies = [
    parse_cookie_string(base64.b64decode(key).decode("utf-8")).unwrap()
    for key in tweet_api_key_rows.split(",")
]
pool = Pool(
    task_id="twcookies",
    limits=[
        RateLimitRule(max_requests=1, interval=10, time_unit="minute"),
    ],
)
# cookie = {"domain": ".x.com", "name": "auth_token", "value": auth_token}

# url = "https://x.com/MariaMari0nette"


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


def get(data, path: str):
    """从嵌套数据中根据路径获取字段值"""
    keys = path.split(".")
    for key in keys:
        if isinstance(data, dict) and key in data:
            data = data[key]
        elif isinstance(data, list):
            try:
                index = int(key)
                data = data[index] if abs(index) < len(data) else None
            except ValueError:
                return None
        else:
            return None
    return data


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


class Tweet:
    search_url = "https://x.com/i/api/graphql/nK1dw4oV3k4w5TdtcAdSww/SearchTimeline"
    auth_token = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"

    @retry(wait=wait_fixed(2), stop=stop_after_attempt(3))
    def user_tweet(self, id="1545351225293426688"):
        with pool.context(cookies) as cookie:
            endpoint = "https://x.com/i/api/graphql/9bXBrlmUXOHFZEq0DuvYWA/UserTweets"
            variables = json.dumps(
                {
                    "userId": id,
                    "includePromotedContent": False,
                    "withQuickPromoteEligibilityTweetFields": False,
                    "withVoice": False,
                    "withV2Timeline": False,
                }
            )
            features = json.dumps(
                {
                    "responsive_web_graphql_exclude_directive_enabled": True,
                    "verified_phone_label_enabled": True,
                    "responsive_web_home_pinned_timelines_enabled": False,
                    "creator_subscriptions_tweet_preview_api_enabled": True,
                    "responsive_web_graphql_timeline_navigation_enabled": True,
                    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
                    "tweetypie_unmention_optimization_enabled": True,
                    "responsive_web_edit_tweet_api_enabled": True,
                    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
                    "view_counts_everywhere_api_enabled": True,
                    "longform_notetweets_consumption_enabled": True,
                    "responsive_web_twitter_article_tweet_consumption_enabled": False,
                    "tweet_awards_web_tipping_enabled": False,
                    "freedom_of_speech_not_reach_fetch_enabled": True,
                    "standardized_nudges_misinfo": True,
                    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
                    "longform_notetweets_rich_text_read_enabled": True,
                    "longform_notetweets_inline_media_enabled": True,
                    "responsive_web_media_download_video_enabled": False,
                    "responsive_web_enhance_cards_enabled": False,
                }
            )
            headers = {
                "authorization": f"Bearer {self.auth_token}",
                "x-csrf-token": cookie.get("ct0", ""),
                "cookie": "; ".join([f"{k}={v}" for k, v in cookie.items()]),
            }
            with httpx.Client() as client:
                response = client.get(
                    endpoint,
                    headers=headers,
                    params={"variables": variables, "features": features},
                )
                response.raise_for_status()
            return response.json()

    def _best_quality_image(self, url: str) -> str:
        parsed = urlparse(url)
        basename = os.path.basename(parsed.path)
        # Get the path component and extract the asset name
        asset_name = basename.split(".")[0]
        # Get the file extension
        extension = basename.split(".")[-1]
        return f"https://pbs.twimg.com/media/{asset_name}?format={extension}&name=4096x4096"

    # @snoop
    def _filter(self, data: Union[Dict[str, Any], List[Any]]) -> Dict[str, Any]:
        def remove_urls(text: str, urls: List[str]) -> str:
            """
            只移除在 text 尾部出现、并且属于 urls 列表中的 URL。
            urls 可能很多，所以这里先按长度倒序排一下，
            防止出现较短 URL 先匹配把长 URL 给拆了的情况。
            """
            # 如果urls为None或为空，直接返回原始文本

            # 先对要匹配的 urls 根据长度倒序排列，防止长的被短的覆盖
            urls_sorted = sorted(set([u for u in urls if u]), key=len, reverse=True)

            # 由于可能末尾连续存在多个 URL，我们用 while 循环一直砍到不匹配为止
            while True:
                # 去掉末尾多余空格（有些末尾 URL 前面可能留有空格或换行）
                stripped_text = text.rstrip()
                if stripped_text == text:
                    # 如果没有额外空格，那就直接检查 URL
                    pass
                else:
                    # 如果发生了 rstrip，则更新 text
                    text = stripped_text

                found = False
                for url in urls_sorted:
                    if text.endswith(url):
                        # 如果末尾匹配，去掉该 URL，并把末尾再做一次 rstrip
                        text = text[: -len(url)].rstrip()
                        found = True
                        # 这里 break 是因为一次只移除一个匹配 URL，移除后再从头来
                        break
                if not found:
                    # 末尾不再匹配任何 URL 就结束
                    break

            return text

        def get_format_content(data: Dict[str, Any]):
            # 原始文本获取
            text_content: str = get(
                data, "note_tweet.note_tweet_results.result.text"
            ) or get(data, "legacy.full_text")

            # 收集所有需要处理的 URL（要替换成什么这里先不管）
            url_replacements = {
                ("legacy.quoted_status_permalink.url", ""): "",
                ("card.rest_id", ""): "",
                ("legacy.entities.media", "url"): "",
                ("legacy.entities.urls", "url"): "expanded_url",
                (
                    "note_tweet.note_tweet_results.result.entity_set.urls",
                    "url",
                ): "expanded_url",
                ("legacy.quoted_status_permalink.expanded", ""): "",
            }

            # 用来保存要在末尾检测并移除的 url
            urls_for_removal = []

            # 这个 expanded_urls 你原本是用来收集真正的 "expanded_url" 的
            expanded_urls = []
            card = parse_card(data)
            card and urls_for_removal.append(card.get("url"))
            article = parse_article(data)

            for (path, url_key), expanded_key in url_replacements.items():
                result = get(data, path)
                if not result:
                    continue
                # 如果是字符串，说明只有一个 url
                if isinstance(result, str):
                    urls_for_removal.append(result)
                else:
                    # 否则就认为是 list
                    for url_item in result:
                        url_val = url_item.get(url_key) if url_key else url_item
                        expanded_val = (
                            url_item.get(expanded_key) if expanded_key else ""
                        )

                        if expanded_val:
                            text_content = text_content.replace(url_val, expanded_val)
                            article and urls_for_removal.append(
                                article.get("id") in expanded_val and expanded_val
                            )
                            expanded_urls.append(expanded_val)
                        else:
                            urls_for_removal.append(url_val)

            content = remove_urls(text_content, urls_for_removal)

            return {
                "text": html.unescape(content).strip(),
                "expanded_urls": list(set(expanded_urls)),
            }

        def parse_media(_data):
            return (m := get(_data, "legacy.entities.media")) and (
                [
                    {
                        **{
                            "type": t,
                            "url": (
                                max(
                                    get(e, "video_info.variants") or [],
                                    key=lambda x: int(x.get("bitrate", 0) or 0),
                                    default={},
                                ).get("url")
                            ),
                            "aspect_ratio": get(e, "video_info.aspect_ratio"),
                            "thumb": get(e, "media_url_https"),
                        },
                        **(
                            {"duration_millis": get(e, "video_info.duration_millis")}
                            if t == "video"
                            else {}
                        ),
                    }
                    if (t := get(e, "type")) in ["animated_gif"]
                    else {
                        "type": t,
                        "url": self._best_quality_image(get(e, "media_url_https")),
                    }
                    for e in m
                ]
            )

        def parse_article(_data):
            return (a := get(_data, "article.article_results.result")) and (
                {
                    "id": get(a, "rest_id"),
                    "title": get(a, "title"),
                    "description": get(a, "preview_text") + "...",
                    "url": "https://x.com/i/status/" + get(a, "rest_id"),
                }
            )

        def parse_card(_data):
            def get_binding_value(key):
                return next(
                    (
                        get(b, "value.string_value")
                        for b in get(card, "legacy.binding_values")
                        if b.get("key") == key
                    ),
                    None,
                )

            def get_expanded_url(card_url):
                return next(
                    (
                        get(r, "expanded_url")
                        for r in get(_data, "legacy.entities.urls")
                        if r.get("url") == card_url
                    ),
                    None,
                )

            if not (card := get(_data, "card")) or (
                "card://" in get(_data, "card.rest_id")
            ):
                return None

            title = get_binding_value("title")
            description = get_binding_value("description")
            card_url = get_binding_value("card_url")
            url = get_expanded_url(card_url)

            return {"title": title, "description": description, "url": url}

        def parse_author(_data):
            return {
                "name": get(_data, "core.user_results.result.legacy.name"),
                "screen_name": get(
                    _data, "core.user_results.result.legacy.screen_name"
                ),
                "avatar": {
                    "url": get(
                        _data, "core.user_results.result.legacy.profile_image_url_https"
                    )
                },
            }

        def parse_tweet(_data):
            return _data and {
                "rest_id": get(_data, "rest_id"),
                "author": parse_author(_data),
                "created_at": get(_data, "legacy.created_at"),
                "content": {
                    **get_format_content(_data),
                    **{"lang": get(_data, "legacy.lang")},
                },
                "media": parse_media(_data),
                "card": parse_card(_data),
                "article": parse_article(_data),
            }

        quote_data = get(data, "quoted_status_result.result.tweet") or get(
            data, "quoted_status_result.result"
        )
        quote = (
            None
            if not quote_data or quote_data.get("__typename") == "TweetTombstone"
            else quote_data
        )
        return {**parse_tweet(data), "quote": parse_tweet(quote)}


async def get_tweets(interval: int = 2):
    tweets_data = []
    tweet = Tweet()
    user = "MariaMari0nette"
    data = tweet.user_tweet()
    tweets = [
        tweet._filter(detail)
        for t in next(
            instruction
            for instruction in get(
                data,
                "data.user.result.timeline.timeline.instructions",
            )
            if instruction.get("type") == "TimelineAddEntries"
        ).get("entries")
        if (
            detail := get(t, "content.itemContent.tweet_results.result.tweet")
            or get(t, "content.itemContent.tweet_results.result")
        )
    ]
    for t in tweets:
        time_format = "%a %b %d %H:%M:%S %z %Y"
        ttime = datetime.strptime(get(t, "created_at"), time_format)
        fil = {
            "text": get(t, "content.text"),
            "medias": [{"url": m.get("url"), "type": m.get("type")} for m in medias]
            if (medias := t.get("media"))
            else None,
            "quote": {
                "text": get(t, "quote.content.text"),
                "medias": [{"url": m.get("url"), "type": m.get("type")} for m in medias]
                if (medias := get(t, "quote.media"))
                else None,
            }
            if t.get("quote")
            else None,
        }
        # print(json.dumps(fil, ensure_ascii=False))
        if (datetime.now(timezone.utc) - ttime).total_seconds() > interval * 60 or get(
            t, "author.screen_name"
        ) != user:
            continue
        print(datetime.now(timezone.utc), ttime, json.dumps(fil, ensure_ascii=False))
        tweets_data.append(fil)
    return tweets_data
