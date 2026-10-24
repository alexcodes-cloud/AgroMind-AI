import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const viteEntry = fileURLToPath(new URL("../node_modules/vite/bin/vite.js", import.meta.url));
const viteArgs = process.argv.slice(2);
let child;
let restartTimer;
let stopping = false;
let restartCount = 0;

function stop() {
  stopping = true;
  if (restartTimer) clearTimeout(restartTimer);
  if (child && !child.killed) child.kill();
}

process.on("SIGINT", stop);
process.on("SIGTERM", stop);

function startVite() {
  child = spawn(process.execPath, [viteEntry, ...viteArgs], {
    cwd: process.cwd(),
    env: process.env,
    stdio: "inherit",
  });

  child.once("error", (error) => {
    console.error(`[dev-supervisor] Vite process error: ${error.message}`);
  });

  child.once("exit", (code, signal) => {
    if (stopping) {
      process.exit(code ?? 0);
    }
    const delay = Math.min(1000 * 2 ** restartCount, 5000);
    restartCount += 1;
    console.error(
      `[dev-supervisor] Vite stopped (code=${code ?? "none"}, signal=${signal ?? "none"}); restarting in ${delay}ms...`,
    );
    restartTimer = setTimeout(startVite, delay);
  });
}

startVite();
