'use strict'

const path = require('node:path')
const { createRequire } = require('node:module')
const { createInterface } = require('node:readline')

const RUNNER_MARKERS = {
  GITHUB_ACTIONS: 'true',
  RUNNER_ENVIRONMENT: 'github-hosted',
  RUNNER_OS: 'Windows',
  RUNNER_ARCH: 'X64',
  HERMES_NATIVE_CI_ISOLATION: 'github-hosted-ephemeral-windows'
}
const COMPOSER = '[data-slot="composer-rich-input"]:visible'

function requireRunnerGate(env) {
  for (const [key, expected] of Object.entries(RUNNER_MARKERS)) {
    if (env[key] !== expected) throw new Error(`refusing Desktop CDP outside qualified runner: ${key}`)
  }
}

function validateEndpoint(value) {
  let endpoint
  try {
    endpoint = new URL(value)
  } catch {
    throw new Error('invalid Desktop CDP endpoint')
  }
  if (endpoint.protocol !== 'ws:' || endpoint.hostname !== '127.0.0.1' ||
      !/^\d+$/.test(endpoint.port) || Number(endpoint.port) < 1 || Number(endpoint.port) > 65535 ||
      endpoint.username || endpoint.password || endpoint.search || endpoint.hash ||
      !/^\/devtools\/browser\/[^/]+$/.test(endpoint.pathname)) {
    throw new Error('Desktop CDP endpoint must be an ephemeral numeric-loopback browser WebSocket')
  }
  return endpoint.href
}

function loadChromium(sourceRoot) {
  const requireFromHermes = createRequire(path.join(sourceRoot, 'package.json'))
  return requireFromHermes('@playwright/test').chromium
}

async function desktopPage(browser, timeout) {
  const deadline = Date.now() + timeout
  while (true) {
    const page = browser.contexts().flatMap(context => context.pages())
      .find(candidate => candidate.url().startsWith('file:'))
    if (page) return page
    if (Date.now() >= deadline) throw new Error('no actual Desktop renderer page on CDP')
    await new Promise(resolve => setTimeout(resolve, 50))
  }
}

async function submitButton(composer, page, timeout) {
  const forms = composer.locator('xpath=ancestor::form[1]')
  if (await forms.count() !== 1) throw new Error('Desktop composer must have one containing form')
  const buttons = forms.locator('button[type="submit"]')
  const deadline = Date.now() + timeout
  while (true) {
    const count = await buttons.count()
    if (count > 1) throw new Error('Desktop composer form must have one visible submit button')
    if (count === 1 && await buttons.isVisible()) return buttons
    if (Date.now() >= deadline) throw new Error('Desktop composer form must have one visible submit button')
    await page.waitForTimeout(50)
  }
}

async function submitPageSnapshot(page) {
  let timer
  try {
    const value = await Promise.race([
      page.evaluate(() => {
        const composers = [...document.querySelectorAll('[data-slot="composer-rich-input"]')]
        const visible = element => {
          const style = getComputedStyle(element)
          const rect = element.getBoundingClientRect()
          return style.display !== 'none' && style.visibility !== 'hidden' &&
            rect.width > 0 && rect.height > 0
        }
        const visibleComposers = composers.filter(visible)
        const sampledComposers = (visibleComposers.length ? visibleComposers : composers).slice(0, 2)
        return {
          composerCount: composers.length,
          visibleComposerCount: visibleComposers.length,
          composers: sampledComposers.map(composer => {
            let formCount = 0
            for (let node = composer.parentElement; node; node = node.parentElement) {
              if (node.tagName === 'FORM') formCount++
            }
            const form = composer.closest('form')
            const buttons = form ? [...form.querySelectorAll('button[type="submit"]')] : []
            return {
              visible: visible(composer),
              contenteditable: composer.getAttribute('contenteditable'),
              ariaDisabled: composer.getAttribute('aria-disabled'),
              textLength: (composer.innerText || '').length,
              formCount,
              submitButtonCount: buttons.length,
              buttons: buttons.slice(0, 4).map(button => {
                const rect = button.getBoundingClientRect()
                return {
                  type: button.getAttribute('type'),
                  disabled: button.disabled,
                  ariaDisabled: button.getAttribute('aria-disabled'),
                  visible: visible(button),
                  rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height}
                }
              })
            }
          })
        }
      }),
      new Promise((_, reject) => {
        timer = setTimeout(() => {
          const error = new Error('submit metadata snapshot timed out')
          error.code = 'snapshot-timeout'
          reject(error)
        }, 1200)
      })
    ])
    return {status: 'captured', ...value}
  } catch (error) {
    return {status: error?.code === 'snapshot-timeout' ? 'timeout' : 'failed'}
  } finally {
    clearTimeout(timer)
  }
}

