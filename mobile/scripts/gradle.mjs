// Runs the Android Gradle wrapper with the given task(s), on Windows, macOS or Linux.
import { spawnSync } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const androidDir = fileURLToPath(new URL("../android", import.meta.url));
const win = process.platform === "win32";
const res = spawnSync(`"${join(androidDir, win ? "gradlew.bat" : "gradlew")}"`, process.argv.slice(2), {
  cwd: androidDir,
  stdio: "inherit",
  shell: true,
});
process.exit(res.status ?? 1);
