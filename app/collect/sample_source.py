"""离线样例数据源。

用途：在爬虫实现之前，提供与真实接口结构一致的**平台原始字段**数据，
用于打通「采集 → 融合 → 存储 → 分析 → AI → 看板」全链路，并可导出 CSV 供人工替换。

数据为确定性生成（固定随机种子），包含：
- 双平台各 2 个创作者账号
- 每个账号若干作品，最近 N 天的每日累计指标快照（含爆款突增、平稳衰减两类曲线）
- 中文评论语料（正/负/中性，用于验证情感分析与词云）
"""

from __future__ import annotations

import csv
import math
import random
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.collect.contracts import RawBatch
from app.config import SAMPLE_DIR, platform_label

# --------------------------------------------------------------------------- #
# 样例画像与语料
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _Profile:
    platform: str
    uid: str
    nickname: str
    followers: int
    signature: str
    verified: bool
    topic: str
    base_views: int
    titles: tuple[str, ...]


_PROFILES: tuple[_Profile, ...] = (
    _Profile(
        platform="bilibili",
        uid="100001",
        nickname="科技老张",
        followers=132_000,
        signature="专注数码测评与效率工具，每周三更新",
        verified=True,
        topic="数码测评",
        base_views=41_000,
        titles=(
            "3000元档笔记本怎么选？实测6款后我悟了",
            "用了半年的效率神器，第3个你肯定没听过",
            "开学季显示器避坑指南：这4个参数别被忽悠",
            "自己组了台小主机，性能和静音能兼得吗",
            "AI工具真能帮我省下2小时/天？实测一周记录",
            "踩坑总结：买二手显卡前必须检查的5个地方",
        ),
    ),
    _Profile(
        platform="bilibili",
        uid="100002",
        nickname="数码小美",
        followers=48_600,
        signature="女生视角讲数码，讲人话不堆参数",
        verified=False,
        topic="数码测评",
        base_views=15_000,
        titles=(
            "手残党也能学会的手机摄影教程",
            "被问了100遍的桌面好物清单",
            "百元耳机能听出区别吗？盲测结果有点意外",
            "通勤党背包里到底装了什么",
            "手写笔记电子化，我的一套流程",
            "便宜一半的键盘手感差在哪",
        ),
    ),
    _Profile(
        platform="douyin",
        uid="200001",
        nickname="老张说科技",
        followers=286_000,
        signature="30秒讲明白一个数码知识点",
        verified=True,
        topic="数码测评",
        base_views=88_000,
        titles=(
            "手机卡顿？先关掉这3个开关 #数码",
            "为什么你的充电宝越充越慢 #科普",
            "买平板前先想清楚这1件事 #避坑",
            "这招让笔记本续航多2小时 #效率",
            "3秒教你清理手机垃圾 #手机技巧",
            "安卓传文件到电脑，最快的办法 #办公",
        ),
    ),
    _Profile(
        platform="douyin",
        uid="200002",
        nickname="美美Vlog",
        followers=63_500,
        signature="记录普通人的一天",
        verified=False,
        topic="生活方式",
        base_views=23_000,
        titles=(
            "打工人的周末实录 #vlog",
            "一个人吃饭也可以很治愈 #日常",
            "搬家第7天，房间终于有样子了 #家居",
            "月薪八千怎么存钱 #生活",
            "早起1小时，我的一天变了 #自律",
            "第一次尝试citywalk路线分享 #城市",
        ),
    ),
)

_POSITIVE_COMMENTS = (
    "讲得太清楚了",
    "已收藏",
    "干货满满",
    "实测过了确实香",
    "这个方法有用",
    "关注了",
    "性价比高",
    "太及时了",
    "讲得比参数好懂",
    "希望多出实测",
    "学到了",
    "讲得很专业",
)
_NEGATIVE_COMMENTS = (
    "结论太武断",
    "广告味重",
    "音质一般",
    "没讲重点",
    "价格虚高",
    "画面有点糊",
    "标题党",
    "误导人",
    "劝退",
    "实测翻车了",
)
_NEUTRAL_COMMENTS = (
    "沙发",
    "路过看看",
    "用得什么剪辑软件",
    "背景音乐叫什么",
    "期待下期",
    "第几个了",
    "来学习",
    "建议加字幕",
)
_NICKNAMES = (
    "路过的风", "会飞的鱼", "小张同学", "数字民工", "阿May", "键盘侠客",
    "打工人小陈", "晚风", "咸鱼翻身", "林深见鹿", "夜航船", "半糖主义",
)


