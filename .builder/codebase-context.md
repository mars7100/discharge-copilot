# Mockup context
React 19 + TypeScript + Vite 7. Existing UI is src/App.tsx, mounted by src/main.tsx.
User approved two interactive mockups with simulated events, not real backend mutations.
Build a dev-only ?mockup=canvas|board branch; preserve normal App.
No new dependencies. Modern SaaS visual style: warm gray background, white panels,
dark ink text, indigo accent, mint completed states. Native CSS/SVG for visual work.
Each variant owns its TSX and CSS files. Shared shell, workflow and review are integration work.
Existing unrelated user modifications: core/load_graph.py and tests/test_ticket12_routing.py.
Validation: npm run build, focused mockup checks, browser desktop/mobile evidence.
