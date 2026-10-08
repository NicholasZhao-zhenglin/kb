#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
个人知识库生成器 —— 把《IPC 数据下载与清洗手册》拆成分类条目，产出 0 依赖单文件知识库。

用法：
    python3 build.py                 # 用默认源文件重新生成 index.html
    python3 build.py --src X.html --out Y.html

设计要点：
  * 输出为单个自包含 HTML（CSS/JS/数据全内联），file:// 直接打开，无网络、无 CDN
  * 源文档按 <h2> 切分为独立条目；每条锚点加 <条目id>-- 前缀，避免多文档合并 id 冲突
  * 条目内 h3→h2、h4→h3 降一级（条目标题由阅读器渲染，正文里不该再有一级标题）
  * 内容逐字保留，不做改写
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_SRC = Path("/Users/yangqijun/patent_dev/ipc/docs/IPC数据下载与清洗手册.html")
DEFAULT_OUT = HERE / "index.html"


# --------------------------------------------------------------------------
# 1. 分类体系 + 条目登记表（源文档第 N 个 <h2> 片段 → 知识库条目）
# --------------------------------------------------------------------------
CATS = [
    {
        "id": "data-eng",
        "name": "数据工程",
        "icon": "数",
        "desc": "把非规整的官方文档（PDF / 年报 / 标准 / 分类表 / 法规）变成可用的结构化数据："
                "下载、解析、清洗、自检、验收的完整方法与踩坑记录。",
    },
]

# 原文整篇作为一个条目放进知识库 —— 不拆分。
# 需要再放别的知识时，往这里追加（并可用侧栏「导入 JSON」追加到浏览器本地）。
ARTICLES = [
    {
        "id": "ipc-handbook",
        "cat": "data-eng",
        "title": "IPC 数据下载与清洗手册",
        "kicker": "国知局《国际专利分类表》2026.01 · 8 部 PDF / 1,890 页 → 78,449 个结构化节点",
        "summary": "从国知局 8 部 PDF 到 78,449 个结构化节点的完整记录：前半是通用 SOP"
                   "（先决策、五个阶段、四层纯函数清洗、数字断言自检、抽样验收），"
                   "后半是真实踩坑复盘（3 个下载坑、7 个解析坑、1 次把 bug 修得更大的事故）"
                   "以及每一步的量化证据。",
        "tags": ["IPC", "国知局", "PDF 解析", "数据清洗", "ETL", "SOP", "踩坑复盘", "结构化抽取", "专利"],
    },
]



# --------------------------------------------------------------------------
# 2. 解析源文档（整篇作为一个条目，不拆分）
# --------------------------------------------------------------------------
def shift_headings(body: str, delta: int = 1) -> str:
    """把正文里的标题整体降 delta 级：h1→h2、h2→h3、h3→h4、h4→h5。

    条目自己的标题由阅读器渲染成 h1，正文里不能再出现一级标题，
    否则页面的标题层级会出现两个 h1。

    必须**从最深层往浅层**替换：先 h4→h5，再 h3→h4 …… 最后 h1→h2。
    反过来写会把刚降下来的标题再降一次，全篇塌成同一个级别。
    """
    for lvl in range(4, 0, -1):
        body = body.replace(f"<h{lvl}", f"<h{lvl + delta}").replace(
            f"</h{lvl}>", f"</h{lvl + delta}>"
        )
    return body


def ensure_heading_ids(body: str, art_id: str) -> str:
    """保证每个标题都带 id。

    原文档里「第一部分 / 第二部分」的锚点挂在包裹它们的 <section> 上，
    标题标签本身没有 id —— 不补的话这两级会直接从目录里消失。
    """
    # 1) 部分标题：借外层 section 的 id
    body = re.sub(
        r'(<section\b[^>]*\sid="([^"]+)">\s*)(<h[1-6]\b(?![^>]*\sid=)[^>]*>)',
        lambda m: m.group(1)
        + re.sub(r"^<(h[1-6])", rf'<\1 id="{m.group(2)}-title"', m.group(3), count=1),
        body,
    )
    # 2) 兜底：仍然没有 id 的标题，按出现顺序给个稳定 id
    n = [0]

    def fallback(m):
        n[0] += 1
        return re.sub(r"^<(h[1-6])", rf'<\1 id="{art_id}--auto-{n[0]}"', m.group(0), count=1)

    body = re.sub(r"<h[1-6]\b(?![^>]*\sid=)[^>]*>", fallback, body)
    leftover = re.findall(r"<h[1-6]\b(?![^>]*\sid=)[^>]*>", body)
    assert not leftover, f"× 仍有标题没有 id：{leftover[:3]}"
    return body


def prefix_anchors(body: str, art_id: str) -> str:
    """给锚点 id 加条目前缀（防多文档合并时 id 冲突），内部链接同步改。"""
    body = re.sub(r'(<(?:h[1-6]|section)\b[^>]*?\s)id="([^"]+)"', rf'\1id="{art_id}--\2"', body)
    return re.sub(r'href="#([^"]+)"', rf'href="#{art_id}--\1"', body)


def outline_of(body: str) -> list[dict]:
    """抽取目录树：h2→1 级（部）、h3→2 级（章）、h4→3 级、h5→4 级。"""
    out = []
    for m in re.finditer(r"<(h[2-5])\b([^>]*)>(.*?)</\1>", body, re.S):
        tag, attrs, inner = m.group(1), m.group(2), m.group(3)
        idm = re.search(r'id="([^"]+)"', attrs)
        text = htmllib.unescape(re.sub(r"<[^>]+>", "", inner)).strip()
        if not text or not idm:
            continue
        out.append({"lvl": int(tag[1]) - 1, "text": text, "id": idm.group(1)})
    return out


def strip_tags(s: str) -> str:
    s = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", s, flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", htmllib.unescape(s)).strip()


def word_count(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text)) + len(re.findall(r"[A-Za-z0-9_]+", text))


def build_data(src: Path) -> dict:
    raw = src.read_text(encoding="utf-8")
    m = re.search(r"<main>(.*?)</main>", raw, re.S)
    if not m:
        sys.exit("× 源文件里找不到 <main>")
    main_html = m.group(1).strip()

    # 原文自带的那套 <nav class="toc"> 不用：知识库的目录是从真实标题现生成的，
    # 少一份需要同步维护的重复清单，也彻底避开多份文档合并时的锚点冲突。
    n_h = {t: len(re.findall(rf"<{t}\b", main_html)) for t in ("h1", "h2", "h3", "h4")}
    print(f"  源文档标题分布：{n_h}")

    arts = []
    for spec in ARTICLES:
        art_id = spec["id"]
        body = shift_headings(main_html, 1)
        body = ensure_heading_ids(body, art_id)
        body = prefix_anchors(body, art_id)
        plain = strip_tags(body)
        arts.append({
            **spec,
            "html": body,
            "outline": outline_of(body),
            "words": word_count(spec["title"] + spec["summary"] + " ".join(spec["tags"]) + plain),
            "read": max(1, round(word_count(plain) / 400)),
        })
        ol = arts[-1]["outline"]
        print(f"    [{art_id}] {spec['title']} —— 正文 {word_count(plain)} 字，"
              f"目录 {len(ol)} 项（1级 {sum(1 for o in ol if o['lvl'] == 1)}"
              f" / 2级 {sum(1 for o in ol if o['lvl'] == 2)}"
              f" / 3级 {sum(1 for o in ol if o['lvl'] == 3)}"
              f" / 4级 {sum(1 for o in ol if o['lvl'] == 4)}）")

    ids = [a["id"] for a in arts]
    assert len(ids) == len(set(ids)), "条目 id 重复"
    all_ids = re.findall(
        r'<(?:h[1-6]|section)\b[^>]*?\sid="([^"]+)"', "".join(a["html"] for a in arts)
    )
    assert len(all_ids) == len(set(all_ids)), "锚点 id 重复 → 前缀逻辑没生效"

    stat = {
        "arts": len(arts),
        "cats": len(CATS),
        "words": sum(a["words"] for a in arts),
        "tables": sum(a["html"].count("<table") for a in arts),
        "code": sum(a["html"].count("<pre>") for a in arts),
        "anchors": len(all_ids),
        "read": sum(a["read"] for a in arts),
    }
    print(f"  统计：{stat}")

    return {
        "meta": {
            "title": "个人知识库",
            "subtitle": "数据工程 · 结构化抽取",
            "built": "2026-09-21",
            "source": "IPC 数据下载与清洗手册（国知局《国际专利分类表》2026.01，8 部 PDF → 78,449 个结构化节点）",
            "stats": stat,
        },
        "cats": CATS,
        "arts": arts,
    }


