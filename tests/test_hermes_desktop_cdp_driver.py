"""Pure protocol checks for the future disposable-runner Desktop caller driver."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


DRIVER = Path(__file__).parent / "fixtures" / "hermes_desktop_cdp_driver.cjs"
ENDPOINT = "ws://127.0.0.1:43123/devtools/browser/synthetic"


def node_executable() -> str:
    node = os.environ.get("HERMES_NODE") or shutil.which("node")
    if not node or not Path(node).is_file():
        pytest.skip("Node.js is required for pure Desktop CDP driver checks")
    return node


def run_node(source: str, tmp_path: Path) -> dict:
    node = node_executable()
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    temp = tmp_path / "node-temp"
    temp.mkdir()
    child_env = {
        "SystemRoot": system_root,
        "WINDIR": system_root,
        "PATH": os.pathsep.join((str(Path(node).parent), str(Path(system_root) / "System32"))),
        "TEMP": str(temp),
        "TMP": str(temp),
    }
    result = subprocess.run(
        [node, "-e", source, str(DRIVER)],
        env=child_env,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    return json.loads(result.stdout)


def test_runner_gate_and_endpoint_reject_before_playwright_load(tmp_path):
    result = run_node(r"""
const d = require(process.argv[1]);
(async () => {
  let loads = 0;
  const load = () => { loads++; throw Error('must not load'); };
  const attempts = [];
  for (const env of [{}, {...Object.fromEntries(Object.entries({
    GITHUB_ACTIONS:'true', RUNNER_ENVIRONMENT:'github-hosted', RUNNER_OS:'Windows',
    RUNNER_ARCH:'X64', HERMES_NATIVE_CI_ISOLATION:'github-hosted-ephemeral-windows'
  })), RUNNER_ARCH:'ARM64'}]) {
    try { await d.connectDriver({endpoint: 'ws://127.0.0.1:43123/devtools/browser/x', sourceRoot: '.', env, load}); }
    catch (e) { attempts.push(e.message); }
  }
  const good = {GITHUB_ACTIONS:'true', RUNNER_ENVIRONMENT:'github-hosted', RUNNER_OS:'Windows',
    RUNNER_ARCH:'X64', HERMES_NATIVE_CI_ISOLATION:'github-hosted-ephemeral-windows'};
  for (const endpoint of ['ws://localhost:43123/devtools/browser/x', 'ws://127.0.0.1:0/devtools/browser/x',
    'ws://127.0.0.1:43123/json/list', 'ws://user@127.0.0.1:43123/devtools/browser/x',
    'wss://127.0.0.1:43123/devtools/browser/x']) {
    try { await d.connectDriver({endpoint, sourceRoot:'.', env:good, load}); }
    catch (e) { attempts.push(e.message); }
  }
  console.log(JSON.stringify({loads, attempts}));
})().catch(e => { console.error(e); process.exit(1); });
""", tmp_path)
    assert result["loads"] == 0
    assert len(result["attempts"]) == 7


def test_endpoint_accepts_only_numeric_loopback_browser_websocket(tmp_path):
    result = run_node(r"""
const d = require(process.argv[1]);
console.log(JSON.stringify({accepted: d.validateEndpoint('ws://127.0.0.1:43123/devtools/browser/synthetic')}));
""", tmp_path)
    assert result["accepted"] == ENDPOINT


def test_cwd_desktop_uses_native_settings_and_visible_new_draft(tmp_path):
    runner = tmp_path / "runner"
    workspace = runner / "home" / "scratch"
    workspace.mkdir(parents=True)
    (runner / "home" / "not-a-directory").write_text("test", encoding="utf-8")
    source = r"""
const d=require(process.argv[1]);
const path=require('node:path');
const [runner,home,workspace]=process.argv.slice(2);
const env={GITHUB_ACTIONS:'true',RUNNER_ENVIRONMENT:'github-hosted',RUNNER_OS:'Windows',
  RUNNER_ARCH:'X64',HERMES_NATIVE_CI_ISOLATION:'github-hosted-ephemeral-windows',
  RUNNER_TEMP:runner,USERPROFILE:home};
