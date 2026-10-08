/**
 * 个人知识库端到端验证 —— 用 jsdom 真跑一遍页面脚本，断言 DOM 与副作用。
 * 运行：
 *   NODE_PATH=/Users/yangqijun/.workbuddy/binaries/node/workspace/node_modules \
 *   /Users/yangqijun/.workbuddy/binaries/node/versions/22.22.2-3/bin/node verify.js
 */
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");

const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");

let pass = 0, fail = 0;
const fails = [];
function ok(name, cond, detail) {
  if (cond) { pass++; console.log(`  PASS  ${name}${detail ? "  → " + detail : ""}`); }
  else { fail++; fails.push(name); console.log(`  FAIL  ${name}${detail ? "  → " + detail : ""}`); }
}
function eq(name, got, want) {
  ok(name, got === want, `got=${JSON.stringify(got)} want=${JSON.stringify(want)}`);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ------------- 静态检查（先静态，再动态） -------------
console.log("\n[1] 静态检查：零依赖 + 数据完整性");

[
  [/<link\b[^>]*\bhref="(?!#)/i, "外部 <link>"],
  [/<script\b[^>]*\bsrc=/i, "外部 <script src>"],
  [/@import/i, "CSS @import"],
  [/https?:\/\/(?!www\.w3\.org)[^\s"')]+\.(?:js|css|woff2?|ttf|png|jpe?g|gif|svg)/i, "外部资源 URL"],
].forEach(([re, label]) => ok(`零外部依赖：无${label}`, !re.test(html)));

const m = html.match(/<script id="kb-data" type="application\/json">([\s\S]*?)<\/script>/);
ok("内联数据块存在", !!m);
let DATA = null;
try { DATA = JSON.parse(m[1].replace(/<\\\//g, "</")); ok("内联数据块是合法 JSON", true); }
catch (e) { ok("内联数据块是合法 JSON", false, e.message); }

// 从正文现算的全量统计：首页 / 侧栏显示的数字必须与它一致。
// 内容会持续增长，所以断言「UI 忠实反映数据」，而不是硬编码某个时期的绝对值。
const calc = DATA ? {
  arts: DATA.arts.length,
  cats: DATA.cats.length,
  words: DATA.arts.reduce((s, a) => s + a.words, 0),
  tables: DATA.arts.reduce((s, a) => s + (a.html.match(/<table/g) || []).length, 0),
  code: DATA.arts.reduce((s, a) => s + (a.html.match(/<pre>/g) || []).length, 0),
  anchors: DATA.arts.reduce((s, a) => s + (a.html.match(/\sid="/g) || []).length, 0),
} : {};

if (DATA) {
  ok("数据：至少收录 1 个条目", DATA.arts.length >= 1,
    `${DATA.arts.length} 条 / ${DATA.cats.length} 类`);
  eq("数据：条目 id 唯一", new Set(DATA.arts.map((a) => a.id)).size, DATA.arts.length);
  ok("数据：每个条目的分类都已登记",
    DATA.arts.every((a) => DATA.cats.some((c) => c.id === a.cat)),
    DATA.arts.filter((a) => !DATA.cats.some((c) => c.id === a.cat)).map((a) => a.id).join(","));
  eq("数据：首篇表格 15（与原文一致）", (DATA.arts[0].html.match(/<table/g) || []).length, 15);
  eq("数据：首篇代码块 34（与原文一致）", (DATA.arts[0].html.match(/<pre>/g) || []).length, 34);
  ok("数据：全量统计与现算一致",
    calc.tables === DATA.meta.stats.tables && calc.code === DATA.meta.stats.code
      && calc.anchors === DATA.meta.stats.anchors && calc.words === DATA.meta.stats.words,
    `表格 ${calc.tables}/${DATA.meta.stats.tables} 代码 ${calc.code}/${DATA.meta.stats.code} `
      + `锚点 ${calc.anchors}/${DATA.meta.stats.anchors} 字数 ${calc.words}/${DATA.meta.stats.words}`);
  const ol = DATA.arts[0].outline;
  const lv = [1, 2, 3, 4].map((k) => ol.filter((o) => o.lvl === k).length);
  eq("数据：目录层级 [2,17,28,6]（原文 h1/h2/h3/h4 = 2/17/28/6）", lv.join(","), "2,17,28,6");
  ok("数据：正文里没有 h1（条目标题独占 h1）", !/<h1\b/.test(DATA.arts[0].html));
  const anchors = [...DATA.arts[0].html.matchAll(/\sid="([^"]+)"/g)].map((x) => x[1]);
  eq("数据：锚点全局唯一", new Set(anchors).size, anchors.length);
  eq("数据：锚点总数 55（53 标题 + 2 部分容器）", anchors.length, 55);
  ok("数据：目录锚点全部能在正文里找到",
    ol.every((o) => anchors.includes(o.id)),
    ol.filter((o) => !anchors.includes(o.id)).map((o) => o.id).join(","));
  ok("数据：「第一部分」「第二部分」都在目录里",
    ol.some((o) => o.text.includes("第一部分")) && ol.some((o) => o.text.includes("第二部分")));
  ok("数据：条目有摘要与标签", !!DATA.arts[0].summary && DATA.arts[0].tags.length >= 5);
}

// ------------- 动态检查 -------------
(async () => {
  console.log("\n[2] 启动");
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push("jsdomError: " + e.message));
  vc.on("error", (msg) => errors.push("console.error: " + msg));

  const dom = new JSDOM(html, {
    runScripts: "dangerously",
    pretendToBeVisual: true,
    url: "http://localhost:8080/index.html",
    virtualConsole: vc,
    beforeParse(window) {
      window.addEventListener("error", (e) => errors.push("window.onerror: " + e.message));
    },
  });
  const { window } = dom;
  const doc = window.document;
  const $ = (s) => doc.querySelector(s);
  const $$ = (s) => Array.from(doc.querySelectorAll(s));
  const go = async (hash) => {
    window.location.hash = hash;
    window.dispatchEvent(new window.HashChangeEvent("hashchange"));
    await sleep(20);
  };

  eq("启动无 JS 异常", errors.length, 0, errors.slice(0, 3).join(" | "));

  console.log("\n[3] 侧栏（首页态）");
  eq("侧栏：分类块数 = 数据分类数", $$(".catblk").length, calc.cats);
  eq("侧栏：条目链接数 = 数据条目数", $$("#side a[data-art]").length, calc.arts);
  eq("侧栏：快捷入口 4 个", $$("#side a[data-nav]").length, 4);
  ok("侧栏：首页默认高亮", $('#side a[data-nav="home"]').classList.contains("on"));
  eq("侧栏：条目名正确", $('#side a[data-art]').textContent.trim(), "IPC 数据下载与清洗手册");
  eq("首页态不显示本页目录", $$("#dout").length, 0);

  console.log("\n[4] 首页");
  const stats = $$(".statrow .stat b").map((b) => b.textContent.replace(/,/g, ""));
  eq("首页：统计卡 6 张", stats.length, 6);
  eq("首页：条目数 = 数据条目数", stats[0], String(calc.arts));
  eq("首页：分类数 = 数据分类数", stats[1], String(calc.cats));
  eq("首页：总字数与数据一致", stats[2], String(calc.words));
  eq("首页：表格数 = 现算表格数", stats[3], String(calc.tables));
  eq("首页：代码块数 = 现算代码块数", stats[4], String(calc.code));
  eq("首页：锚点数 = 现算锚点数", stats[5], String(calc.anchors));
  eq("首页：卡片数 = 分类 + 条目", $$(".cards .card").length, calc.cats + calc.arts);
  ok("首页：标签云有内容", $$(".tagcloud a").length >= 9, `${$$(".tagcloud a").length} 个`);
  eq("首页文档标题", doc.title, "个人知识库");

  console.log("\n[5] 文档页 = 整篇一个页面");
  await go("#/a/ipc-handbook");
  eq("标题渲染", $(".doc h1").textContent, "IPC 数据下载与清洗手册");
  eq("文档标题跟随", doc.title, "IPC 数据下载与清洗手册 · 个人知识库");
  ok("面包屑 3 段", $$(".crumbs a, .crumbs span").length >= 3);
  const chars = $("#docbody").textContent.replace(/\s+/g, "").length;
  ok("正文完整（>7000 字）", chars > 7000, `${chars} 字`);
  eq("原文的 15 张表全在", $$("#docbody .tw table").length, 15);
  eq("原文的 34 个代码块全在", $$("#docbody pre").length, 34);
  eq("代码块都注入了复制按钮", $$("#docbody pre .copy").length, 34);
  ok("表格都套了横滑容器", $$("#docbody table").every((t) => t.parentElement.classList.contains("tw")));
  eq("两个「部分」都在", $$("#docbody section.part").length, 2);
  eq("部分标题渲染为 h2", $$("#docbody h2.part-title").length, 2);
  ok("保留了 blockquote 提示块", $$("#docbody blockquote").length >= 10, `${$$("#docbody blockquote").length} 个`);
  eq("翻页栏只在多条目时出现", $$(".pager").length, calc.arts > 1 ? 1 : 0);

  console.log("\n[6] 章节目录挂在侧栏（不是右侧栏）");
  eq("右侧栏已移除", $$(".rail").length, 0);
  const dout = $$("#dout a");
  eq("侧栏目录 53 项", dout.length, 53);
  eq("目录一级 2 项", $$("#dout a.l1").length, 2);
  eq("目录二级 17 项", $$("#dout a.l2").length, 17);
  eq("目录三级 28 项", $$("#dout a.l3").length, 28);
  eq("目录四级 6 项", $$("#dout a.l4").length, 6);
  const dead = dout.filter((l) => {
    const el = doc.getElementById(l.dataset.anchor);
    return !el || !$("#docbody").contains(el);
  });
  eq("目录锚点全部命中正文（0 个悬空）", dead.length, 0, dead.map((d) => d.dataset.anchor).join(","));
  ok("目录首项是「第一部分」", dout[0].textContent.includes("第一部分"), dout[0].textContent);

  console.log("\n[7] 点目录 = 页内跳转，不能触发路由（关键）");
  const before = window.location.hash;
  const target = dout[12];
  target.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true }));
  await sleep(30);
  eq("点击目录后 hash 没被改（没走路由）", window.location.hash, before);
  ok("点击目录后正文仍在（页面没被换掉）", $("#docbody") !== null);
  ok("点击的目录项被标为当前项", target.classList.contains("on"));
  eq("其它目录项没有同时高亮", $$("#dout a.on").length, 1);

  console.log("\n[8] 重新进入文档，目录仍在");
  await go("#/");
  await go("#/a/ipc-handbook");
  eq("目录恢复 53 项", $$("#dout a").length, 53);
  ok("目录分组默认展开", $("#outline-group").hasAttribute("open"));

  console.log("\n[9] 搜索");
  const q = $("#q");
  const search = async (text) => {
    q.value = text;
    q.dispatchEvent(new window.Event("input", { bubbles: true }));
    await sleep(20);
    return $$("#panel .sitem");
  };
  let res = await search("gzip");
  eq("搜索 gzip：命中唯一一篇", res.length, 1);
  ok("搜索 gzip：带高亮", $("#panel .sitem mark") !== null);
  res = await search("物联网");
  eq("搜索中文「物联网」：命中", res.length, 1);
  res = await search("过度合并");
  eq("搜索「过度合并」：命中", res.length, 1);
  res = await search("zzzz不存在zzzz");
  eq("搜索无结果：返回空集（证明确实在过滤）", res.length, 0);
  res = await search("GZIP");
  eq("搜索不区分大小写", res.length, 1);
  await search("&");
  const bad = [...$$("#panel mark")].filter((k) => k.textContent.includes("amp"));
  eq("搜索特殊字符 & ：高亮不半截（不出现 &amp;）", bad.length, 0,
    [...$$("#panel mark")].map((k) => k.textContent).join("|") || "(无高亮)");

  q.value = "坑";
  q.dispatchEvent(new window.Event("input", { bubbles: true }));
  await sleep(20);
  q.dispatchEvent(new window.KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
  await sleep(20);
  ok("搜索：↑↓ 有当前项", $("#panel .sitem.cur") !== null);
  q.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  await sleep(20);
  ok("搜索：Esc 关闭面板", !$("#panel").classList.contains("open"));

  console.log("\n[10] 快捷键");
  doc.dispatchEvent(new window.KeyboardEvent("keydown", { key: "/", bubbles: true }));
  ok("快捷键 / ：聚焦搜索框", doc.activeElement === q);
  eq("快捷键 / ：搜索框被清空", q.value, "");

  console.log("\n[11] 收藏");
  const favBtn = $(".favbtn");
  eq("收藏按钮初始态", favBtn.querySelector(".tx").textContent, "收藏");
  favBtn.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await sleep(20);
  eq("收藏后文案", $(".favbtn .tx").textContent, "已收藏");
  eq("收藏写入 localStorage", JSON.parse(window.localStorage.getItem("kb.favs")).join(","), "ipc-handbook");
  eq("收藏后侧栏出现星标", $$('#side a[data-art="ipc-handbook"] .fav').length, 1);
  eq("收藏动作不会把目录弄丢（侧栏重建后仍在）", $$("#dout a").length, 53);
  $(".favbtn").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await sleep(20);
  eq("取消收藏后 localStorage 为空", window.localStorage.getItem("kb.favs"), "[]");

  console.log("\n[12] 路由：首页 / 分类 / 标签 / 收藏 / 最近");
  await go("#/hist");
  eq("最近阅读：1 条记录", $$(".artlist a").length, 1);
  eq("历史最新一条", JSON.parse(window.localStorage.getItem("kb.hist"))[0], "ipc-handbook");
  await go("#/fav");
  ok("收藏页：显示空态", $(".empty") !== null);
  await go("#/c/data-eng");
  eq("分类页：1 篇", $$(".artlist a").length, 1);
  eq("分类页标题", $(".hero h1").textContent, "数据工程");
  await go("#/tags");
  ok("标签页：有标签", $$(".tagcloud a").length >= 9, `${$$(".tagcloud a").length} 个`);
  await go("#/t/" + encodeURIComponent("IPC"));
  eq("标签 IPC：1 篇", $$(".artlist a").length, 1);
  await go("#/t/不存在zzz");
  ok("不存在的标签：空态", $(".empty") !== null);

  console.log("\n[13] 主题 / 字号");
  const themeBtn = $("#theme-btn");
  eq("初始主题", doc.documentElement.getAttribute("data-theme"), "light");
  themeBtn.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  eq("切换后主题", doc.documentElement.getAttribute("data-theme"), "dark");
  eq("主题写入 localStorage", JSON.parse(window.localStorage.getItem("kb.theme")), "dark");
  eq("主题按钮图标跟随", themeBtn.textContent, "☀");
  themeBtn.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  eq("切回浅色", doc.documentElement.getAttribute("data-theme"), "light");

  const fsBtn = $("#font-btn");
  const fs0 = doc.documentElement.style.getPropertyValue("--fs");
  fsBtn.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  const fs1 = doc.documentElement.style.getPropertyValue("--fs");
  ok("字号可切换", fs0 !== fs1, `${fs0} → ${fs1}`);

  console.log("\n[14] 分类折叠 / 移动端抽屉");
  const head = $('.catblk[data-cat="data-eng"] .chead');
  head.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await sleep(10);
  eq("点击后折叠", $('.catblk[data-cat="data-eng"]').classList.contains("collapsed"), true);
  eq("折叠态写入 localStorage",
    JSON.parse(window.localStorage.getItem("kb.collapsed")).join(","), "data-eng");
  head.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await sleep(10);
  eq("再点展开", $('.catblk[data-cat="data-eng"]').classList.contains("collapsed"), false);

  $("#menu-btn").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  ok("菜单按钮开抽屉", doc.body.classList.contains("nav-open"));
  $("#scrim").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  ok("遮罩点击关抽屉", !doc.body.classList.contains("nav-open"));
  await go("#/");
  await go("#/a/ipc-handbook");
  ok("路由跳转会关掉抽屉", !doc.body.classList.contains("nav-open"));

  console.log("\n[15] 代码复制降级路径（jsdom 无 clipboard）");
  const copyBtn = $("#docbody pre .copy");
  let threw = null;
  try { copyBtn.dispatchEvent(new window.MouseEvent("click", { bubbles: true })); await sleep(30); }
  catch (e) { threw = e.message; }
  eq("点击复制不抛异常", threw, null);

  console.log("\n[16] 导出 / 导入");
  let dl = null;
  window.URL.createObjectURL = (b) => { dl = b; return "blob:fake"; };
  window.URL.revokeObjectURL = () => {};
  window.HTMLAnchorElement.prototype.click = function () { dl = dl || "__clicked__"; };
  doc.querySelector('#side [data-act="export"]').dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await sleep(30);
  ok("导出：生成了下载 payload", dl instanceof window.Blob);
  ok("导出：有 toast 反馈", $("#toast").textContent.includes("导出"), $("#toast").textContent);

  const importBtn = doc.querySelector('#side [data-act="import"]');
  ok("导入：侧栏按钮存在", !!importBtn);
  let importThrew = null;
  const realCreate = doc.createElement.bind(doc);
  doc.createElement = function (tag) {
    const el = realCreate(tag);
    if (String(tag).toLowerCase() === "input") el.click = () => {};
    return el;
  };
  try { importBtn.dispatchEvent(new window.MouseEvent("click", { bubbles: true })); }
  catch (e) { importThrew = e.message; }
  doc.createElement = realCreate;
  eq("导入：点击不抛异常", importThrew, null);

  console.log("\n[17] 最终一致性");
  eq("清理：仍无 JS 异常", errors.length, 0);
  if (errors.length) errors.forEach((e) => console.log("        异常详情: " + e));
  ok("清理：document.title 正确", doc.title.includes("· 个人知识库"), doc.title);
  eq("清理：正文仍在", $$("#docbody section.part").length, 2);

  console.log("\n" + "=".repeat(62));
  console.log(`合计: ${pass} passed, ${fail} failed`);
  if (fail) console.log("失败项：\n  - " + fails.join("\n  - "));
  console.log("=".repeat(62));
  window.close();
  process.exit(fail ? 1 : 0);
})();
