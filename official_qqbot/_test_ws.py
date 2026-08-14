import asyncio, json, httpx, websockets

APP_ID = "1903707124"
APP_SECRET = "QAvgSE1ocRG6wneWOHA4ytplifdbaZZZ"
BOT_TOKEN = "K9S9YOLZcXiem0kZeWarwTvHbY6Wgodi"


async def test():
    # get access_token
    async with httpx.AsyncClient() as c:
        r = await c.post(
            "https://bots.qq.com/app/getAppAccessToken",
            json={"appId": APP_ID, "clientSecret": APP_SECRET},
        )
        access_token = r.json()["access_token"]
    print(f"access_token: {access_token[:20]}...")

    # test both production and sandbox gateways
    endpoints = [
        ("production", "https://api.sgroup.qq.com"),
        ("sandbox", "https://sandbox.api.sgroup.qq.com"),
    ]

    for env_name, base in endpoints:
        print(f"\n=== {env_name} ===")
        try:
            async with httpx.AsyncClient() as c:
                r = await c.get(
                    f"{base}/gateway",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if r.status_code != 200:
                    print(f"  gateway failed: {r.status_code} {r.text[:100]}")
                    continue
                url = r.json().get("url", "")
                if not url:
                    print(f"  gateway empty url: {r.text[:100]}")
                    continue
            print(f"  gateway: {url}")
        except Exception as e:
            print(f"  gateway error: {e}")
            continue

        # token formats to test
        tokens = [
            ("QQBotToken", f"QQBotToken {APP_ID}.{access_token}"),
            ("Bot+access", f"Bot {APP_ID}.{access_token}"),
            ("Bot+static", f"Bot {APP_ID}.{BOT_TOKEN}"),
        ]

        # intent combos
        intent_combos = [
            ("1<<25", 1 << 25),
            ("0", 0),
            ("1<<0|1<<25", (1 << 0) | (1 << 25)),
        ]

        for tlabel, tok in tokens:
            for ilabel, intents in intent_combos:
                try:
                    async with websockets.connect(url, open_timeout=10) as ws:
                        hello = json.loads(await asyncio.wait_for(ws.recv(), 5))

                        # try with and without shard
                        payload = {
                            "op": 2,
                            "d": {"token": tok, "intents": intents, "shard": [0, 1]},
                        }
                        await ws.send(json.dumps(payload))

                        resp = json.loads(await asyncio.wait_for(ws.recv(), 5))
                        op = resp.get("op")
                        t = resp.get("t")
                        d = resp.get("d")
                        if op == 0 and t == "READY":
                            print(
                                f"  [{tlabel} | {ilabel}] SUCCESS! user={d.get('user', {})}"
                            )
                            return
                        else:
                            print(f"  [{tlabel} | {ilabel}] op={op} d={d}")
                except Exception as e:
                    print(f"  [{tlabel} | {ilabel}] error: {e}")

    # also try without shard at all
    print("\n=== no shard test ===")
    async with httpx.AsyncClient() as c:
        r = await c.get(
            "https://api.sgroup.qq.com/gateway",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        url = r.json()["url"]
    try:
        async with websockets.connect(url, open_timeout=10) as ws:
            hello = json.loads(await asyncio.wait_for(ws.recv(), 5))
            payload = {
                "op": 2,
                "d": {
                    "token": f"QQBotToken {APP_ID}.{access_token}",
                    "intents": (1 << 25),
                },
            }
            await ws.send(json.dumps(payload))
            resp = json.loads(await asyncio.wait_for(ws.recv(), 5))
            print(
                f"  no-shard: op={resp.get('op')} d={resp.get('d')} t={resp.get('t')}"
            )
    except Exception as e:
        print(f"  no-shard error: {e}")


asyncio.run(test())
