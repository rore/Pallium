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
