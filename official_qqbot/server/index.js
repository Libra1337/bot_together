const { createApp } = require("./app");

const { config, server } = createApp();

server.listen(config.server.port, config.server.host, () => {
  console.log(
    `[panel] listening on http://${config.server.host}:${config.server.port}`
  );
  console.log("[panel] default login is admin / admin123456. Change it in data/panel.json.");
});