# --------------------------------------------------------------------------- #
# 生成逻辑
# --------------------------------------------------------------------------- #
def _cumulative_curve(
    rng: random.Random, base_views: int, days_alive: int, viral_day: int | None
) -> list[int]:
    """返回某作品从发布日到今天的每日**累计**播放量序列（长度 days_alive）。

    形态贴近真实：发布后 1~3 天达到高峰，之后长尾衰减；若命中「爆款日」，
    当日增量会突增数倍（用于验证异常拐点检测）。
    """
    tau = rng.uniform(1.5, 3.0)  # 峰值位置（发布后第几天）
    weights = [pow(t + 1, 1.3) * math.exp(-(t + 1) / tau) for t in range(days_alive)]
    if viral_day is not None and 0 <= viral_day < days_alive:
        weights[viral_day] *= rng.uniform(3.0, 7.0)
    total_weight = sum(weights) or 1.0
    target = base_views * rng.uniform(1.5, 3.0)

    cumulative = 0
    series: list[int] = []
    for weight in weights:
        daily = target * weight / total_weight * rng.uniform(0.9, 1.1)
        cumulative += max(0, int(daily))
        series.append(cumulative)
    return series


def _ratios(rng: random.Random, platform: str) -> dict[str, float]:
    """不同平台互动行为差异（B站弹幕/收藏更活跃，抖音点赞/分享更活跃）。"""
    if platform == "bilibili":
        return {
            "like": rng.uniform(0.045, 0.085),
            "comment": rng.uniform(0.004, 0.010),
            "share": rng.uniform(0.004, 0.012),
            "favorite": rng.uniform(0.012, 0.030),
            "danmaku": rng.uniform(0.006, 0.018),
        }
    return {
        "like": rng.uniform(0.030, 0.070),
        "comment": rng.uniform(0.002, 0.007),
        "share": rng.uniform(0.006, 0.020),
        "favorite": rng.uniform(0.004, 0.014),
        "danmaku": 0.0,
    }


