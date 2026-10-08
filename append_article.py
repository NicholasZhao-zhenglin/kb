#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
往已生成的知识库 index.html 里「追加一篇文章」——不修改 build.py，也不重写外壳。

做法：
  1. 从 build.py 复用转换函数（shift_headings / ensure_heading_ids / prefix_anchors / outline_of …），
     不复制代码、不修改 build.py
  2. 读现有 index.html，解析出内联的 kb-data JSON
  3. 把 src/backend-scaffold.html 处理成条目对象，追加进去（按 id 幂等：已存在则替换）
  4. 只替换 <script id="kb-data"> 那一段，CSS / JS / HTML 外壳一字不动
  5. 跑断言后写回

用法：
    python3 append_article.py
    python3 append_article.py --dry-run     # 只打印将要发生什么，不写盘
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# 复用 build.py 里已有的实现 —— 只 import，不改它
from build import (  # noqa: E402
    shift_headings,
    ensure_heading_ids,
    prefix_anchors,
    outline_of,
    strip_tags,
    word_count,
)

INDEX = HERE / "index.html"
SRC = HERE / "src" / "backend-scaffold.html"

CAT = {
    "id": "backend-eng",
    "name": "服务端工程",
    "icon": "服",
    "desc": "从零拆解一个 FastAPI 后端骨架的每一层：配置、日志、异常体系、异步 ORM、"
            "依赖注入、外部服务封装、健康探针、数据库迁移。含实测踩坑与可复制的落地步骤。",
}

SPEC = {
    "id": "backend-scaffold",
    "cat": "backend-eng",
    "title": "FastAPI 后端脚手架拆解",
    "kicker": "agentic_rag-1/backend · 10 个模块 / 4 部分 / 15 章 · 从 uvicorn 到 pgvector 的逐层解剖",
    "summary": "把一个真实跑起来的 FastAPI 后端骨架拆开讲透：从「一次请求的完整旅程」入手，"
               "再逐层解剖配置、日志、异常体系、异步 ORM 会话、依赖注入、外部服务封装与健康探针，"
               "最后补上 Alembic 迁移、工程化缺口盘点和一份九步落地清单。"
               "文中四条踩坑记录（依赖名拼错却安装成功、缩进断裂导致属性消失、函数名差一个词、"
               "配置粘进 .py 忘了引号）都是这个项目上真实发生的，附运行时断言与复现命令。",
    "tags": ["FastAPI", "SQLAlchemy 2.0", "异步", "依赖注入", "pydantic-settings", "Alembic",
             "PostgreSQL", "pgvector", "uv", "uvicorn", "架构分层", "踩坑复盘", "健康检查"],
}

DATA_RE = re.compile(r'(<script id="kb-data" type="application/json">)(.*?)(</script>)', re.S)


