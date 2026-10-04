const { Schema } = require('koishi')
const crypto = require('node:crypto')

exports.name = 'python-bridge'
exports.inject = ['server']

exports.Config = Schema.object({
  endpoint: Schema.string().default('http://127.0.0.1:8765/koishi/message'),
  token: Schema.string().default(''),
  whitelist: Schema.array(String).default([]),
  qqWebhookPath: Schema.string().default('/qq'),
  qqAppId: Schema.string().default(''),
  qqAppSecret: Schema.string().default(''),
})

exports.apply = (ctx, config) => {
  const logger = ctx.logger('python-bridge')

  if (ctx.server && config.qqWebhookPath && config.qqAppSecret) {
    ctx.server.post(config.qqWebhookPath, async (requestContext) => {
      const payload = requestContext.request.body || {}
      logger.info(`[QQWebhook] op=${payload.op ?? ''} event=${payload.t || ''}`)

      const appId = config.qqAppId || process.env.QQ_APP_ID || ''
      if (appId && requestContext.get('X-Bot-Appid') !== appId) {
        logger.warn('[QQWebhook] rejected request with mismatched X-Bot-Appid')
        requestContext.status = 403
        return
      }

      if (payload.op === 13) {
        requestContext.status = 200
        requestContext.body = {
          plain_token: payload.d?.plain_token || '',
          signature: signWebhookVerification(
            config.qqAppSecret,
            payload.d?.event_ts || '',
            payload.d?.plain_token || '',
          ),
        }
        return
      }

      if (payload.op === 0) {
        if (!verifyWebhookDispatch(config.qqAppSecret, requestContext)) {
          logger.warn(`[QQWebhook] rejected unsigned event=${payload.t || ''}`)
          requestContext.status = 403
          return
        }

        const bridgePayload = adaptOfficialWebhookPayload(payload, config.whitelist)
        if (bridgePayload) {
          logger.info(
            `[QQWebhook] forwarding event=${payload.t || ''} group=${bridgePayload.group_openid || ''} msg=${bridgePayload.msg_id || ''}`,
          )
          await sendToPythonBridge(config, logger, bridgePayload)
        } else {
          logger.info(`[QQWebhook] ignored event=${payload.t || ''}`)
        }
      }

      requestContext.status = 200
      requestContext.body = {
        d: {},
        op: 12,
      }
    })
  }

  ctx.middleware(async (session, next) => {
    if (!session.content) return next()
    if (session.userId && session.selfId && session.userId === session.selfId) return next()

    const eventType = session.qq?.t || ''
    if (session.qq?.d?.author?.bot) return next()
    const rawContent = String(session.content || '')
    const content = stripLeadingMention(rawContent)
    const groupId = firstNonEmpty(
      session.qq?.d?.group_openid,
      session.event?.guild?.id,
      session.guildId,
      session.channelId,
    )
    const isAt = hasSelfMention(session) || eventType === 'GROUP_AT_MESSAGE_CREATE'
    const isDirect = Boolean(session.isDirect || !groupId)

    if (!isDirect && !isAt && config.whitelist.length && !config.whitelist.includes(groupId)) {
      return next()
    }

    const payload = {
      type: isDirect ? 'c2c' : 'group',
      group_openid: isDirect ? '' : groupId,
      user_openid: firstNonEmpty(
        session.qq?.d?.author?.member_openid,
        session.qq?.d?.author?.user_openid,
        session.userId,
      ),
      limit_user_id: firstNonEmpty(
        session.qq?.d?.author?.user_openid,
        session.qq?.d?.author?.union_openid,
        session.qq?.d?.author?.union_user_account,
        session.userId,
        session.qq?.d?.author?.member_openid,
      ),
      msg_id: firstNonEmpty(session.qq?.d?.id, session.messageId, `${Date.now()}-${session.userId || 'unknown'}`),
      content,
      raw_content: rawContent,
      is_at: isAt,
      event_type: eventType,
      source: 'koishi-adapter-qq-crack',
    }

    await sendToPythonBridge(config, logger, payload)
  })
}