async function run(fault) {
  const events=[]; let dir=null; let url='file:///synthetic/index.html#/sessions';
  let polls=0, exited=false;
  const loaded=()=>polls>=(fault.delay??0);
  const filtersVisible=()=>{
    if(fault.ambiguous) throw Error('ambiguous Filters');
    return loaded()&&!fault.noOverview&&!fault.stuckExit&&(exited||fault.overview);
  };
  const sidebar={
    getByRole:(_,options)=>options.name==='Filters'?{
      isVisible:async()=>filtersVisible(),waitFor:async()=>{
        if(!filtersVisible())throw Error('Filters not ready');events.push('filters-ready');}
    }:{isVisible:async()=>loaded()&&!fault.allProjects&&!fault.overview&&!fault.noOverview,
      click:async()=>{events.push('overview');exited=true;}},
    getByText:()=>({isVisible:async()=>loaded()&&!!fault.allProjects,
      click:async()=>{events.push('overview');exited=true;}}),
    locator:selector=>page.locator(selector)
  };
  const composer={count:async()=>1,first(){return this},getAttribute:async key=>key==='contenteditable'?'true':null,
    innerText:async()=>''};
  const page={url:()=>url,waitForTimeout:async()=>{polls++;events.push('poll');},reload:async()=>events.push('reload'),
    evaluate:async(fn,arg)=>{
      if(!fault.bridge) global.window={hermesDesktop:{settings:{
        setDefaultProjectDir:async value=>{events.push('set');dir=value;return {dir:fault.setter?'wrong':value}},
        getDefaultProjectDir:async()=>{events.push('get');return {dir,
          resolvedCwd:fault.mismatch?'wrong':dir}}}}};
      else global.window={};
      return fn(arg);
    },
    locator:selector=>selector==='[data-tour="sessions-sidebar"]'?sidebar:
      selector.includes('composer-rich-input')?composer:{
      click:async()=>{events.push('new');url='file:///synthetic/index.html#/'},
      count:async()=>fault.absentRail?0:1,isVisible:async()=>!fault.hiddenRail,
      innerText:async()=>{events.push('cwd-rail');return fault.rail?'wrong':workspace.split(/[\\/]/).at(-1)}},
    waitForURL:async predicate=>{events.push('route');if(!predicate(new URL(url)))throw Error('bad route')}};
  const browser={contexts:()=>[{pages:()=>[page]}],close:async()=>{}};
  let error=null;
  try {const driver=await d.connectDriver({endpoint:'ws://127.0.0.1:43123/devtools/browser/x',
    sourceRoot:'.',workspace:fault.invalid?home:(fault.input??workspace),scopeMode:'cwd',env,
    timeout:fault.noOverview?0:30000,
    load:()=>({connectOverCDP:async()=>browser})});
    await driver.ready(); if(!fault.invalid&&!fault.bridge&&!fault.mismatch) await driver.newSession();
    await driver.close();
  } catch(e) {error=e.message}
  return {events,error};
}
(async()=>console.log(JSON.stringify({valid:await run({}),allProjects:await run({allProjects:true}),
  overview:await run({overview:true}),noOverview:await run({noOverview:true}),
  delayedFlat:await run({overview:true,delay:2}),delayedExit:await run({delay:2}),
  ambiguous:await run({ambiguous:true}),stuckExit:await run({stuckExit:true}),
  invalid:await run({invalid:true}),missing:await run({input:path.join(home,'missing')}),
  relative:await run({input:'scratch'}),file:await run({input:path.join(home,'not-a-directory')}),
  traversal:await run({input:workspace+path.sep+'..'+path.sep+'scratch'}),
  bridge:await run({bridge:true}),setter:await run({setter:true}),
  mismatch:await run({mismatch:true}),rail:await run({rail:true}),
  absentRail:await run({absentRail:true}),hiddenRail:await run({hiddenRail:true,rail:true})})))();
