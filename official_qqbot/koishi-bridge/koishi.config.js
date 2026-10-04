const path = require('path')
const { webcrypto } = require('node:crypto')

if (!globalThis.crypto) {
  globalThis.crypto = webcrypto
}

const appId = process.env.QQ_APP_ID
const appSecret = process.env.QQ_APP_SECRET

if (!appId || !appSecret) {
  throw new Error('QQ_APP_ID and QQ_APP_SECRET are required')
}

const whitelist = (process.env.QQ_GROUP_WHITELIST || '')
  .split(',')
  .map((item) => item.trim())
  .filter(Boolean)

module.exports = {
  host: process.env.KOISHI_HOST || '0.0.0.0',
  port: Number(process.env.KOISHI_PORT || 5140),
  plugins: {
    'database-sqlite': {
      path: process.env.KOISHI_DB_PATH || 'data/koishi.db',
    },
    'adapter-qq-crack': {
      id: appId,
      secret: appSecret,
      type: process.env.QQ_BOT_TYPE || 'public',
      protocol: process.env.QQ_ADAPTER_PROTOCOL || 'websocket',
      path: process.env.QQ_WEBHOOK_PATH || '/qq',
      endpoint: process.env.QQ_API_ENDPOINT || 'https://api.sgroup.qq.com/',
      intents: Number(process.env.QQ_INTENTS || 33554432),
      loggerinfo: process.env.QQ_ADAPTER_DEBUG === '1',
    },
    [path.resolve(__dirname, 'plugins/python-bridge')]: {
      endpoint: process.env.PY_BRIDGE_ENDPOINT || 'http://127.0.0.1:8765/koishi/message',
      token: process.env.PY_BRIDGE_TOKEN || 'miracle-koishi-bridge',
      whitelist,
      qqWebhookPath: process.env.QQ_WEBHOOK_PATH || '/qq',
      qqAppId: appId,
      qqAppSecret: appSecret,
    },
  },
}
