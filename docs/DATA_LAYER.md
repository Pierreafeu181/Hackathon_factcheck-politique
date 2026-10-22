# The data layer in action

**What data.** What politicians say: YouTube captions and press articles read in the browser, or audio (videos without captions, TikTok, Reels, X, radio podcasts) transcribed by Deepgram. What is true: 15 INSEE/DARES employment series frozen from the INSEE API, the full INSEE catalogue queried live by Claude (inflation, debt, GDP…), and web search as a last resort.

**Where it lives.** Aiven PostgreSQL stores every speech, transcript, claim and verification (verdict, official value, sources), which builds a reliability profile per politician. A local cache avoids re-analysing a page; the user's history stays in the browser.

**How it flows.**

```mermaid
flowchart LR
  A[Chrome extension<br/>captions · articles] --> B[Local server<br/>cache · Deepgram]
  B --> C[Claude extracts claims]
  C --> D{Official series?}
  D -- yes --> E[Code compares<br/>with INSEE value]
  D -- no --> F[Claude: live INSEE<br/>or web search]
  E --> G[(Aiven PostgreSQL)]
  F --> G
  G --> H[Verdict + sources<br/>back in the panel]
```

Numbers are compared in code, not by the LLM, whenever an official series exists. Every verdict links to its source.