# --------------------------------------------------------------------------
# 3. 外壳：CSS + HTML + JS（全部内联）
# --------------------------------------------------------------------------
CSS = r"""
*,*::before,*::after{box-sizing:border-box}
:root{
  --side-w:280px;
  --sans:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",system-ui,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,"PingFang SC",monospace;
  --r:10px; --r-sm:7px;
  --fs:16px;
}
html[data-theme="light"]{
  --bg:#ffffff; --bg-soft:#f7f7f4; --side:#fbfbf9; --card:#ffffff;
  --text:#1e1e1c; --text-2:#5f5f59; --muted:#8b8b84; --border:#e7e6e1; --border-2:#f0efeb;
  --accent:#185FA5; --accent-2:#0f4a85; --accent-soft:#eaf1f9; --accent-line:#cfe0f2;
  --note-bg:#fdf8ee; --note-br:#c98a1e; --note-fg:#4a3a1a;
  --code-bg:#f6f6f3; --mark:#ffe9a8; --shadow:0 1px 2px rgba(20,20,20,.05),0 8px 24px rgba(20,20,20,.06);
}
html[data-theme="dark"]{
  --bg:#15171a; --bg-soft:#1b1e22; --side:#191c20; --card:#1c1f24;
  --text:#e7e7e3; --text-2:#a8a8a2; --muted:#7d7d78; --border:#2b2f35; --border-2:#22262b;
  --accent:#6aa9e0; --accent-2:#8dc0ee; --accent-soft:#1c2733; --accent-line:#2b3d51;
  --note-bg:#2a2618; --note-br:#c9a24a; --note-fg:#e3d9be;
  --code-bg:#1b1f24; --mark:#5c4a12; --shadow:0 1px 2px rgba(0,0,0,.3),0 8px 24px rgba(0,0,0,.35);
}
html{-webkit-text-size-adjust:100%}
body{
  margin:0;height:100vh;height:100dvh;background:var(--bg);color:var(--text);
  font:var(--fs)/1.75 var(--sans);overflow:hidden;
  display:grid;grid-template-columns:var(--side-w) minmax(0,1fr);grid-template-rows:auto minmax(0,1fr);
  grid-template-areas:"top top" "side main";
  transition:background .18s,color .18s;
}
a{color:var(--accent)}
button{font:inherit;color:inherit;background:none;border:0;cursor:pointer}
mark{background:var(--mark);color:inherit;border-radius:3px;padding:0 2px}
::-webkit-scrollbar{width:9px;height:9px}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:5px}
::-webkit-scrollbar-thumb:hover{background:var(--muted)}
::-webkit-scrollbar-track{background:transparent}

/* ---------- 顶栏 ---------- */
#topbar{
  grid-area:top;display:flex;align-items:center;gap:12px;padding:0 16px;height:56px;
  background:var(--side);border-bottom:1px solid var(--border);z-index:40;
}
#menu-btn{display:none}
.icon-btn{
  width:34px;height:34px;border-radius:var(--r-sm);color:var(--text-2);
  display:inline-flex;align-items:center;justify-content:center;font-size:14px;
  transition:background .12s,color .12s;flex:none;
}
.icon-btn:hover{background:var(--bg-soft);color:var(--text)}
.icon-btn:active{transform:translateY(1px)}
.brand{
  display:flex;align-items:center;gap:9px;text-decoration:none;color:var(--text);
  font-weight:650;font-size:15px;letter-spacing:-.2px;flex:none;padding:4px 6px;border-radius:var(--r-sm);
}
.brand:hover{background:var(--bg-soft)}
.brand .dot{width:9px;height:9px;border-radius:50%;background:var(--accent);flex:none}
.brand small{color:var(--muted);font-weight:400;font-size:12.5px;
  padding-left:10px;margin-left:3px;border-left:1px solid var(--border)}
#searchwrap{flex:1;max-width:620px;margin-left:auto;position:relative}
#q{
  width:100%;height:36px;padding:0 62px 0 34px;border:1px solid var(--border);border-radius:999px;
  background:var(--bg);color:var(--text);font:14px var(--sans);outline:none;transition:border-color .15s,box-shadow .15s;
}
#q::placeholder{color:var(--muted)}
#q:focus{border-color:var(--accent-line);box-shadow:0 0 0 3px var(--accent-soft)}
#searchwrap .i{position:absolute;left:12px;top:50%;transform:translateY(-50%);color:var(--muted);pointer-events:none;font-size:13px}
#searchwrap kbd{
  position:absolute;right:9px;top:50%;transform:translateY(-50%);font:11px var(--mono);
  color:var(--muted);border:1px solid var(--border);border-bottom-width:2px;border-radius:5px;padding:1px 5px;background:var(--bg-soft);
}
#topbar .tools{display:flex;gap:2px;flex:none;margin-left:auto}

/* ---------- 侧栏 ---------- */
#side{
  grid-area:side;overflow-y:auto;overscroll-behavior:contain;background:var(--side);
  border-right:1px solid var(--border);padding:14px 10px 40px;
}
.snav{display:flex;flex-direction:column;gap:1px;margin-bottom:14px}
.snav a{
  display:flex;align-items:center;gap:9px;padding:7px 10px;border-radius:var(--r-sm);
  color:var(--text-2);text-decoration:none;font-size:13.5px;transition:background .12s,color .12s;
}
.snav a:hover{background:var(--bg-soft);color:var(--text)}
.snav a.on{background:var(--accent-soft);color:var(--accent);font-weight:600}
.snav a .n{margin-left:auto;font:11px var(--mono);color:var(--muted)}
.sgroup{margin:0 0 10px}
.sgroup>summary{
  display:flex;align-items:center;gap:7px;cursor:pointer;list-style:none;
  font-size:11.5px;font-weight:700;letter-spacing:.07em;color:var(--muted);
  padding:8px 10px 6px;text-transform:uppercase;
}
.sgroup>summary::-webkit-details-marker{display:none}
.sgroup>summary::after{
  content:"›";margin-left:auto;font-size:15px;line-height:1;color:var(--muted);
  transition:transform .15s;transform:rotate(90deg);
}
.sgroup:not([open])>summary::after{transform:rotate(0)}
.catblk{margin-bottom:6px}
.catblk>.chead{
  display:flex;align-items:center;gap:8px;width:100%;padding:7px 10px;border-radius:var(--r-sm);
  font-size:13px;font-weight:640;color:var(--text);text-align:left;line-height:1.45;
}
.catblk>.chead:hover{background:var(--bg-soft)}
.catblk>.chead .badge{
  flex:none;font:10px/16px var(--mono);font-weight:700;letter-spacing:.03em;
  padding:1px 6px;border-radius:5px;background:var(--accent-soft);color:var(--accent);height:18px;
}
.catblk>.chead .cnt{margin-left:auto;font:11px var(--mono);color:var(--muted)}
.catblk>.chead .arw{flex:none;color:var(--muted);font-size:14px;transition:transform .15s}
.catblk.collapsed>.chead .arw{transform:rotate(-90deg)}
.clist{display:flex;flex-direction:column;gap:1px;padding:2px 0 4px 10px;margin-left:9px;border-left:1px solid var(--border)}
.catblk.collapsed .clist{display:none}
.clist a{
  display:flex;gap:8px;align-items:baseline;padding:6px 9px;border-radius:var(--r-sm);
  color:var(--text-2);text-decoration:none;font-size:13px;line-height:1.5;
}
.clist a:hover{background:var(--bg-soft);color:var(--text)}
.clist a.on{background:var(--accent-soft);color:var(--accent);font-weight:600}
.clist a .fav{color:#e0a52a;font-size:11px;flex:none}
.catdesc{padding:2px 10px 8px;font-size:11.5px;line-height:1.6;color:var(--muted);
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
#side .sfoot{
  margin-top:18px;padding:12px 10px 0;border-top:1px solid var(--border);
  display:flex;flex-wrap:wrap;gap:6px;
}
#side .sfoot button{
  font-size:12px;padding:5px 10px;border:1px solid var(--border);border-radius:999px;color:var(--text-2);background:var(--bg);
}
#side .sfoot button:hover{border-color:var(--accent-line);color:var(--accent)}
#side .meta-line{padding:10px 10px 0;font-size:11px;color:var(--muted);line-height:1.7}

/* ---------- 主区 ---------- */
#main{grid-area:main;overflow-y:auto;overscroll-behavior:contain;scroll-behavior:smooth}
#progress{position:fixed;top:0;left:0;height:2px;background:var(--accent);width:0;z-index:60;transition:width .1s linear;pointer-events:none}
.page{max-width:920px;margin:0 auto;padding:34px 40px 90px}

/* 文章 */
.crumbs{display:flex;align-items:center;gap:7px;font-size:12.5px;color:var(--muted);margin-bottom:14px;flex-wrap:wrap}
.crumbs a{color:var(--muted);text-decoration:none}
.crumbs a:hover{color:var(--accent)}
.crumbs .sep{opacity:.5}
.doc h1{font-size:27px;line-height:1.35;margin:0 0 8px;font-weight:680;letter-spacing:-.4px}
.kicker{color:var(--muted);font-size:13.5px;margin:0 0 12px;font-weight:500}
.lede{
  color:var(--text-2);font-size:15px;line-height:1.8;margin:0 0 16px;padding:13px 16px;
  background:var(--bg-soft);border-left:3px solid var(--accent-line);border-radius:0 var(--r) var(--r) 0;
}
.metabar{display:flex;flex-wrap:wrap;gap:7px;align-items:center;padding-bottom:16px;border-bottom:1px solid var(--border);margin-bottom:26px}
.chip{
  font-size:11.5px;padding:3px 9px;border-radius:999px;background:var(--bg-soft);
  color:var(--text-2);border:1px solid var(--border);text-decoration:none;
}
a.chip:hover{border-color:var(--accent-line);color:var(--accent);background:var(--accent-soft)}
.chip.plain{border-color:transparent;background:none;color:var(--muted);padding-left:0}
.chip.stat{font-variant-numeric:tabular-nums;font-family:var(--mono)}
.favbtn{
  margin-left:auto;font-size:12.5px;padding:5px 13px;border-radius:999px;
  border:1px solid var(--border);color:var(--text-2);display:inline-flex;gap:6px;align-items:center;
}
.favbtn:hover{border-color:#e0a52a;color:#e0a52a}
.favbtn.on{background:#fdf6e3;border-color:#e9cf8a;color:#9a7212}
html[data-theme="dark"] .favbtn.on{background:#332c14;border-color:#6b5a22;color:#e9cf8a}

/* 正文排版 —— 标题层级整体降了一级（条目标题占 h1），这里复刻原手册的视觉层次 */
.body h2{                                   /* 部（第一部分 / 第二部分） */
  font-size:22px;font-weight:680;color:var(--accent);letter-spacing:-.3px;
  margin:46px 0 6px;line-height:1.4;scroll-margin-top:74px;
}
.body h3{                                   /* 章（0. / 1. / Stage 0 …） */
  font-size:19px;font-weight:650;line-height:1.45;margin:38px 0 12px;
  padding-left:12px;border-left:3px solid var(--accent);scroll-margin-top:74px;
}
.body h4{font-size:16px;font-weight:640;margin:26px 0 8px;scroll-margin-top:74px}
.body h4::before{content:"§ ";color:var(--muted);font-weight:400}
.body h5{font-size:14.5px;font-weight:640;margin:20px 0 6px;color:var(--text-2);scroll-margin-top:74px}
.body h5::before{content:"· ";color:var(--muted);font-weight:400}
.body h2:first-child,.body h3:first-child{margin-top:0}
.body>*:first-child{margin-top:0}
/* 「部分」这两块之间给一条重分割线，翻页感更强 */
.body section.part{margin-top:40px}
.body section.part:first-child{margin-top:0}
.body section.part>h2:first-child{margin-top:0}
.body section.part + section.part{border-top:2px solid var(--accent);padding-top:22px;margin-top:56px}
.body p{margin:11px 0}
.body ul,.body ol{margin:11px 0;padding-left:23px}
.body li{margin:5px 0}
.body li::marker{color:var(--muted)}
.body strong{font-weight:650}
.body hr{border:none;border-top:1px solid var(--border-2);margin:32px 0}
.body a{color:var(--accent);text-underline-offset:2px}
.body code{
  background:var(--code-bg);border:1px solid var(--border);border-radius:5px;
  padding:1px 5px;font:13.5px var(--mono);word-break:break-word;
}
.body blockquote{
  margin:16px 0;padding:12px 18px;background:var(--note-bg);color:var(--note-fg);
  border-left:3px solid var(--note-br);border-radius:0 var(--r) var(--r) 0;
}
.body blockquote p{margin:6px 0}
.body blockquote code{background:rgba(255,255,255,.45);border-color:rgba(180,140,40,.3)}
html[data-theme="dark"] .body blockquote code{background:rgba(255,255,255,.07)}
.body pre{
  position:relative;background:var(--code-bg);border:1px solid var(--border);border-radius:var(--r);
  padding:14px 16px;overflow-x:auto;margin:15px 0;-webkit-overflow-scrolling:touch;
}
.body pre code{background:none;border:none;padding:0;font-size:13px;line-height:1.68;font-family:var(--mono);white-space:pre}
.body pre .copy{
  position:absolute;top:7px;right:7px;font:11px var(--sans);padding:3px 9px;border-radius:6px;
  background:var(--bg);border:1px solid var(--border);color:var(--muted);opacity:0;transition:opacity .15s;
}
.body pre:hover .copy,.body pre .copy:focus{opacity:1}
.body pre .copy:hover{color:var(--accent);border-color:var(--accent-line)}
.body pre .copy.done{color:#2f7d4f;border-color:#9ed3b2;opacity:1}
html[data-theme="dark"] .body pre .copy.done{color:#7fd6a2;border-color:#2f5c42}
.tw{overflow-x:auto;margin:16px 0;border:1px solid var(--border);border-radius:var(--r);-webkit-overflow-scrolling:touch}
.tw::-webkit-scrollbar{height:7px}
.body table{border-collapse:collapse;width:100%;font-size:14px}
.body th,.body td{padding:9px 13px;border-bottom:1px solid var(--border);text-align:left;vertical-align:top}
.body th{background:var(--bg-soft);font-weight:640;white-space:nowrap;font-size:13px}
.body tbody tr:last-child td{border-bottom:none}
.body .cb{display:inline-block;width:12px;height:12px;border:1.5px solid var(--muted);border-radius:3px;margin-right:7px;vertical-align:-1px}
.body .cb-on{background:var(--accent);border-color:var(--accent)}
@media(max-width:700px){.body table{min-width:520px}}

/* 文章内目录 */
.rail{position:sticky;top:24px;max-height:calc(100dvh - 130px);overflow-y:auto;padding-bottom:20px}
.rail .rt{font-size:11px;font-weight:700;letter-spacing:.08em;color:var(--muted);text-transform:uppercase;margin-bottom:9px}
.rail a{
  display:block;font-size:12.5px;line-height:1.55;color:var(--muted);text-decoration:none;
  padding:3px 0 3px 11px;border-left:2px solid var(--border-2);transition:color .12s,border-color .12s;
}
.rail a.l2{padding-left:24px;font-size:12px}
.rail a:hover{color:var(--text)}
.rail a.on{color:var(--accent);border-left-color:var(--accent);font-weight:600}

/* 侧栏里的「本页目录」—— 单文档知识库把章节目录放左边，右侧不占阅读宽度 */
.dout{display:flex;flex-direction:column;gap:1px;padding:2px 0 6px 10px;margin-left:9px;border-left:1px solid var(--border)}
.dout a{
  display:block;font-size:12.5px;line-height:1.5;color:var(--muted);text-decoration:none;
  padding:4px 8px;border-radius:var(--r-sm);transition:background .12s,color .12s;
}
.dout a.l1{font-weight:650;color:var(--text-2);font-size:13px;margin-top:5px}
.dout a.l2{padding-left:16px}
.dout a.l3{padding-left:28px;font-size:12px}
.dout a.l4{padding-left:40px;font-size:12px;color:var(--muted)}
.dout a:hover{background:var(--bg-soft);color:var(--text)}
.dout a.on{background:var(--accent-soft);color:var(--accent);font-weight:600}
.sgroup>summary .oc{margin-left:auto;font:10px var(--mono);font-weight:700;color:var(--muted);
  background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:0 5px;letter-spacing:0}

/* 翻页 */
.pager{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:52px;padding-top:24px;border-top:1px solid var(--border)}
.pager a{
  display:block;padding:13px 16px;border:1px solid var(--border);border-radius:var(--r);
  text-decoration:none;color:var(--text);background:var(--card);transition:border-color .15s,box-shadow .15s;
}
.pager a:hover{border-color:var(--accent-line);box-shadow:var(--shadow)}
.pager a .lab{font-size:11px;color:var(--muted);display:block;margin-bottom:4px}
.pager a .t{font-size:14px;font-weight:600;line-height:1.5}
.pager a.next{text-align:right}
.pager .ph{visibility:hidden}

/* 首页 / 列表页 */
.hero{margin-bottom:34px}
.hero h1{font-size:31px;margin:0 0 10px;font-weight:700;letter-spacing:-.6px;line-height:1.3}
.hero .sub{color:var(--text-2);font-size:15.5px;margin:0;max-width:64ch;line-height:1.75}
.statrow{display:grid;grid-template-columns:repeat(auto-fit,minmax(112px,1fr));gap:12px;margin:26px 0 38px}
.stat{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px 16px}
.stat b{display:block;font-size:24px;font-weight:700;font-variant-numeric:tabular-nums;letter-spacing:-.5px;line-height:1.25}
.stat span{font-size:12px;color:var(--muted)}
.stat.bl b{color:var(--accent)}
.h2sec{display:flex;align-items:baseline;gap:10px;margin:34px 0 16px}
.h2sec h2{font-size:18px;margin:0;font-weight:660}
.h2sec .c{font-size:12px;color:var(--muted);font-family:var(--mono)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(268px,1fr));gap:14px}
.card{
  display:block;background:var(--card);border:1px solid var(--border);border-radius:var(--r);
  padding:16px 18px;text-decoration:none;color:var(--text);transition:border-color .15s,box-shadow .15s,transform .15s;
}
.card:hover{border-color:var(--accent-line);box-shadow:var(--shadow);transform:translateY(-1px)}
.card .ct{display:flex;align-items:center;gap:9px;font-weight:650;font-size:14.5px;margin-bottom:3px}
.card .badge{flex:none;font:10px/16px var(--mono);font-weight:700;padding:1px 6px;border-radius:5px;background:var(--accent-soft);color:var(--accent)}
.card .k{font-size:12px;color:var(--accent);margin-bottom:7px;font-weight:500}
.card .cs{font-size:12.5px;color:var(--muted);line-height:1.65}
.card .cf{margin-top:10px;font-size:11px;color:var(--muted);font-family:var(--mono)}
.artlist{display:flex;flex-direction:column;gap:2px}
.artlist a{
  display:block;padding:12px 14px;border-radius:var(--r-sm);text-decoration:none;color:var(--text);
  border:1px solid transparent;transition:background .12s,border-color .12s;
}
.artlist a:hover{background:var(--bg-soft);border-color:var(--border)}
.artlist .at{font-size:14.5px;font-weight:600;margin-bottom:3px;display:flex;align-items:center;gap:8px}
.artlist .as{font-size:12.5px;color:var(--muted);line-height:1.65}
.tagcloud{display:flex;flex-wrap:wrap;gap:7px}
.tagcloud a{
  font-size:12.5px;padding:4px 11px;border-radius:999px;background:var(--bg-soft);
  border:1px solid var(--border);color:var(--text-2);text-decoration:none;
}
.tagcloud a:hover{border-color:var(--accent-line);color:var(--accent);background:var(--accent-soft)}
.tagcloud a b{font-weight:600;color:var(--muted);font-size:11px;margin-left:5px;font-family:var(--mono)}
.note{
  background:var(--bg-soft);border:1px solid var(--border);border-radius:var(--r);padding:15px 18px;
  font-size:13.5px;color:var(--text-2);line-height:1.75;
}
.note h3{margin:0 0 8px;font-size:14.5px;color:var(--text);font-weight:650}
.note h3:not(:first-child){margin-top:18px}
.note ul{margin:6px 0;padding-left:20px}
.note li{margin:3px 0}
.note code{background:var(--code-bg);border:1px solid var(--border);border-radius:5px;padding:1px 5px;font:12.5px var(--mono)}
.col2{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:14px}
.empty{text-align:center;padding:70px 20px;color:var(--muted);font-size:14px}

/* 搜索结果面板 */
#panel{
  position:fixed;inset:56px 0 0;background:rgba(20,22,26,.28);z-index:35;
  display:none;backdrop-filter:blur(2px);
}
#panel.open{display:block}
.sresults{
  max-width:760px;margin:0 auto;background:var(--card);border:1px solid var(--border);
  border-top:none;border-radius:0 0 var(--r) var(--r);box-shadow:var(--shadow);
  max-height:calc(100dvh - 76px);overflow-y:auto;
}
.sresults .sh{padding:11px 18px;font-size:12px;color:var(--muted);border-bottom:1px solid var(--border-2);position:sticky;top:0;background:var(--card)}
.sitem{display:block;padding:11px 18px;text-decoration:none;color:var(--text);border-bottom:1px solid var(--border-2);cursor:pointer}
.sitem:last-child{border-bottom:none}
.sitem:hover,.sitem.cur{background:var(--accent-soft)}
.sitem .st{font-size:13.5px;font-weight:620;margin-bottom:3px}
.sitem .sp{font-size:12.5px;color:var(--muted);line-height:1.65}
.sitem .sn{font-size:11px;color:var(--muted);font-family:var(--mono);margin-top:4px}
.sitem mark{background:var(--mark);color:inherit;font-weight:600;border-radius:3px}

#toast{
  position:fixed;left:50%;bottom:34px;transform:translate(-50%,14px);background:var(--text);color:var(--bg);
  font-size:12.5px;padding:8px 16px;border-radius:999px;opacity:0;pointer-events:none;
  transition:opacity .2s,transform .2s;z-index:80;
}
#toast.on{opacity:1;transform:translate(-50%,0)}
#scrim{display:none}

@media(max-width:900px){
  body{grid-template-columns:minmax(0,1fr);grid-template-areas:"top" "main"}
  #menu-btn{display:inline-flex}
  #side{
    position:fixed;top:56px;bottom:0;left:0;width:min(84vw,308px);z-index:45;
    transform:translateX(-102%);transition:transform .22s cubic-bezier(.4,0,.2,1);
    box-shadow:0 0 40px rgba(0,0,0,.18);
  }
  body.nav-open #side{transform:none}
  body.nav-open #scrim{display:block;position:fixed;inset:56px 0 0;background:rgba(20,22,26,.4);z-index:44}
  .brand small{display:none}
  .brand .bt{display:none}
  .page{padding:22px 18px 80px}
  .doc h1{font-size:23px}
  .body h2{font-size:19px}
  .body h3{font-size:17.5px}
  .pager{grid-template-columns:1fr}
  .pager a.next{text-align:left}
  .hero h1{font-size:25px}
  #q{padding-right:16px}
  #searchwrap kbd{display:none}
}
@media(max-width:480px){
  #font-btn{display:none}
  .brand{padding:4px 3px}
}
@media print{
  #topbar,#side,#progress,.pager,#panel,.sfoot{display:none!important}
  body{display:block;height:auto;overflow:visible}
  #main{overflow:visible}
  .page{padding:0;max-width:none}
  .body pre,.body .tw{overflow:visible;page-break-inside:avoid}
  .body h2,.body h3{page-break-after:avoid}
}
"""

