# Gemini relevance screen

- Last run: 2026-11-02T18:17:55+00:00
- Model: none this run
- Prompt hash: 60436d22a4df
- Screened: 0 of 4808 candidates; yes 0, no 0
- Unscreened posts count as relevant.
- Queue groups: 1 (second term, relevant) 2770; 2 (earlier, relevant) 2038; 3 (not relevant) 0
- Double-labeled: 961
- Stopped early: HTTP 400: {
  "error": {
    "code": 400,
    "message": "API key not valid. Please pass a valid API key.",
    "status": "INVALID_ARGUMENT",
    "details": [
      {
        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
        "reason": "API_KEY_INVALID",
        "domain": "googleapis.com",
        "

The screen sets queue order only, never a label. The model's knowledge cutoff postdates the posts; that cannot leak into training targets because humans make every label.
