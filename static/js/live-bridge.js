(function(){
'use strict';

const TOKEN_KEY='fulfillmentpro.dashboard.token';
const token=()=>sessionStorage.getItem(TOKEN_KEY)||'';
const state={open:false,cronOpen:false,syncing:false,connections:[],jobs:[]};

function headers(){return {'Authorization':'Bearer '+token(),'Content-Type':'application/json'};}
function esc(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));}

function ensureStyle(){
 if(document.getElementById('fp-live-bridge-style'))return;
 const style=document.createElement('style');
 style.id='fp-live-bridge-style';
 style.textContent=`
 .fp-live-trigger{position:fixed;right:18px;bottom:18px;z-index:95;display:flex;align-items:center;gap:9px;min-height:44px;padding:0 15px;border:1px solid #274d74;border-radius:999px;background:#061522;color:#fff;font:700 12px/1 system-ui;box-shadow:0 16px 45px rgba(0,0,0,.42);cursor:pointer}
 .fp-live-dot{width:10px;height:10px;border-radius:50%;background:#ffb02e}.fp-live-dot.ok{background:#2ddd88;box-shadow:0 0 14px rgba(45,221,136,.8)}
 .fp-live-panel{position:fixed;right:18px;bottom:72px;z-index:95;width:min(430px,calc(100vw - 28px));max-height:min(720px,calc(100vh - 100px));overflow:auto;border:1px solid #244566;border-radius:18px;background:#061522;color:#fff;box-shadow:0 24px 70px rgba(0,0,0,.56);display:none}
 .fp-live-panel.open{display:block}.fp-live-head{display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid #15304c}.fp-live-head b{display:block;font-size:14px}.fp-live-head small{color:#86a0ba}.fp-live-head button,.fp-cron-toggle{border:1px solid #284d73;background:#0a2037;color:#b9d4ef;border-radius:9px;padding:7px 10px;cursor:pointer}
 .fp-live-list{display:grid;gap:8px;padding:14px}.fp-live-item{display:grid;grid-template-columns:12px minmax(0,1fr) auto;gap:10px;align-items:center;padding:11px;border:1px solid #173652;border-radius:12px;background:#091b2e}.fp-live-item .status{width:10px;height:10px;border-radius:50%;background:#ff6570}.fp-live-item .status.ok{background:#2ddd88;box-shadow:0 0 12px rgba(45,221,136,.65)}.fp-live-item b{font-size:12px}.fp-live-item small{display:block;color:#849db6;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.fp-live-item strong{font-size:10px;color:#ff7d86}.fp-live-item strong.ok{color:#35df8d}
 .fp-sync{padding:14px;border-top:1px solid #15304c}.fp-sync-row{display:flex;justify-content:space-between;font-size:11px}.fp-sync-track{height:9px;border-radius:999px;background:#14283e;margin:9px 0;overflow:hidden}.fp-sync-fill{height:100%;width:0;background:linear-gradient(90deg,#277cff,#39a7ff);transition:width .25s ease}.fp-sync-fill.error{background:#ff5e66}.fp-sync p{margin:0 0 10px;color:#8ba2b9;font-size:11px}.fp-sync button{width:100%;min-height:40px;border:0;border-radius:10px;background:#2583ff;color:#fff;font-weight:800;cursor:pointer}.fp-sync button:disabled{opacity:.55}
 .fp-cron{border-top:1px solid #15304c}.fp-cron-toggle{width:100%;border:0;border-radius:0;padding:13px 16px;text-align:left;display:flex;justify-content:space-between}.fp-cron-body{display:none;padding:0 14px 14px}.fp-cron-body.open{display:grid;gap:10px}.fp-cron-job{border:1px solid #173652;border-radius:12px;background:#091b2e;padding:11px}.fp-cron-job header{display:flex;justify-content:space-between;gap:10px}.fp-cron-job b{font-size:12px}.fp-cron-job small{display:block;color:#8299b1;margin-top:3px}.fp-cron-job input[type=text]{width:100%;margin-top:9px;height:36px;border:1px solid #244766;border-radius:8px;background:#04111e;color:#fff;padding:0 10px;font:11px ui-monospace,monospace}.fp-cron-save{min-height:40px;border:0;border-radius:10px;background:#18a765;color:#fff;font-weight:800;cursor:pointer}
 @media(max-width:767px){.fp-live-trigger{right:12px;bottom:82px}.fp-live-panel{right:12px;bottom:136px;max-height:calc(100vh - 160px)}}`;
 document.head.appendChild(style);
}

function shell(){
 if(document.getElementById('fpLiveTrigger'))return;
 ensureStyle();
 document.body.insertAdjacentHTML('beforeend',`
  <button id="fpLiveTrigger" class="fp-live-trigger"><span id="fpLiveDot" class="fp-live-dot"></span><span id="fpLiveText">Checking connections</span></button>
  <section id="fpLivePanel" class="fp-live-panel">
   <header class="fp-live-head"><div><b>Operations Bridge</b><small>FulfillmentPro ↔ Dropship Pro</small></div><button id="fpLiveRefresh">Refresh</button></header>
   <div id="fpLiveList" class="fp-live-list"></div>
   <div class="fp-sync"><div class="fp-sync-row"><b>Sync progress</b><span id="fpSyncPct">0%</span></div><div class="fp-sync-track"><div id="fpSyncFill" class="fp-sync-fill"></div></div><p id="fpSyncMessage">Ready to sync</p><button id="fpSyncButton">Sync Shopify + connected systems</button></div>
   <div class="fp-cron"><button id="fpCronToggle" class="fp-cron-toggle"><span>Editable cron jobs</span><span id="fpCronGlyph">+</span></button><div id="fpCronBody" class="fp-cron-body"><div id="fpCronJobs"></div><button id="fpCronSave" class="fp-cron-save">Save cron jobs</button></div></div>
  </section>`);
 bind();
 refresh();
 loadCron();
 setInterval(refresh,15000);
}

