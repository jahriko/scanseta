import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import { chromium } from "playwright";

const root = fileURLToPath(new URL("../", import.meta.url));
const output = new URL("../verification/", import.meta.url);
const origin = "http://127.0.0.1:4187";
const api = "http://127.0.0.1:49999";
const cases = [
  ["RX000005.jpg", ["Amlodipine"], "5 mg"],
  ["RX002290.jpg", ["Atorvastatin"], "40 mg"],
  ["RX002335.jpg", ["Metronidazole", "Ciprofloxacin", "Unclear medication (review needed)"], "500 mg/tablet"],
  ["RX002336.jpg", ["Paracetamol (Biogesic)"], "500 mg/tablet"],
  ["RX002340.jpg", ["Salbutamol syrup", "Salinase nasal spray"], "uncertain"],
  ["RX002347.jpg", ["Salbutamol nebulizer"], "Every 12 hours"],
  ["RX002359.jpg", ["Amoxicillin"], "500 mg"],
  ["RX002364.png", ["Cefalexin"], "500 mg/capsule"],
];
const report = [];
let browser;
let serverLog = "";
const server = spawn(process.execPath, ["node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", "4187", "--strictPort"], {
  cwd: root,
  env: { ...process.env, VITE_DEMO_MODE: "true", VITE_API_BASE_URL: api },
  stdio: ["ignore", "pipe", "pipe"],
});
server.stdout.on("data", (chunk) => { serverLog += chunk; });
server.stderr.on("data", (chunk) => { serverLog += chunk; });

const pass = (message) => { report.push(message); console.log(`PASS ${message}`); };