def _build_video_payload(
    rng: random.Random,
    profile: _Profile,
    index: int,
    video_id: str,
    pub_dt: datetime,
    today: date,
) -> dict[str, Any]:
    """构造单个作品的平台原始数据（B站/抖音字段名不同，模拟真实响应）。"""
    title = profile.titles[index % len(profile.titles)]
    days_alive = max(1, (today - pub_dt.date()).days + 1)
    viral_day = (
        rng.randrange(1, min(days_alive, 9))
        if days_alive > 4 and rng.random() < 0.45
        else None
    )
    views = _cumulative_curve(rng, profile.base_views, days_alive, viral_day)
    ratios = _ratios(rng, profile.platform)
    duration = rng.randrange(45, 420) if profile.platform == "bilibili" else rng.randrange(18, 90)
    favor_total = int(profile.followers * rng.uniform(0.4, 0.6))

    snapshots: list[dict[str, Any]] = []
    prev_followers = profile.followers
    for offset, view in enumerate(views):
        stat_date = pub_dt.date() + timedelta(days=offset)
        likes = int(view * ratios["like"])
        comments = int(view * ratios["comment"])
        shares = int(view * ratios["share"])
        favorites = int(view * ratios["favorite"])
        danmaku = int(view * ratios["danmaku"])
        fan_gain = int(max(0, view) * rng.uniform(0.0002, 0.0016))
        followers_now = prev_followers + fan_gain
        prev_followers = followers_now

        if profile.platform == "bilibili":
            raw = {
                "stat": {
                    "view": view,
                    "like": likes,
                    "reply": comments,
                    "share": shares,
                    "favorite": favorites,
                    "danmaku": danmaku,
                },
                "author_stat": {"follower": followers_now},
            }
        else:
            raw = {
                "statistics": {
                    "play_count": view,
                    "digg_count": likes,
                    "comment_count": comments,
                    "share_count": shares,
                    "collect_count": favorites,
                },
                "author_stat": {"follower_count": followers_now},
            }

        snapshots.append(
            {
                "stat_date": stat_date,
                "view_count": view,
                "like_count": likes,
                "comment_count": comments,
                "share_count": shares,
                "favorite_count": favorites,
                "danmaku_count": danmaku,
                "follower_gain": fan_gain,
                "raw": raw,
            }
        )

    # 评论：按情感倾向加权抽样，最新作品的评论更集中
    comments: list[dict[str, Any]] = []
    n_comments = rng.randrange(6, 16)
    pool = (
        list(_POSITIVE_COMMENTS) * 5 + list(_NEUTRAL_COMMENTS) * 3 + list(_NEGATIVE_COMMENTS) * 2
    )
    for i in range(n_comments):
        text = rng.choice(pool)
        cid = f"{profile.platform[:2]}_c_{video_id}_{i}"
        comments.append(
            {
                "platform_comment_id": cid,
                "content": text,
                "user_nickname": rng.choice(_NICKNAMES),
                "like_count": rng.randrange(0, 260),
                "publish_time": pub_dt + timedelta(days=rng.randrange(0, days_alive), hours=rng.randrange(1, 20)),
            }
        )

    if profile.platform == "bilibili":
        video_raw = {
            "bvid": video_id,
            "aid": int(video_id.replace("BV", "")) if video_id[2:].isdigit() else 0,
            "title": title,
            "desc": f"{profile.nickname} 的{topic_label(profile)}内容，欢迎三连支持~",
            "tag": [profile.topic, "数码", "实测"],
            "duration": duration,
            "pubdate": int(pub_dt.timestamp()),
            "pic": f"https://example.com/cover/{video_id}.jpg",
            "owner": {
                "mid": profile.uid,
                "name": profile.nickname,
                "follower": profile.followers,
                "official_verify": profile.verified,
                "sign": profile.signature,
                "total_favorited": favor_total,
            },
        }
    else:
        video_raw = {
            "aweme_id": video_id,
            "desc": f"{title} #{(profile.topic)}",
            "create_time": int(pub_dt.timestamp()),
            "duration": duration * 1000,
            "cover": {"url_list": [f"https://example.com/cover/{video_id}.jpg"]},
            "author": {
                "uid": profile.uid,
                "nickname": profile.nickname,
                "follower_count": profile.followers,
                "favoriting_count": favor_total,
                "custom_verify": "数码博主" if profile.verified else "",
                "signature": profile.signature,
            },
        }
    return {"video": video_raw, "snapshots": snapshots, "comments": comments}


def topic_label(profile: _Profile) -> str:
    return profile.topic


def build_sample_batch(
    days: int = 30, seed: int = 2024, platforms: tuple[str, ...] | None = None
) -> RawBatch:
    """生成一份完整样例数据集。"""
    rng = random.Random(seed)
    today = date.today()
    accounts: list[dict[str, Any]] = []
    videos: list[dict[str, Any]] = []

    for profile in _PROFILES:
        if platforms and profile.platform not in platforms:
            continue
        follower_now = profile.followers + int(profile.followers * rng.uniform(0.03, 0.12))
        if profile.platform == "bilibili":
            accounts.append(
                {
                    "mid": profile.uid,
                    "name": profile.nickname,
                    "follower": follower_now,
                    "following": rng.randrange(50, 600),
                    "total_favorited": int(follower_now * rng.uniform(0.4, 0.7)),
                    "official_verify": profile.verified,
                    "sign": profile.signature,
                    "home_url": f"https://space.bilibili.com/{profile.uid}",
                }
            )
        else:
            accounts.append(
                {
                    "uid": profile.uid,
                    "nickname": profile.nickname,
                    "follower_count": follower_now,
                    "following_count": rng.randrange(30, 400),
                    "favoriting_count": int(follower_now * rng.uniform(0.2, 0.5)),
                    "custom_verify": "优质创作者" if profile.verified else "",
                    "signature": profile.signature,
                    "home_url": f"https://www.douyin.com/user/{profile.uid}",
                }
            )

        for i, _ in enumerate(profile.titles):
            if profile.platform == "bilibili":
                video_id = f"BV1{profile.uid}{i:02d}"
            else:
                video_id = f"7{profile.uid}{i:02d}00"
            published_offset = rng.randrange(0, days)
            pub_dt = datetime.combine(
                today - timedelta(days=published_offset), datetime.min.time()
            ) + timedelta(hours=rng.randrange(9, 23), minutes=rng.randrange(0, 60))
            videos.append(_build_video_payload(rng, profile, i, video_id, pub_dt, today))

    batch = RawBatch(
        platform="*",
        accounts=accounts,
        videos=videos,
        source="sample",
    )
    return batch


