// api.js -- all calls to the FastAPI backend live here.
// During dev, Vite proxies "/api" to http://localhost:8000 (see vite.config.js).

// Safely parse a response: read the body as text first, then JSON.parse it.
// This turns an empty/non-JSON body (e.g. backend down) into a CLEAR error
// instead of the cryptic "Unexpected end of JSON input".
async function parseJson(res) {
  const text = await res.text();
  if (!text) {
    throw new Error(
      "Empty response from server. Is the backend running on http://localhost:8000?"
    );
  }
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`Server returned non-JSON response: ${text.slice(0, 120)}`);
  }
}

// Wrap fetch so a refused connection (backend not started) is reported clearly.
async function safeFetch(url, options) {
  try {
    return await fetch(url, options);
  } catch {
    throw new Error(
      "Cannot reach the backend. Start it with: uvicorn app.main:app --port 8000"
    );
  }
}

export async function getStatus() {
  const res = await safeFetch("/api/status");
  if (!res.ok) throw new Error("Status failed");
  return parseJson(res);
}

// Streaming chat via Server-Sent Events parsed manually from a fetch stream.
// Calls onSources(list), onToken(str), onDone(), onError(msg).
export async function streamChat(question, { sourceUrl, onSources, onToken, onDone, onError }) {
  try {
    const res = await safeFetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, source_url: sourceUrl || null }),
    });
    if (!res.ok || !res.body) throw new Error("Stream failed to start (is the backend running?)");

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE events are separated by a blank line.
      const parts = buffer.split("\n\n");
      buffer = parts.pop(); // keep the trailing, possibly-incomplete chunk

      for (const part of parts) {
        const lines = part.split("\n");
        let event = "message";
        let data = "";
        for (const line of lines) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) data += line.slice(5).trim();
        }
        if (!data) continue;
        const parsed = JSON.parse(data);

        if (event === "sources") onSources(parsed);
        else if (event === "token") onToken(parsed);
        else if (event === "done") onDone();
        else if (event === "error") onError(parsed);
      }
    }
    onDone();
  } catch (err) {
    onError(err.message);
  }
}