"""
    result = run_node(source.replace("process.argv.slice(2)",
                                     f"{json.dumps([str(runner), str(runner / 'home'), str(workspace)])}"), tmp_path)
    valid = result["valid"]
    assert valid["error"] is None
    assert valid["events"].count("set") == 1 and valid["events"].count("reload") == 1
    assert valid["events"].count("overview") == 1
    assert valid["events"].count("new") == 2
    assert valid["events"].index("set") < valid["events"].index("get") < valid["events"].index("reload") \
        < valid["events"].index("overview") < valid["events"].index("new") \
        < valid["events"].index("route") < valid["events"].index("cwd-rail")
    assert result["invalid"]["events"] == []
    for key in ("invalid", "missing", "relative", "file", "traversal"):
        assert result[key]["error"] and result[key]["events"] == [], result[key]
    assert result["allProjects"]["error"] is None
    assert result["allProjects"]["events"].count("overview") == 1
    assert result["overview"]["error"] is None
    assert result["overview"]["events"].count("new") == 2
    assert "overview" not in result["overview"]["events"]
    for key in ("delayedFlat", "delayedExit"):
        assert result[key]["error"] is None
        assert result[key]["events"].count("poll") == 2
        assert result[key]["events"].index("filters-ready") < result[key]["events"].index("new")
    assert result["noOverview"]["error"] == "Desktop project overview is not visible"
    assert "new" not in result["noOverview"]["events"]
    assert result["ambiguous"]["error"] == "ambiguous Filters"
    assert "new" not in result["ambiguous"]["events"]
    assert result["stuckExit"]["error"] == "Filters not ready"
    assert result["stuckExit"]["events"].count("overview") == 1
    assert "new" not in result["stuckExit"]["events"]
    assert result["bridge"]["events"] == []
    assert result["bridge"]["error"]
    assert result["setter"]["error"] and result["setter"]["events"] == ["set"]
    assert result["mismatch"]["events"] == ["set", "get"]
    assert result["mismatch"]["error"]
    assert result["rail"]["error"] and "cwd-rail" in result["rail"]["events"]
    for key in ("absentRail", "hiddenRail"):
        draft = result[key]
        assert draft["error"] is None and "cwd-rail" not in draft["events"]
        assert draft["events"].count("set") == draft["events"].count("reload") == 1
        assert draft["events"].count("get") >= 2
        assert draft["events"].count("new") == 2 and draft["events"].count("route") == 1
        assert draft["events"].index("set") < draft["events"].index("get") \
            < draft["events"].index("reload") < draft["events"].index("new") \
            < draft["events"].index("route")


def test_ready_waits_for_renderer_page_and_enabled_composer(tmp_path):
    result = run_node(r"""
const d = require(process.argv[1]);
const env = {GITHUB_ACTIONS:'true', RUNNER_ENVIRONMENT:'github-hosted', RUNNER_OS:'Windows',
  RUNNER_ARCH:'X64', HERMES_NATIVE_CI_ISOLATION:'github-hosted-ephemeral-windows'};
let pageReads=0, composerReads=0, waits=0, closed=0;
const page={url:()=> 'file:///synthetic/index.html',
  locator:()=>({count:async()=>++composerReads < 2 ? 0 : 1, first:()=>({
    getAttribute:async name=>name==='contenteditable'?'true':name==='aria-disabled'&&waits<2?'true':null
  })}), waitForTimeout:async()=>{waits++;}};
const browser={contexts:()=>[{pages:()=>++pageReads < 2 ? [] : [page]}],close:async()=>{closed++;}};
(async()=>{
  const driver=await d.connectDriver({endpoint:'ws://127.0.0.1:43123/devtools/browser/x',sourceRoot:'.',env,
    timeout:1000,load:()=>({connectOverCDP:async()=>browser})});
  const ready=await driver.ready();
  await driver.close();
  console.log(JSON.stringify({ready,pageReads,composerReads,waits,closed}));
})().catch(e=>{console.error(e);process.exit(1)});
""", tmp_path)
    assert result == {"ready": {"ready": True}, "pageReads": 2, "composerReads": 3, "waits": 2, "closed": 1}


def test_commands_drive_only_public_visible_desktop_controls(tmp_path):
    result = run_node(r"""
