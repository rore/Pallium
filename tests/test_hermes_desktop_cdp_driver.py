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
function loc(kind) {
  return {
    count: async () => 1,
    first() { return this; },
    getAttribute: async name => name === 'contenteditable' ? 'true' : null,
    locator: selector => { calls.push(['locator', kind, selector]); return loc(selector); },
    isEnabled: async () => true,
    isVisible: async () => true,
    innerText: async () => '',
    fill: async text => calls.push(['fill', text]),
    click: async () => calls.push(['click', kind]),
    waitFor: async options => calls.push(['waitFor', kind, options])
  };
}
const page = {
  url: () => 'file:///synthetic/index.html',
  locator: selector => { calls.push(['pageLocator', selector]); return loc('composer'); },
  getByRole: (role, options) => { calls.push(['role', role, options]); return loc('button:New session'); },
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
    ]
    assert [entry[2] for entry in calls if entry[0] == "locator"] == [
        "xpath=ancestor::form[1]",
        'button[type="submit"]',
    ]
    assert [entry for entry in calls if entry[0] == "role"] == [
        ["role", "button", {"name": "New session", "exact": True}]
    ]
    assert [entry for entry in calls if entry[0] == "text"] == [
        ["text", "Réponse ✓ 日本語", {"exact": False}]
    ]
    assert [entry for entry in calls if entry[0] == "close"] == [["close"]]
    assert result["responses"] == [
        {"id": 1, "ok": True, "result": {"ready": True}},
        {"id": 2, "ok": True, "result": {"submitted": True}},
        {"id": 3, "ok": True, "result": {"visible": True}},
        {"id": 4, "ok": True, "result": {"newSession": True}},
        {"id": 5, "ok": True, "result": {"closed": True}},
    ]


def test_submit_waits_for_payload_control_mount_and_visibility(tmp_path):
    result = run_node(r"""
const d = require(process.argv[1]);
const env = {GITHUB_ACTIONS:'true', RUNNER_ENVIRONMENT:'github-hosted', RUNNER_OS:'Windows',
  RUNNER_ARCH:'X64', HERMES_NATIVE_CI_ISOLATION:'github-hosted-ephemeral-windows'};
let waits=0, filled='', clicks=0, snapshotCalls=0;
const button={count:async()=>waits<1?0:1, isVisible:async()=>waits>=2,
  isEnabled:async()=>true, click:async()=>{clicks++;}};
const form={count:async()=>1, locator:()=>button};
const composer={getAttribute:async name=>name==='contenteditable'?'true':null,
  fill:async text=>{filled=text;}, locator:()=>form};
const page={url:()=> 'file:///synthetic/index.html',
  locator:()=>({count:async()=>1, first:()=>composer}), waitForTimeout:async()=>{waits++;},
  evaluate:async()=>{snapshotCalls++; return {};}};
const browser={contexts:()=>[{pages:()=>[page]}],close:async()=>{}};
(async()=>{
  const driver=await d.connectDriver({endpoint:'ws://127.0.0.1:43123/devtools/browser/x',sourceRoot:'.',env,
    timeout:1000,load:()=>({connectOverCDP:async()=>browser})});
  const submitted=await driver.submit('synthetic follow-up');
  await driver.close();
  console.log(JSON.stringify({submitted,filled,waits,clicks,snapshotCalls}));
})().catch(e=>{console.error(e);process.exit(1)});
""", tmp_path)
    assert result == {"submitted": {"submitted": True}, "filled": "synthetic follow-up", "waits": 2,
                      "clicks": 1, "snapshotCalls": 0}


def test_failed_submit_reports_bounded_metadata_without_retry(tmp_path):
    result = run_node(r"""
const d = require(process.argv[1]);
const {PassThrough} = require('node:stream');
const env = {GITHUB_ACTIONS:'true', RUNNER_ENVIRONMENT:'github-hosted', RUNNER_OS:'Windows',
  RUNNER_ARCH:'X64', HERMES_NATIVE_CI_ISOLATION:'github-hosted-ephemeral-windows'};
let mode=0, clicks=0, snapshotCalls=0;
const buttons=Array.from({length:6},()=>({type:'submit',disabled:false,
  getAttribute:name=>name==='type'?'submit':null,
  getBoundingClientRect:()=>({x:1,y:2,width:3,height:4})}));
const form={tagName:'FORM',parentElement:null,querySelectorAll:selector=>{
  if(selector!=='button[type="submit"]') throw Error('unexpected selector'); return buttons;
}};
const makeComposer=(snapshotVisible=true)=>({parentElement:form,innerText:'private composer contents',snapshotVisible,
  getAttribute:name=>name==='contenteditable'?'true':null,closest:()=>form,
  getBoundingClientRect:()=>snapshotVisible?{x:1,y:2,width:3,height:4}:{x:0,y:0,width:0,height:0},
  fill:async()=>{},locator:()=>({count:async()=>1,locator:()=>({count:async()=>1,
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
  console.log(JSON.stringify({clicks,snapshotCalls,responses:chunks.join('').trim().split('\n').map(JSON.parse)}));
})().catch(e=>{console.error(e);process.exit(1)});
""", tmp_path)
    assert result["clicks"] == 3
    assert result["snapshotCalls"] == 3
    captured, failed, timed_out = result["responses"]
    for index, response in enumerate((captured, failed, timed_out), 1):
        assert response["id"] == index and response["ok"] is False
        assert response["error"] == "synthetic click failure"
        assert response["diagnostics"]["stage"] == "click"
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
