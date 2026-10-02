"""导入校验器单测：字段/数值判断、报告统计与 Markdown 渲染。"""

from __future__ import annotations

from app.collect.validation import (
    ERROR,
    WARNING,
    ValidationReport,
    first_value,
    is_number,
    write_report,
)


# ---------------------------------------------------------------------- #
# 基础判断
# ---------------------------------------------------------------------- #
def test_is_number_accepts_numeric_strings_and_thousands_separator():
    assert is_number(12)
    assert is_number(3.5)
    assert is_number("1,234")
    assert is_number(" 42 ")


def test_is_number_rejects_text_and_bool():
    assert not is_number("很多")
    assert not is_number("")
    assert not is_number(None)
    assert not is_number(True), "布尔值不应被当作数字"


def test_first_value_skips_empty_and_none():
    row = {"a": None, "b": "", "c": "命中"}
    assert first_value(row, "a", "b", "c") == "命中"
    assert first_value(row, "a", "b", "missing") == ""


# ---------------------------------------------------------------------- #
# 报告结构
# ---------------------------------------------------------------------- #
def test_report_starts_clean_and_summarizes():
    report = ValidationReport(source="单元测试仓库")
    assert report.is_clean
    assert "未发现问题" in report.summary()


def test_report_counts_errors_and_warnings():
    report = ValidationReport()
    report.error("账号", "accounts.csv:1", "缺少账号 ID", "补 mid")
    report.warn("作品", "videos.json:2", "标题为空")
    report.warn("评论", "comments.csv:3", "内容为空")

    assert not report.is_clean
    assert len(report.errors) == 1
    assert len(report.warnings) == 2
    summary = report.summary()
    assert "错误 1 处" in summary and "警告 2 处" in summary


def test_report_stats_bump():
    report = ValidationReport()
    report.bump("作品", "读取", 3)
    report.bump("作品", "导入", 2)
    report.bump("作品", "跳过")

    bucket = report.stats["作品"]
    assert bucket == {"读取": 3, "导入": 2, "跳过": 1}


def test_issue_line_marks_level_and_suggestion():
    report = ValidationReport()
    report.error("快照", "2026-09-28.csv:2", "作品 BV404 不在库中", "先导入该作品")
    line = report.errors[0].line()
    assert line.startswith("❌")
    assert "先导入该作品" in line

    report.warn("文件", "readme.csv", "未识别")
    warning_line = report.warnings[0].line()
    assert warning_line.startswith("⚠️")
    assert ERROR != WARNING


# ---------------------------------------------------------------------- #
# 报告渲染与落盘
# ---------------------------------------------------------------------- #
def test_to_dict_is_ui_friendly():
    report = ValidationReport(source="仓库")
    report.error("账号", "a.csv:1", "缺少账号 ID")
    payload = report.to_dict()

    assert payload["error_count"] == 1
    assert payload["warning_count"] == 0
    assert payload["errors"] and "缺少账号 ID" in payload["errors"][0]
    assert payload["report_path"] == ""


def test_to_markdown_contains_sections_and_hint():
    report = ValidationReport(source="仓库")
    report.files = {"accounts": 2, "videos": 1}
    report.unrecognized_files = ["notes.csv"]
    report.bump("账号", "读取", 5)
    report.warn("文件", "notes.csv", "命名未识别")
    markdown = report.to_markdown()

    assert "# 导入校验报告" in markdown
    assert "## 文件统计" in markdown
    assert "## 行统计" in markdown
    assert "## 问题清单" in markdown
    assert "重复导入不会产生重复数据" in markdown, "应提示修好数据后重新导入即可"


def test_write_report_creates_file_and_records_path(tmp_path):
    report = ValidationReport(source="仓库")
    report.warn("文件", "notes.csv", "命名未识别")

    path = write_report(report, directory=tmp_path)

    assert path is not None and path.is_file()
    assert report.report_path == path
    content = path.read_text(encoding="utf-8")
    assert "导入校验报告" in content