JS = r"""
(function(){
'use strict';
var $=function(s,r){return (r||document).querySelector(s)};
var $$=function(s,r){return Array.prototype.slice.call((r||document).querySelectorAll(s))};
function esc(s){return String(s).replace(/[&<>"]/g,function(c){
  return c==='&'?'&amp;':c==='<'?'&lt;':c==='>'?'&gt;':'&quot;'})}
function reEsc(s){return s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')}
function hl(text,q){
  if(!q) return esc(text);
  var parts=q.trim().split(/\s+/).filter(function(x){return x.length>0}).map(reEsc);
  if(!parts.length) return esc(text);
  var re=new RegExp('('+parts.join('|')+')','gi');
  return esc(text).replace(re,function(m){return '<mark>'+m+'</mark>'});
}

/* ---------------- 数据 ---------------- */
var DATA=JSON.parse(document.getElementById('kb-data').textContent);
var LS={
  get:function(k,d){try{var v=localStorage.getItem('kb.'+k);return v==null?d:JSON.parse(v)}catch(e){return d}},
  set:function(k,v){try{localStorage.setItem('kb.'+k,JSON.stringify(v))}catch(e){}}
};
var extra=LS.get('extra',[]);
var ARTS=DATA.arts.concat(extra.map(function(a){
  a.outline=a.outline||[];a.tags=a.tags||[];a.words=a.words||0;a.read=a.read||1;return a}));
var CATS=DATA.cats.slice();
extra.forEach(function(a){
  if(!CATS.some(function(c){return c.id===a.cat})) CATS.push({id:a.cat,name:a.cat,icon:'·',desc:'来自导入的知识条目。'});
});
var byId={}; ARTS.forEach(function(a){byId[a.id]=a});
function artsOf(cid){return ARTS.filter(function(a){return a.cat===cid})}

/* 纯文本 & 搜索索引 */
function plain(h){
  var d=document.createElement('div'); d.innerHTML=h;
  return (d.textContent||'').replace(/\s+/g,' ').trim();
}
ARTS.forEach(function(a){ a._plain=plain(a.html) });
var INDEX=ARTS.map(function(a){
  return {a:a, t:(a.title+' '+(a.kicker||'')+' '+a.tags.join(' ')).toLowerCase(),
          g:a.tags.join(' ').toLowerCase(), x:a._plain.toLowerCase()};
});

/* ---------------- 状态 ---------------- */
var S={
  favs:LS.get('favs',[]),
  hist:LS.get('hist',[]),
  theme:LS.get('theme','light'),
  fs:LS.get('fs',0),
  collapsed:LS.get('collapsed',[]),
  cur:null
};
var FSS=[16,17,18,15];

function toast(msg){
  var t=$('#toast'); t.textContent=msg; t.classList.add('on');
  clearTimeout(t._h); t._h=setTimeout(function(){t.classList.remove('on')},1700);
}
function isFav(id){return S.favs.indexOf(id)>=0}
function toggleFav(id){
  var i=S.favs.indexOf(id);
  if(i>=0){S.favs.splice(i,1);toast('已取消收藏')}else{S.favs.unshift(id);toast('已收藏')}
  LS.set('favs',S.favs); renderSide(); syncFavBtn();
}
function syncFavBtn(){
  var b=$('.favbtn'); if(!b) return;
  b.classList.toggle('on', isFav(b.dataset.id));
  b.querySelector('.ic').textContent = isFav(b.dataset.id)?'★':'☆';
  b.querySelector('.tx').textContent = isFav(b.dataset.id)?'已收藏':'收藏';
}
function pushHist(id){
  S.hist=S.hist.filter(function(x){return x!==id}); S.hist.unshift(id);
  S.hist=S.hist.slice(0,24); LS.set('hist',S.hist);
}

/* ---------------- 主题 / 字号 ---------------- */
function applyTheme(){
  document.documentElement.setAttribute('data-theme',S.theme);
  $('#theme-btn').textContent = S.theme==='dark'?'☀':'☾';
  $('#theme-btn').title = S.theme==='dark'?'切换到浅色':'切换到深色';
}
function applyFs(){ document.documentElement.style.setProperty('--fs',FSS[S.fs%FSS.length]+'px') }

/* ---------------- 侧栏 ---------------- */
function renderSide(){
  var h='';
  h+='<nav class="snav">';
  h+='<a href="#/" data-nav="home">'+ic('home')+'首页<span class="n">'+ARTS.length+'</span></a>';
  h+='<a href="#/fav" data-nav="fav">'+ic('star')+'我的收藏<span class="n">'+S.favs.length+'</span></a>';
  h+='<a href="#/hist" data-nav="hist">'+ic('clock')+'最近阅读<span class="n">'+S.hist.length+'</span></a>';
  h+='<a href="#/tags" data-nav="tags">'+ic('tag')+'全部标签<span class="n">'+allTags().length+'</span></a>';
  h+='</nav>';
  h+='<details class="sgroup" open><summary>分类</summary>';
  CATS.forEach(function(c){
    var list=artsOf(c.id); if(!list.length) return;
    var col=S.collapsed.indexOf(c.id)>=0;
    h+='<div class="catblk'+(col?' collapsed':'')+'" data-cat="'+c.id+'">';
    h+='<button class="chead" data-toggle="'+c.id+'"><span class="arw">⌄</span>'
      +'<span class="badge">'+esc(c.icon||'·')+'</span><span>'+esc(c.name)+'</span>'
      +'<span class="cnt">'+list.length+'</span></button>';
    if(c.desc) h+='<div class="catdesc">'+esc(c.desc)+'</div>';
    h+='<div class="clist">';
    list.forEach(function(a){
      h+='<a href="#/a/'+a.id+'" data-art="'+a.id+'">'
        +(isFav(a.id)?'<span class="fav">★</span>':'')
        +'<span>'+esc(a.title)+'</span></a>';
    });
    h+='</div></div>';
  });
  h+='</details>';
  // 当前条目的章节目录：单文档知识库把它放在左栏，右边不占阅读宽度
  var cur=S.cur&&byId[S.cur];
  if(cur&&cur.outline&&cur.outline.length){
    var og=$('#outline-group'), ogOpen=og?og.hasAttribute('open'):true;
    h+='<details class="sgroup" id="outline-group"'+(ogOpen?' open':'')+'><summary>本页目录'
      +'<span class="oc">'+cur.outline.length+'</span></summary>';
    h+='<div class="dout" id="dout">'+cur.outline.map(function(o){
      return '<a href="#'+o.id+'" data-anchor="'+o.id+'" class="l'+o.lvl+'">'+esc(o.text)+'</a>';
    }).join('')+'</div></details>';
  }
  h+='<div class="sfoot">'
    +'<button data-act="export">导出备份</button>'
    +'<button data-act="import">导入 JSON</button>'
    +'<button data-act="print">打印</button>'
    +'</div>';
  h+='<div class="meta-line">'
    +'构建 '+esc(DATA.meta.built)+' · 单文件 / 零依赖<br>'
    +'快捷键：<code style="font:11px var(--mono)">/</code> 搜索 · '
    +'<code style="font:11px var(--mono)">Esc</code> 关闭</div>';
  $('#side').innerHTML=h;
}
function ic(name){
  var p={
    home:'<path d="M3 9.5 12 3l9 6.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
    star:'<path d="m12 3 2.6 5.6 6 .8-4.4 4.2 1.1 6L12 16.8 6.7 19.6l1.1-6L3.4 9.4l6-.8z"/>',
    clock:'<path d="M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zm1 5v4.3l3.2 1.9-.9 1.5L11 13V8z"/>',
    tag:'<path d="M3 11V4a1 1 0 0 1 1-1h7l10 10-8 8zM7.5 6a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3z"/>'
  }[name]||'';
  return '<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'+p+'</svg>';
}
function allTags(){
  var m={}; ARTS.forEach(function(a){a.tags.forEach(function(t){m[t]=(m[t]||0)+1})});
  return Object.keys(m).sort(function(a,b){return m[b]-m[a]||a.localeCompare(b,'zh')}).map(function(t){return {t:t,n:m[t]}});
}
function markSide(){
  var hash=location.hash||'#/';
  $$('#side a[data-nav],#side a[data-art]').forEach(function(el){el.classList.remove('on')});
  if(hash.indexOf('#/a/')===0){
    var el=$('#side a[data-art="'+hash.slice(4)+'"]');
    if(el){el.classList.add('on');var b=el.closest('.catblk');if(b){b.classList.remove('collapsed');
      var c=b.dataset.cat;if(S.collapsed.indexOf(c)>=0){S.collapsed=S.collapsed.filter(function(x){return x!==c});}}}
  }else if(hash==='#/fav'){var f=$('#side a[data-nav="fav"]');if(f)f.classList.add('on')}
  else if(hash==='#/hist'){var h2=$('#side a[data-nav="hist"]');if(h2)h2.classList.add('on')}
  else if(hash==='#/tags'){var t=$('#side a[data-nav="tags"]');if(t)t.classList.add('on')}
  else {var hm=$('#side a[data-nav="home"]');if(hm)hm.classList.add('on')}
}

/* ---------------- 视图 ---------------- */
var MAIN=$('#main');

function crumbs(items){
  return '<div class="crumbs">'+items.map(function(it,i){
    var s=i?'<span class="sep">/</span>':'';
    return s+(it.href?'<a href="'+it.href+'">'+esc(it.t)+'</a>':'<span>'+esc(it.t)+'</span>');
  }).join('')+'</div>';
}
function chipRow(a){
  var s='<div class="metabar">';
  s+='<span class="chip stat">'+a.words+' 字</span>';
  s+='<span class="chip stat">约 '+a.read+' 分钟</span>';
  s+='<a class="chip" href="#/c/'+a.cat+'">'+esc(catName(a.cat))+'</a>';
  a.tags.forEach(function(t){s+='<a class="chip" href="#/t/'+encodeURIComponent(t)+'">#'+esc(t)+'</a>'});
  s+='<button class="favbtn" data-id="'+a.id+'"><span class="ic">☆</span><span class="tx">收藏</span></button>';
  s+='</div>';
  return s;
}
function viewArticle(id){
  var a=byId[id]; if(!a) return viewHome();
  S.cur=id;
  var i=ARTS.indexOf(a);
  var prev=ARTS[i-1], next=ARTS[i+1];
  var h='<div class="page"><article class="doc">';
  h+=crumbs([{t:'首页',href:'#/'},{t:catName(a.cat),href:'#/c/'+a.cat},{t:a.title}]);
  h+='<h1>'+esc(a.title)+'</h1>';
  if(a.kicker) h+='<p class="kicker">'+esc(a.kicker)+'</p>';
  if(a.summary) h+='<p class="lede">'+esc(a.summary)+'</p>';
  h+=chipRow(a);
  h+='<div class="body" id="docbody">'+a.html+'</div>';
  if(ARTS.length>1){
    h+='<nav class="pager">';
    h+= prev?'<a href="#/a/'+prev.id+'"><span class="lab">← 上一篇</span><span class="t">'+esc(prev.title)+'</span></a>'
            :'<a class="ph"></a>';
    h+= next?'<a class="next" href="#/a/'+next.id+'"><span class="lab">下一篇 →</span><span class="t">'+esc(next.title)+'</span></a>'
            :'<a class="ph"></a>';
    h+='</nav>';
  }
  h+='</article></div>';
  MAIN.innerHTML=h;
  renderSide();          // 重建侧栏，把本篇的章节目录挂上去
  syncFavBtn(); markSide();
  $('#main').scrollTop=0;
  decorate(); buildSpy(); pushHist(id);
  document.title=a.title+' · 个人知识库';
}
function catName(id){var c=CATS.filter(function(x){return x.id===id})[0];return c?c.name:id}

function viewCat(cid){
  var list=artsOf(cid); if(!list.length) return viewHome();
  var c=CATS.filter(function(x){return x.id===cid})[0]||{name:cid};
  var h='<div class="page">';
  h+=crumbs([{t:'首页',href:'#/'},{t:c.name}]);
  h+='<div class="hero"><h1>'+esc(c.name)+'</h1><p class="sub">'+esc(c.desc||'')+'</p></div>';
  h+='<div class="h2sec"><h2>条目</h2><span class="c">'+list.length+' 篇 · '
    +list.reduce(function(s,a){return s+a.words},0)+' 字</span></div>';
  h+='<div class="artlist">'+list.map(function(a){
      return '<a href="#/a/'+a.id+'"><div class="at">'+(isFav(a.id)?'<span class="fav" style="color:#e0a52a">★</span>':'')
        +esc(a.title)+'</div><div class="as">'+esc(a.summary)+'</div></a>'}).join('')+'</div>';
  h+='</div>';
  MAIN.innerHTML=h; markSide(); document.title=c.name+' · 个人知识库';
}

function cardOf(a){
  return '<a class="card" href="#/a/'+a.id+'">'
    +'<div class="ct"><span class="badge">'+esc(catIcon(a.cat))+'</span>'+esc(a.title)+'</div>'
    +'<div class="k">'+esc(a.kicker||'')+'</div>'
    +'<div class="cs">'+esc(a.summary)+'</div>'
    +'<div class="cf">'+a.words+' 字 · '+a.read+' min'+(isFav(a.id)?' · ★':'')+'</div></a>';
}
function catIcon(id){var c=CATS.filter(function(x){return x.id===id})[0];return c?(c.icon||'·'):'·'}

function viewHome(){
  var st=DATA.meta.stats;
  var h='<div class="page">';
  h+='<div class="hero"><h1>'+esc(DATA.meta.title)+'</h1><p class="sub">'+esc(DATA.meta.subtitle)
    +' —— 把踩过的坑、验证过的方法和可复用的清单放在一处，本地单文件，断网可读、可检索、可长期存档。</p></div>';
  h+='<div class="statrow">'
    +'<div class="stat bl"><b>'+ARTS.length+'</b><span>知识条目</span></div>'
    +'<div class="stat"><b>'+CATS.length+'</b><span>分类</span></div>'
    +'<div class="stat"><b>'+st.words.toLocaleString()+'</b><span>总字数</span></div>'
    +'<div class="stat"><b>'+st.tables+'</b><span>表格</span></div>'
    +'<div class="stat"><b>'+st.code+'</b><span>代码块</span></div>'
    +'<div class="stat"><b>'+st.anchors+'</b><span>章节锚点</span></div>'
    +'</div>';
  h+='<div class="h2sec"><h2>分类地图</h2><span class="c">'+CATS.length+' 类</span></div>';
  h+='<div class="cards">'+CATS.map(function(c){
      var l=artsOf(c.id), w=l.reduce(function(s,a){return s+a.words},0);
      return '<a class="card" href="#/c/'+c.id+'"><div class="ct"><span class="badge">'+esc(c.icon)
        +'</span>'+esc(c.name)+'</div><div class="cs">'+esc(c.desc||'')+'</div>'
        +'<div class="cf">'+l.length+' 篇 · '+w.toLocaleString()+' 字</div></a>'}).join('')+'</div>';
  if(S.hist.length){
    var rec=S.hist.slice(0,4).map(function(id){return byId[id]}).filter(Boolean);
    if(rec.length){
      h+='<div class="h2sec"><h2>接着上次读</h2><span class="c">最近 '+S.hist.length+' 篇</span></div>';
      h+='<div class="cards">'+rec.map(cardOf).join('')+'</div>';
    }
  }
  if(S.favs.length){
    var fv=S.favs.slice(0,4).map(function(id){return byId[id]}).filter(Boolean);
    if(fv.length){
      h+='<div class="h2sec"><h2>收藏</h2><span class="c">共 '+S.favs.length+' 篇</span></div>';
      h+='<div class="cards">'+fv.map(cardOf).join('')+'</div>';
    }
  }
  h+='<div class="h2sec"><h2>全部条目</h2><span class="c">'+ARTS.length+' 篇</span></div>';
  h+='<div class="cards">'+ARTS.map(cardOf).join('')+'</div>';
  h+='<div class="h2sec"><h2>标签</h2><span class="c">'+allTags().length+' 个</span></div>';
  h+='<div class="tagcloud">'+allTags().slice(0,40).map(function(t){
      return '<a href="#/t/'+encodeURIComponent(t.t)+'">'+esc(t.t)+'<b>'+t.n+'</b></a>'}).join('')+'</div>';
  h+='<div class="h2sec"><h2>关于这个知识库</h2></div>';
  h+='<div class="col2"><div class="note"><h3>来源</h3><p>'+esc(DATA.meta.source)
    +'。原文<strong>整篇作为一个条目</strong>收录，内容逐字保留、未改写；只做了两件事：'
    +'标题层级整体降一级（让条目标题独占 <code>h1</code>），锚点加条目前缀（为以后收录别的文档留位置）。</p>'
    +'<h3>为什么是零依赖单文件</h3><ul>'
    +'<li>只用原生 HTML / CSS / JS，无 CDN、无构建、无框架</li>'
    +'<li>直接从 <code>file://</code> 打开即可，断网可用</li>'
    +'<li>内容内联在页面里，不靠 <code>fetch</code>（浏览器会拦本地请求）</li>'
    +'<li>整份知识库 = 一个文件，拷到 U 盘 / 手机 / 归档都不会散</li></ul></div>'
    +'<div class="note"><h3>怎么扩展</h3><ul>'
    +'<li><b>导入</b>：侧栏「导入 JSON」，条目存进浏览器本地存储，与内置条目合并</li>'
    +'<li><b>导出</b>：侧栏「导出备份」，落一份 JSON，换设备再导入</li>'
    +'<li><b>改内置</b>：编辑同目录 <code>build.py</code> 的 <code>ARTICLES</code> 列表后重跑，'
    +'即可加入更多文档或分类</li>'
    +'<li><b>快捷键</b>：<code>/</code> 或 <code>⌘K</code> 搜索，<code>↑↓</code> 选，<code>Enter</code> 打开，<code>Esc</code> 关闭</li></ul>'
    +'<h3>章节目录从哪来</h3><p>左栏「本页目录」由正文标题<strong>现生成</strong>，'
    +'所以不会和正文脱节；原文自带的那份 TOC 已弃用，少一处要同步维护的重复清单。滚动时目录会跟着高亮当前章节。</p>'
    +'<h3>浏览记录存在哪</h3><p>收藏、历史、主题、字号都写在浏览器 <code>localStorage</code>，不上传、不联网。</p></div></div>';
  h+='</div>';
  MAIN.innerHTML=h; markSide(); document.title='个人知识库';
}

function viewList(title,desc,list,emptyMsg){
  var h='<div class="page">'+crumbs([{t:'首页',href:'#/'},{t:title}]);
  h+='<div class="hero"><h1>'+esc(title)+'</h1><p class="sub">'+esc(desc)+'</p></div>';
  if(!list.length){h+='<div class="empty">'+esc(emptyMsg)+'</div>'}
  else{h+='<div class="artlist">'+list.map(function(a){
    return '<a href="#/a/'+a.id+'"><div class="at">'+esc(a.title)+'</div>'
      +'<div class="as">'+esc(a.summary)+'</div></a>'}).join('')+'</div>'}
  h+='</div>';
  MAIN.innerHTML=h; markSide(); document.title=title+' · 个人知识库';
}

function viewTags(){
  var ts=allTags();
  var h='<div class="page">'+crumbs([{t:'首页',href:'#/'},{t:'全部标签'}]);
  h+='<div class="hero"><h1>全部标签</h1><p class="sub">共 '+ts.length+' 个标签，点击筛选相关条目。</p></div>';
  h+='<div class="tagcloud">'+ts.map(function(t){
    return '<a href="#/t/'+encodeURIComponent(t.t)+'">'+esc(t.t)+'<b>'+t.n+'</b></a>'}).join('')+'</div></div>';
  MAIN.innerHTML=h; markSide(); document.title='全部标签 · 个人知识库';
}

function viewTag(tag){
  var list=ARTS.filter(function(a){return a.tags.indexOf(tag)>=0});
  viewList('#'+tag,'标签「'+tag+'」下的 '+list.length+' 个条目。',list,'没有这个标签的条目。');
}

/* ---------------- 搜索 ---------------- */
var panel=$('#panel'), qEl=$('#q'), curIdx=-1, curList=[];
function search(q){
  q=q.trim(); if(!q) return [];
  var parts=q.toLowerCase().split(/\s+/).filter(Boolean), out=[];
  INDEX.forEach(function(it){
    var score=0, hit=true;
    parts.forEach(function(p){
      var inT=it.t.indexOf(p)>=0, inG=it.g.indexOf(p)>=0, inX=it.x.indexOf(p)>=0;
      if(!inT&&!inG&&!inX){hit=false;return}
      if(inT) score+=inG?14:12; else if(inG) score+=8; else score+=3;
    });
    if(!hit) return;
    var snippet='';
    var pos=it.x.indexOf(parts[0]);
    if(pos<0) pos=0;
    var s=Math.max(0,pos-46), e=Math.min(it.x.length,pos+parts[0].length+92);
    snippet=(s>0?'…':'')+it.x.slice(s,e)+(e<it.x.length?'…':'');
    out.push({a:it.a,score:score,snippet:snippet});
  });
  out.sort(function(x,y){return y.score-x.score||x.a.title.length-y.a.title.length});
  return out.slice(0,24);
}
function renderPanel(q,res){
  if(!q){panel.classList.remove('open');return}
  var h='<div class="sresults"><div class="sh">';
  h+= res.length?('找到 <b>'+res.length+'</b> 个条目 · <b>↑↓</b> 选择 · <b>Enter</b> 打开'):'没有匹配「'+esc(q)+'」的条目';
  h+='</div>';
  h+=res.map(function(r,i){
    return '<a class="sitem'+(i===curIdx?' cur':'')+'" href="#/a/'+r.a.id+'" data-i="'+i+'">'
      +'<div class="st">'+hl(r.a.title,q)+'</div>'
      +'<div class="sp">'+hl(r.snippet,q)+'</div>'
      +'<div class="sn">'+esc(catName(r.a.cat))+(r.a.tags.length?' · #'+esc(r.a.tags.join(' #')):'')+'</div></a>'}).join('');
  h+='</div>'; panel.innerHTML=h; panel.classList.add('open');
}
function closeSearch(){panel.classList.remove('open');curIdx=-1;curList=[]}

/* ---------------- 代码块装饰 + 滚动同步 ---------------- */
function decorate(){
  $$('#docbody pre').forEach(function(pre){
    if(pre.querySelector('.copy')) return;
    var b=document.createElement('button');
    b.className='copy'; b.type='button'; b.textContent='复制';
    b.addEventListener('click',function(){
      var code=pre.querySelector('code'); var txt=code?code.textContent:pre.textContent;
      var done=function(){b.textContent='已复制';b.classList.add('done');
        setTimeout(function(){b.textContent='复制';b.classList.remove('done')},1400)};
      if(navigator.clipboard&&navigator.clipboard.writeText){
        navigator.clipboard.writeText(txt).then(done).catch(function(){fallback(txt,done)});
      }else{fallback(txt,done)}
    });
    pre.appendChild(b);
  });
}
function fallback(txt,cb){
  var ta=document.createElement('textarea'); ta.value=txt;
  ta.style.cssText='position:fixed;top:-1000px'; document.body.appendChild(ta);
  ta.select(); try{document.execCommand('copy');cb()}catch(e){}
  document.body.removeChild(ta);
}
var spyHandler=null, rafPending=false;
function buildSpy(){
  var main=$('#main');
  if(spyHandler){ main.removeEventListener('scroll',spyHandler); spyHandler=null }
  var links=$$('#dout a'); if(!links.length) return;
  var map={}; links.forEach(function(l){ if(l.dataset.anchor) map[l.dataset.anchor]=l });
  var hs=$$('#docbody h2,#docbody h3,#docbody h4,#docbody h5'); if(!hs.length) return;
  spyHandler=function(){
    if(rafPending) return;
    rafPending=true;
    (window.requestAnimationFrame||function(f){setTimeout(f,16)})(function(){
      rafPending=false;
      // 取「已经滚过顶栏、且最靠下」的那个标题 = 当前正在阅读的章节
      var line=main.getBoundingClientRect().top+86;
      var cur=hs[0];
      for(var i=0;i<hs.length;i++){
        if(hs[i].getBoundingClientRect().top<=line) cur=hs[i]; else break;
      }
      var l=map[cur.id];
      if(!l||l.classList.contains('on')) return;
      links.forEach(function(x){x.classList.remove('on')});
      l.classList.add('on');
      // 目录很长时把当前项带进视野（block:'nearest' 只做最小滚动）
      if(l.scrollIntoView) l.scrollIntoView({block:'nearest'});
    });
  };
  main.addEventListener('scroll',spyHandler,{passive:true});
  spyHandler();
}
function bindProgress(){
  $('#main').addEventListener('scroll',function(){
    var el=$('#main');
    var max=el.scrollHeight-el.clientHeight;
    $('#progress').style.width=(max>0?(el.scrollTop/max*100):0)+'%';
  },{passive:true});
}

/* ---------------- 导入 / 导出 ---------------- */
function doExport(){
  var payload={type:'kb-extra',version:1,exported:new Date().toISOString(),
    arts:extra, favs:S.favs, hist:S.hist};
  var blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json'});
  var a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  a.download='kb-backup-'+new Date().toISOString().slice(0,10)+'.json';
  document.body.appendChild(a); a.click();
  setTimeout(function(){URL.revokeObjectURL(a.href);a.remove()},600);
  toast('已导出 '+ARTS.length+' 条（含收藏/历史）');
}
function doImport(){
  var inp=document.createElement('input'); inp.type='file'; inp.accept='.json,application/json';
  inp.addEventListener('change',function(){
    var f=inp.files&&inp.files[0]; if(!f) return;
    var fr=new FileReader();
    fr.onload=function(){
      try{
        var o=JSON.parse(fr.result);
        var list=o.arts||o;
        if(!Array.isArray(list)) throw new Error('格式不对');
        var added=0;
        list.forEach(function(a){
          if(!a||!a.id||!a.html) return;
          if(ARTS.some(function(x){return x.id===a.id})) return;
          a.cat=a.cat||'imported'; a.tags=a.tags||[]; a.title=a.title||a.id;
          a.summary=a.summary||''; a.outline=a.outline||[]; a.words=a.words||0; a.read=a.read||1;
          extra.push(a); a._plain=plain(a.html); ARTS.push(a); byId[a.id]=a;
          INDEX.push({a:a,t:(a.title+' '+a.tags.join(' ')).toLowerCase(),g:a.tags.join(' ').toLowerCase(),x:a._plain.toLowerCase()});
          added++;
        });
        if(o.favs&&o.favs.length){o.favs.forEach(function(id){if(S.favs.indexOf(id)<0)S.favs.push(id)});LS.set('favs',S.favs)}
        LS.set('extra',extra);
        renderSide(); location.hash==='#/'?viewHome():route();
        toast(added?('已导入 '+added+' 条知识'):'没有新条目（id 已存在）');
      }catch(e){toast('导入失败：'+e.message)}
    };
    fr.readAsText(f,'utf-8');
  });
  inp.click();
}

/* ---------------- 路由 ---------------- */
function route(){
  var hash=location.hash||'#/';
  // 页内锚点（#ipc-handbook--p1-0-5）不参与路由，否则点目录会被当成换页
  if(hash.charAt(1)!=='/') return;
  closeSearch(); qEl.value='';
  document.body.classList.remove('nav-open');
  if(hash.indexOf('#/a/')===0){ viewArticle(decodeURIComponent(hash.slice(4))) }
  else if(hash.indexOf('#/c/')===0){ viewCat(decodeURIComponent(hash.slice(4))) }
  else if(hash.indexOf('#/t/')===0){ viewTag(decodeURIComponent(hash.slice(4))) }
  else if(hash==='#/fav'){ viewList('我的收藏','标了星号的条目会出现在这里。',
      S.favs.map(function(id){return byId[id]}).filter(Boolean),'还没有收藏。打开任意条目，点右上角「收藏」。') }
  else if(hash==='#/hist'){ viewList('最近阅读','按打开时间倒序，最多保留 24 条。',
      S.hist.map(function(id){return byId[id]}).filter(Boolean),'还没有阅读记录。') }
  else if(hash==='#/tags'){ viewTags() }
  else { viewHome() }
  $('#main').scrollTop = (hash.indexOf('#/a/')===0)?0:$('#main').scrollTop;
}

/* ---------------- 事件 ---------------- */
$('#menu-btn').addEventListener('click',function(){document.body.classList.toggle('nav-open')});
$('#scrim').addEventListener('click',function(){document.body.classList.remove('nav-open')});
$('#theme-btn').addEventListener('click',function(){
  S.theme=S.theme==='dark'?'light':'dark'; LS.set('theme',S.theme); applyTheme();
});
$('#font-btn').addEventListener('click',function(){
  S.fs=(S.fs+1)%FSS.length; LS.set('fs',S.fs); applyFs();
  toast('正文字号 '+FSS[S.fs]+'px');
});
qEl.addEventListener('input',function(){curIdx=0;curList=search(qEl.value);renderPanel(qEl.value,curList)});
qEl.addEventListener('keydown',function(e){
  if(e.key==='ArrowDown'||e.key==='ArrowUp'){
    e.preventDefault();
    if(!curList.length) return;
    curIdx=(curIdx+(e.key==='ArrowDown'?1:-1)+curList.length)%curList.length;
    renderPanel(qEl.value,curList);
    var c=panel.querySelector('.sitem.cur');
    if(c&&c.scrollIntoView) c.scrollIntoView({block:'nearest'});
  }else if(e.key==='Enter'){
    if(curList[curIdx]){ location.hash='#/a/'+curList[curIdx].a.id; qEl.value=''; closeSearch(); qEl.blur() }
  }else if(e.key==='Escape'){ qEl.value=''; closeSearch(); qEl.blur() }
});
panel.addEventListener('click',function(e){
  if(e.target===panel){ qEl.value=''; closeSearch() }
});
document.addEventListener('keydown',function(e){
  var tag=(e.target.tagName||'').toLowerCase();
  var typing=tag==='input'||tag==='textarea'||e.target.isContentEditable;
  if((e.key==='/'&&!typing)||((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k')){
    e.preventDefault(); qEl.focus(); qEl.select();
  }
  if(e.key==='Escape'&&document.body.classList.contains('nav-open')){document.body.classList.remove('nav-open')}
});
document.addEventListener('click',function(e){
  if(!e.target.closest) return;
  // 侧栏目录 → 正文内的页内跳转，不能走 hash 路由
  var anc=e.target.closest('[data-anchor]');
  if(anc){
    e.preventDefault();
    var el=document.getElementById(anc.dataset.anchor);
    // 用 instant：长文里跳两万像素，平滑滚动会拖很久，像卡住了
    if(el&&el.scrollIntoView) el.scrollIntoView({block:'start',behavior:'instant'});
    document.body.classList.remove('nav-open');   // 手机上点完就收起抽屉
    $$('#dout a').forEach(function(l){l.classList.toggle('on',l===anc)});
    if(anc.scrollIntoView) anc.scrollIntoView({block:'nearest'});
    return;
  }
  var t=e.target.closest('[data-toggle],[data-act],.favbtn');
  if(!t) return;
  if(t.classList.contains('favbtn')){ toggleFav(t.dataset.id); return }
  if(t.dataset.toggle){
    var id=t.dataset.toggle, blk=t.closest('.catblk');
    blk.classList.toggle('collapsed');
    var i=S.collapsed.indexOf(id);
    if(blk.classList.contains('collapsed')){ if(i<0) S.collapsed.push(id) } else { if(i>=0) S.collapsed.splice(i,1) }
    LS.set('collapsed',S.collapsed); return;
  }
  if(t.dataset.act==='export') doExport();
  if(t.dataset.act==='import') doImport();
  if(t.dataset.act==='print') window.print();
});
window.addEventListener('hashchange',route);
window.addEventListener('keydown',function(e){
  if(e.key==='j'||e.key==='k'){
    var tag=(e.target.tagName||'').toLowerCase();
    if(tag==='input'||tag==='textarea') return;
    if(e.metaKey||e.ctrlKey||e.altKey) return;
    var links=$$('#side .clist a'); if(!links.length) return;
    var cur=-1; links.forEach(function(l,i){if(l.classList.contains('on'))cur=i});
    var nx=cur+(e.key==='j'?1:-1);
    if(nx<0||nx>=links.length){ // 跨分类时用全部条目顺序
      var all=ARTS; var ci=all.indexOf(byId[S.cur]); if(ci<0) return;
      var t2=all[ci+(e.key==='j'?1:-1)]; if(t2) location.hash='#/a/'+t2.id;
      return;
    }
    location.hash=links[nx].getAttribute('href');
  }
});

/* ---------------- 启动 ---------------- */
applyTheme(); applyFs(); renderSide(); bindProgress(); route();
})();
"""

