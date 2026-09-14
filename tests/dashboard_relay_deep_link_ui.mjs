import assert from 'node:assert/strict';
import fs from 'node:fs';

const html=fs.readFileSync(process.argv[2],'utf8');
const resolverStart=html.indexOf('function relayDeepLinkId('),resolverEnd=html.indexOf('async function fetchRelay(',resolverStart);
const flowEnd=html.indexOf('}async function loadMoreRelaySessions(',resolverEnd)+1;
const selectionStart=html.indexOf('function selectRelaySession('),selectionEnd=html.indexOf('function applyRelayWorkRefLookup(',selectionStart);
assert.ok(resolverStart>=0&&resolverEnd>resolverStart&&flowEnd>resolverEnd&&selectionStart>=0&&selectionEnd>selectionStart);
const resolverSource=html.slice(resolverStart,resolverEnd),flowSource=html.slice(resolverStart,flowEnd),selectionSource=html.slice(selectionStart,selectionEnd);
assert.doesNotMatch(resolverSource+selectionSource,/POST|wake|relay\/messages|fetch\(/);

function resolverHarness(relayJson){
  const status={_text:''};
  Object.defineProperties(status,{
    textContent:{get(){return this._text},set(value){this._text=String(value)}},
    innerHTML:{set(){throw new Error('deep-link status must use textContent')}},
  });
  const state={generation:7,showAllSessions:false,endpointSessions:{},sessions:[],selected:'existing',pair:null,message:null};
  const window={location:{hash:''}};
  let scope='scope-a';
  const api=new Function('document','window','state','relayJson','scopeValue',`
    let _relay=state;
    function relayScopeSnapshot(){return scopeValue()}
    function rf(value,names,fallback='unknown'){for(const name of names)if(value&&value[name]!=null&&value[name]!=='')return String(value[name]);return fallback}
    function rsessionName(row){return row.alias||row.session_ref||row.id}
    function renderRelay(){}function relayFocus(){}
    ${selectionSource}
    ${resolverSource}
    return {relayDeepLinkId,resolveRelayDeepLink};
  `)({getElementById:id=>id==='relay-window-note'?status:null},window,state,relayJson,()=>scope);
  return{...api,status,state,window,setScope:value=>{scope=value}};
}

const endpoint='relay-session-'+'a'.repeat(32),other='relay-session-'+'b'.repeat(32),raw='#relay?session='+endpoint;
let requests=[];
let harness=resolverHarness(async url=>{requests.push(String(url));return{sessions:[]}});
assert.equal(harness.relayDeepLinkId(raw),endpoint);
assert.equal(harness.relayDeepLinkId('#relay?session=%72elay-session-'+'a'.repeat(32)),endpoint);
for(const bad of ['#relay?','#relay?session=','#relay?session='+endpoint+'&session='+endpoint,'#relay?session='+endpoint+'&extra=1','#relay?extra='+endpoint,'#relay?session=%E0%A4%A','#relay?session=@alias','#relay?session='+endpoint.slice(0,-1),'#relay?session='+endpoint.toUpperCase()])assert.equal(harness.relayDeepLinkId(bad),null,bad);

harness.window.location.hash='#relay?session=@alias';
await harness.resolveRelayDeepLink(harness.window.location.hash,7,'scope-a');
assert.equal(harness.state.selected,'existing');assert.equal(requests.length,0);assert.match(harness.status.textContent,/Invalid/);

harness.window.location.hash=raw;
await harness.resolveRelayDeepLink(raw,7,'scope-a');
assert.equal(requests[0],'/dashboard/api/relay/sessions?endpoint_id='+endpoint+'&limit=1');
assert.equal(harness.state.selected,'existing');assert.match(harness.status.textContent,/not found/);

requests=[];const hostile={id:endpoint,session_ref:'session',alias:'<img src=x onerror=alert(1)>'};
harness=resolverHarness(async url=>{requests.push(String(url));return{sessions:[hostile]}});harness.window.location.hash=raw;
await harness.resolveRelayDeepLink(raw,7,'scope-a');
assert.equal(harness.state.selected,endpoint);assert.equal(harness.state.sessions[0],hostile);assert.equal(harness.state.showAllSessions,true);
assert.equal(harness.status.textContent,'Opened <img src=x onerror=alert(1)>.');

let answer;harness=resolverHarness(()=>new Promise(resolve=>{answer=resolve}));harness.window.location.hash=raw;
const staleHash=harness.resolveRelayDeepLink(raw,7,'scope-a');await Promise.resolve();harness.window.location.hash='#operational';answer({sessions:[hostile]});await staleHash;
assert.equal(harness.state.selected,'existing');assert.equal(harness.state.sessions.length,0);

let answerGeneration;harness=resolverHarness(()=>new Promise(resolve=>{answerGeneration=resolve}));harness.window.location.hash=raw;
const staleGeneration=harness.resolveRelayDeepLink(raw,7,'scope-a');await Promise.resolve();harness.state.generation=8;answerGeneration({sessions:[hostile]});await staleGeneration;
assert.equal(harness.state.selected,'existing');

let answerScope;harness=resolverHarness(()=>new Promise(resolve=>{answerScope=resolve}));harness.window.location.hash=raw;
const staleScope=harness.resolveRelayDeepLink(raw,7,'scope-a');await Promise.resolve();harness.setScope('scope-b');answerScope({sessions:[hostile]});await staleScope;
assert.equal(harness.state.selected,'existing');

function integratedFetchHarness(hash){
  const status={textContent:''},elements={
    'relay-window-note':status,'relay-filter-bar':{hidden:true},'relay-workspace':{hidden:true},
    'relay-container-search':{value:''},'relay-sessions':{textContent:''},'relay-map':{textContent:''},
  };
  const window={location:{hash}},pending=[],state={generation:0,facetGeneration:0,selected:'existing',pair:null,message:null,showAllSessions:true,endpointSessions:{existing:{id:'existing'}},sessions:[{id:'existing'}],sessionOffset:1,sessionTotal:1,messages:[],mapFitPending:false};
  const api=new Function('document','window','state','pending',`
    let _relay=state;
    function scoped(id){return(document.getElementById(id)||{}).value||''}
    function relayScopeSnapshot(){return 'scope-a'}
    function relaySessionParams(){return new URLSearchParams({limit:'100',offset:'0',lifecycle:'recent'})}
    function relayMessageParams(){return new URLSearchParams({limit:'100'})}
    function relayJson(url){return new Promise(resolve=>pending.push({url:String(url),resolve}))}
    function resetRelayData(){throw new Error('deep-link refresh must not reset selection')}
    function relayFacets(){}function rememberRelayEndpoints(){}function fmtNum(value){return String(value)}function renderRelay(){}
    function rf(value,names,fallback='unknown'){for(const name of names)if(value&&value[name]!=null&&value[name]!=='')return String(value[name]);return fallback}
    function rsession(id){return _relay.sessions.find(row=>rf(row,['endpoint_id','id','session_id'])===id)||_relay.endpointSessions[id]}
    function rsessionName(row){return row.alias||row.session_ref||row.id}
    function relayFocus(){}
    ${selectionSource}
    ${flowSource}
    return{fetchRelay};
  `)({getElementById:id=>elements[id]||{value:''}},window,state,pending);
  return{...api,status,state,window,pending};
}

const invalid='#relay?session=@alias',flow=integratedFetchHarness(raw),oldFetch=flow.fetchRelay(true,null,raw);
await Promise.resolve();flow.window.location.hash=invalid;const newFetch=flow.fetchRelay(true,null,invalid);await Promise.resolve();
assert.equal(flow.state.generation,2);for(const [index,body] of [[3,{containers:[]}],[4,{sessions:[{id:'current-base'}],total:2}],[5,{messages:[],has_more:false}]])flow.pending[index].resolve(body);
await newFetch;assert.match(flow.status.textContent,/Invalid/);assert.equal(flow.state.selected,'existing');
for(const [index,body] of [[0,{containers:[]}],[1,{sessions:[{id:'stale-base'}],total:1}],[2,{messages:[],has_more:false}]])flow.pending[index].resolve(body);
await oldFetch;assert.match(flow.status.textContent,/Invalid/);assert.equal(flow.state.selected,'existing');assert.deepEqual(flow.state.sessions.map(row=>row.id),['current-base','existing']);assert.equal(flow.state.sessionOffset,1);

const viewStart=html.indexOf('const _VIEWS ='),viewEnd=html.indexOf('// ──────────────────────────────────────────────────',viewStart);
assert.ok(viewStart>=0&&viewEnd>viewStart);const viewSource=html.slice(viewStart,viewEnd);
function viewHarness(hash){
  const classList=()=>{const values=new Set();return{toggle:(name,on)=>on?values.add(name):values.delete(name),contains:name=>values.has(name)}};
  const elements=Object.fromEntries(['view-operational','view-relay','view-how-it-helps','tab-operational','tab-relay','tab-evaluation'].map(id=>[id,{classList:classList(),setAttribute(){}}]));
  const window={location:{hash},scrollTo(){},addEventListener(){}};const fetches=[],resolves=[],replacements=[];
  const history={replaceState(_a,_b,next){replacements.push(next);window.location.hash=next}};
  const api=new Function('document','window','history','fetches','resolves',`
    const DASHBOARD_ROI_ENABLED=true;let _relay={generation:3};
    function fetchRelay(...args){fetches.push(args)}function fetchEffectivenessReports(){}
    function resolveRelayDeepLink(...args){resolves.push(args)}function relayScopeSnapshot(){return 'scope-a'}
    ${viewSource}
    return{init:_initViewFromHash,switchView,current:()=>_currentDashboardView};
  `)({getElementById:id=>elements[id]||null},window,history,fetches,resolves);
  return{...api,window,fetches,resolves,replacements};
}

let view=viewHarness(raw);view.init();assert.equal(view.current(),'relay');assert.deepEqual(view.fetches[0],[true,null,raw]);assert.deepEqual(view.replacements,[]);
let reload=viewHarness(raw);reload.init();assert.deepEqual(reload.fetches[0],[true,null,raw]);
view.window.location.hash='#relay?session='+other;view.init();assert.equal(view.fetches.length,2);assert.deepEqual(view.fetches.at(-1),[true,null,view.window.location.hash]);assert.equal(view.resolves.length,0);
view.window.location.hash='#operational';view.init();assert.equal(view.current(),'operational');
view.window.location.hash=raw;view.init();assert.equal(view.current(),'relay');assert.deepEqual(view.fetches.at(-1),[true,null,raw]);
const plain=viewHarness('#relay');plain.init();assert.deepEqual(plain.fetches[0],[true,null,null]);assert.deepEqual(plain.replacements,[]);
const unknown=viewHarness('#unknown');unknown.init();assert.equal(unknown.current(),'operational');assert.deepEqual(unknown.replacements,['#operational']);
const explicit=viewHarness(raw);explicit.init();explicit.switchView('relay');assert.equal(explicit.window.location.hash,'#relay');assert.deepEqual(explicit.fetches.at(-1),[true,null,null]);

console.log('relay dashboard deep links: all cases passed');