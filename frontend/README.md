# Run the Scanseta demo

From this directory, run:

```sh
npm ci
npm run dev
```

Open the address printed by Vite. Demo mode is on by default and needs no backend or AI model. Select a sample prescription to see a short processing simulation and the prepared result for that image.

The eight samples have separate results based on manual image inspection. Unclear handwriting and missing strengths stay marked for review. The results are simulated, patient details are fictional, and no live FDA or PNDF checks run. Confidence is not measured. These sample transcriptions are for demonstration, not clinical use.

You can upload an unchanged copy of a sample, including a renamed copy. Other images show an unsupported-sample message. Camera capture is available in Live mode.

To use live scanning, configure `VITE_API_BASE_URL` in `.env.local`, restart Vite, and select **Live mode**. Set `VITE_DEMO_MODE=false` to start in Live mode. See `.env.example`. Live mode requires the original backend and model.

## Check the demo

```sh
npx playwright install chromium --only-shell
npm run verify:demo
npm run build
npm run typecheck
```

The browser check starts its own temporary Vite server on port 4187. It checks every sample, repeated scans, cancellation, image identity, mobile layout, and the absence of backend requests in Demo mode. It also checks that Live mode sends the original API requests using intercepted test responses. It does not test an actual model.

Screenshots and the check report are saved in `verification/`.