HTML_SHELL = r"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="description" content="个人知识库 · 数据工程 / 结构化抽取 —— 本地零依赖单文件">
<title>个人知识库</title>
<style>%%CSS%%</style>
</head>
<body>
<div id="progress"></div>
<header id="topbar">
  <button id="menu-btn" class="icon-btn" type="button" aria-label="打开导航">☰</button>
  <a class="brand" href="#/"><span class="dot"></span><span class="bt">个人知识库</span><small>数据工程 · 结构化抽取</small></a>
  <div id="searchwrap">
    <span class="i">⌕</span>
    <input id="q" type="search" placeholder="搜索标题、标签、正文…" autocomplete="off" spellcheck="false" aria-label="搜索知识库">
    <kbd>/</kbd>
  </div>
  <div class="tools">
    <button id="font-btn" class="icon-btn" type="button" title="切换正文字号">Aa</button>
    <button id="theme-btn" class="icon-btn" type="button" title="切换深浅色">☾</button>
  </div>
</header>
<aside id="side"></aside>
<main id="main"></main>
<div id="panel"></div>
<div id="scrim"></div>
<div id="toast"></div>
<script id="kb-data" type="application/json">%%DATA%%</script>
<script>%%JS%%</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(DEFAULT_SRC))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    src = Path(args.src)
    print(f"读取源文档：{src}")
    data = build_data(src)

    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")          # 防止提前闭合 <script>
    assert "</script" not in payload.lower()

    out = (HTML_SHELL
           .replace("%%CSS%%", CSS)
           .replace("%%JS%%", JS)
           .replace("%%DATA%%", payload))

    # ---- 交付前断言（只针对正文内容，不扫 JS 模板串）----
    content = "".join(a["html"] for a in data["arts"])
    assert "<h1" not in content, "× 正文里出现了 h1（条目标题已经占了 h1）"
    ids = re.findall(r'<(?:h[1-6]|section)\b[^>]*?\sid="([^"]+)"', content)
    assert len(ids) == len(set(ids)), "× 正文锚点 id 有重复"
    assert len(ids) == data["meta"]["stats"]["anchors"], "× 锚点统计对不上"
    bad = {t for t in set(re.findall(r'href="#([^"]+)"', content)) if t not in set(ids)}
    assert not bad, f"× 正文里有失效锚点：{list(bad)[:5]}"
    # 每篇条目的目录锚点都必须能在正文里找到
    for a in data["arts"]:
        body_ids = set(re.findall(r'id="([^"]+)"', a["html"]))
        for o in a["outline"]:
            assert o["id"] in body_ids, f"× [{a['id']}] 目录锚点 {o['id']} 在正文里不存在"
        lv = [sum(1 for o in a["outline"] if o["lvl"] == k) for k in (1, 2, 3, 4)]
        assert sum(lv) == len(a["outline"]), f"× [{a['id']}] 目录层级越界"
    # 源文档的 h1/h2/h3/h4 = 2/17/28/6，整体降一级后应变成 2/17/28/6 的 1~4 级
    lvl_total = [sum(1 for a in data["arts"] for o in a["outline"] if o["lvl"] == k)
                 for k in (1, 2, 3, 4)]
    assert lvl_total == [2, 17, 28, 6], (
        f"× 标题层级不对：得到 {lvl_total}，应为 [2, 17, 28, 6]"
        " —— 多半是 shift_headings 的替换顺序写反了")
    assert content.count("<table") == content.count('<div class="tw"><table>'), "× 表格没套横滑容器"
    assert content.count("</table>") == content.count("</table></div>"), "× 表格容器没闭合"
    assert content.count("<pre>") == 34, "× 代码块数量变了"
    # 单文件零依赖：不得出现任何外部资源引用
    for pat in (r'<link\b[^>]*\bhref="(?!#)', r'<script\b[^>]*\bsrc=', r'@import', r'https?://[^\s"\')]+\.(?:js|css|woff2?|png|jpg|svg)'):
        assert not re.search(pat, out, re.I), f"× 出现了外部依赖：{pat}"
    # 数据块必须能作为 JSON 解析
    m = re.search(r'<script id="kb-data" type="application/json">(.*?)</script>', out, re.S)
    assert m, "× 找不到内联数据块"
    reparsed = json.loads(m.group(1).replace("<\\/", "</"))
    assert len(reparsed["arts"]) == len(data["arts"]), "× 内联数据条目数对不上"
    print(f"  断言通过：{len(ids)} 锚点 · 目录层级 {lvl_total} · {len(data['cats'])} 分类 · "
          f"零外部依赖 · JSON 可解析")

    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(out, encoding="utf-8")

    kb = len(out.encode("utf-8")) / 1024
    print(f"\n✓ 已生成 {dest}")
    print(f"  {kb:.1f} KB · {len(data['arts'])} 条 · {len(data['cats'])} 类 · "
          f"{data['meta']['stats']['anchors']} 锚点 · {data['meta']['stats']['tables']} 表格 · "
          f"{data['meta']['stats']['code']} 代码块")


if __name__ == "__main__":
    main()