# --------------------------------------------------------------------------- #
# CSV 导出
# --------------------------------------------------------------------------- #
_CSV_FIELDS: dict[str, tuple[str, ...]] = {
    "accounts.csv": (
        "platform", "platform_account_id", "nickname", "follower_count", "following_count",
        "total_favorite", "verified", "signature", "home_url",
    ),
    "videos.csv": (
        "platform", "platform_video_id", "account_platform_id", "title", "description",
        "tags", "content_type", "duration_sec", "publish_time", "cover_url", "video_url", "topic",
    ),
    "snapshots.csv": (
        "platform", "platform_video_id", "stat_date", "view_count", "like_count",
        "comment_count", "share_count", "favorite_count", "danmaku_count", "follower_gain",
    ),
    "comments.csv": (
        "platform", "platform_comment_id", "platform_video_id", "content",
        "user_nickname", "like_count", "publish_time",
    ),
}


def export_sample_csv(batch: RawBatch, out_dir: Path | None = None) -> dict[str, Path]:
    """把归一化后的样例数据导出为 CSV，方便查看/手工替换后再导入。"""
    from app.collect.fusion import normalize_account, normalize_comment, normalize_video

    out_dir = Path(out_dir or SAMPLE_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    account_rows: list[dict[str, Any]] = []
    video_rows: list[dict[str, Any]] = []
    snapshot_rows: list[dict[str, Any]] = []
    comment_rows: list[dict[str, Any]] = []

    for raw in batch.accounts:
        platform = "bilibili" if "mid" in raw else "douyin"
        account_rows.append(normalize_account(platform, raw))

    for item in batch.videos:
        platform = "bilibili" if "bvid" in item["video"] else "douyin"
        video = normalize_video(platform, item["video"])
        video_rows.append(video)
        for snap in item["snapshots"]:
            row = {
                "platform": platform,
                "platform_video_id": video["platform_video_id"],
                "stat_date": snap["stat_date"].isoformat(),
                "view_count": snap["view_count"],
                "like_count": snap["like_count"],
                "comment_count": snap["comment_count"],
                "share_count": snap["share_count"],
                "favorite_count": snap["favorite_count"],
                "danmaku_count": snap["danmaku_count"],
                "follower_gain": round(snap["follower_gain"], 2),
            }
            snapshot_rows.append(row)
        for raw_comment in item["comments"]:
            comment = normalize_comment(platform, raw_comment)
            comment["platform_video_id"] = video["platform_video_id"]
            comment_rows.append(comment)

    for name, rows in (
        ("accounts.csv", account_rows),
        ("videos.csv", video_rows),
        ("snapshots.csv", snapshot_rows),
        ("comments.csv", comment_rows),
    ):
        path = out_dir / name
        fields = _CSV_FIELDS[name]
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(fields), extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({k: _csv_value(row.get(k)) for k in fields})
        written[name] = path
    return written


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "|".join(str(v) for v in value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return int(value)
    return value


def exported_at() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def sample_source_hint() -> str:
    return f"样例数据来源：{platform_label('bilibili')} / {platform_label('douyin')} 模拟接口结构"
