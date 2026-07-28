import json
import os
import subprocess
import textwrap
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KOISHI_DIR = os.path.join(ROOT, "koishi-bridge")


class KoishiWebhookFallbackTests(unittest.TestCase):
    def test_python_bridge_declares_server_injection(self):
        script = "console.log(require('./plugins/python-bridge').inject.includes('server'))"

        result = subprocess.run(
            ["node", "-e", script],
            cwd=KOISHI_DIR,
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertEqual(result.stdout.strip(), "true")

    def test_python_bridge_registers_qq_verification_route(self):
        script = textwrap.dedent(
            """
            const plugin = require('./plugins/python-bridge')
            const routes = {}
            const ctx = {
              logger: () => ({ info: () => {}, warn: () => {} }),
              middleware: () => {},
              server: { post: (path, handler) => { routes[path] = handler } },
            }

            plugin.apply(ctx, {
              endpoint: 'http://127.0.0.1:1',
              token: '',
              whitelist: ['1097445697'],
              qqWebhookPath: '/qq',
              qqAppId: '1903707124',
              qqAppSecret: '12345678901234567890123456789012',
            })

            ;(async () => {
              const requestContext = {
                request: {
                  body: {
                    op: 13,
                    d: { plain_token: 'testplain', event_ts: '1234567890' },
                  },
                },
                get: (name) => name.toLowerCase() === 'x-bot-appid' ? '1903707124' : '',
              }
              await routes['/qq'](requestContext)
              console.log(JSON.stringify({
                status: requestContext.status,
                plainToken: requestContext.body.plain_token,
                signatureLength: requestContext.body.signature.length,
              }))
            })().catch((error) => {
              console.error(error)
              process.exit(1)
            })
            """
        )

        result = subprocess.run(
            ["node", "-e", script],
            cwd=KOISHI_DIR,
            text=True,
            capture_output=True,
            check=True,
        )
        data = json.loads(result.stdout)

        self.assertEqual(data["status"], 200)
        self.assertEqual(data["plainToken"], "testplain")
        self.assertEqual(data["signatureLength"], 128)

    def test_python_bridge_forwards_signed_group_dispatch(self):
        script = textwrap.dedent(
            """
            const crypto = require('node:crypto')
            const plugin = require('./plugins/python-bridge')
            const routes = {}
            const forwarded = []
            global.fetch = async (url, init) => {
              forwarded.push({
                url,
                token: init.headers['x-bridge-token'],
                payload: JSON.parse(init.body),
              })
              return { ok: true, status: 200, text: async () => '' }
            }

            const ctx = {
              logger: () => ({ info: () => {}, warn: () => {} }),
              middleware: () => {},
              server: { post: (path, handler) => { routes[path] = handler } },
            }
            const secret = '12345678901234567890123456789012'

            plugin.apply(ctx, {
              endpoint: 'http://127.0.0.1:8765/koishi/message',
              token: 'bridge-token',
              whitelist: ['1097445697'],
              qqWebhookPath: '/qq',
              qqAppId: '1903707124',
              qqAppSecret: secret,
            })

            function privateSeed(secret) {
              let seed = String(secret || '')
              while (seed.length < 32) seed += seed
              return Buffer.from(seed).subarray(0, 32)
            }

            function privateKey(secret) {
              return crypto.createPrivateKey({
                key: Buffer.concat([
                  Buffer.from('302e020100300506032b657004220420', 'hex'),
                  privateSeed(secret),
                ]),
                format: 'der',
                type: 'pkcs8',
              })
            }

            ;(async () => {
              const body = JSON.stringify({
                op: 0,
                t: 'GROUP_MESSAGE_CREATE',
                d: {
                  id: 'msg-1',
                  group_openid: '1097445697',
                  content: 'menu',
                  author: { member_openid: 'user-1' },
                },
              })
              const timestamp = '1234567890'
              const signature = crypto.sign(null, Buffer.from(timestamp + body), privateKey(secret)).toString('hex')
              const requestContext = {
                request: {
                  body: {
                    ...JSON.parse(body),
                    [Symbol.for('unparsedBody')]: body,
                  },
                },
                get: (name) => ({
                  'x-bot-appid': '1903707124',
                  'x-signature-timestamp': timestamp,
                  'x-signature-ed25519': signature,
                })[name.toLowerCase()] || '',
              }

              await routes['/qq'](requestContext)
              console.log(JSON.stringify({
                status: requestContext.status,
                ack: requestContext.body,
                forwarded,
              }))
            })().catch((error) => {
              console.error(error)
              process.exit(1)
            })
            """
        )

        result = subprocess.run(
            ["node", "-e", script],
            cwd=KOISHI_DIR,
            text=True,
            capture_output=True,
            check=True,
        )
        data = json.loads(result.stdout)

        self.assertEqual(data["status"], 200)
        self.assertEqual(data["ack"], {"d": {}, "op": 12})
        self.assertEqual(len(data["forwarded"]), 1)
        self.assertEqual(data["forwarded"][0]["token"], "bridge-token")
        self.assertEqual(data["forwarded"][0]["payload"]["type"], "group")
        self.assertEqual(data["forwarded"][0]["payload"]["group_openid"], "1097445697")
        self.assertEqual(data["forwarded"][0]["payload"]["msg_id"], "msg-1")
        self.assertEqual(data["forwarded"][0]["payload"]["content"], "menu")

    def test_python_bridge_forwards_group_at_outside_full_message_whitelist(self):
        script = textwrap.dedent(
            """
            const crypto = require('node:crypto')
            const plugin = require('./plugins/python-bridge')
            const routes = {}
            const forwarded = []
            global.fetch = async (url, init) => {
              forwarded.push(JSON.parse(init.body))
              return { ok: true, status: 200, text: async () => '' }
            }

            const ctx = {
              logger: () => ({ info: () => {}, warn: () => {} }),
              middleware: () => {},
              server: { post: (path, handler) => { routes[path] = handler } },
            }
            const secret = '12345678901234567890123456789012'

            plugin.apply(ctx, {
              endpoint: 'http://127.0.0.1:8765/koishi/message',
              token: 'bridge-token',
              whitelist: ['1097445697'],
              qqWebhookPath: '/qq',
              qqAppId: '1903707124',
              qqAppSecret: secret,
            })

            function privateSeed(secret) {
              let seed = String(secret || '')
              while (seed.length < 32) seed += seed
              return Buffer.from(seed).subarray(0, 32)
            }

            function privateKey(secret) {
              return crypto.createPrivateKey({
                key: Buffer.concat([
                  Buffer.from('302e020100300506032b657004220420', 'hex'),
                  privateSeed(secret),
                ]),
                format: 'der',
                type: 'pkcs8',
              })
            }

            ;(async () => {
              const body = JSON.stringify({
                op: 0,
                t: 'GROUP_AT_MESSAGE_CREATE',
                d: {
                  id: 'msg-at-1',
                  group_openid: 'not-full-message-whitelisted',
                  content: '@bot menu',
                  author: { member_openid: 'user-1' },
                },
              })
              const timestamp = '1234567890'
              const signature = crypto.sign(null, Buffer.from(timestamp + body), privateKey(secret)).toString('hex')
              await routes['/qq']({
                request: {
                  body: {
                    ...JSON.parse(body),
                    [Symbol.for('unparsedBody')]: body,
                  },
                },
                get: (name) => ({
                  'x-bot-appid': '1903707124',
                  'x-signature-timestamp': timestamp,
                  'x-signature-ed25519': signature,
                })[name.toLowerCase()] || '',
              })
              console.log(JSON.stringify({ forwarded }))
            })().catch((error) => {
              console.error(error)
              process.exit(1)
            })
            """
        )

        result = subprocess.run(
            ["node", "-e", script],
            cwd=KOISHI_DIR,
            text=True,
            capture_output=True,
            check=True,
        )
        data = json.loads(result.stdout)

        self.assertEqual(len(data["forwarded"]), 1)
        self.assertEqual(data["forwarded"][0]["event_type"], "GROUP_AT_MESSAGE_CREATE")
        self.assertEqual(data["forwarded"][0]["group_openid"], "not-full-message-whitelisted")
        self.assertTrue(data["forwarded"][0]["is_at"])

    def test_middleware_forwards_group_at_outside_full_message_whitelist(self):
        script = textwrap.dedent(
            """
            const plugin = require('./plugins/python-bridge')
            let middleware
            let nextCalled = false
            const forwarded = []
            global.fetch = async (url, init) => {
              forwarded.push(JSON.parse(init.body))
              return { ok: true, status: 200, text: async () => '' }
            }

            const ctx = {
              logger: () => ({ info: () => {}, warn: () => {} }),
              middleware: (fn) => { middleware = fn },
            }

            plugin.apply(ctx, {
              endpoint: 'http://127.0.0.1:8765/koishi/message',
              token: 'bridge-token',
              whitelist: ['full-group'],
              qqWebhookPath: '',
              qqAppId: '1903707124',
              qqAppSecret: '',
            })

            ;(async () => {
              await middleware({
                content: '<at id="1903707124"/> 菜单',
                elements: [{ type: 'at', attrs: { id: '1903707124' } }],
                selfId: '1903707124',
                userId: 'user-openid',
                guildId: 'outside-full-group',
                channelId: 'outside-full-group',
                messageId: 'msg-at-middleware',
                qq: { t: 'GROUP_AT_MESSAGE_CREATE', d: { group_openid: 'outside-full-group' } },
              }, async () => { nextCalled = true })

              console.log(JSON.stringify({ forwarded, nextCalled }))
            })().catch((error) => {
              console.error(error)
              process.exit(1)
            })
            """
        )

        result = subprocess.run(
            ["node", "-e", script],
            cwd=KOISHI_DIR,
            text=True,
            capture_output=True,
            check=True,
        )
        data = json.loads(result.stdout)

        self.assertFalse(data["nextCalled"])
        self.assertEqual(len(data["forwarded"]), 1)
        self.assertEqual(data["forwarded"][0]["group_openid"], "outside-full-group")
        self.assertEqual(data["forwarded"][0]["event_type"], "GROUP_AT_MESSAGE_CREATE")
        self.assertTrue(data["forwarded"][0]["is_at"])

    def test_middleware_forwards_whitelisted_full_group_message(self):
        script = textwrap.dedent(
            """
            const plugin = require('./plugins/python-bridge')
            let middleware
            const forwarded = []
            global.fetch = async (url, init) => {
              forwarded.push(JSON.parse(init.body))
              return { ok: true, status: 200, text: async () => '' }
            }

            const ctx = {
              logger: () => ({ info: () => {}, warn: () => {} }),
              middleware: (fn) => { middleware = fn },
            }

            plugin.apply(ctx, {
              endpoint: 'http://127.0.0.1:8765/koishi/message',
              token: 'bridge-token',
              whitelist: ['full-group-openid'],
              qqWebhookPath: '',
              qqAppId: '1903707124',
              qqAppSecret: '',
            })

            ;(async () => {
              await middleware({
                content: 'menu',
                elements: [{ type: 'text', attrs: { content: 'menu' } }],
                selfId: '1903707124',
                userId: 'member-openid',
                guildId: 'fallback-group-id',
                channelId: 'fallback-group-id',
                messageId: 'fallback-msg-id',
                qq: {
                  t: 'GROUP_MESSAGE_CREATE',
                  d: {
                    id: 'group-full-msg-id',
                    group_openid: 'full-group-openid',
                    author: {
                      member_openid: 'member-openid',
                      user_openid: 'global-user-openid',
                    },
                  },
                },
              }, async () => {})

              console.log(JSON.stringify({ forwarded }))
            })().catch((error) => {
              console.error(error)
              process.exit(1)
            })
            """
        )

        result = subprocess.run(
            ["node", "-e", script],
            cwd=KOISHI_DIR,
            text=True,
            capture_output=True,
            check=True,
        )
        data = json.loads(result.stdout)

        self.assertEqual(len(data["forwarded"]), 1)
        self.assertEqual(data["forwarded"][0]["group_openid"], "full-group-openid")
        self.assertEqual(data["forwarded"][0]["user_openid"], "member-openid")
        self.assertEqual(data["forwarded"][0]["limit_user_id"], "global-user-openid")
        self.assertEqual(data["forwarded"][0]["msg_id"], "group-full-msg-id")
        self.assertEqual(data["forwarded"][0]["content"], "menu")
        self.assertEqual(data["forwarded"][0]["event_type"], "GROUP_MESSAGE_CREATE")
        self.assertFalse(data["forwarded"][0]["is_at"])

    def test_middleware_ignores_non_at_group_message_outside_whitelist(self):
        script = textwrap.dedent(
            """
            const plugin = require('./plugins/python-bridge')
            let middleware
            let nextCalled = false
            const forwarded = []
            global.fetch = async (url, init) => {
              forwarded.push(JSON.parse(init.body))
              return { ok: true, status: 200, text: async () => '' }
            }

            const ctx = {
              logger: () => ({ info: () => {}, warn: () => {} }),
              middleware: (fn) => { middleware = fn },
            }

            plugin.apply(ctx, {
              endpoint: 'http://127.0.0.1:8765/koishi/message',
              token: 'bridge-token',
              whitelist: ['full-group-openid'],
              qqWebhookPath: '',
              qqAppId: '1903707124',
              qqAppSecret: '',
            })

            ;(async () => {
              await middleware({
                content: 'menu',
                elements: [{ type: 'text', attrs: { content: 'menu' } }],
                selfId: '1903707124',
                userId: 'member-openid',
                guildId: 'other-group-openid',
                channelId: 'other-group-openid',
                messageId: 'group-full-msg-id',
                qq: {
                  t: 'GROUP_MESSAGE_CREATE',
                  d: {
                    id: 'group-full-msg-id',
                    group_openid: 'other-group-openid',
                    author: { member_openid: 'member-openid' },
                  },
                },
              }, async () => { nextCalled = true })

              console.log(JSON.stringify({ forwarded, nextCalled }))
            })().catch((error) => {
              console.error(error)
              process.exit(1)
            })
            """
        )

        result = subprocess.run(
            ["node", "-e", script],
            cwd=KOISHI_DIR,
            text=True,
            capture_output=True,
            check=True,
        )
        data = json.loads(result.stdout)

        self.assertEqual(data["forwarded"], [])
        self.assertTrue(data["nextCalled"])


if __name__ == "__main__":
    unittest.main()
