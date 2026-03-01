# ISL Voice — Final Rork Integration Prompt

**Copy the entire block below into Rork to fully sync the mobile app with the ISL Voice backend API.**

---

## Prompt (copy from here)

Integrate the ISL Voice backend API into the mobile app. Sync every API call with the backend. Do not ask the user for base URL or any configuration — everything is hardcoded or fetched from the API.

### Constants

```ts
const BASE_URL = "https://we-make-devs.onrender.com";
```

**Rule:** Base URL = origin ONLY. No `/api`, no trailing slash, no path.

```
✓ BASE_URL = "https://we-make-devs.onrender.com"
✗ BASE_URL = "https://we-make-devs.onrender.com/api"  ← causes JSON parse error (hits /, returns HTML)
```

**URL pattern:** `BASE_URL + "/api/" + endpoint` (e.g. `BASE_URL + "/api/health"`)

### API Reference

| Purpose | Method | URL | Request |
|---------|--------|-----|---------|
| Health check | GET | `{BASE_URL}/api/health` | — |
| Config | GET | `{BASE_URL}/api/config` | — |
| Auth token | POST | `{BASE_URL}/api/auth/token` | `{ user_id: string, user_name?: string }` |
| Auth token (tokenProvider) | GET | `{BASE_URL}/api/auth/token?user_id=xxx&user_name=yyy` | — |
| Start agent | POST | `{BASE_URL}/api/sessions` | `{ call_type: "default", call_id: string }` |
| End session | DELETE | `{BASE_URL}/api/sessions/{session_id}` | — |

**Note:** `/api/token` is an alias for `/api/auth/token` — both work.

### Response shapes

- **GET /api/health** → `{ status: "ok" }`
- **GET /api/config** → `{ stream_api_key: string, base_url: string, api_prefix: "/api" }`
- **POST|GET /api/auth/token** → `{ token: string, user_id: string, user_name: string }`
- **POST /api/sessions** → returns session info (use `session_id` for DELETE if needed)

### Implementation flow

1. **App launch**
   - Call `GET ${BASE_URL}/api/config`
   - Store `stream_api_key` and `base_url` in app state
   - Optional: call `GET ${BASE_URL}/api/health` to verify backend is up

2. **User enters name and taps Join/Start**
   - Create `user_id`: `user-${slugify(name)}-${Date.now()}` or a UUID
   - Call `POST ${BASE_URL}/api/auth/token` with `{ user_id, user_name: name }`
   - Store `token`, `user_id`, `user_name` from the response

3. **Initialize Stream Video client**
   - Use `apiKey: config.stream_api_key` from step 1
   - Use `user: { id: user_id, name: user_name }` from step 2
   - Use `token` from step 2
   - For token refresh (tokenProvider): `GET ${BASE_URL}/api/auth/token?user_id=${user.id}&user_name=${user.name}`

4. **Join call**
   - Generate `call_id`: `call-${user_id}-${Date.now()}` or UUID
   - Join Stream Video call with `call_type: "default"` and `call_id`
   - Immediately call `POST ${BASE_URL}/api/sessions` with `{ call_type: "default", call_id }` — this starts the ISL Voice agent in the same call

5. **User signs → agent speaks**

6. **On leave**
   - Optional: `DELETE ${BASE_URL}/api/sessions/{session_id}` to end the agent session

### Code example (token fetch)

```ts
const getToken = async (userId: string, userName: string) => {
  const res = await fetch(`${BASE_URL}/api/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, user_name: userName }),
  });
  if (!res.ok) throw new Error(`Auth failed: ${res.status}`);
  const data = await res.json();
  return data.token;
};
```

### Code example (tokenProvider for Stream)

```ts
const tokenProvider = async () => {
  const res = await fetch(
    `${BASE_URL}/api/auth/token?user_id=${encodeURIComponent(user.id)}&user_name=${encodeURIComponent(user.name || "")}`,
    { method: "GET" }
  );
  const data = await res.json();
  return data.token;
};
```

### Error handling

- **404** → Wrong URL. Ensure `BASE_URL` has no trailing slash and path starts with `/api/`
- **400 "user_id required"** → Send non-empty `user_id` in auth request
- **500 "Failed to create token"** → Backend config issue; check backend logs
- **JSON parse error** → Do not call `/` or parse HTML; use `/api/health` or `/api/config` for JSON

### Do not

- Include `/api` in BASE_URL — causes JSON parse error (requests hit `/` which returns HTML)
- Use `BASE_URL + "/health"` (missing `/api` in path)
- Ask the user for API URL or Stream API key — fetch from `/api/config`
