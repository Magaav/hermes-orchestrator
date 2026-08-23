const assert = require("assert");
const { EventEmitter } = require("events");
const { createFullPowerExecutor, invocation, normalizedTimeout } = require("./full-power-executor");

function fakeChild({ code = 0, stdout = "", stderr = "" } = {}) {
  const child = new EventEmitter();
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.kill = () => child.emit("close", null, "SIGTERM");
  queueMicrotask(() => {
    if (stdout) child.stdout.emit("data", Buffer.from(stdout));
    if (stderr) child.stderr.emit("data", Buffer.from(stderr));
    child.emit("close", code, null);
  });
  return child;
}

assert.deepStrictEqual(invocation({ command: "Get-Process", shell: "powershell" }, "win32"), {
  file: "powershell.exe",
  args: ["-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", "Get-Process"],
  shell: "powershell",
});
assert.deepStrictEqual(invocation({ command: "whoami", shell: "cmd" }, "win32"), { file: "cmd.exe", args: ["/d", "/s", "/c", "whoami"], shell: "cmd" });
assert.throws(() => invocation({ command: "" }, "win32"), /full_power_command_missing/);
assert.strictEqual(normalizedTimeout(999999), 240000);

(async () => {
  const calls = [];
  let clock = 100;
  const executor = createFullPowerExecutor({
    platform: "win32",
    baseEnv: { BASE: "1" },
    now: () => (clock += 5),
    spawn: (file, args, options) => {
      calls.push({ file, args, options });
      return fakeChild({ stdout: "hello\n", stderr: "warning\n" });
    },
  });
  const result = await executor.execute({ command: "Write-Output hello", cwd: "C:\\work", environment: { TOKEN: 7 } }, "cmd-1");
  assert.strictEqual(result.ok, true);
  assert.strictEqual(result.command_id, "cmd-1");
  assert.strictEqual(result.stdout, "hello\n");
  assert.strictEqual(result.stderr, "warning\n");
  assert.strictEqual(result.inherited_process_token, true);
  assert.strictEqual(calls[0].options.cwd, "C:\\work");
  assert.deepStrictEqual(calls[0].options.env, { BASE: "1", TOKEN: "7" });
  console.log("full power executor tests passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
