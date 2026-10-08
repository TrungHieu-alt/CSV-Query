# Separate Data Studio landing page

Open `http://localhost:8080/landing/` with the existing frontend server running.
The original app remains at `/` and `/index.html`. All landing code, styles,
and fonts live in `frontend/landing/`; the app files and backend are unchanged
by this addition.

## Design and interaction

The product-led layouts of [Rows AI](https://rows.com/ai) and
[Julius](https://julius.ai/) informed the headline, prominent call to action,
and product preview. The copy, layout, and illustrative chart are original.
The cream and green palette matches the existing studio.

Scroll down or click **Open Data Studio** to enter. Once the landing content
has scrolled into view, scroll progress fades the page out, moves it up by
72 pixels, and applies up to 3.5 pixels of blur. The existing app fades in
behind it. At the end, navigation hands over to `/index.html`, where the
original app runs normally. Scrolling upward reverses the effect before
the handoff.

The app preview loads only when entering the transition. It is inert during
the animation. Browser Back resets the landing to the top. Reduced-motion
users enter directly from the button; without JavaScript the button remains
a normal app link. A delayed preview cannot prevent navigation indefinitely.

The page includes a chart/table sample toggle, a walkthrough, and a FAQ.
Sample values are explicitly illustrative. Fonts are served locally;
their OFL licenses are included in `frontend/landing/fonts/`.

## Verification

Run from the repository root:

```powershell
.venv/Scripts/python.exe -B tests/ui_landing_smoke.py
```

All nine Chrome check groups passed on October 8, 2026:

- Desktop layout without horizontal overflow.
- Sample toggle, walkthrough, FAQ, and dialog dismissal.
- Scroll fade, upward motion, blur, and reverse scrolling.
- Button handoff to the standalone app, followed by a CSV upload and query.
- Browser Back without a redirect loop.
- Mobile layout and entry into the functioning app.
- Reduced-motion behavior.
- Navigation with JavaScript disabled.
- No JavaScript exceptions in the desktop flow.

The suite uses a deterministic LLM fixture with the real backend and pandas
execution. Earlier full-flow and live Gemini checks are documented in
`docs/FULL_FLOW_TEST_REPORT.md`.

Screenshots and results from the latest run are in
`C:\Users\manhh\AppData\Local\Temp\studio-landing-ui-rnxt_nhi`.
Temporary browser artifacts are not committed.