try {
  await mkdir(output, { recursive: true });
  let ready = false;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (server.exitCode !== null) throw new Error(`Vite failed: ${serverLog}`);
    try {
      ready = (await fetch(origin)).ok;
      if (ready) break;
    } catch { /* Server is still starting. */ }
    await delay(100);
  }
  assert(ready, `Vite did not start: ${serverLog}`);
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1365, height: 1000 }, reducedMotion: "reduce" });
  const page = await context.newPage();
  const requests = [];
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (request.url().startsWith(api)) requests.push(`${request.method()} ${new URL(request.url()).pathname}`);
  });
  await page.route(`${api}/**`, async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    const body = pathname === "/health"
      ? { message: "Test backend", status: "ok", model_loaded: false }
      : pathname === "/load-model"
        ? { success: true, message: "Test model loaded", base_model: "test", adapter_repo: "test" }
        : { success: true, processing_time: 0.01, medications: [{ name: "Live test result", confidence: 0 }], can_enrich: false, enrichment_status: "not_requested" };
    await route.fulfill({ json: body });
  });

  const open = async () => {
    await page.goto(origin);
    await page.getByRole("button", { name: "Demo mode", exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: "Demo mode", exact: true }).getAttribute("aria-pressed"), "true");
  };
  const sample = (name) => page.getByRole("button", { name: `Scan sample ${name}`, exact: true }).first();
  const result = async (name, medications, detail) => {
    await page.getByRole("heading", { name: "Medication Review", exact: true }).waitFor();
    const text = await page.locator("body").innerText();
    assert(!text.includes("Simulated results for"));
    assert(!text.includes("Model confidence was not measured."));
    assert(text.includes(medications.length === 1 ? "1 medication found" : `${medications.length} medications found`));
    if (name === "RX002335.jpg") {
      assert(text.includes("Check against the image"));
      assert(text.includes("1 needs review"));
    }
    assert(!text.includes("Validation Running"));
    const names = await page.locator("h4").allTextContents();
    assert.deepEqual(names.map((value) => value.toLowerCase()), medications.map((value) => value.toLowerCase()));
    if (detail) assert(text.includes(detail), `Missing detail ${detail}`);
  };

  await open();
  await page.getByRole("heading", { name: "Choose a sample prescription", exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Upload Prescription Image" }).count(), 0);
  assert.equal(await page.getByRole("button", { name: "Capture with Camera" }).count(), 0);
  assert.equal(await page.getByText("Configuration Error", { exact: true }).count(), 0);
  await page.screenshot({ path: fileURLToPath(new URL("gallery.png", output)), fullPage: true });
  for (const [name, medications, detail] of cases) {
    await sample(name).click();
    await page.getByRole("heading", { name: "Replaying Sample Prescription" }).waitFor();
    assert(!(await page.locator("body").innerText()).includes("Analyzing image with AI model"));
    await result(name, medications, detail);
    if (name === "RX002335.jpg") {
      await page.screenshot({ path: fileURLToPath(new URL("results-desktop.png", output)), fullPage: true });
    }
    await page.getByRole("button", { name: "Scan Another Prescription", exact: true }).click();
    pass(`${name}: correct medication results, review notes, simulated label, completed`);
  }
  await sample("RX000005.jpg").click();
  await result("RX000005.jpg", ["Amlodipine"], "5 mg");
  await page.getByRole("button", { name: "Scan Another Prescription", exact: true }).click();
  pass("Repeated scan returns the matching sample without stale results");

  const sampleBytes = await readFile(new URL("../public/demo-prescriptions/RX000005.jpg", import.meta.url));
  await page.locator("#file-upload").setInputFiles({ name: "renamed-prescription.jpg", mimeType: "image/jpeg", buffer: sampleBytes });
  await result("RX000005.jpg", ["Amlodipine"], "5 mg");
  await page.getByRole("button", { name: "Scan Another Prescription", exact: true }).click();
  pass("Renamed sample upload matches by image bytes");

  await page.locator("#file-upload").setInputFiles({ name: "RX000005.jpg", mimeType: "image/jpeg", buffer: Buffer.from("unrelated image data") });
  await page.getByRole("heading", { name: "Scan Failed", exact: true }).waitFor();
  assert((await page.locator("body").innerText()).includes("No prepared result for this image."));
  assert.equal(await page.locator("h4").count(), 0);
  await page.getByRole("button", { name: "Scan Another", exact: true }).first().click();
  pass("Unrelated upload named like a sample is rejected, with no medication results");

  await sample("RX000005.jpg").click();
  await page.getByRole("heading", { name: "Replaying Sample Prescription" }).waitFor();
  await page.getByRole("button", { name: "Scan Another", exact: true }).click();
  await sample("RX002290.jpg").click();
  await result("RX002290.jpg", ["Atorvastatin"], "40 mg");
  await page.getByRole("button", { name: "Scan Another Prescription", exact: true }).click();
  pass("Cancelled scan cannot overwrite the next sample");

  assert.deepEqual(requests, [], "Demo mode must not call the backend");
  pass("Zero health, model, scan or enrichment requests in Demo mode");

  let releaseImage;
  let imageStarted;
  const started = new Promise((resolve) => { imageStarted = resolve; });
  const released = new Promise((resolve) => { releaseImage = resolve; });
  await page.route("**/demo-prescriptions/RX000005.jpg", async (route) => {
    if (route.request().resourceType() !== "fetch") return route.continue();
    imageStarted();
    await released;
    await route.continue();
  });
  await sample("RX000005.jpg").click();
  await started;
  await page.getByRole("button", { name: "Live mode", exact: true }).click();
  await page.getByText("Model Not Loaded", { exact: true }).waitFor();
  releaseImage();
  await page.waitForLoadState("networkidle");
  assert.equal(await page.getByRole("heading", { name: "Replaying Sample Prescription" }).count(), 0);
  assert.equal(await page.getByRole("heading", { name: "Analyzing Prescription" }).count(), 0);
  await page.unroute("**/demo-prescriptions/RX000005.jpg");
  pass("Switching modes during image loading cancels the old selection");

  await Promise.all([
    page.waitForResponse((response) => response.url().includes("/load-model") && response.ok()),
    page.getByRole("button", { name: "Load Model", exact: true }).click(),
  ]);
  await sample("RX002290.jpg").click();
  await page.getByRole("heading", { name: "Live Test Result", exact: true }).waitFor();
  assert.equal(await page.getByText(/medications? found/).count(), 1);
  assert(requests.includes("GET /health"));
  assert(requests.includes("POST /load-model"));
  assert(requests.includes("POST /scan"));
  pass("Live mode reaches health, model loading and scan API with test responses");

  const requestCount = requests.length;
  await page.getByRole("button", { name: "Demo mode", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await sample("RX002336.jpg").click();
  await result("RX002336.jpg", ["Paracetamol (Biogesic)"], "500 mg/tablet");
  assert.equal(requests.length, requestCount);
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: fileURLToPath(new URL("results-mobile.png", output)), fullPage: true });
  pass("Returning to Demo mode works on mobile without backend requests or horizontal overflow");
  assert.deepEqual(errors, []);
  pass("No browser JavaScript errors");
  await writeFile(new URL("report.json", output), JSON.stringify({ checks: report, liveTestRequests: requests, errors }, null, 2) + "\n");
  console.log(`${report.length} checks passed. Screenshots and report saved in verification/.`);
} finally {
  await browser?.close();
  server.kill("SIGTERM");
}
