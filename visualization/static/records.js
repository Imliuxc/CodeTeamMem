'use strict';
const $=id=>document.getElementById(id);
const query=new URLSearchParams(location.search);
let selected=query.get('recording')||localStorage.getItem('ctm.recording')||'', callIndex=query.has('call')?Number(query.get('call')):null;
let busy=false,listKey='',summaryKey='',tableKey='',detailKey='',focusCall=query.has('call');
const outcomes={pass:'正确',model_wrong:'答案不符',parse_error:'解析失败',env_error:'环境错误'};
function el(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
function value(x){return x===undefined||x===null?'未记录':typeof x==='object'?JSON.stringify(x,null,2):String(x);}
async function get(path){const r=await fetch(path,{cache:'no-store'});if(!r.ok){const e=await r.json();throw new Error(e.error||`HTTP ${r.status}`);}return r.json();}
function connection(ok){$('record-connection').className=`connection ${ok?'online':'offline'}`;$('record-connection').textContent=ok?'已连接 · 只读文件':'读取异常 · 正在重试';}
function metadata(target,items){target.replaceChildren();for(const [label,text]of items){const d=el('div');d.append(el('span','field-label',label),el('strong','',value(text)));target.append(d);}}
function persist(){localStorage.setItem('ctm.recording',selected);const q=new URLSearchParams({recording:selected});if(callIndex!==null)q.set('call',String(callIndex));history.replaceState(null,'',`/records?${q}`);}
function renderList(runs){const key=JSON.stringify([runs,selected]);if(key===listKey)return;listKey=key;$('record-list').replaceChildren();for(const r of runs){const a=el('a',`run-item ${r.id===selected?'selected':''}`);a.href=`/records?recording=${r.id}`;a.append(el('strong','',r.case_id),el('small','',`第 ${r.attempt} 次运行 · ${r.error?'文件异常':`${r.call_count} 条记录`}`));a.addEventListener('click',e=>{e.preventDefault();selected=r.id;callIndex=null;summaryKey=tableKey=detailKey='';$('record-workspace').hidden=true;persist();poll();});$('record-list').append(a);}}
function renderSummary(s){const key=JSON.stringify(s);if(key===summaryKey)return;summaryKey=key;
$('record-title').textContent=`${s.case_id} · 第 ${s.attempt} 次 QA 运行`;
$('record-status').textContent=s.complete===true?(s.passed===true?'本次初筛通过':'本次初筛未通过'):'记录未完成';
$('record-status').className=`status-pill ${s.complete===true&&s.passed===false?'error':''}`;
metadata($('record-meta'),[['模型',s.model],['记录请求数',s.call_count],['记录正确 / 答案不符',`${s.outcomes.pass||0} / ${s.outcomes.model_wrong||0}`],['记录 Token 合计',s.usage_tokens],['当前 Case 状态',s.current_case_state.status]]);
$('record-path').textContent=`源文件：datasets/${s.path}`;
$('record-errors').hidden=!s.warnings.length;$('record-errors').textContent=s.warnings.join('\n');
$('record-config').textContent=JSON.stringify({run_info:s.run_info,request_config:s.request_config,seed_hash:s.seed_hash,policy_hash:s.policy_hash,schema_hash:s.schema_hash,scope:s.scope,current_case_state:s.current_case_state},null,2);
$('score-grid').replaceChildren();
const table=el('table');const head=el('tr');for(const h of ['记录条件','A 情境','B 情境','C 情境'])head.append(el('th','',h));table.append(head);
for(const a of ['B0','B1','B2']){const tr=el('tr');tr.append(el('th','',a));for(const c of ['A','B','C']){const cell=s.cells.find(x=>x.anchor===a&&x.context===c);const td=el('td');td.append(el('strong','',`${cell.passed} / ${cell.recorded}`),el('small','',`保存分数：${typeof cell.saved_score==='number'?(cell.saved_score*100).toFixed(1)+'%':'未记录'}`));if(cell.declared_denominator!==undefined&&cell.recorded!==cell.declared_denominator)td.append(el('small','record-warning',`计划分母 ${cell.declared_denominator}，记录未齐`));tr.append(td);}table.append(tr);}$('score-grid').append(table);
}
function selectCall(index){callIndex=index;detailKey='';focusCall=true;persist();poll();}
function renderCalls(calls){if(!calls.some(c=>c.index===callIndex))callIndex=calls.length?calls[0].index:null;const key=JSON.stringify([calls,callIndex]);if(key===tableKey)return;tableKey=key;
$('filtered-count').textContent=`筛选后 ${calls.length} 条`;$('call-picker').replaceChildren();$('call-table').replaceChildren();
for(const c of calls){const o=el('option','',`#${c.index+1} · ${c.anchor}/${c.context} · 第 ${c.repeat} 次 · ${outcomes[c.outcome]||value(c.outcome)}`);o.value=c.index;$('call-picker').append(o);
const a=el('a',`call-row ${c.index===callIndex?'selected':''} ${c.outcome==='pass'?'':'incorrect'}`);a.href=`/records?recording=${selected}&call=${c.index}`;a.append(el('span','call-index',`#${String(c.index+1).padStart(2,'0')}`),el('strong','',`${c.anchor} / ${c.context}`),el('span','',`第 ${c.repeat} 次`),el('span','outcome',outcomes[c.outcome]||value(c.outcome)),el('span','',`${value(c.usage_tokens)} Token`));a.addEventListener('click',e=>{e.preventDefault();selectCall(c.index);});$('call-table').append(a);}
if(callIndex!==null)$('call-picker').value=callIndex;else $('call-table').append(el('p','placeholder','没有符合筛选条件的调用。'));persist();}
function renderDetail(c){const key=JSON.stringify(c);if(key===detailKey)return;detailKey=key;$('call-detail').hidden=false;
$('call-title').textContent=`#${c.index+1} · ${c.anchor} / ${c.context} · 第 ${c.repeat} 次`;
$('call-download').href=`/api/recordings/${selected}/calls/${c.index}`;
metadata($('call-meta'),[['记录判分',outcomes[c.outcome]||value(c.outcome)],['输入 Token',c.input_tokens],['输出 Token',c.output_tokens],['合计 Token',c.usage_tokens],['响应状态',c.response_status]]);
$('prompt-text').textContent=c.availability.prompt?c.prompt:'未记录 Prompt';$('raw-answer').textContent=c.availability.raw_answer?c.raw_answer:'未记录原始回答';$('expected-answer').textContent=c.availability.expected?value(c.expected):'未记录预期答案';
$('parsed-answer').textContent=JSON.stringify({parsed:c.availability.parsed?c.parsed:'未记录',outcome:c.outcome,error:c.error||null,response_id:c.response_id||'未记录'},null,2);
try{const parsed=JSON.parse(c.prompt);$('prompt-formatted').textContent=JSON.stringify(parsed,null,2);$('prompt-structured').hidden=false;}catch(e){$('prompt-structured').hidden=true;}
if(focusCall){focusCall=false;requestAnimationFrame(()=>{if(!$('call-detail').hidden)$('call-detail').scrollIntoView({block:'start'});});}
}
for(const id of ['anchor-filter','context-filter','outcome-filter'])$(id).addEventListener('change',()=>{callIndex=null;tableKey='';poll();});
$('call-picker').addEventListener('change',()=>selectCall(Number($('call-picker').value)));
async function poll(){if(busy)return;busy=true;try{
const runs=await get('/api/recordings');if(!runs.some(r=>r.id===selected)){selected=runs[0]?.id||'';callIndex=null;}
renderList(runs);$('record-empty').hidden=!!selected;if(!selected)$('record-workspace').hidden=true;
if(selected){const id=selected;const s=await get(`/api/recordings/${id}`);if(id!==selected)return;renderSummary(s);
const filters=new URLSearchParams();for(const [key,dom]of [['anchor','anchor-filter'],['context','context-filter'],['outcome','outcome-filter']]){if($(dom).value)filters.set(key,$(dom).value);}
const calls=await get(`/api/recordings/${id}/calls?${filters}`);if(id!==selected)return;renderCalls(calls);
if(callIndex!==null){const index=callIndex;const c=await get(`/api/recordings/${id}/calls/${index}`);if(id!==selected||index!==callIndex)return;renderDetail(c);}else $('call-detail').hidden=true;$('record-workspace').hidden=false;}
$('record-read-error').hidden=true;connection(true);
}catch(e){connection(false);$('record-workspace').hidden=true;$('record-read-error').hidden=false;$('record-read-error').textContent='记录读取失败：'+e.message;}finally{busy=false;}}
poll();setInterval(poll,1000);
