"""离线自检脚本：不启动界面，验证「采集/导入 → 存储 → 分析 → AI 解读」全链路。

用法（项目根目录）：
    .venv\\Scripts\\python.exe scripts\\smoke_check.py            # 用合成夹具数据跑全链路
    .venv\\Scripts\\python.exe scripts\\smoke_check.py --no-import # 只用已有数据

软件已**不含演示数据功能**：默认用 ``scripts/_fixture.py`` 生成的**最小合成数据集**
（2 账号 / 4 作品 / 数天快照与评论）跑通链路，仅用于自检。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/_fixture.py

from _fixture import write_fixture_repo  # noqa: E402
from app.ai import InsightService  # noqa: E402
from app.analysis import run_daily_analysis  # noqa: E402
from app.collect import archive_snapshots_csv, import_csv_dir  # noqa: E402
from app.datasource.loader import import_repository, scan_repository  # noqa: E402
from app.config import ensure_dirs, load_settings  # noqa: E402
from app.db.base import init_db  # noqa: E402
from app.db.repository import data_overview  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="多源数据融合与AI决策系统 - 离线自检")
    parser.add_argument("--no-import", action="store_true", help="跳过自检数据导入")
    parser.add_argument("--csv", action="store_true", help="额外验证 CSV 目录导入（幂等）")
    parser.add_argument("--days", type=int, default=5, help="自检快照天数（≥4 天才能覆盖趋势与拐点）")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ensure_dirs()
    settings = load_settings()
    db_url = settings.resolved_db_url()
    print(f"[1/6] 数据库：{db_url}")
    init_db(db_url)

    fixture: Path | None = None
    if not args.no_import:
        fixture = Path(tempfile.mkdtemp(prefix="ccd-smoke-"))
        write_fixture_repo(fixture, days=args.days)
        result = import_repository(db_url, scan_repository(fixture), source="自检夹具")
        print(f"[2/6] 自检数据导入：{result.summary()}")
        print(f"      夹具目录：{fixture}（脚本合成的自检数据，非产品功能）")
    else:
        print("[2/6] 跳过数据导入")

    if args.csv and fixture is not None:
        csv_result = import_csv_dir(db_url, fixture)
        print(f"[3/6] CSV 目录重新导入（幂等校验）：{csv_result.summary()}")
    else:
        print("[3/6] 跳过 CSV 导入")

    overview = data_overview(db_url)
    print(
        "[4/6] 数据总览：账号 {accounts}｜作品 {videos}｜快照 {snapshots}｜评论 {comments}"
        "｜分析日期 {date_min} ~ {date_max}".format(**overview)
    )

    metrics = run_daily_analysis(db_url)
    if not metrics:
        print("分析失败：没有数据")
        return 1
    print("[5/6] 分析结果：")
    print("      headline = " + json.dumps(metrics["headline"], ensure_ascii=False))
    print("      平台对比 = " + json.dumps(metrics["platform_compare"], ensure_ascii=False))
    print(f"      异常拐点 {len(metrics['anomalies'])} 条，热词 " + "、".join(k["word"] for k in metrics["keywords"][:8]))
    print("      评论情感 = " + json.dumps(
        {k: v for k, v in metrics["sentiment"].items() if k in ("total", "positive_ratio", "negative_ratio", "avg_score")},
        ensure_ascii=False,
    ))

    service = InsightService(settings, db_url)
    print("[6/6] AI 解读（" + service.status()["text"] + "）：")
    brief = service.daily_brief(metrics)
    print("      --- 数据简报 ---")
    print("\n".join("      " + line for line in brief["content"].splitlines()[:12]))
    answer = service.ask("抖音和B站哪个平台互动更好？", metrics)
    print("      --- 问答 ---")
    print("\n".join("      " + line for line in answer["content"].splitlines()[:6]))

    archive = archive_snapshots_csv(db_url)
    if archive:
        print(f"      历史归档：{archive}")
    print("自检完成 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