const d = require(process.argv[1]);
const calls = [];
let filledText = '';
let currentUrl = 'file:///synthetic/index.html#/sessions';
function loc(kind) {
  return {
    count: async () => 1,
    first() { return this; },
    getAttribute: async name => name === 'contenteditable' ? 'true' : null,
    locator: selector => { calls.push(['locator', kind, selector]); return loc(selector); },
    isEnabled: async () => true,
    isVisible: async () => true,
    innerText: async () => '',
    fill: async text => { filledText = text; calls.push(['fill', text]); },
    press: async (key, options) => {
      calls.push(['locator-press', kind, key, options.timeout]);
      if (kind === 'composer' && key === 'Control+n') currentUrl = 'file:///synthetic/index.html#/';
    },
    elementHandle: async () => {
      const id = calls.filter(entry => entry[0] === 'elementHandle').length + 1;
      calls.push(['elementHandle', id]);
      return {isVisible: async () => true, innerText: async () => filledText,
        press: async (key, options) => calls.push(['press', id, key, options.timeout]),
        dispose: async () => calls.push(['dispose', id])};
    },
    click: async options => {
      calls.push(['click', kind, options]);
    },
    waitFor: async options => calls.push(['waitFor', kind, options])
  };
}
const page = {
  url: () => currentUrl,
  locator: selector => { calls.push(['pageLocator', selector]); return loc('composer'); },
  waitForURL: async (predicate, options) => {
    calls.push(['waitForURL', options]);
    if (!predicate(new URL(currentUrl))) throw Error('route not reached');
  },
  getByText: (text, options) => { calls.push(['text', text, options]); return {first: () => loc('answer')}; },
  waitForTimeout: async () => {}
};
const browser = {contexts: () => [{pages: () => [page]}], close: async () => calls.push(['close'])};
const {PassThrough} = require('node:stream');
const env = {GITHUB_ACTIONS:'true', RUNNER_ENVIRONMENT:'github-hosted', RUNNER_OS:'Windows',
  RUNNER_ARCH:'X64', HERMES_NATIVE_CI_ISOLATION:'github-hosted-ephemeral-windows'};
(async () => {
  const input = new PassThrough();
  const output = new PassThrough();
  const chunks = [];
  output.on('data', chunk => chunks.push(chunk.toString('utf8')));
  const running = d.serveProtocol({endpoint:'ws://127.0.0.1:43123/devtools/browser/synthetic',
    sourceRoot:'.', env, stdin:input, stdout:output,
    load: () => ({connectOverCDP: async (url, options) => {
      calls.push(['connect', url, options]); return browser;
    }})});
  for (const [id, op, text] of [[1,'ready'], [2,'submit','Gr\u00fc\u00dfe \u65e5\u672c\u8a9e \u{1f602}'],
    [3,'wait','R\u00e9ponse \u2713 \u65e5\u672c\u8a9e'], [4,'new'], [5,'close']]) {
    input.write(JSON.stringify({id, op, text}) + '\n');
  }
  await running;
  console.log(JSON.stringify({calls, responses:chunks.join('').trim().split('\n').map(JSON.parse)}));
})().catch(e => { console.error(e); process.exit(1); });
""", tmp_path)
    calls = result["calls"]
    assert [entry for entry in calls if entry[0] == "fill"] == [["fill", "Grüße 日本語 😂"]]
    assert [entry for entry in calls if entry[0] == "pageLocator"] == [
        ['pageLocator', '[data-slot="composer-rich-input"]:visible'],
        ['pageLocator', '[data-slot="composer-rich-input"]:visible'],
        ['pageLocator', '[data-slot="composer-rich-input"]:visible'],
        ['pageLocator', '[data-slot="composer-rich-input"]:visible'],
    ]
    assert [entry[2] for entry in calls if entry[0] == "locator"] == [
        "xpath=ancestor::form[1]",
        'button[type="submit"]',
    ]
    assert [entry for entry in calls if entry[0] == "locator-press"] == [["locator-press", "composer", "Control+n", 30000]]
    assert not [entry for entry in calls if entry[0] == "click"]
    assert [entry for entry in calls if entry[0] == "waitForURL"] == [["waitForURL", {"timeout": 30000}]]
    assert [entry for entry in calls if entry[0] == "text"] == [
        ["text", "Réponse ✓ 日本語", {"exact": False}]
    ]
    assert [entry for entry in calls if entry[0] == "close"] == [["close"]]
    assert [entry for entry in calls if entry[0] == "elementHandle"] == [["elementHandle", 1]]
    assert [entry for entry in calls if entry[0] == "press"] == [["press", 1, "Enter", 30000]]
    assert [entry for entry in calls if entry[0] == "dispose"] == [["dispose", 1]]
    assert not [entry for entry in calls if entry[0] == "click" and entry[1] == 'button[type="submit"]']
    assert result["responses"] == [
        {"id": 1, "ok": True, "result": {"ready": True}},
        {"id": 2, "ok": True, "result": {"submitted": True}},
        {"id": 3, "ok": True, "result": {"visible": True}},
        {"id": 4, "ok": True, "result": {"newSession": True}},
        {"id": 5, "ok": True, "result": {"closed": True}},
    ]


def test_new_session_uses_ctrl_n_and_waits_for_fresh_route(tmp_path):
    result = run_node(r"""
