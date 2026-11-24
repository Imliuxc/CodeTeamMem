'use strict';
const $ = id => document.getElementById(id);
const labels = {READY:'准备就绪', RUNNING:'正在执行', GATE:'等待确认', WAITING_STEP:'等待下一轮', FAILED:'阶段失败', CIRCUIT_OPEN:'战略熔断', LOCKED:'已锁定', COMPLETE:'全部完成', INTERRUPTED:'执行已中断'};
const eventLabels = {created:'运行已创建',stage_started:'阶段开始',turn_started:'下一轮开始',turn_completed:'协作轮次完成',waiting_step:'等待会话推进',stage_completed:'阶段完成',gate_approved:'Gate 已确认',retry_prepared:'重试已准备',stage_failed:'阶段失败',circuit_open:'触发战略熔断',interrupted:'运行中断',evidence_page:'工具证据'};
const phaseNames = ['配方与 QA 校验','代码与 Coding 校验','协作流与整段验真','拼接与指标汇总'];
let selectedRun = localStorage.getItem('ctm.run') || '', selectedCase = localStorage.getItem('ctm.case') || '';
let cursor = 0, events = [], loadedRun = '', busy = false, view = null, runsKey = '', renderKey = '';
function element(tag, cls, text) { const e = document.createElement(tag); if(cls) e.className=cls; if(text !== undefined) e.textContent=text; return e; }
function sourceName(source) { return source === 'mock' ? 'Mock 演示' : '已有产物校验 / 回放'; }
async function get(url) { const r=await fetch(url,{cache:'no-store'}); if(!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }
function setConnection(online) { $('connection').className=`connection ${online?'online':'offline'}`; $('connection').textContent=online?'服务已连接 · 每秒刷新':'连接中断 · 正在重连'; }
function selectRun(id) { selectedRun=id; selectedCase=''; cursor=0; events=[]; loadedRun=''; localStorage.setItem('ctm.run',id); localStorage.removeItem('ctm.case'); }
function renderRuns(runs) {
  const key=JSON.stringify([runs,selectedRun]); if(key===runsKey) return; runsKey=key;
  $('run-count').textContent=runs.length; $('run-list').replaceChildren();
  if(!runs.length) { $('run-list').append(element('p','muted','尚无运行记录')); return; }
  for(const r of runs) {
    const a=element('a',`run-item ${r.id===selectedRun?'selected':''}`); a.href=`#${r.id}`;
    a.append(element('strong','',r.id),element('small','',`${sourceName(r.source)} · ${new Date(r.created).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}`));
    a.addEventListener('click',e=>{e.preventDefault(); if(r.id!==selectedRun) {selectRun(r.id); poll();}}); $('run-list').append(a);
  }
}
function notice(c) {
  const messages={READY:'在会话中说“下一步”，推进一个阶段。',RUNNING:'控制命令正在执行，状态与事件持续更新。',GATE:'本阶段已完成。请在会话中确认 Gate，然后再推进下一步。',WAITING_STEP:'本轮已完成。下一次会话指令只推进一轮。',LOCKED:c.gate?'整段验真已通过。确认 Gate 后可进入汇总阶段。':'整段已锁定，可在会话中推进最终汇总。',COMPLETE:'本次运行已完成。结果来源见下方说明。',FAILED:'请检查失败原因。首次失败可在会话中准备重试，再推进当前阶段。',CIRCUIT_OPEN:'同一阶段已失败两次。停止补丁，先讨论简化方案。',INTERRUPTED:'服务在执行中退出。显式准备重试后，从当前阶段开头重新执行。'};
  const error=['FAILED','CIRCUIT_OPEN','INTERRUPTED'].includes(c.status);
  $('notice').className=`notice ${error?'error':''}`; $('notice-title').textContent=labels[c.status]||c.status;
  $('notice-text').textContent=c.error ? `${messages[c.status]}\n${c.error}` : messages[c.status];
  $('failure-count').textContent=Object.entries(c.failures).map(([s,n])=>`S${s}: ${n}`).join(' · ')||'0';
}
function render(c) {
  const key=JSON.stringify([selectedRun,selectedCase,c,events.length]); if(key===renderKey) return; renderKey=key;
  $('overall').textContent=`${labels[c.status]||c.status} / ${c.status}`;
  $('overall').className=`status-pill ${['FAILED','CIRCUIT_OPEN','INTERRUPTED'].includes(c.status)?'error':''}`;
  $('completed').textContent=`${c.completed_stage} / 4 阶段完成`;
  const active=c.active_stage||(c.gate?c.completed_stage:Math.min(c.completed_stage+1,4)); $('stages').replaceChildren();
  phaseNames.forEach((name,i)=>{
    const n=i+1, atGate=c.gate&&n===c.completed_stage, state=atGate?'active':n<=c.completed_stage?'done':n===active?(['FAILED','CIRCUIT_OPEN','INTERRUPTED'].includes(c.status)?'error':'active'):'pending';
    const card=element('div','stage'); card.dataset.state=state;
    const number=element('div','stage-number',`STAGE 0${n}`); number.append(element('span','',state==='done'?'✓':state==='active'?'●':state==='error'?'!':'○'));
    card.append(number,element('h3','',name),element('p','',state==='done'?'已完成':state==='pending'?'尚未开始':labels[c.status]||c.status)); $('stages').append(card);
  });
  const p=c.progress; $('act').textContent=p ? String(p.act).padStart(2,'0') : '—';
  $('turn').textContent=p ? (p.done?'完成':p.turns) : '—'; $('turns').textContent=p?p.total_turns:'—';
  $('exit-condition').textContent=p?(p.exit_condition||'fact_ids'):'未产生'; $('exit-met').textContent=p?(p.exit_met?'已满足':'待满足'):'未产生';
  $('round-detail').textContent=p?`上一轮：第 ${p.last_act} 幕 · 第 ${p.last_turn} 轮${p.done?' · 全部幕已结束':`；当前幕允许 ${p.min_turns}–${p.max_turns} 轮`}`:'Stage 3 开始后显示幕与轮次信息。';
  $('facts').replaceChildren(); $('fact-count').textContent=c.facts.length;
  for(const f of c.facts) $('facts').append(element('p','',`${f.role} / ${f.id} · ${f.text}`));
  $('dialogue').replaceChildren(); $('dialogue-count').textContent=`${c.dialogue.length} 轮`;
  if(!c.dialogue.length) $('dialogue').append(element('p','placeholder','尚未产生对话，未来轮次不会提前展示。'));
  for(const row of c.dialogue) {
    const m=element('div','message'), h=element('div','message-head');
    h.append(element('strong','',row.role),element('span','',`幕 ${row.act} / 轮 ${row.sequence+1}`)); m.append(h,element('p','',row.text)); $('dialogue').append(m);
  }
  $('results').replaceChildren(); const results=Object.entries(c.results);
  if(!results.length) $('results').append(element('p','placeholder','未产生。完成阶段后显示来源与校验结果。'));
  for(const [stage,r] of results) {
    const div=element('div','result-item'); div.append(element('strong','',`STAGE ${stage} · ${sourceName(r.source)}`),element('p','',r.summary));
    if(r.metrics||r.verification) {const d=element('details');d.append(element('summary','','查看已有记录明细'),element('pre','',JSON.stringify(r.metrics||r.verification,null,2)));div.append(d);}
    $('results').append(div);
  }
  notice(c); renderTimeline();
}
function renderTimeline() {
  const filtered=events.filter(e=>e.case_id===selectedCase); $('event-count').textContent=`${filtered.length} 条`; $('timeline').replaceChildren();
  for(const e of [...filtered].reverse()) {
    const div=element('div',`event ${['stage_failed','circuit_open','interrupted'].includes(e.kind)?'error':''}`), top=element('div','event-top');
    top.append(element('span','',`#${String(e.seq).padStart(4,'0')}`),element('time','',new Date(e.at).toLocaleTimeString('zh-CN',{hour12:false})));
    div.append(top,element('h4','',eventLabels[e.kind]||e.kind));
    const p=e.payload, text=p.stage?`STAGE ${p.stage}${p.act?` · 幕 ${p.act} / 轮 ${p.turn_in_act}`:''}${p.error?` · ${p.error}`:''}`:p.source?sourceName(p.source):'';
    if(text) div.append(element('p','',text));
    if(p.text) { const d=element('details');d.append(element('summary','',`${p.kind} · 第 ${p.page} 页`),element('pre','',p.text));div.append(d); }
    $('timeline').append(div);
  }
}
$('case-select').addEventListener('change',()=>{ selectedCase=$('case-select').value;localStorage.setItem('ctm.case',selectedCase);render(view.cases.find(c=>c.id===selectedCase)); });
async function poll() {
  if(busy) return; busy=true;
  try {
    const runs=await get('/api/runs');
    if(!runs.some(r=>r.id===selectedRun)) { if(runs.length) selectRun(runs[0].id); else selectedRun=''; }
    renderRuns(runs); $('empty').hidden=!!selectedRun; $('workspace').hidden=!selectedRun;
    if(selectedRun) {
      const requested=selectedRun, fresh=await get(`/api/runs/${requested}`);
      if(selectedRun!==requested) return;
      if(loadedRun!==selectedRun) {events=[];cursor=0;loadedRun=selectedRun;}
      // Drain all pages. Do not advance the cursor from a newer snapshot.
      for(;;) {const batch=await get(`/api/runs/${requested}/events?after=${cursor}`);if(selectedRun!==requested)return;events.push(...batch);if(batch.length)cursor=batch[batch.length-1].seq;if(batch.length<100)break;}
      view=fresh;
      if(!view.cases.some(c=>c.id===selectedCase)) {selectedCase=view.cases[0].id;localStorage.setItem('ctm.case',selectedCase);}
      const select=$('case-select'); const ids=view.cases.map(c=>c.id);
      if([...select.options].map(o=>o.value).join('\0')!==ids.join('\0')) {select.replaceChildren();for(const id of ids) {const o=element('option','',id);o.value=id;select.append(o);}}
      select.value=selectedCase; $('run-id').textContent=selectedRun;
      $('source').textContent=sourceName(view.source);$('source').className=`source-pill ${view.source}`;
      $('updated').textContent=`同步于 ${new Date().toLocaleTimeString('zh-CN',{hour12:false})}`;
      render(view.cases.find(c=>c.id===selectedCase));
    }
    setConnection(true);
  } catch(e) {setConnection(false);} finally {busy=false;}
}
poll();setInterval(poll,1000);
