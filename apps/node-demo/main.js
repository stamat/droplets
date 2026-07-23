// Node backend for the node-demo droplet.
//
// The runner spawned this as a child process because the droplet's `executable`
// resolved to main.js (no main.py). We speak the droplet stdio protocol:
//   host  -> child : {"method": <name>, "args": {...}}   (one JSON per line)
//   child -> host  : {"result": <any>} | {"error": <str>}
// stdout carries replies ONLY -- diagnostics go to stderr (drained to the host log).

const methods = {
  // Proves the backend really is Node: returns the interpreter version.
  node_info: () => `Node ${process.version} (pid ${process.pid})`,

  // Shows args in / value out.
  reverse: ({ text = "" }) => String(text).split("").reverse().join(""),

  // Shows the {error} path: throwing here reaches droplets.recieve({error}).
  boom: () => {
    throw new Error("intentional failure from main.js");
  },
};

require("readline")
  .createInterface({ input: process.stdin })
  .on("line", (line) => {
    let reply;
    try {
      const { method, args } = JSON.parse(line);
      const fn = methods[method];
      if (!fn) {
        reply = { error: `no such method: ${method}` };
      } else {
        process.stderr.write(`node-demo: handling ${method}\n`); // stderr = safe
        reply = { result: fn(args || {}) };
      }
    } catch (e) {
      reply = { error: String(e && e.message ? e.message : e) };
    }
    process.stdout.write(JSON.stringify(reply) + "\n");
  });