const d = require(process.argv[1]);
const env = {GITHUB_ACTIONS:'true', RUNNER_ENVIRONMENT:'github-hosted', RUNNER_OS:'Windows',
  RUNNER_ARCH:'X64', HERMES_NATIVE_CI_ISOLATION:'github-hosted-ephemeral-windows'};
async function run(config) {
  const events=[];
  let url='file:///synthetic/index.html'+config.initialHash;
  let fills=0, keypresses=0, enters=0, composerReads=0, textReads=0;
  let routeChecks=0;
  const composer={count:async()=>{composerReads++;events.push('composer-count');return 1;},first(){return this;},
    getAttribute:async name=>name==='contenteditable'?'true':null,
    innerText:async()=>{textReads++;events.push('composer-text');return '';},
    fill:async()=>{fills++;},
    press:async(key,options)=>{events.push(['composer-press',key,options]);if(key==='Control+n'){keypresses++;if(config.keyFailure)throw Error('Ctrl+N failed');}else if(key==='Enter')enters++;}};
  const page={url:()=>url,locator:selector=>{
      events.push(['locator',selector]);
      return composer;
    },
    waitForURL:async(predicate,options)=>{
      events.push(['route-wait',options]);
      if(config.routeFailure)throw Error('route wait timed out');
      while(routeChecks<config.maxChecks){
        if(predicate(new URL(url))){events.push('route-ready');return;}
        routeChecks++;
        events.push('route-poll');
        if(config.transitionAfter===routeChecks) url='file:///synthetic/index.html#/';
      }
      if(predicate(new URL(url))){events.push('route-ready');return;}
      throw Error('route wait timed out');
    },waitForTimeout:async()=>{}};
  const browser={contexts:()=>[{pages:()=>[page]}],close:async()=>{}};
  const driver=await d.connectDriver({endpoint:'ws://127.0.0.1:43123/devtools/browser/x',sourceRoot:'.',env,
    timeout:30000,load:()=>({connectOverCDP:async()=>browser})});
  let result,error;
  try { result=await driver.newSession(); } catch(e) { error=e.message; }
  await driver.close();
  return {result:result??null,error:error??null,events,fills,keypresses,enters,composerReads,textReads,routeChecks};
}
(async()=>{
  const delayed=await run({initialHash:'#/sessions',transitionAfter:2,maxChecks:4});
  const alreadyFresh=await run({initialHash:'#/',maxChecks:1});
  const keyFailure=await run({initialHash:'#/sessions',keyFailure:true,maxChecks:1});
  const routeFailure=await run({initialHash:'#/sessions',routeFailure:true,maxChecks:1});
  console.log(JSON.stringify({delayed,alreadyFresh,keyFailure,routeFailure}));
})().catch(e=>{console.error(e);process.exit(1)});
""", tmp_path)
    delayed = result["delayed"]
    assert delayed["result"] == {"newSession": True} and delayed["error"] is None
    assert delayed["fills"] == delayed["enters"] == 0 and delayed["keypresses"] == 1
    assert delayed["events"].count(["composer-press", "Control+n", {"timeout": 30000}]) == 1
    assert delayed["events"].count("route-ready") == 1 and delayed["routeChecks"] == 2
    assert delayed["events"].index("composer-count") < delayed["events"].index(
        ["composer-press", "Control+n", {"timeout": 30000}]
    ) < delayed["events"].index("route-ready") < max(
        index for index, event in enumerate(delayed["events"]) if event == "composer-count"
    ) < delayed["events"].index("composer-text")
    assert delayed["composerReads"] == 2 and delayed["textReads"] == 1

    already_fresh = result["alreadyFresh"]
    assert already_fresh["result"] == {"newSession": True} and already_fresh["error"] is None
    assert already_fresh["events"].count(["composer-press", "Control+n", {"timeout": 30000}]) == 1
    assert already_fresh["events"].count("route-ready") == 1
    assert already_fresh["composerReads"] == 2 and already_fresh["textReads"] == 1

    key_failure = result["keyFailure"]
    assert key_failure["error"] == "Ctrl+N failed" and key_failure["result"] is None
    assert key_failure["keypresses"] == 1 and key_failure["routeChecks"] == key_failure["textReads"] == key_failure["enters"] == key_failure["fills"] == 0
    assert not [event for event in key_failure["events"] if isinstance(event, list) and event[0] == "route-wait"]

    route_failure = result["routeFailure"]
    assert route_failure["error"] == "route wait timed out" and route_failure["result"] is None
    assert route_failure["keypresses"] == 1 and route_failure["routeChecks"] == 0
    assert route_failure["textReads"] == route_failure["enters"] == route_failure["fills"] == 0


def test_submit_waits_for_payload_control_mount_and_visibility(tmp_path):
    result = run_node(r"""
