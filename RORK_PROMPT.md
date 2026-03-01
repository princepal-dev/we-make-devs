# ISL Voice — Final Rork Integration Prompt

**This is the final integration prompt. Copy the entire block below into Rork to sync the mobile app with the ISL Voice backend.**

---

## Copy from here ▼

```
Integrate the ISL Voice backend API into the mobile app. Sync every API call with the backend. Do not ask the user for base URL or configuration — hardcode or fetch from the API.

### Constants

const BASE_URL = "https://we-make-devs.onrender.com";

Rule: BASE_URL = origin only. No /api, no trailing slash.
✓ BASE_URL = "https://we-make-devs.onrender.com"
✗ BASE_URL = "https://we-make-devs.onrender.com/api"  // causes JSON parse error

URL pattern: BASE_URL + "/api/" + endpoint

### API Reference

| Purpose        | Method | URL                             | Request                              |
|----------------|--------|----------------------------------|--------------------------------------|
| Health check   | GET    | {BASE_URL}/api/health            | —                                     |
| Config         | GET    | {BASE_URL}/api/config            | —                                     |
| Auth token     | POST   | {BASE_URL}/api/auth/token        | { user_id: string, user_name?: string } |
| Auth token GET | GET    | {BASE_URL}/api/auth/token?user_id=xxx&user_name=yyy | — |
| Start agent    | POST   | {BASE_URL}/api/sessions          | { call_type: "default", call_id: string } |
| End session    | DELETE | {BASE_URL}/api/sessions/{session_id} | — |

Responses: /api/health → { status: "ok" }; /api/config → { stream_api_key, base_url, api_prefix }; /api/auth/token → { token, user_id, user_name }; POST /api/sessions → session info with session_id.

### CRITICAL FLOW — Follow this exact order

1. App launch: GET {BASE_URL}/api/config. Store stream_api_key, base_url.

2. User enters name, taps Join:
   - Create user_id: `user-${slugify(name)}-${Date.now()}` or UUID
   - POST {BASE_URL}/api/auth/token with { user_id, user_name: name }
   - Store token, user_id, user_name

3. Initialize Stream Video client:
   - apiKey: config.stream_api_key
   - user: { id: user_id, name: user_name }
   - token: from step 2
   - tokenProvider: async () => { const r = await fetch(`${BASE_URL}/api/auth/token?user_id=${user.id}&user_name=${user.name||""}`); return (await r.json()).token; }

4. Join flow:
   - Generate call_id: `call-${user_id}-${Date.now()}` or UUID
   - Create call: call = client.call("default", call_id)
   - STEP A: POST {BASE_URL}/api/sessions with body { call_type: "default", call_id } — backend creates the call
   - STEP B: await call.join() — join the Stream Video call. Wait until fully joined.
   - Store session_id from response for DELETE on leave.

5. User signs; agent speaks. On leave: optional DELETE {BASE_URL}/api/sessions/{session_id}.

### Order (per Stream API docs)

The backend creates the call when you POST /sessions. Then you join that call. Flow:
  A) POST /sessions first (creates the call on Stream)
  B) call.join() with the SAME call_id (joins the existing call)

Use the exact same call_id for POST /sessions and call.join().

### Token fetch example

const getToken = async (userId, userName) => {
  const r = await fetch(`${BASE_URL}/api/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, user_name: userName }),
  });
  if (!r.ok) throw new Error("Auth failed");
  return (await r.json()).token;
};

### Error handling

- 404: Wrong URL. Ensure BASE_URL has no trailing slash, path starts with /api/
- 400 "user_id required": Send non-empty user_id
- 500: Backend config issue
- JSON parse error: Do not call / or parse HTML; use /api/health or /api/config for JSON

### Do not

- Put /api in BASE_URL
- Use BASE_URL + "/health" (missing /api)
- Use different call_ids for POST /sessions and call.join()
```

---

## Copy to here ▲
