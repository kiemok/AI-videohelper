"""AI 短剧提示词与本地回退。

三级生成链：**一句话梗概 → 分集大纲 → 分集剧本 → 分镜表**（含多模态提示词）。
无 API Key 时使用结构化模板生成骨架，保证流程与界面可用。
"""

from __future__ import annotations

from typing import Any

GENRES: tuple[str, ...] = (
    "都市逆袭",
    "悬疑反转",
    "职场成长",
    "甜宠恋爱",
    "玄幻修仙",
    "家庭伦理",
    "科幻脑洞",
)

SHOT_TYPES: tuple[str, ...] = ("远景", "全景", "中景", "近景", "特写", "空镜")

#: 单个镜头的时长（秒）；竖屏短剧普遍 2~4 秒一个镜头
DEFAULT_SHOT_SECONDS = (2, 3, 4)

SYSTEM_PROMPT = (
    "你是一名擅长抖音/B站竖屏短剧的编剧与分镜师，熟悉 3 秒钩子、强冲突、快节奏反转与结尾悬念的写法。"
    "输出使用简体中文，结构化、可直接拍摄执行；台词口语化，避免书面语。"
)


def build_outline_messages(project: dict[str, Any], episode_count: int) -> list[dict[str, str]]:
    user = (
        f"短剧项目：《{project.get('title')}》\n"
        f"题材：{project.get('genre')}｜目标平台：{project.get('target_platform')}｜"
        f"画幅：{project.get('aspect_ratio')}\n"
        f"一句话梗概：{project.get('logline') or '（待补充，请先设计核心冲突）'}\n"
        f"视觉风格：{project.get('style') or '（自定）'}\n\n"
        f"请设计 {episode_count} 集大纲，每集严格按以下格式输出：\n"
        "### 第N集 标题\n"
        "- 前 3 秒钩子：\n"
        "- 核心冲突：\n"
        "- 关键反转：\n"
        "- 结尾悬念：\n"
        "- 预计时长：秒"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def build_script_messages(project: dict[str, Any], episode: dict[str, Any]) -> list[dict[str, str]]:
    user = (
        f"短剧《{project.get('title')}》（{project.get('genre')}）"
        f"第 {episode.get('episode_no')} 集：{episode.get('title')}\n"
        f"钩子：{episode.get('hook')}\n冲突：{episode.get('core_conflict') or episode.get('outline')}\n"
        f"悬念：{episode.get('cliffhanger')}\n\n"
        "请写出可直接拍摄的分场剧本，要求：\n"
        "1) 标注场景（时间/地点/内外景）；\n"
        "2) 镜头级动作描述与台词（台词口语化）；\n"
        "3) 每场标注时长；\n"
        "4) 结尾保留悬念，并在末尾给出下集预告式一句话。"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def build_storyboard_messages(
    project: dict[str, Any], episode: dict[str, Any], shot_count: int
) -> list[dict[str, str]]:
    user = (
        f"短剧《{project.get('title')}》第 {episode.get('episode_no')} 集"
        f"（视觉风格：{project.get('style') or '写实都市'}）\n"
        f"请输出 {shot_count} 个镜头的分镜表，每行严格用竖线分隔：\n"
        "镜头号|景别|时长(秒)|画面描述|台词|文生图提示词(英文)|文生视频提示词(英文)\n\n"
        "要求：前 3 秒必须有视觉冲击的钩子镜头；镜头平均 2~4 秒；"
        "画面描述具体到人物动作、机位与光线；台词极简；提示词适合主流文生图/文生视频模型。"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


# --------------------------------------------------------------------------- #
# 本地回退（无 API Key）
# --------------------------------------------------------------------------- #
_NOTE = "> 未配置大模型 API Key，以下为本地模板生成（配置 Key 后自动切换为大模型创作）。\n"


def local_outline(project: dict[str, Any], episode_count: int) -> str:
    title = project.get("title") or "未命名短剧"
    genre = project.get("genre") or "都市逆袭"
    beats = ("身份反差被揭穿", "关键证据到手却被抢", "盟友背叛", "绝地反击", "真相反转", "阶段胜利留悬念")
    lines = [_NOTE, f"### 《{title}》{genre} · {episode_count} 集大纲（本地模板）"]
    for index in range(1, episode_count + 1):
        beat = beats[(index - 1) % len(beats)]
        lines.append(
            f"\n### 第{index}集 {beat}\n"
            f"- 前 3 秒钩子：主角在众目睽睽下被质疑，画面直接给出冲突结果\n"
            f"- 核心冲突：{beat}，对手施压，主角被逼到选择点\n"
            f"- 关键反转：出现一条此前埋下的信息，重新解释上一集的误会\n"
            f"- 结尾悬念：关键人物出现，留下一句未说完的话\n"
            f"- 预计时长：75 秒"
        )
    return "\n".join(lines)


def local_script(project: dict[str, Any], episode: dict[str, Any]) -> str:
    title = project.get("title") or "未命名短剧"
    episode_no = episode.get("episode_no") or 1
    hook = episode.get("hook") or "主角被当众质疑，冲突直接爆发"
    cliff = episode.get("cliffhanger") or "关键人物出现，留下未说完的话"
    return "\n".join(
        [
            _NOTE,
            f"## 《{title}》第 {episode_no} 集 剧本（本地模板）",
            "",
            "### 场 1｜日｜内｜公司会议室｜0:00-0:15",
            f"- 钩子镜头：{hook}",
            "- 台词（主角）：这件事我能解释，但你先看看这份文件。",
            "- 台词（对手）：你凭什么让我相信你？",
            "",
            "### 场 2｜日｜内｜走廊｜0:15-0:45",
            "- 主角独白式交代利害关系，节奏快切，插入闪回 2 秒。",
            "- 台词（配角）：你不该把底牌现在打出来。",
            "- 台词（主角）：不打出来，我今天就走不出这栋楼。",
            "",
            "### 场 3｜夜｜外｜天台｜0:45-1:15",
            "- 情绪转向，主角复盘线索，发现此前的破绽。",
            "- 台词（主角）：原来问题一直出在这一步。",
            "",
            "### 场 4｜夜｜内｜停车场｜1:15-1:20",
            f"- 悬念收尾：{cliff}",
            "",
            "> 下集预告：主角掌握的这份材料，会指向谁？",
        ]
    )


def local_storyboard(project: dict[str, Any], episode: dict[str, Any], shot_count: int) -> list[dict[str, Any]]:
    style = project.get("style") or "cinematic urban realism, 35mm, moody lighting"
    titles = [
        "主角被当众质疑，镜头快速推近表情",
        "对手摔下文件，特写手部动作",
        "主角捡起文件，环境音抽离",
        "闪回两秒，交代关键信息",
        "配角侧目，暗示立场变化",
        "主角走向窗边，逆光剪影",
        "手机屏幕特写，出现关键名字",
        "电话接通，双方沉默",
        "对手表情松动，动摇可察",
        "场景转换到天台，风起",
        "主角独白，镜头环绕",
        "线索拼合，快速剪辑三连",
        "反派登场，压迫式机位",
        "对峙升级，越肩镜头",
        "悬念定格，画面收缩变黑",
    ]
    dialogues = [
        "我能解释。",
        "你凭什么？",
        "（无台词）",
        "等一下…",
        "他不该现在摊牌。",
        "（无台词）",
        "这是谁的名字？",
        "（无台词）",
        "你赢了这一局。",
        "（无台词）",
        "问题出在这一步。",
        "全对上了。",
        "好久不见。",
        "你想清楚了？",
        "（留白）",
    ]
    rows: list[dict[str, Any]] = []
    for index in range(shot_count):
        shot_type = SHOT_TYPES[index % (len(SHOT_TYPES) - 1)]
        description = titles[index % len(titles)]
        dialogue = dialogues[index % len(dialogues)]
        rows.append(
            {
                "scene_no": index + 1,
                "shot_type": shot_type,
                "duration_sec": DEFAULT_SHOT_SECONDS[index % len(DEFAULT_SHOT_SECONDS)],
                "description": description,
                "dialogue": dialogue,
                "image_prompt": (
                    f"{style}, {shot_type} shot, {description}, "
                    f"vertical 9:16, shallow depth of field, high detail"
                ),
                "video_prompt": (
                    f"{shot_type} shot, {description}, subtle camera move, "
                    f"{DEFAULT_SHOT_SECONDS[index % len(DEFAULT_SHOT_SECONDS)]}s, cinematic color"
                ),
            }
        )
    return rows