const d = require(process.argv[1]);
const env = {GITHUB_ACTIONS:'true', RUNNER_ENVIRONMENT:'github-hosted', RUNNER_OS:'Windows',
  RUNNER_ARCH:'X64', HERMES_NATIVE_CI_ISOLATION:'github-hosted-ephemeral-windows'};
let waits=0, filled='', clicks=0, presses=0, pressTimeout=null, handleDisposals=0, snapshotCalls=0;
const button={count:async()=>waits<1?0:1, isVisible:async()=>waits>=2,
  isEnabled:async()=>true, click:async()=>{clicks++;}};
const form={count:async()=>1, locator:()=>button};
const editorHandle={isVisible:async()=>true, innerText:async()=>filled,
  press:async(key,options)=>{presses++; pressTimeout=options.timeout; if(key!=='Enter') throw Error('wrong key');},
  dispose:async()=>{handleDisposals++;}};
const composer={getAttribute:async name=>name==='contenteditable'?'true':null,
  fill:async text=>{filled=text;}, locator:()=>form, elementHandle:async()=>editorHandle};
const page={url:()=> 'file:///synthetic/index.html',
  locator:()=>({count:async()=>1, first:()=>composer}), waitForTimeout:async()=>{waits++;},
  evaluate:async()=>{snapshotCalls++; return {};}};
const browser={contexts:()=>[{pages:()=>[page]}],close:async()=>{}};
(async()=>{
  const driver=await d.connectDriver({endpoint:'ws://127.0.0.1:43123/devtools/browser/x',sourceRoot:'.',env,
    timeout:1000,load:()=>({connectOverCDP:async()=>browser})});
  const submitted=await driver.submit('synthetic follow-up');
  await driver.close();
  console.log(JSON.stringify({submitted,filled,waits,clicks,presses,pressTimeout,handleDisposals,snapshotCalls}));
})().catch(e=>{console.error(e);process.exit(1)});
""", tmp_path)
    assert result == {"submitted": {"submitted": True}, "filled": "synthetic follow-up", "waits": 2,
                      "clicks": 0, "presses": 1, "pressTimeout": 1000, "handleDisposals": 1, "snapshotCalls": 0}


def test_failed_submit_reports_bounded_metadata_without_retry(tmp_path):
    result = run_node(r"""
const d = require(process.argv[1]);
const {PassThrough} = require('node:stream');
const env = {GITHUB_ACTIONS:'true', RUNNER_ENVIRONMENT:'github-hosted', RUNNER_OS:'Windows',
  RUNNER_ARCH:'X64', HERMES_NATIVE_CI_ISOLATION:'github-hosted-ephemeral-windows'};
let mode=0, clicks=0, presses=0, handleDisposals=0, snapshotCalls=0;
const buttons=Array.from({length:6},()=>({type:'submit',disabled:false,
  getAttribute:name=>name==='type'?'submit':null,
  getBoundingClientRect:()=>({x:1,y:2,width:3,height:4})}));
const form={tagName:'FORM',parentElement:null,querySelectorAll:selector=>{
  if(selector!=='button[type="submit"]') throw Error('unexpected selector'); return buttons;
}};
const makeComposer=(snapshotVisible=true)=>({parentElement:form,innerText:'private composer contents',snapshotVisible,
  getAttribute:name=>name==='contenteditable'?'true':null,closest:()=>form,
  getBoundingClientRect:()=>snapshotVisible?{x:1,y:2,width:3,height:4}:{x:0,y:0,width:0,height:0},
  fill:async()=>{},elementHandle:async()=>({isVisible:async()=>true,innerText:async()=>'private prompt',
    press:async()=>{presses++;throw Error('synthetic keyboard failure');},dispose:async()=>{handleDisposals++;}}),
  locator:()=>({count:async()=>1,locator:()=>({count:async()=>1,
    isVisible:async()=>true,isEnabled:async()=>true,click:async()=>{clicks++;throw Error('synthetic click failure');}})})});
