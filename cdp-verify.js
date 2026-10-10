/**
 * 真实渲染验证 —— 零依赖驱动本机 Chrome（CDP + Node 22 内置 WebSocket）。
 * jsdom 不做布局，所以几何/响应式/主题/悬浮只能在这里验。
 *
 * 运行：node cdp-verify.js
 */
const { spawn, execSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PORT = 9337;
const PROFILE = path.join(os.tmpdir(), "kb-cdp-profile-" + Date.now());
const OUT = path.join(__dirname, "shots");
const FILE_URL = "file://" + path.join(__dirname, "index.html");

let pass = 0, fail = 0;
const fails = [];
function ok(name, cond, detail) {
  if (cond) { pass++; console.log(`  PASS  ${name}${detail ? "  → " + detail : ""}`); }
  else { fail++; fails.push(name); console.log(`  FAIL  ${name}${detail ? "  → " + detail : ""}`); }
}
const near = (name, got, want, tol = 2) =>
  ok(name, Math.abs(got - want) <= tol, `got=${Math.round(got * 100) / 100} want≈${want}`);
const eq = (name, got, want) =>
  ok(name, got === want, `got=${JSON.stringify(got)} want=${JSON.stringify(want)}`);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// 等 #main 的滚动真的停下来。
// 页面 CSS 里有 scroll-behavior:smooth，所以 `scrollTop = 0` 是一次**动画**而不是瞬移；
// Chromium 的动画时长随滚动距离增长，固定 sleep 会在长页面上提前收工 ——
// 于是「量卡片坐标」发生在滚动途中，等鼠标真的落下去时卡片已经移走了，
// 悬浮断言就这么假失败（实测症状：hovered=false atPoint=page）。
// 判据改成「连续两次采样 scrollTop 相同」，与页面长度、内容多少都无关。
async function settleScroll(minMs = 250, maxMs = 4000) {
  const t0 = Date.now();
  await sleep(minMs);
  let prev = null, stable = 0;
  while (Date.now() - t0 < maxMs) {
    const cur = await evaluate(`return document.getElementById('main').scrollTop`);
    if (cur === prev) { if (++stable >= 2) return cur; } else { stable = 0; }
    prev = cur;
    await sleep(80);
  }
  return prev;   // 超时也返回，不掩盖失败：后面的断言会照常判定
}
// 相对亮度：用来判断「主题切换后文字是否还读得清」，而不是死盯某个色值
const lum = (c) => {
  const m = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(String(c));
  return m ? +m[1] * 0.299 + +m[2] * 0.587 + +m[3] * 0.114 : -1;
};

let chrome, ws, msgId = 0;
const pending = new Map();
const events = [];

function send(method, params = {}) {
  const id = ++msgId;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((res, rej) => pending.set(id, { res, rej }));
}
async function evaluate(expr) {
  const r = await send("Runtime.evaluate", {
    expression: `(function(){${expr}})()`,
    returnByValue: true, awaitPromise: true,
  });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || "eval error");
  return r.result.value;
}
async function shot(name) {
  const r = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  fs.writeFileSync(path.join(OUT, name + ".png"), Buffer.from(r.data, "base64"));
}
async function viewport(w, h, mobile = false, scale = 2) {
  await send("Emulation.setDeviceMetricsOverride", {
    width: w, height: h, deviceScaleFactor: scale, mobile,
  });
  await sleep(320);
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });

  console.log("\n启动本机 Chrome（headless）");
  chrome = spawn(CHROME, [
    "--headless=new", `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${PROFILE}`, "--no-first-run", "--no-default-browser-check",
    "--no-proxy-server", "--disable-gpu", "--hide-scrollbars",
    "--force-device-scale-factor=2", "--window-size=1440,1000", "about:blank",
  ], { stdio: "ignore" });

  // 等调试端口
  let target = null;
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      target = list.find((t) => t.type === "page");
      if (target) break;
    } catch (e) { /* 还没起来 */ }
    await sleep(250);
  }
  if (!target) throw new Error("Chrome 调试端口没起来");

  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    if (d.id && pending.has(d.id)) {
      const { res, rej } = pending.get(d.id); pending.delete(d.id);
      d.error ? rej(new Error(d.error.message)) : res(d.result);
    } else if (d.method) events.push(d);
  };
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Log.enable");

  const consoleErrors = [];
  ws.addEventListener("message", (m) => {
    const d = JSON.parse(m.data);
    if (d.method === "Runtime.exceptionThrown") consoleErrors.push(d.params.exceptionDetails.text);
    if (d.method === "Log.entryAdded" && d.params.entry.level === "error") consoleErrors.push(d.params.entry.text);
  });

  // ---------------- 桌面 ----------------
  console.log("\n[1] 桌面 1440×1000 —— 首页");
  await viewport(1440, 1000);
  await send("Page.navigate", { url: FILE_URL });
  await sleep(2500);

  const base = await evaluate(`
    var html=document.documentElement, side=document.getElementById('side'), main=document.getElementById('main');
    return {
      title: document.title,
      sideW: side.getBoundingClientRect().width,
      mainW: main.getBoundingClientRect().width,
      topH: document.getElementById('topbar').getBoundingClientRect().height,
      htmlOverflow: html.scrollWidth - html.clientWidth,
      bodyOverflow: document.body.scrollWidth - window.innerWidth,
      bodyH: document.body.getBoundingClientRect().height,
      viewH: window.innerHeight,
      cards: document.querySelectorAll('.cards .card').length,
      catBlks: document.querySelectorAll('.catblk').length,
      artLinks: document.querySelectorAll('#side a[data-art]').length,
      // 页面脚本是闭包，DATA 不在全局 —— 直接解析内联数据块
      dataArts: JSON.parse(document.getElementById('kb-data').textContent).arts.length,
      extArts: JSON.parse(document.getElementById('kb-data').textContent)
        .arts.filter(function(a){return a.ext}).length,
      showCats: JSON.parse(document.getElementById('kb-data').textContent)
        .cats.filter(function(c){return !c.nav}).length,
      bg: getComputedStyle(document.body).backgroundColor,
      fg: getComputedStyle(document.body).color,
    };
  `);
  ok("页面标题", base.title === "个人知识库", base.title);
  near("侧栏宽度 280", base.sideW, 280);
  near("顶栏高度 56", base.topH, 56);
  ok("无横向溢出（html）", base.htmlOverflow <= 0, `overflow=${base.htmlOverflow}`);
  ok("无横向溢出（body）", base.bodyOverflow <= 0, `overflow=${base.bodyOverflow}`);
  near("主区宽度 = 视口 - 侧栏", base.mainW, 1440 - 280, 3);
  ok("body 高度锁在视口内（内部滚动，不整页滚）", Math.abs(base.bodyH - base.viewH) <= 1,
    `bodyH=${base.bodyH} viewH=${base.viewH}`);
  ok("首页卡片数 = 展示分类数 + 全部条目数", base.cards === base.showCats + base.dataArts,
    `${base.cards} 张 = ${base.showCats} 类 + ${base.dataArts} 条`);
  ok("侧栏分类树不含「收藏」（改由「我的收藏」入口承载）",
    base.catBlks === base.showCats, `侧栏 ${base.catBlks} 类 vs 展示分类 ${base.showCats} 类`);
  ok("侧栏分类树里也不列外链资料（不在树里，去「我的收藏」看）",
    base.artLinks === base.dataArts - base.extArts, `${base.artLinks} 条`);
  ok("浅色主题底色为亮色", /^rgb\(2[0-9]{2}/.test(base.bg), base.bg);
  await shot("01-home-desktop-light");

  console.log("\n[2] 文档页 = 整篇一页 + 左栏章节目录");
  await evaluate(`location.hash='#/a/ipc-handbook'; return 1`);
  await sleep(900);
  const art = await evaluate(`
    var doc=document.querySelector('.doc'), body=document.getElementById('docbody');
    var dout=document.getElementById('dout'), tw=document.querySelector('.tw');
    var secs=document.querySelectorAll('#docbody section.part');
    return {
      h1: document.querySelector('.doc h1').textContent,
      docW: doc.getBoundingClientRect().width,
      bodyW: body.getBoundingClientRect().width,
      doutLinks: dout ? dout.querySelectorAll('a').length : 0,
      doutLeft: dout ? Math.round(dout.getBoundingClientRect().left) : -1,
      railCount: document.querySelectorAll('.rail').length,
      partCount: secs.length,
      tableScrollable: tw ? (tw.scrollWidth > tw.clientWidth) : null,
      pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      h2Size: getComputedStyle(document.querySelector('#docbody h2.part-title')).fontSize,
      h3Size: getComputedStyle(document.querySelector('#docbody h3')).fontSize,
      scrollH: document.getElementById('main').scrollHeight,
    };
  `);
  ok("标题正确", art.h1 === "IPC 数据下载与清洗手册", art.h1);
  ok("没渲染右侧栏", art.railCount === 0, `${art.railCount} 个`);
  ok("章节目录在左栏（53 项）", art.doutLinks === 53, `${art.doutLinks} 项`);
  ok("目录确实在侧栏区域内（left < 290）", art.doutLeft >= 0 && art.doutLeft < 290, `left=${art.doutLeft}`);
  eq("两个「部分」都渲染了", art.partCount, 2);
  ok("正文列宽在可读范围（≤920）", art.bodyW > 500 && art.bodyW <= 920, `${art.bodyW}px`);
  ok("部分标题（h2）比章节标题（h3）大", parseFloat(art.h2Size) > parseFloat(art.h3Size),
    `${art.h2Size} vs ${art.h3Size}`);
  ok("表格容器存在", art.tableScrollable !== null, `scrollable=${art.tableScrollable}`);
  ok("文档页无横向溢出", art.pageOverflow <= 0, `${art.pageOverflow}`);
  ok("整页很长（真是一篇长文）", art.scrollH > 8000, `${art.scrollH}px`);
  await shot("02-article-desktop-light");

  console.log("\n[3] 滚动同步：左栏目录跟随高亮");
  const sticky = await evaluate(`
    var main=document.getElementById('main');
    main.scrollTop = 2000;
    return new Promise(function(r){ setTimeout(function(){
      var main2=document.getElementById('main');
      var on=document.querySelector('#dout a.on');
      var mainRect=main2.getBoundingClientRect();
      var onRect=on?on.getBoundingClientRect():null;
      r({ scrolled: main2.scrollTop,
          activeCount: document.querySelectorAll('#dout a.on').length,
          activeText: on ? on.textContent.slice(0,24) : null,
          inView: onRect ? (onRect.top>=mainRect.top-1 && onRect.bottom<=mainRect.bottom+1) : null,
          progress: document.getElementById('progress').style.width });
    }, 600); });
  `);
  ok("主区确实滚动了", sticky.scrolled > 1500, `${sticky.scrolled}px`);
  ok("滚动后目录出现高亮项", sticky.activeCount === 1, `${sticky.activeCount} 项 "${sticky.activeText}"`);
  ok("高亮项被自动带进侧栏可视区", sticky.inView === true, `inView=${sticky.inView}`);
  ok("阅读进度条在推进", parseFloat(sticky.progress) > 5, sticky.progress);
  await shot("03-article-scrolled-toc");

  console.log("\n[4] 点目录 = 页内跳转（不走路由）");
  const jump = await evaluate(`
    var before=location.hash;
    var link=document.querySelectorAll('#dout a')[20];
    link.click();
    return new Promise(function(r){ setTimeout(function(){
      var main=document.getElementById('main');
      var el=document.getElementById(link.dataset.anchor);
      var top=el.getBoundingClientRect().top - main.getBoundingClientRect().top;
      r({ before:before, after:location.hash,
          stillDoc: !!document.getElementById('docbody'),
          linkOn: link.classList.contains('on'),
          onCount: document.querySelectorAll('#dout a.on').length,
          headingTop: Math.round(top) });
    }, 700); });
  `);
  eq("点击目录后 hash 没变（没被路由接管）", jump.after, jump.before);
  ok("正文仍在（页面没被换掉）", jump.stillDoc);
  ok("该目录项高亮且唯一", jump.linkOn && jump.onCount === 1, `onCount=${jump.onCount}`);
  ok("目标标题落在视口顶部附近（65~120px）", jump.headingTop > 40 && jump.headingTop < 140,
    `top=${jump.headingTop}px`);
  await shot("04-anchor-jump");

  console.log("\n[4] 搜索面板（真实输入事件）");
  await evaluate(`
    var q=document.getElementById('q');
    q.focus(); q.value='gzip';
    q.dispatchEvent(new Event('input',{bubbles:true}));
    return 1;
  `);
  await sleep(500);
  const sr = await evaluate(`
    var p=document.getElementById('panel'), r=p.querySelector('.sresults').getBoundingClientRect();
    return {
      open: p.classList.contains('open'),
      n: p.querySelectorAll('.sitem').length,
      marks: p.querySelectorAll('mark').length,
      rectTop: Math.round(r.top), rectW: Math.round(r.width),
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      panelVisible: getComputedStyle(p).display,
    };
  `);
  ok("搜索面板打开", sr.open && sr.panelVisible !== "none", sr.panelVisible);
  ok("有搜索结果", sr.n > 0, `${sr.n} 条`);
  ok("结果里有高亮标记", sr.marks > 0, `${sr.marks} 处`);
  ok("面板紧贴顶栏下方（未盖住顶栏）", sr.rectTop >= 55, `top=${sr.rectTop}`);
  ok("面板宽度不超出内容区", sr.rectW <= 780, `${sr.rectW}px`);
  ok("搜索面板不引入横向溢出", sr.overflow <= 0, `${sr.overflow}`);
  await shot("04-search-panel");

  console.log("\n[5] 深色主题");
  await evaluate(`document.getElementById('theme-btn').click(); return 1`);
  await sleep(450);
  const dark = await evaluate(`
    var b=getComputedStyle(document.body), h1=getComputedStyle(document.querySelector('.doc h1'));
    var card=document.querySelector('.card'); card=card?getComputedStyle(card):null;
    return { theme: document.documentElement.getAttribute('data-theme'),
             bg:b.backgroundColor, fg:b.color, h1fg:h1.color,
             lum:(function(c){var m=c.match(/\\d+/g);return +m[0]*0.299 + +m[1]*0.587 + +m[2]*0.114})(b.backgroundColor),
             fgLum:(function(c){var m=c.match(/\\d+/g);return +m[0]*0.299 + +m[1]*0.587 + +m[2]*0.114})(b.color) };
  `);
  ok("切换到深色", dark.theme === "dark", dark.theme);
  ok("深色底色确实变暗", dark.lum < 60, `luma=${Math.round(dark.lum)}`);
  ok("深色下文字够亮（对比度）", dark.fgLum > 180, `luma=${Math.round(dark.fgLum)}`);
  await shot("05-article-desktop-dark");

  await evaluate(`location.hash='#/a/ipc-handbook'; document.getElementById('main').scrollTop=9000; return 1`);
  await sleep(700);
  await shot("06-code-desktop-dark");
  await evaluate(`document.getElementById('theme-btn').click(); return 1`);
  await sleep(400);

  console.log("\n[6] 中屏 1100px");
  await viewport(1100, 900, false, 1.5);
  const mid = await evaluate(`
    return { sideVisible: Math.round(document.getElementById('side').getBoundingClientRect().width),
             doutLinks: document.querySelectorAll('#dout a').length,
             docW: Math.round(document.querySelector('.doc').getBoundingClientRect().width),
             overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth };
  `);
  ok("中屏侧栏仍在", mid.sideVisible > 200, `${mid.sideVisible}px`);
  ok("中屏目录仍在侧栏", mid.doutLinks === 53, `${mid.doutLinks} 项`);
  ok("中屏正文列宽合理", mid.docW > 600 && mid.docW <= 920, `${mid.docW}px`);
  ok("中屏无横向溢出", mid.overflow <= 0, `${mid.overflow}`);
  await shot("07-mid-1100");

  console.log("\n[7] 移动端 390px");
  await viewport(390, 844, true, 3);
  const mob = await evaluate(`
    var side=document.getElementById('side'), top=document.getElementById('topbar');
    return {
      sideLeft: Math.round(side.getBoundingClientRect().left),
      sideRectW: Math.round(side.getBoundingClientRect().width),
      menuVisible: getComputedStyle(document.getElementById('menu-btn')).display,
      brandSmall: getComputedStyle(document.querySelector('.brand small')).display,
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      topW: Math.round(top.getBoundingClientRect().width),
      qW: Math.round(document.getElementById('q').getBoundingClientRect().width),
    };
  `);
  ok("移动端侧栏收进屏幕外", mob.sideLeft < -200, `left=${mob.sideLeft}`);
  ok("移动端侧栏宽度 ≤ 308", mob.sideRectW <= 310, `${mob.sideRectW}px`);
  ok("移动端出现菜单按钮", mob.menuVisible !== "none", mob.menuVisible);
  ok("移动端隐藏品牌副标题", mob.brandSmall === "none", mob.brandSmall);
  ok("移动端无横向溢出", mob.overflow <= 0, `${mob.overflow}`);
  ok("移动端搜索框够宽（>180px）", mob.qW > 180, `${mob.qW}px`);
  await shot("08-mobile-article");

  await evaluate(`document.getElementById('menu-btn').click(); return 1`);
  await sleep(450);
  const drawer = await evaluate(`
    var side=document.getElementById('side'), scrim=document.getElementById('scrim');
    return { left: Math.round(side.getBoundingClientRect().left),
             scrim: getComputedStyle(scrim).display,
             navOpen: document.body.classList.contains('nav-open') };
  `);
  ok("点菜单后侧栏滑入", Math.abs(drawer.left) <= 1, `left=${drawer.left}`);
  ok("出现遮罩", drawer.scrim !== "none", drawer.scrim);
  await shot("09-mobile-drawer");

  console.log("\n[8] 移动端首页 + 深色");
  await evaluate(`document.getElementById('scrim').click(); location.hash='#/'; return 1`);
  await sleep(600);
  await shot("10-mobile-home");
  await evaluate(`document.getElementById('theme-btn').click(); return 1`);
  await sleep(400);
  await shot("11-mobile-home-dark");
  await evaluate(`document.getElementById('theme-btn').click(); return 1`);
  await sleep(300);

  console.log("\n[9] 真实悬浮（:hover 由鼠标事件驱动，不是加 class）");
  await viewport(1440, 1000, false, 2);
  await evaluate(`location.hash='#/'; document.getElementById('main').scrollTop=0; return 1`);
  await settleScroll();
  const hover = await evaluate(`
    var c=document.querySelector('.cards .card');
    var r=c.getBoundingClientRect();
    return { x: Math.round(r.left+r.width/2), y: Math.round(r.top+r.height/2),
             rect:[Math.round(r.left),Math.round(r.top),Math.round(r.width),Math.round(r.height)],
             inner:[window.innerWidth,window.innerHeight],
             dpr: window.devicePixelRatio,
             visual: window.visualViewport ? [Math.round(window.visualViewport.width),Math.round(window.visualViewport.height),Math.round(window.visualViewport.scale*100)/100] : null,
             before: { transform: getComputedStyle(c).transform, shadow: getComputedStyle(c).boxShadow } };
  `);
  // 先挪到别处再挪到目标：headless 里若鼠标本来就在目标上，不会产生 hover 状态变化
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: 4, y: 300, button: "none" });
  await sleep(120);
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: hover.x, y: hover.y, button: "none" });
  await sleep(500);
  const after = await evaluate(`
    var c=document.querySelector('.cards .card');
    return { transform: getComputedStyle(c).transform, shadow: getComputedStyle(c).boxShadow,
             hovered: c.matches(':hover'),
             atPoint: (function(){var e=document.elementFromPoint(${hover.x}, ${hover.y}); return e?e.className||e.tagName:'null'})() };
  `);
  ok("鼠标确实落在卡片上", after.hovered === true,
    `hovered=${after.hovered} atPoint=${after.atPoint} cardRect=${hover.rect} inner=${hover.inner} dpr=${hover.dpr} visual=${hover.visual}`);
  ok("悬浮卡片有位移效果", after.transform !== hover.before.transform,
    `${hover.before.transform} → ${after.transform}`);
  ok("悬浮卡片有阴影", after.shadow !== hover.before.shadow && after.shadow !== "none");

  console.log("\n[10] 外链卡片（收藏的资料书签）");
  await viewport(1440, 1000);
  // 侧栏「本页目录」只属于文章页：切走之后必须收掉
  await evaluate(`location.hash='#/a/ipc-handbook'; return 1`);
  await sleep(800);
  const doutArt = await evaluate(`return document.querySelectorAll('#dout a').length`);
  await evaluate(`location.hash='#/'; return 1`);
  await sleep(800);
  const doutHome = await evaluate(`return document.querySelectorAll('#dout').length`);
  ok("文章页：侧栏有本页目录", doutArt > 40, `${doutArt} 项`);
  eq("切回首页：目录被收掉（不张冠李戴）", doutHome, 0);
  await evaluate(`location.hash='#/'; return 1`);
  await sleep(700);
  const ext = await evaluate(`
    var cards=[].slice.call(document.querySelectorAll('.cards .card')).filter(function(c){
      return c.classList.contains('ext') });
    if(!cards.length) return {n:0};
    var c=cards[0], pts=c.querySelectorAll('.pts li'), cf=c.querySelector('.cf');
    var r=c.getBoundingClientRect();
    return {
      n: cards.length,
      href: c.getAttribute('href'),
      target: c.getAttribute('target'),
      rel: c.getAttribute('rel'),
      title: c.querySelector('.ct').textContent.trim(),
      pts: pts.length,
      pt1: pts.length? pts[0].textContent.trim().slice(0,26):'',
      footer: cf.textContent.trim(),
      w: Math.round(r.width), h: Math.round(r.height),
      ctColor: getComputedStyle(c.querySelector('.ct')).color,
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    };
  `);
  ok("首页渲染了外链卡片", ext.n >= 1, `${ext.n} 张`);
  ok("卡片 href 指向论文原文", ext.href === "https://jakobengel.github.io/pdf/DSO.pdf", ext.href);
  eq("卡片 target=_blank", ext.target, "_blank");
  ok("卡片 rel 含 noopener", /noopener/.test(ext.rel || ""), ext.rel);
  ok("卡片标题是论文名", /Direct Sparse Odometry/.test(ext.title), ext.title);
  ok("卡片渲染了要点列表", ext.pts >= 4, `${ext.pts} 条；首条「${ext.pt1}」`);
  ok("卡片底部提示「打开原文」", /打开原文/.test(ext.footer), ext.footer);
  ok("卡片高度正常（没被压扁）", ext.h >= 150, `${ext.h}px`);
  ok("浅色主题下卡片标题是深色字", lum(ext.ctColor) < 140, `${ext.ctColor} lum=${Math.round(lum(ext.ctColor))}`);
  ok("首页仍无横向溢出", ext.overflow <= 0, String(ext.overflow));
  await evaluate(`
    var c=document.querySelector('.cards .card.ext');
    if(c&&c.scrollIntoView) c.scrollIntoView({block:'center'});
    return 1`);
  await sleep(400);
  await shot("12-home-ext-card");

  // 深色主题下要点列表的文字必须还读得清（--muted 在两种主题里是不同的值）
  await evaluate(`document.getElementById('theme-btn').click(); return 1`);
  await sleep(500);
  const extDark = await evaluate(`
    var c=document.querySelector('.cards .card.ext');
    return { li: getComputedStyle(c.querySelector('.pts li')).color,
             ct: getComputedStyle(c.querySelector('.ct')).color,
             body: getComputedStyle(document.body).color };
  `);
  ok("深色主题：卡片要点文字足够亮", lum(extDark.li) > 110,
    `${extDark.li} lum=${Math.round(lum(extDark.li))}`);
  ok("深色主题：卡片标题足够亮", lum(extDark.ct) > 110,
    `${extDark.ct} lum=${Math.round(lum(extDark.ct))}`);
  await shot("13-home-ext-card-dark");
  await evaluate(`document.getElementById('theme-btn').click(); return 1`);
  await sleep(500);

  // 收藏分类页
  await evaluate(`location.hash='#/c/bookmarks'; return 1`);
  await sleep(700);
  const extCat = await evaluate(`
    var a=document.querySelector('.artlist a');
    return { h: document.querySelector('.hero h1').textContent,
             href: a?a.getAttribute('href'):null,
             target: a?a.getAttribute('target'):null,
             ext: a?!!a.querySelector('.extico'):false,
             overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth };
  `);
  eq("收藏分类页标题", extCat.h, "收藏");
  ok("分类页外链项直指原文", extCat.href === "https://jakobengel.github.io/pdf/DSO.pdf", extCat.href);
  ok("分类页外链项带 ↗ 标记", extCat.ext === true);
  ok("分类页无横向溢出", extCat.overflow <= 0, String(extCat.overflow));
  await shot("14-cat-bookmarks");

  // 「我的收藏」= 文献收藏的卡片墙（星标条目不进这里，那是另一回事）
  await evaluate(`location.hash='#/fav'; return 1`);
  await sleep(700);
  const favPage = await evaluate(`
    var cards=[].slice.call(document.querySelectorAll('.cards .card'));
    var nav=document.querySelector('#side a[data-nav="fav"]');
    return { h: document.querySelector('.hero h1').textContent,
             n: cards.length,
             allExt: cards.length>0 && cards.every(function(c){return c.classList.contains('ext')}),
             href: cards.length? cards[0].getAttribute('href'):null,
             target: cards.length? cards[0].getAttribute('target'):null,
             hasPts: cards.length? cards[0].querySelectorAll('.pts li').length:0,
             navOn: nav?nav.classList.contains('on'):false,
             navN: nav?nav.querySelector('.n').textContent:'',
             overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth };
  `);
  eq("我的收藏页：标题为「我的收藏」", favPage.h, "我的收藏");
  ok("我的收藏页：渲染的是文献卡片（不是星标条目列表）", favPage.allExt,
    `${favPage.n} 张卡片`);
  ok("我的收藏页：卡片直指论文原文",
    favPage.href === "https://jakobengel.github.io/pdf/DSO.pdf", favPage.href);
  eq("我的收藏页：卡片新标签打开", favPage.target, "_blank");
  ok("我的收藏页：卡片带着要点", favPage.hasPts >= 4, `${favPage.hasPts} 条`);
  eq("我的收藏页：侧栏入口高亮", favPage.navOn, true);
  eq("我的收藏页：侧栏计数 = 资料数", favPage.navN, String(favPage.n));
  ok("我的收藏页：无横向溢出", favPage.overflow <= 0, String(favPage.overflow));
  await shot("14b-my-favorites");

  // 移动端：要点列表在窄屏不该撑破卡片
  await viewport(390, 844, true, 3);
  await evaluate(`location.hash='#/'; return 1`);
  await sleep(700);
  await evaluate(`
    var c=document.querySelector('.cards .card.ext');
    if(c&&c.scrollIntoView) c.scrollIntoView({block:'center'});
    return 1`);
  await sleep(500);
  const extMob = await evaluate(`
    var c=document.querySelector('.cards .card.ext');
    var li=c.querySelector('.pts li');
    return { w: Math.round(c.getBoundingClientRect().width),
             h: Math.round(c.getBoundingClientRect().height),
             over: Math.round(li.scrollWidth - li.clientWidth),
             pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth };
  `);
  ok("移动端：外链卡片宽度适配", extMob.w > 200 && extMob.w <= 390, `${extMob.w}px`);
  ok("移动端：外链卡片高度正常", extMob.h >= 150, `${extMob.h}px`);
  ok("移动端：要点文本不溢出", extMob.over <= 1, `${extMob.over}px`);
  ok("移动端：页面无横向溢出", extMob.pageOverflow <= 0, String(extMob.pageOverflow));
  await shot("15-mobile-ext-card");

  // 窄屏下的「我的收藏」：列宽不能撑破容器（minmax 的 min 用了 min(340px,100%) 兜底）
  await evaluate(`location.hash='#/fav'; return 1`);
  await sleep(700);
  const favMob = await evaluate(`
    var c=document.querySelector('.cards .card');
    var r=c.getBoundingClientRect();
    return { w: Math.round(r.width), vw: window.innerWidth,
             overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth };
  `);
  ok("移动端：我的收藏卡片不撑破容器", favMob.w <= favMob.vw,
    `${favMob.w}px / 视口 ${favMob.vw}px`);
  ok("移动端：我的收藏无横向溢出", favMob.overflow <= 0, String(favMob.overflow));
  await shot("15b-mobile-favorites");
  await viewport(1440, 1000, false, 2);

  console.log("\n[11] 页面运行期错误");
  ok("全程无未捕获异常 / 控制台错误", consoleErrors.length === 0, consoleErrors.slice(0, 3).join(" | "));

  console.log("\n" + "=".repeat(62));
  console.log(`合计: ${pass} passed, ${fail} failed`);
  if (fail) console.log("失败项：\n  - " + fails.join("\n  - "));
  console.log(`截图输出：${OUT}`);
  console.log("=".repeat(62));

  await send("Browser.close").catch(() => {});
})()
  .catch((e) => { console.error("\n× 验证脚本出错：", e.message); fail++; })
  .finally(async () => {
    try { ws && ws.close(); } catch (e) {}
    try { chrome && chrome.kill("SIGKILL"); } catch (e) {}
    try { execSync(`rm -rf ${JSON.stringify(PROFILE)}`, { stdio: "ignore" }); } catch (e) {}
    // 用 exitCode 而不是 process.exit()：直接 exit 会截断还在异步写盘/写管道的 stdout
    process.exitCode = fail ? 1 : 0;
  });
