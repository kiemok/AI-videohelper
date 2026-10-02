"""PNG 元数据清理工具：消除 `libpng warning: iCCP: known incorrect sRGB profile`。

背景：部分软件保存的 PNG 会带一个不规范的 ``iCCP``（ICC 色彩配置文件）块，
任何基于 libpng 的程序（Qt/PySide6、PIL、ffmpeg、多数看图工具）读取时都会打印
``libpng warning: iCCP: known incorrect sRGB profile``。**该警告不影响显示与数据**，
若要彻底消除，需要把 PNG 里的 ``iCCP`` 块去掉（像素数据不变）。

用法（项目根目录）：：

    python scripts/png_clean.py                     # 扫描常见目录，列出含 iCCP 的图片
    python scripts/png_clean.py --fix               # 就地清理（自动备份为 .bak）
    python scripts/png_clean.py D:\\图片 --fix        # 指定目录或单个文件
    python scripts/png_clean.py D:\\图片 --fix --drop iCCP,tEXt,iTXt   # 指定要去除的块

实现为纯标准库（``struct`` + ``zlib``），只重写被丢弃的块，其余字节原样保留。
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: 默认要去除的块：iCCP（错误 sRGB 配置）。需要更干净时可加上 tEXt/zTXt/iTXt/eXIf
DEFAULT_DROP = ("iCCP",)

#: 绝对不允许删除的关键块
KEEP_REQUIRED = {"IHDR", "PLTE", "IDAT", "IEND"}


def iter_chunks(data: bytes):
    """遍历 PNG 块，产出 (类型, 数据, 原始字节)。"""
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("不是合法的 PNG 文件（签名不匹配）")
    offset = len(PNG_SIGNATURE)
    total = len(data)
    while offset + 8 <= total:
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        ctype = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > total:
            raise ValueError("PNG 结构损坏（块长度越界）")
        yield ctype.decode("ascii", "replace"), data[offset + 8 : offset + 8 + length], data[offset:end]
        offset = end
        if ctype == b"IEND":
            break


def inspect(path: Path) -> list[str]:
    """返回该 PNG 中含有的块名列表。"""
    return [name for name, _payload, _raw in iter_chunks(path.read_bytes())]


def clean(path: Path, drop: set[str], backup: bool = True) -> tuple[bool, list[str]]:
    """去掉指定块并重写文件；返回 (是否修改, 被去掉的块列表)。"""
    data = path.read_bytes()
    removed: list[str] = []
    out = bytearray(PNG_SIGNATURE)

    for name, _payload, raw in iter_chunks(data):
        if name in drop and name not in KEEP_REQUIRED:
            removed.append(name)
            continue
        if name in KEEP_REQUIRED:
            out += raw
            continue
        # 其余块原样保留；若其 CRC 本就损坏则重算，避免清理后仍报错
        payload = raw[8 : len(raw) - 4]
        crc = struct.unpack(">I", raw[-4:])[0]
        if crc != zlib.crc32(raw[4 : len(raw) - 4]) & 0xFFFFFFFF:
            out += struct.pack(">I", len(payload)) + name.encode("ascii") + payload
            out += struct.pack(">I", zlib.crc32(name.encode("ascii") + payload) & 0xFFFFFFFF)
        else:
            out += raw

    if not removed:
        return False, []
    if backup:
        path.with_suffix(path.suffix + ".bak").write_bytes(data)
    path.write_bytes(bytes(out))
    return True, removed


def collect_targets(args) -> list[Path]:
    if args.paths:
        targets: list[Path] = []
        for item in args.paths:
            p = Path(item)
            if p.is_dir():
                targets.extend(sorted(p.rglob("*.png")))
            elif p.is_file():
                targets.append(p)
        return targets
    # 默认扫描项目内的数据目录与桌面截图等常见位置
    roots = [Path("data"), Path("assets"), Path("docs")]
    found: list[Path] = []
    for root in roots:
        if root.exists():
            found.extend(sorted(root.rglob("*.png")))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="清理 PNG 中的 iCCP 块（消除 libpng 警告）")
    parser.add_argument("paths", nargs="*", help="要处理的文件或目录（默认扫描 data/、assets/、docs/）")
    parser.add_argument("--fix", action="store_true", help="就地清理（默认仅报告）")
    parser.add_argument(
        "--drop",
        default=",".join(DEFAULT_DROP),
        help=f"要去除的块名，逗号分隔（默认 {','.join(DEFAULT_DROP)}）",
    )
    parser.add_argument("--no-backup", action="store_true", help="不生成 .bak 备份")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    drop = {name.strip() for name in args.drop.split(",") if name.strip()}
    targets = collect_targets(args)
    if not targets:
        print("未找到 PNG 文件（可用位置参数指定目录）")
        return 0

    flagged = 0
    fixed = 0
    for path in targets:
        try:
            names = inspect(path)
        except (OSError, ValueError) as exc:
            print(f"跳过 {path}：{exc}")
            continue
        hits = sorted(set(names) & drop)
        if not hits:
            continue
        flagged += 1
        if not args.fix:
            print(f"[需清理] {path}  含块：{', '.join(hits)}")
            continue
        try:
            changed, removed = clean(path, drop, backup=not args.no_backup)
        except (OSError, ValueError) as exc:
            print(f"[失败] {path}：{exc}")
            continue
        if changed:
            fixed += 1
            print(f"[已清理] {path}  去除：{', '.join(removed)}")

    if not flagged:
        print(f"扫描 {len(targets)} 个 PNG，未发现需要清理的块（{', '.join(sorted(drop))}）")
        return 0
    if args.fix:
        print(f"完成：{fixed}/{flagged} 个文件已清理（原文件已备份为 *.png.bak）")
    else:
        print(f"发现 {flagged} 个文件含 {'/'.join(sorted(drop))} 块；加 --fix 参数即可清理")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