const snapshotComposers=[makeComposer(false),makeComposer(false),makeComposer(false),makeComposer(true)];
global.getComputedStyle=element=>({display:element.snapshotVisible===false?'none':'block',visibility:'visible'});
global.document={querySelectorAll:selector=>{
  if(selector!=='[data-slot="composer-rich-input"]') throw Error('non-CSS snapshot selector');
  return snapshotComposers;
}};
const page={url:()=> 'file:///synthetic/index.html',locator:()=>({count:async()=>1,first:makeComposer}),
  waitForTimeout:async()=>{},evaluate:async fn=>{
    snapshotCalls++;
    if(mode++===1) throw Error('synthetic snapshot failure');
    if(mode===3) return new Promise(()=>{});
    return fn();
  }};
const browser={contexts:()=>[{pages:()=>[page]}],close:async()=>{}};
(async()=>{
  const input=new PassThrough(), output=new PassThrough(), chunks=[];
  output.on('data',chunk=>chunks.push(chunk.toString('utf8')));
  const running=d.serveProtocol({endpoint:'ws://127.0.0.1:43123/devtools/browser/x',sourceRoot:'.',env,
    stdin:input,stdout:output,load:()=>({connectOverCDP:async()=>browser})});
  for(let id=1;id<=3;id++) input.write(JSON.stringify({id,op:'submit',text:'private prompt'})+'\n');
  input.end(); await running;
  console.log(JSON.stringify({clicks,presses,handleDisposals,snapshotCalls,responses:chunks.join('').trim().split('\n').map(JSON.parse)}));
})().catch(e=>{console.error(e);process.exit(1)});
""", tmp_path)
    assert result["clicks"] == 0 and result["presses"] == 3 and result["handleDisposals"] == 3
    assert result["snapshotCalls"] == 3
    captured, failed, timed_out = result["responses"]
    for index, response in enumerate((captured, failed, timed_out), 1):
        assert response["id"] == index and response["ok"] is False
        assert response["error"] == "synthetic keyboard failure"
        assert response["diagnostics"]["stage"] == "keyboard-submit"
    snapshot = captured["diagnostics"]["snapshot"]
    assert snapshot["status"] == "captured" and snapshot["composerCount"] == 4
    assert snapshot["visibleComposerCount"] == 1
    assert len(snapshot["composers"]) == 1 and snapshot["composers"][0]["visible"] is True
    assert snapshot["composers"][0] == {
        "visible": True, "contenteditable": "true", "ariaDisabled": None,
        "textLength": len("private composer contents"),
        "formCount": 1, "submitButtonCount": 6,
        "buttons": [{"type": "submit", "disabled": False, "ariaDisabled": None, "visible": True,
                     "rect": {"x": 1, "y": 2, "width": 3, "height": 4}}] * 4,
    }
    assert "private composer contents" not in json.dumps(snapshot)
    assert len(json.dumps(snapshot)) < 1600
    assert set(snapshot) == {"status", "composerCount", "visibleComposerCount", "composers"}
    assert set(snapshot["composers"][0]) == {
        "visible", "contenteditable", "ariaDisabled", "textLength", "formCount", "submitButtonCount", "buttons",
    }
    assert failed["diagnostics"]["snapshot"]["status"] == "failed"
    assert set(failed["diagnostics"]["snapshot"]) == {"status"}
    assert timed_out["diagnostics"]["snapshot"]["status"] == "timeout"


def test_submit_does_not_press_missing_detached_or_changed_editor_handle(tmp_path):
    result = run_node(r"""
const d = require(process.argv[1]);
const {PassThrough} = require('node:stream');
const env = {GITHUB_ACTIONS:'true', RUNNER_ENVIRONMENT:'github-hosted', RUNNER_OS:'Windows',
  RUNNER_ARCH:'X64', HERMES_NATIVE_CI_ISOLATION:'github-hosted-ephemeral-windows'};
