let input = "";

process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => {
  input += chunk;
});

process.stdin.on("end", () => {
  const event = JSON.parse(input || "{}");
  const content = String(event.content || "");
  const text = content.replace(/^\/echo\s*/i, "").trim();
  process.stdout.write(
    JSON.stringify({
      handled: true,
      reply: text ? `Node 插件收到：${text}` : "请发送 /echo 内容",
    })
  );
});

