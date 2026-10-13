/* Behavior tests for persistent note edits. Run alongside verify.js. */
const fs=require('fs'), path=require('path'), assert=require('node:assert/strict');
const {JSDOM,VirtualConsole}=require('jsdom');
const html=fs.readFileSync(path.join(__dirname,'index.html'),'utf8');
const tick=()=>new Promise(r=>setTimeout(r,20));
let checks=0;
function check(name,fn){fn();checks++;console.log('PASS '+name)}
function boot(storage={}){
  const errors=[],downloads=[];let fileInput;
  const vc=new VirtualConsole();vc.on('jsdomError',e=>{if(!e.message.includes('navigation'))errors.push(e.message)});
  const dom=new JSDOM(html,{url:'https://kb.test/#/a/rag-system-architecture',runScripts:'dangerously',pretendToBeVisual:true,virtualConsole:vc,
    beforeParse(w){
      Object.entries(storage).forEach(([k,v])=>w.localStorage.setItem(k,v));
      w.HTMLDialogElement.prototype.showModal=function(){this.open=true};
      w.HTMLDialogElement.prototype.close=function(){this.open=false};
      w.confirm=()=>true;
      w.URL.createObjectURL=b=>{downloads.push(b);return 'blob:backup'};w.URL.revokeObjectURL=()=>{};
      w.HTMLInputElement.prototype.click=function(){if(this.type==='file')fileInput=this};
    }});
  const w=dom.window, d=w.document, $=s=>d.querySelector(s);
  const click=s=>{assert.ok($(s),s);$(s).click()};
  const snapshot=()=>Object.fromEntries(Object.keys(w.localStorage).map(k=>[k,w.localStorage.getItem(k)]));
  const submit=()=>$('#edit-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
  const importBackup=async obj=>{click('[data-act="import"]');Object.defineProperty(fileInput,'files',{value:[new w.File([JSON.stringify(obj)],'notes.json',{type:'application/json'})],configurable:true});fileInput.dispatchEvent(new w.Event('change'));await tick()};
  return {dom,w,d,$,click,snapshot,submit,importBackup,errors,downloads};
}
(async()=>{
  let b=boot(),{$,w,click,submit}=b;
  const origTitle=$('.doc h1').textContent,origBody=$('#docbody').innerHTML;
  click('[data-act="edit-note"]');
  check('editor opens with title and preserved tables/code',()=>{assert.ok($('#note-editor').open);assert.equal($('#edit-title').value,origTitle);assert.ok($('#edit-body pre'))});
  submit();
  check('saving original preserves Chinese anchors and internal navigation',()=>{
    assert.ok(b.d.getElementById('rag-system-architecture--架构判断'));
    assert.ok($('#docbody a[href="index.html#/a/rag-core-call-chains"]'));
    assert.equal($('#docbody').querySelectorAll('table').length,3);
  });
  click('[data-act="edit-note"]');
  $('#edit-title').value='可修改的笔记 Alpha';$('#edit-summary').value='修改摘要';$('#edit-tags').value='编辑测试, 新标签';
  $('#edit-body').innerHTML='<h2>新章节</h2><p>检索词UniqueEditorToken</p><table><tr><td>数据</td></tr></table><pre><code>const n = 1;</code></pre><a href="index.html#/a/rag-core-call-chains">同系列</a>';
  submit();
  check('save updates article, metadata and persisted content',()=>{assert.equal($('#note-editor').open,false);assert.equal($('.doc h1').textContent,'可修改的笔记 Alpha');assert.ok($('#docbody').textContent.includes('UniqueEditorToken'));assert.ok(JSON.parse(w.localStorage.getItem('kb.notes')).edits['rag-system-architecture']);assert.ok($('[data-act="reset-note"]'))});
  check('outline, table wrapping and cross-note links updated',()=>{assert.equal($('#dout a').textContent,'新章节');assert.equal($('#dout a').dataset.anchor,$('#docbody h2').id);assert.ok($('#docbody .tw table'));assert.equal($('#docbody a').getAttribute('href'),'index.html#/a/rag-core-call-chains')});
  $('#q').value='UniqueEditorToken';$('#q').dispatchEvent(new w.Event('input'));
  check('search uses edited content immediately',()=>assert.ok($('#panel .st').textContent.includes('Alpha')));
  const saved=b.snapshot();b.dom.window.close();b=boot(saved);({$,w,click,submit}=b);
  check('edits survive a new page instance',()=>{assert.equal($('.doc h1').textContent,'可修改的笔记 Alpha');assert.equal($('#dout a').textContent,'新章节')});
  click('[data-act="edit-note"]');$('#edit-title').value='unsaved';w.confirm=()=>false;click('#edit-cancel');
  check('cancel respects keep-editing choice',()=>assert.ok($('#note-editor').open));
  const unload=new w.Event('beforeunload',{cancelable:true});w.dispatchEvent(unload);
  check('dirty editor protects refresh/close',()=>assert.ok(unload.defaultPrevented));
  w.confirm=()=>true;click('#edit-cancel');
  check('discard leaves saved article untouched',()=>assert.equal($('.doc h1').textContent,'可修改的笔记 Alpha'));
  click('[data-act="edit-note"]');$('#edit-title').value='Storage failure';
  const set=w.Storage.prototype.setItem;w.Storage.prototype.setItem=function(){throw new Error('QuotaExceededError')};submit();
  check('quota failure keeps editor and previous saved data',()=>{assert.ok($('#note-editor').open);assert.ok($('#edit-error').textContent.includes('尚未保存'));assert.equal(JSON.parse(w.localStorage.getItem('kb.notes')).edits['rag-system-architecture'].title,'可修改的笔记 Alpha')});
  w.Storage.prototype.setItem=set;click('#edit-cancel');
  click('[data-act="edit-note"]');$('#edit-title').value='Stale overwrite';
  const newer=JSON.parse(w.localStorage.getItem('kb.notes'));newer.edits['rag-system-architecture'].title='Other tab';w.localStorage.setItem('kb.notes',JSON.stringify(newer));submit();
  check('concurrent change is not overwritten',()=>{assert.ok($('#edit-error').textContent.includes('其他页面'));assert.equal(JSON.parse(w.localStorage.getItem('kb.notes')).edits['rag-system-architecture'].title,'Other tab')});
  click('#edit-cancel');check('closing editor refreshes concurrent content',()=>assert.equal($('.doc h1').textContent,'Other tab'));
  await b.importBackup({type:'kb-extra',version:2,arts:[],edits:Object.values(JSON.parse(saved['kb.notes']).edits),favs:['rag-system-architecture'],hist:['rag-core-call-chains']});
  check('v2 backup restores edits to existing IDs',()=>assert.equal($('.doc h1').textContent,'可修改的笔记 Alpha'));
  check('backup restores stars and history',()=>{assert.ok(JSON.parse(w.localStorage.getItem('kb.favs')).includes('rag-system-architecture'));assert.ok(JSON.parse(w.localStorage.getItem('kb.hist')).includes('rag-core-call-chains'))});
  click('[data-act="export"]');const blob=b.downloads[0];const payload=await new Promise(resolve=>{const r=new w.FileReader();r.onload=()=>resolve(JSON.parse(r.result));r.readAsText(blob)});
  check('export includes changed built-in notes and version',()=>{assert.equal(payload.version,2);assert.equal(payload.edits[0].title,'可修改的笔记 Alpha');assert.deepEqual(payload.arts,[])});
  const second=boot();await second.importBackup(payload);
  check('export/import round-trip into clean browser',()=>assert.equal(second.$('.doc h1').textContent,'可修改的笔记 Alpha'));second.dom.window.close();
  const before=w.localStorage.getItem('kb.notes');
  await b.importBackup({version:2,arts:[{id:'valid-new',title:'valid',html:'<p>new</p>',tags:[]}],edits:[{id:'missing',title:'bad',html:'x',tags:[]}]});
  check('invalid import is atomic and leaves content unchanged',()=>assert.equal(w.localStorage.getItem('kb.notes'),before));
  w.confirm=()=>false;await b.importBackup(payload);
  check('declining restore leaves local data unchanged',()=>assert.equal(w.localStorage.getItem('kb.notes'),before));w.confirm=()=>true;
  await b.importBackup({version:1,arts:[{id:'legacy-note',title:'旧备份',cat:'new-cat',html:'<h2>旧章节</h2><p>hello</p>',tags:[]}]});
  check('legacy imports create accessible category',()=>assert.ok(b.d.querySelector('[data-cat="new-cat"]')));
  w.location.hash='#/a/legacy-note';await tick();click('[data-act="edit-note"]');$('#edit-title').value='旧笔记已编辑';
  $('#edit-body').innerHTML='<h1><img src=x onerror="window.pwn=1"><a href="javascript:alert(1)" onclick="window.pwn=1">unsafe</a></h1><svg onload="window.pwn=1"></svg><iframe srcdoc="bad"></iframe><h2 id="q">safe</h2><p id="main">text</p><h2 id="legacy-note--same">A</h2><h2 id="legacy-note--same">B</h2>';
  submit();
  check('editable imported notes sanitize active HTML including nested headings',()=>{assert.equal($('.doc h1').textContent,'旧笔记已编辑');assert.equal($('#docbody').querySelectorAll('img,svg,iframe,[onclick],[onerror],h1').length,0);assert.equal($('#docbody a').getAttribute('href'),null);assert.equal($('#docbody [id="main"]'),null);const ids=Array.from($('#docbody').querySelectorAll('[id]')).map(e=>e.id);assert.equal(new Set(ids).size,ids.length)});
  const legacySaved=b.snapshot();const third=boot(legacySaved);third.w.location.hash='#/a/legacy-note';await tick();
  check('edited imported note persists on reload',()=>assert.equal(third.$('.doc h1').textContent,'旧笔记已编辑'));third.dom.window.close();
  w.location.hash='#/a/rag-system-architecture';await tick();click('[data-act="reset-note"]');
  check('restore removes override and returns original content',()=>{assert.equal($('.doc h1').textContent,origTitle);assert.equal($('#docbody').innerHTML,origBody);assert.equal(JSON.parse(w.localStorage.getItem('kb.notes')).edits['rag-system-architecture'],undefined)});
  check('no runtime errors',()=>assert.deepEqual(b.errors,[]));b.dom.window.close();
  const legacy=boot({'kb.extra':JSON.stringify([{id:'preexisting',title:'迁移',html:'<p>历史笔记</p>',cat:'migrated',tags:[]}])});
  legacy.w.location.hash='#/a/preexisting';await tick();legacy.click('[data-act="edit-note"]');legacy.$('#edit-title').value='迁移后保存';legacy.submit();
  check('old localStorage notes migrate without losing content',()=>{const n=JSON.parse(legacy.w.localStorage.getItem('kb.notes'));assert.equal(n.extra[0].id,'preexisting');assert.equal(n.edits.preexisting.title,'迁移后保存')});legacy.dom.window.close();
  console.log(`\n${checks} editor checks passed`);
})().catch(e=>{console.error(e);process.exit(1)});