let locateCalls=0, fills=0, presses=0, disposed=0;
const button={count:async()=>1,isVisible:async()=>true,isEnabled:async()=>true,click:async()=>{throw Error('click forbidden');}};
const form={count:async()=>1,locator:()=>button};
let currentText='';
const composer={getAttribute:async name=>name==='contenteditable'?'true':null,
  fill:async text=>{fills++;currentText=text;},locator:()=>form,
  elementHandle:async()=>{
    if(currentText==='missing') return null;
    return {isVisible:async()=>currentText!=='detached',innerText:async()=>currentText==='changed'?'':'changed',
      press:async()=>{presses++;},dispose:async()=>{disposed++;}};
  }};
const page={url:()=> 'file:///synthetic/index.html',locator:()=>{locateCalls++;return {count:async()=>1,first:()=>composer};},
  waitForTimeout:async()=>{},evaluate:async()=>{throw Error('bounded snapshot unavailable');}};
const browser={contexts:()=>[{pages:()=>[page]}],close:async()=>{}};
(async()=>{
  const input=new PassThrough(),output=new PassThrough(),chunks=[];
  output.on('data',chunk=>chunks.push(chunk.toString('utf8')));
  const running=d.serveProtocol({endpoint:'ws://127.0.0.1:43123/devtools/browser/x',sourceRoot:'.',env,
    stdin:input,stdout:output,load:()=>({connectOverCDP:async()=>browser})});
  for(let id=1;id<=3;id++) input.write(JSON.stringify({id,op:'submit',text:['missing','detached','changed'][id-1]})+'\n');
  input.end();await running;
  console.log(JSON.stringify({locateCalls,fills,presses,disposed,responses:chunks.join('').trim().split('\n').map(JSON.parse)}));
})().catch(e=>{console.error(e);process.exit(1)});
""", tmp_path)
    assert result["locateCalls"] == result["fills"] == 3
    assert result["presses"] == 0 and result["disposed"] == 2
    for index, response in enumerate(result["responses"], 1):
        assert response["id"] == index and response["ok"] is False
        assert response["error"] == "Desktop composer payload changed before keyboard submit"
        assert response["diagnostics"]["stage"] == "payload-check"
        assert response["diagnostics"]["snapshot"]["status"] == "failed"


def test_composer_and_submit_ambiguity_fail_closed(tmp_path):
    result = run_node(r"""
const d = require(process.argv[1]);
const env = {GITHUB_ACTIONS:'true', RUNNER_ENVIRONMENT:'github-hosted', RUNNER_OS:'Windows',
  RUNNER_ARCH:'X64', HERMES_NATIVE_CI_ISOLATION:'github-hosted-ephemeral-windows'};
function page(composerCount, buttonCount, enabled) {
  const button = {count:async()=>buttonCount, isEnabled:async()=>enabled, isVisible:async()=>true};
  const form = {count:async()=>1, locator:()=>button};
  const composer = {first(){return this}, getAttribute:async name=>name==='contenteditable'?'true':null,
    locator:()=>form, fill:async()=>{}, innerText:async()=>''};
  return {url:()=> 'file:///app', locator:()=>({count:async()=>composerCount,first:()=>composer}), waitForTimeout:async()=>{}};
}
(async()=>{
  const errors=[];
  const cases = [
    {p:page(2,1,true), op:'ready'},
    {p:page(1,2,true), op:'submit', timeout:0},
    {p:page(1,1,false), op:'submit', timeout:0},
  ];
  for (const {p, op, timeout=30000} of cases) {
    const browser={contexts:()=>[{pages:()=>[p]}],close:async()=>{}};
    const driver=await d.connectDriver({endpoint:'ws://127.0.0.1:43124/devtools/browser/x', sourceRoot:'.', env, timeout,
      load:()=>({connectOverCDP:async()=>browser})});
    try { if (op === 'ready') await driver.ready(); else await driver.submit('synthetic'); }
    catch (e) { errors.push(e.message); }
  }
  console.log(JSON.stringify({errors}));
})().catch(e=>{console.error(e);process.exit(1)});
""", tmp_path)
    assert result["errors"] == [
        "expected exactly one visible Desktop composer",
        "Desktop composer form must have one visible submit button",
        "Desktop submit button did not become enabled",
    ]