async function connectDriver({ endpoint, sourceRoot, env = process.env, load = loadChromium, timeout = 30000 }) {
  requireRunnerGate(env)
  const url = validateEndpoint(endpoint)
  const chromium = load(sourceRoot)
  const browser = await chromium.connectOverCDP(url, { timeout })
  let browserClosed = false
  const closeBrowser = async () => {
    if (browserClosed) return
    browserClosed = true
    await browser.close()
  }
  try {
    const page = await desktopPage(browser, timeout)
    async function waitForComposerReady() {
      const deadline = Date.now() + timeout
      while (true) {
        const composers = page.locator(COMPOSER)
        const count = await composers.count()
        if (count > 1) throw new Error('expected exactly one visible Desktop composer')
        if (count === 1) {
          const composer = composers.first()
          const editable = await composer.getAttribute('contenteditable')
          if (editable === null) throw new Error('Desktop composer is not contenteditable')
          if (editable !== 'false' && (await composer.getAttribute('aria-disabled')) !== 'true') return composer
        }
        if (Date.now() >= deadline) throw new Error('Desktop composer did not become ready')
        await page.waitForTimeout(50)
      }
    }
    async function waitForEnabled(button) {
      const deadline = Date.now() + timeout
      while (!(await button.isEnabled())) {
        if (Date.now() >= deadline) throw new Error('Desktop submit button did not become enabled')
        await page.waitForTimeout(50)
      }
    }
    return {
      async ready() {
        await waitForComposerReady()
        return { ready: true }
      },
      async submit(text) {
        if (typeof text !== 'string' || !text) throw new Error('submit text must be non-empty')
        let stage = 'readiness'
        let editorHandle
        let primaryError
        try {
          const composer = await waitForComposerReady()
          stage = 'fill'
          await composer.fill(text)
          stage = 'button-selection'
          const button = await submitButton(composer, page, timeout)
          stage = 'enabled'
          await waitForEnabled(button)
          stage = 'payload-check'
          editorHandle = await composer.elementHandle()
          if (!editorHandle || !(await editorHandle.isVisible()) || await editorHandle.innerText() !== text) {
            throw new Error('Desktop composer payload changed before keyboard submit')
          }
          stage = 'keyboard-submit'
          await editorHandle.press('Enter', {timeout})
          return { submitted: true }
        } catch (error) {
          primaryError = error
          if (error && typeof error === 'object') {
            error.submitDiagnostics = {stage, snapshot: await submitPageSnapshot(page)}
          }
          throw error
        } finally {
          if (editorHandle) {
            try {
              await editorHandle.dispose()
            } catch (disposeError) {
              if (!primaryError) throw disposeError
            }
          }
        }
      },
      async wait(text) {
        if (typeof text !== 'string' || !text) throw new Error('wait text must be non-empty')
        await page.getByText(text, { exact: false }).first().waitFor({ state: 'visible', timeout })
        return { visible: true }
      },
      async newSession() {
        const button = page.getByRole('button', { name: 'New session', exact: true })
        if (await button.count() !== 1 || !(await button.isVisible())) {
          throw new Error('expected one accessible New session button')
        }
        await button.click()
        const composer = await waitForComposerReady()
        const deadline = Date.now() + timeout
        while ((await composer.innerText()).trim() !== '') {
          if (Date.now() >= deadline) throw new Error('new session did not clear the composer')
          await page.waitForTimeout(50)
        }
        return { newSession: true }
      },
      async close() {
        await closeBrowser()
        return { closed: true }
      }
    }
  } catch (error) {
    await closeBrowser().catch(() => {})
    throw error
  }
}

async function serveProtocol({ endpoint, sourceRoot, env = process.env, stdin = process.stdin,
  stdout = process.stdout, load = loadChromium }) {
  const driver = await connectDriver({ endpoint, sourceRoot, env, load })
  const input = createInterface({ input: stdin, crlfDelay: Infinity })
  try {
    for await (const line of input) {
      let request
      try {
        request = JSON.parse(line)
        let result
        switch (request.op) {
          case 'ready': result = await driver.ready(); break
          case 'submit': result = await driver.submit(request.text); break
          case 'wait': result = await driver.wait(request.text); break
          case 'new': result = await driver.newSession(); break
          case 'close': result = await driver.close(); input.close(); break
          default: throw new Error('unsupported Desktop CDP operation')
        }
        stdout.write(`${JSON.stringify({ id: request.id ?? null, ok: true, result })}\n`)
        if (request.op === 'close') break
      } catch (error) {
        const reply = {id: request?.id ?? null, ok: false, error: String(error?.message || error)}
        if (error?.submitDiagnostics) reply.diagnostics = error.submitDiagnostics
        stdout.write(`${JSON.stringify(reply)}\n`)
      }
    }
  } finally {
    await driver.close()
  }
}

if (require.main === module) {
  const [endpoint, sourceRoot] = process.argv.slice(2)
  if (!endpoint || !sourceRoot) {
    process.stderr.write('usage: hermes_desktop_cdp_driver.cjs <owned-cdp-websocket> <hermes-source-root>\n')
    process.exitCode = 2
  } else {
    serveProtocol({ endpoint, sourceRoot }).catch(error => {
      process.stderr.write(`${error.stack || error}\n`)
      process.exitCode = 1
    })
  }
}

module.exports = { connectDriver, requireRunnerGate, serveProtocol, validateEndpoint }