def make_article(spec: dict, src_path: Path) -> dict:
    if not src_path.exists():
        sys.exit(f"× 源文档不存在：{src_path}")
    raw = src_path.read_text(encoding="utf-8")
    m = re.search(r"<main>(.*?)</main>", raw, re.S)
    if not m:
        sys.exit(f"× 源文档里找不到 <main>：{src_path}")
    main_html = m.group(1).strip()

    n_h = {t: len(re.findall(rf"<{t}\b", main_html)) for t in ("h1", "h2", "h3", "h4")}
    body = shift_headings(main_html, 1)
    body = ensure_heading_ids(body, spec["id"])
    body = prefix_anchors(body, spec["id"])
    ol = outline_of(body)
    plain = strip_tags(body)

    # 与 build.py 同源的断言：源 h1/h2/h3/h4 降一级后即目录的 1/2/3/4 级
    expect = [n_h[t] for t in ("h1", "h2", "h3", "h4")]
    got = [sum(1 for o in ol if o["lvl"] == k) for k in (1, 2, 3, 4)]
    assert got == expect, f"× 目录层级不对：{got} != {expect}"
    assert body.count("<pre>") == main_html.count("<pre>"), "× 代码块数量变了"
    assert "<h1" not in body, "× 正文里出现了 h1（条目标题已经占了 h1）"

    print(f"  [{spec['id']}] 源标题分布 {n_h} → 目录 {len(ol)} 项"
          f"（1级 {got[0]} / 2级 {got[1]} / 3级 {got[2]} / 4级 {got[3]}），正文 {word_count(plain)} 字")

    return {
        **spec,
        "html": body,
        "outline": ol,
        "words": word_count(spec["title"] + spec["summary"] + " ".join(spec["tags"]) + plain),
        "read": max(1, round(word_count(plain) / 400)),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只检查，不写盘")
    args = ap.parse_args()

    html = INDEX.read_text(encoding="utf-8")
    m = DATA_RE.search(html)
    if not m:
        sys.exit("× 在 index.html 里找不到内联数据块 <script id=\"kb-data\">")
    head, payload, tail = m.group(1), m.group(2), m.group(3)

    data = json.loads(payload.replace("<\\/", "</"))
    before_arts, before_cats = len(data["arts"]), len(data["cats"])

    print("追加条目前："
          f"{before_arts} 条 / {before_cats} 类 / {data['meta']['stats']['anchors']} 锚点")

    # 幂等：同 id 的旧条目先摘掉
    data["arts"] = [a for a in data["arts"] if a["id"] != SPEC["id"]]
    data["cats"] = [c for c in data["cats"] if c["id"] != CAT["id"]]

    data["cats"].append(CAT)
    art = make_article(SPEC, SRC)
    data["arts"].append(art)

    # 汇总统计
    all_ids = re.findall(
        r'<(?:h[1-6]|section)\b[^>]*?\sid="([^"]+)"', "".join(a["html"] for a in data["arts"])
    )
    assert len(all_ids) == len(set(all_ids)), "× 锚点 id 重复 → 前缀逻辑没生效"
    data["meta"]["stats"] = {
        "arts": len(data["arts"]),
        "cats": len(data["cats"]),
        "words": sum(a["words"] for a in data["arts"]),
        "tables": sum(a["html"].count("<table") for a in data["arts"]),
        "code": sum(a["html"].count("<pre>") for a in data["arts"]),
        "anchors": len(all_ids),
        "read": sum(a["read"] for a in data["arts"]),
    }
    data["meta"]["subtitle"] = "数据工程 · 服务端工程"
    data["meta"]["source"] = (
        "① IPC 数据下载与清洗手册（国知局《国际专利分类表》2026.01，8 部 PDF → 78,449 个结构化节点）"
        "　② FastAPI 后端脚手架拆解（agentic_rag-1/backend，10 个模块逐层解剖）"
    )

    # 断言：每个条目的分类必须存在，否则它在侧栏里会「消失」
    cat_ids = {c["id"] for c in data["cats"]}
    for a in data["arts"]:
        assert a["cat"] in cat_ids, f"× 条目 [{a['id']}] 引用了不存在的分类 {a['cat']}"
    for a in data["arts"]:
        body_ids = set(re.findall(r'id="([^"]+)"', a["html"]))
        for o in a["outline"]:
            assert o["id"] in body_ids, f"× [{a['id']}] 目录锚点 {o['id']} 在正文里不存在"

    content = "".join(a["html"] for a in data["arts"])
    assert "<h1" not in content, "× 正文里出现了 h1"
    assert content.count("<table") == content.count('<div class="tw"><table>'), "× 表格没套横滑容器"
    assert content.count("</table>") == content.count("</table></div>"), "× 表格容器没闭合"

    new_payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    new_payload = new_payload.replace("</", "<\\/")
    assert "</script" not in new_payload.lower(), "× 数据里出现了 </script"

    out = html[: m.start(2)] + new_payload + html[m.end(2) :]

    # 外壳必须一字未动：只换了中间那段 JSON
    assert out[: m.start(2)] == html[: m.start(2)] and out[m.end(2) + len(new_payload) - len(payload) :] == html[m.end(2) :], \
        "× 外壳被动到了"
    for pat in (r'<link\b[^>]*\bhref="(?!#)', r'<script\b[^>]*\bsrc=', r"@import"):
        assert not re.search(pat, out, re.I), f"× 出现了外部依赖：{pat}"

    print("追加条目后："
          f"{data['meta']['stats']['arts']} 条 / {data['meta']['stats']['cats']} 类 / "
          f"{data['meta']['stats']['anchors']} 锚点 / {data['meta']['stats']['words']} 字")
    print(f"  断言通过：锚点唯一 · 目录锚点全部存在 · 表格已包裹 · 零外部依赖 · JSON 可解析")

    if args.dry_run:
        print("\n[dry-run] 未写盘。")
        return

    INDEX.write_text(out, encoding="utf-8")
    kb = len(out.encode("utf-8")) / 1024
    print(f"\n✓ 已写回 {INDEX}（{kb:.1f} KB，原 {len(html.encode('utf-8')) / 1024:.1f} KB）")


if __name__ == "__main__":
    main()