async function sendToPythonBridge(config, logger, payload) {
  const headers = { 'content-type': 'application/json' }
  if (config.token) headers['x-bridge-token'] = config.token

  try {
    const response = await fetch(config.endpoint, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
    })
    if (!response.ok) {
      const body = await response.text()
      logger.warn(`Python bridge returned ${response.status}: ${body.slice(0, 200)}`)
    }
  } catch (error) {
    logger.warn(`Python bridge request failed: ${error.message}`)
  }
}

function signWebhookVerification(secret, eventTs, plainToken) {
  return crypto
    .sign(null, Buffer.from(`${eventTs}${plainToken}`), createEd25519PrivateKey(secret))
    .toString('hex')
}

function verifyWebhookDispatch(secret, requestContext) {
  const signature = requestContext.get('X-Signature-Ed25519')
  const timestamp = requestContext.get('X-Signature-Timestamp')
  if (!signature || !timestamp) return false

  const rawBody = requestContext.request.body?.[Symbol.for('unparsedBody')]
  const body = Buffer.isBuffer(rawBody) ? rawBody.toString() : String(rawBody || '')
  const publicKey = crypto.createPublicKey(createEd25519PrivateKey(secret))

  return crypto.verify(
    null,
    Buffer.from(`${timestamp}${body}`),
    publicKey,
    Buffer.from(signature, 'hex'),
  )
}

function createEd25519PrivateKey(secret) {
  const pkcs8Prefix = Buffer.from('302e020100300506032b657004220420', 'hex')
  return crypto.createPrivateKey({
    key: Buffer.concat([pkcs8Prefix, privateSeed(secret)]),
    format: 'der',
    type: 'pkcs8',
  })
}

function privateSeed(secret) {
  let seed = String(secret || '')
  while (seed.length < 32) seed += seed
  return Buffer.from(seed).subarray(0, 32)
}

function adaptOfficialWebhookPayload(payload, whitelist) {
  const eventType = String(payload.t || '')
  const data = payload.d || {}
  if (data.author?.bot) return null
  const rawContent = String(data.content || '').trim()

  if (eventType === 'C2C_MESSAGE_CREATE') {
    return {
      type: 'c2c',
      group_openid: '',
      user_openid: data.author?.user_openid || '',
      msg_id: data.id || '',
      content: rawContent,
      raw_content: rawContent,
      event_type: eventType,
      source: 'qq-webhook-fallback',
    }
  }

  if (eventType === 'GROUP_MESSAGE_CREATE' || eventType === 'GROUP_AT_MESSAGE_CREATE') {
    const groupId = data.group_openid || ''
    if (eventType === 'GROUP_MESSAGE_CREATE' && whitelist.length && !whitelist.includes(groupId)) {
      return null
    }

    return {
      type: 'group',
      group_openid: groupId,
      user_openid: data.author?.member_openid || '',
      limit_user_id:
        data.author?.user_openid ||
        data.author?.union_openid ||
        data.author?.union_user_account ||
        data.author?.member_openid ||
        '',
      msg_id: data.id || '',
      content: rawContent,
      raw_content: rawContent,
      is_at: eventType === 'GROUP_AT_MESSAGE_CREATE',
      event_type: eventType,
      source: 'qq-webhook-fallback',
    }
  }

  return null
}

function hasSelfMention(session) {
  return Boolean(
    session.elements?.some((element) => {
      return element.type === 'at' && String(element.attrs?.id || '') === String(session.selfId || '')
    })
  )
}

function firstNonEmpty(...values) {
  for (const value of values) {
    if (value === undefined || value === null) continue
    const text = String(value).trim()
    if (text) return text
  }
  return ''
}

function stripLeadingMention(content) {
  return String(content || '')
    .replace(/^(?:\s*(?:<at\b[^>]*\/>|<@!?[^>\s]+>|@\S+)\s*)+/, '')
    .trim()
}