function renderConnections(){
 const list=document.getElementById('fpLiveList');
 if(!list)return;
 list.innerHTML=state.connections.map(item=>`<div class="fp-live-item"><span class="status ${item.online?'ok':''}"></span><div><b>${esc(item.label)}</b><small>${esc(item.detail||'')}</small></div><strong class="${item.online?'ok':''}">${item.online?'LIVE':'OFFLINE'}</strong></div>`).join('');
 const all=state.connections.length&&state.connections.every(x=>x.online);
 document.getElementById('fpLiveDot').classList.toggle('ok',!!all);
 document.getElementById('fpLiveText').textContent=all?'Live connections':'Connection issue';
}

async function refresh(){
 try{const response=await fetch('/api/integrations/live',{cache:'no-store'});const data=await response.json();state.connections=data.connections||[];renderConnections();}
 catch(error){state.connections=[{label:'Operations Bridge',online:false,detail:error.message||'Status failed'}];renderConnections();}
}

function setProgress(event){
 const pct=Math.max(0,Math.min(100,Number(event.progress||0)));
 document.getElementById('fpSyncPct').textContent=pct+'%';
 const fill=document.getElementById('fpSyncFill');fill.style.width=pct+'%';fill.classList.toggle('error',!!event.error);
 document.getElementById('fpSyncMessage').textContent=event.message||event.stage||'Syncing…';
}

async function sync(){
 if(state.syncing)return;
 const button=document.getElementById('fpSyncButton');state.syncing=true;button.disabled=true;button.textContent='Syncing…';setProgress({progress:2,message:'Starting sync…'});
 try{
  const response=await fetch('/api/integrations/sync-progress',{method:'POST',headers:headers()});
  if(!response.ok)throw new Error('Sync request failed: '+response.status);
  const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
  while(true){const chunk=await reader.read();if(chunk.done)break;buffer+=decoder.decode(chunk.value,{stream:true});const lines=buffer.split('\n');buffer=lines.pop()||'';for(const line of lines){if(line.trim())setProgress(JSON.parse(line));}}
  await refresh();
 }catch(error){setProgress({progress:100,message:error.message||'Sync failed',error:true});}
 finally{state.syncing=false;button.disabled=false;button.textContent='Sync Shopify + connected systems';}
}

async function loadCron(){
 if(!token())return;
 try{const response=await fetch('/api/integrations/cron',{headers:headers(),cache:'no-store'});const data=await response.json();state.jobs=data.jobs||[];renderCron();}catch{}
}

function renderCron(){
 const host=document.getElementById('fpCronJobs');if(!host)return;
 host.innerHTML=state.jobs.map((job,index)=>`<article class="fp-cron-job"><header><div><b>${esc(job.name)}</b><small>${esc(job.description||'')}</small></div><label><input type="checkbox" data-job-enabled="${index}" ${job.enabled?'checked':''}> Active</label></header><input type="text" value="${esc(job.schedule)}" data-job-schedule="${index}"><small>Last run: ${job.lastRun?new Date(job.lastRun).toLocaleString():'Never'}</small></article>`).join('');
 host.querySelectorAll('[data-job-enabled]').forEach(input=>input.onchange=e=>state.jobs[Number(e.target.dataset.jobEnabled)].enabled=e.target.checked);
 host.querySelectorAll('[data-job-schedule]').forEach(input=>input.oninput=e=>state.jobs[Number(e.target.dataset.jobSchedule)].schedule=e.target.value);
}

async function saveCron(){
 const button=document.getElementById('fpCronSave');button.disabled=true;button.textContent='Saving…';
 try{const response=await fetch('/api/integrations/cron',{method:'PATCH',headers:headers(),body:JSON.stringify({jobs:state.jobs})});if(!response.ok)throw new Error('Save failed');await loadCron();button.textContent='Saved';setTimeout(()=>button.textContent='Save cron jobs',1200);}
 catch{button.textContent='Save failed';setTimeout(()=>button.textContent='Save cron jobs',1600);}
 finally{button.disabled=false;}
}

function bind(){
 document.getElementById('fpLiveTrigger').onclick=()=>document.getElementById('fpLivePanel').classList.toggle('open');
 document.getElementById('fpLiveRefresh').onclick=refresh;
 document.getElementById('fpSyncButton').onclick=sync;
 document.getElementById('fpCronToggle').onclick=()=>{state.cronOpen=!state.cronOpen;document.getElementById('fpCronBody').classList.toggle('open',state.cronOpen);document.getElementById('fpCronGlyph').textContent=state.cronOpen?'−':'+';if(state.cronOpen)loadCron();};
 document.getElementById('fpCronSave').onclick=saveCron;
}

document.addEventListener('DOMContentLoaded',shell);if(document.readyState!=='loading')shell();
})();
