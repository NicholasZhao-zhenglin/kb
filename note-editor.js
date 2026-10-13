/* Embedded in build.py's application closure. No network or external runtime. */
function cleanBody(html, id){
  var doc=new DOMParser().parseFromString(html,'text/html');
  var allowed='p div section article span h2 h3 h4 h5 h6 br hr strong b em i u s del blockquote pre code ul ol li table thead tbody tfoot tr th td caption a dl dt dd details summary sup sub kbd samp mark'.split(' ');
  var drop='script style iframe object embed svg math form input button textarea select link meta base img audio video source'.split(' ');
  Array.from(doc.body.querySelectorAll('*')).forEach(function(el){
    var tag=el.tagName.toLowerCase();
    if(drop.indexOf(tag)>=0){el.remove();return}
    if(tag==='h1'){var h=doc.createElement('h2');while(el.firstChild)h.appendChild(el.firstChild);el.replaceWith(h);el=h;tag='h2'}
    if(allowed.indexOf(tag)<0){el.replaceWith.apply(el,Array.from(el.childNodes));return}
    Array.from(el.attributes).forEach(function(at){
      var n=at.name, v=at.value;
      var keep=(n==='id'&&v.indexOf(id+'--')===0&&/^[\w\u0080-\uffff-]+$/.test(v))
        ||(n==='class'&&/^[\w\s-]*$/.test(v))
        ||(tag==='a'&&n==='href'&&/^(https?:\/\/|mailto:|#|(?:\.\/)?index\.html#\/)/i.test(v)&&!/[\u0000-\u0020]/.test(v))
        ||((tag==='td'||tag==='th')&&(n==='colspan'||n==='rowspan')&&/^\d{1,3}$/.test(v));
      if(!keep) el.removeAttribute(n);
    });
    if(tag==='a') el.setAttribute('rel','noopener noreferrer');
  });
  var ids=new Set();
  Array.from(doc.body.querySelectorAll('[id]')).forEach(function(el){
    if(ids.has(el.id)) el.removeAttribute('id'); else ids.add(el.id);
  });
  var outline=[], n=0;
  Array.from(doc.body.querySelectorAll('h2,h3,h4,h5')).forEach(function(h){
    if(!h.id){do{h.id=id+'--edit-'+(++n)}while(ids.has(h.id));ids.add(h.id)}
    if(h.textContent.trim()) outline.push({id:h.id,lvl:Number(h.tagName.slice(1))-1,text:h.textContent.trim()});
  });
  Array.from(doc.body.querySelectorAll('table')).forEach(function(t){
    if(!t.parentElement.classList.contains('tw')){var w=doc.createElement('div');w.className='tw';t.replaceWith(w);w.appendChild(t)}
  });
  return {html:doc.body.innerHTML,outline:outline,text:doc.body.textContent||''};
}
function normalizeNote(a){
  if(!a||typeof a.id!=='string'||!(/^[a-zA-Z0-9_-]+$/).test(a.id)||typeof a.html!=='string'
    ||typeof a.title!=='string'||!a.title.trim()||!Array.isArray(a.tags)||!a.tags.every(function(t){return typeof t==='string'})) throw new Error('笔记字段不完整');
  if(a.ext) throw new Error('外链书签不支持正文编辑');
  var body=cleanBody(a.html,a.id);
  var summary=typeof a.summary==='string'?a.summary:'';
  var text=a.title+summary+a.tags.join(' ')+body.text;
  var words=(text.match(/[\u4e00-\u9fff]/g)||[]).length+(text.match(/[A-Za-z0-9_]+/g)||[]).length;
  return {id:a.id,cat:typeof a.cat==='string'&&/^[\w-]+$/.test(a.cat)?a.cat:'imported',
    title:a.title.trim(),kicker:typeof a.kicker==='string'?a.kicker:'',summary:summary,
    tags:a.tags,html:body.html,outline:body.outline,words:words,read:Math.max(1,Math.ceil(words/500)),
    updated:typeof a.updated==='string'?a.updated:''};
}
function readNotes(){
  var stored=LS.get('notes',null), result={version:2,extra:[],edits:Object.create(null)};
  var list=stored&&stored.version===2?stored.extra:LS.get('extra',[]);
  var seen=new Set(DATA.arts.map(function(a){return a.id}));
  if(Array.isArray(list)) list.forEach(function(a){
    try{a=normalizeNote(a);if(!seen.has(a.id)){result.extra.push(a);seen.add(a.id)}}catch(e){}
  });
  if(stored&&stored.edits&&typeof stored.edits==='object') Object.keys(stored.edits).forEach(function(id){
    try{var a=normalizeNote(stored.edits[id]);if(a.id===id&&seen.has(id)) result.edits[id]=a}catch(e){}
  });
  return result;
}
function refreshNotes(){
  extra=noteState.extra;edits=noteState.edits;
  ARTS=DATA.arts.concat(extra).map(function(a){return Object.assign({},a,edits[a.id]||{})});
  CATS=DATA.cats.slice();
  ARTS.forEach(function(a){if(!CATS.some(function(c){return c.id===a.cat})) CATS.push({id:a.cat,name:a.cat,icon:'·',desc:'来自导入的知识条目。'})});
  SHOWCATS=CATS.filter(function(c){return !c.nav});
  byId=Object.create(null);ARTS.forEach(function(a){byId[a.id]=a;a._plain=plain(a.html)+(a.ext?' '+a.summary+' '+a.tags.join(' '):'')});
  EXTS=ARTS.filter(function(a){return a.ext});
  INDEX=ARTS.map(function(a){return {a:a,t:(a.title+' '+(a.kicker||'')+' '+a.tags.join(' ')).toLowerCase(),g:a.tags.join(' ').toLowerCase(),x:a._plain.toLowerCase()}});
}
function noteStats(){
  return ARTS.reduce(function(s,a){s.words+=a.words;s.tables+=(a.html.match(/<table\b/g)||[]).length;
    s.code+=(a.html.match(/<pre\b/g)||[]).length;s.anchors+=(a.html.match(/\sid="/g)||[]).length;return s},
    {words:0,tables:0,code:0,anchors:0});
}
function persistNotes(next, expected){
  if(expected!==undefined&&localStorage.getItem('kb.notes')!==expected) throw new Error('其他页面已修改笔记，请关闭编辑器后重新打开再保存');
  try{localStorage.setItem('kb.notes',JSON.stringify(next))}
  catch(e){throw new Error('本机存储不可用或空间不足，修改尚未保存。请复制正文或腾出空间后重试')}
  noteState=next;refreshNotes();
}
function importNotes(o){
  if(!Array.isArray(o)&&(!o||!Array.isArray(o.arts))) throw new Error('备份格式不正确');
  if(o.version!==undefined&&o.version!==1&&o.version!==2) throw new Error('不支持这个备份版本');
  var expected=localStorage.getItem('kb.notes'), next=readNotes();
  var list=Array.isArray(o)?o:o.arts, updates=o.edits===undefined?[]:o.edits;
  if(!Array.isArray(updates)) throw new Error('修改记录格式不正确');
  var known=new Set(DATA.arts.concat(next.extra).map(function(a){return a.id}));
  var added=0, changed=0;
  list.forEach(function(a){
    a=normalizeNote(Object.assign({title:a&&a.id,tags:[]},a));
    if(!known.has(a.id)){known.add(a.id);next.extra.push(a);added++}
  });
  updates.forEach(function(a){
    a=normalizeNote(a);
    if(!known.has(a.id)||DATA.arts.some(function(b){return b.id===a.id&&b.ext})) throw new Error('修改记录找不到原笔记：'+a.id);
    next.edits[a.id]=a;changed++;
  });
  if(changed&&!window.confirm('将恢复 '+changed+' 条笔记修改，并覆盖本机同名笔记的当前内容，是否继续？')) return;
  persistNotes(next,expected);
  ['favs','hist'].forEach(function(key){
    if(Array.isArray(o[key])){S[key]=Array.from(new Set(o[key].filter(function(id){return typeof id==='string'&&known.has(id)}).concat(S[key])));
      if(key==='hist') S[key]=S[key].slice(0,24);LS.set(key,S[key])}
  });
  route();toast('已导入 '+added+' 条笔记，恢复 '+changed+' 条修改');
}

var editor=document.createElement('dialog');editor.id='note-editor';
editor.setAttribute('aria-labelledby','edit-heading');editor.setAttribute('aria-describedby','edit-help');
editor.innerHTML='<form id="edit-form"><h2 id="edit-heading">编辑笔记</h2>'
  +'<p id="edit-help">保存到当前浏览器，刷新后仍可查看。不会同步到 GitHub 或其他设备；请用「导出备份」保留副本。</p>'
  +'<label for="edit-title">标题</label><input id="edit-title" required maxlength="300">'
  +'<label for="edit-summary">摘要</label><textarea id="edit-summary" rows="2"></textarea>'
  +'<label for="edit-tags">标签（用逗号分隔）</label><input id="edit-tags">'
  +'<div class="edit-toolbar" role="group" aria-label="正文格式">'
  +'<button type="button" data-format="bold">加粗</button><button type="button" data-format="italic">斜体</button>'
  +'<button type="button" data-block="h2">章节标题</button><button type="button" data-block="p">段落</button>'
  +'<button type="button" data-format="insertUnorderedList">列表</button><button type="button" data-block="pre">代码</button></div>'
  +'<label id="edit-body-label">正文</label><div id="edit-body" class="body" contenteditable="true" role="textbox" aria-multiline="true" aria-labelledby="edit-body-label" spellcheck="false"></div>'
  +'<p id="edit-error" role="alert"></p><footer><button type="button" id="edit-cancel">取消</button>'
  +'<button type="submit" id="edit-save">保存到本机</button></footer></form>';
document.body.appendChild(editor);
var editingId=null, editorOriginal='', editorVersion, returnFocus=null;
function editorValue(){return JSON.stringify([$('#edit-title').value,$('#edit-summary').value,$('#edit-tags').value,$('#edit-body').innerHTML])}
function editorDirty(){return editor.open&&editorValue()!==editorOriginal}
function openEditor(id){
  if(!byId[id]||byId[id].ext) return;
  // Refresh the snapshot even if a storage event was missed while this tab was inactive.
  noteState=readNotes();refreshNotes();
  var a=byId[id];if(!a) return;
  try{editorVersion=localStorage.getItem('kb.notes')}catch(e){editorVersion=undefined}
  editingId=id;returnFocus=document.activeElement;
  $('#edit-title').value=a.title;$('#edit-summary').value=a.summary;$('#edit-tags').value=a.tags.join(', ');
  $('#edit-body').innerHTML=a.html;$('#edit-error').textContent='';editorOriginal=editorValue();
  editor.showModal();$('#edit-title').focus();
}
function closeEditor(){editor.close();editingId=null;noteState=readNotes();refreshNotes();route();if(returnFocus&&returnFocus.isConnected) returnFocus.focus();else {var b=$('[data-act="edit-note"]');if(b)b.focus()}}
function cancelEditor(){if(!editorDirty()||window.confirm('尚有未保存的修改，确定放弃吗？')) closeEditor()}
$('#edit-cancel').addEventListener('click',cancelEditor);
editor.addEventListener('cancel',function(e){e.preventDefault();cancelEditor()});
$('#edit-form').addEventListener('submit',function(e){
  e.preventDefault();
  try{
    var a=normalizeNote(Object.assign({},byId[editingId],{title:$('#edit-title').value,summary:$('#edit-summary').value,
      tags:$('#edit-tags').value.split(/[,，]/).map(function(t){return t.trim()}).filter(Boolean),html:$('#edit-body').innerHTML,updated:new Date().toISOString()}));
    var next={version:2,extra:extra,edits:Object.assign(Object.create(null),edits)};next.edits[editingId]=a;
    persistNotes(next,editorVersion);closeEditor();toast('已保存到本机，可导出备份');
  }catch(err){$('#edit-error').textContent=err.message}
});
editor.addEventListener('keydown',function(e){
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();$('#edit-form').requestSubmit()}
});
$('.edit-toolbar').addEventListener('mousedown',function(e){if(e.target.closest('button')) e.preventDefault()});
$('.edit-toolbar').addEventListener('click',function(e){
  var b=e.target.closest('button');if(!b)return;
  var sel=window.getSelection();
  if(!sel.rangeCount||!$('#edit-body').contains(sel.anchorNode)) $('#edit-body').focus();
  document.execCommand(b.dataset.format||'formatBlock',false,b.dataset.block||null);
});
// Pasted and dropped content must not execute before the save-time sanitizer runs.
$('#edit-body').addEventListener('paste',function(e){
  e.preventDefault();var txt=e.clipboardData&&e.clipboardData.getData('text/plain');
  if(txt) document.execCommand('insertText',false,txt);
});
$('#edit-body').addEventListener('drop',function(e){e.preventDefault()});
function resetNote(id){
  if(!edits[id]||!window.confirm('恢复这篇笔记的原文？本机修改将移除，建议先导出备份。'))return;
  try{var expected=localStorage.getItem('kb.notes'),next=readNotes();delete next.edits[id];persistNotes(next,expected);route();toast('已恢复原文')}
  catch(e){toast(e.message)}
}
window.addEventListener('beforeunload',function(e){if(editorDirty()){e.preventDefault();e.returnValue=''}});
window.addEventListener('storage',function(e){if(e.key==='kb.notes'||e.key===null){
  if(editor.open){$('#edit-error').textContent='其他页面已修改笔记。请保留当前草稿，关闭编辑器后重新打开。';return}
  noteState=readNotes();refreshNotes();route();
}});
