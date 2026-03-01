# ISL Voice — Mobile App Integration Guide

Use this guide to integrate the ISL Voice backend into your mobile app. **No user configuration required** — base URL and API key are fetched from the backend.

---

## Base URL (hardcoded)

```
https://we-make-devs.onrender.com
```

Do **not** ask the user for API URL or base URL. Use this URL for all API calls.

---

## Step 1: Fetch config on app launch

Before anything else, fetch the public config to get the Stream API key:

```
GET https://we-make-devs.onrender.com/config
```

**Response:**
```json
{
  "stream_api_key": "YOUR_STREAM_API_KEY",
  "base_url": "https://we-make-devs.onrender.com"
}
```

Store `stream_api_key` and `base_url` in your app state. Use them for Stream Video SDK initialization and API calls.

---

## Step 2: User enters name → Get auth token

When the user enters their name and taps "Join" / "Start":

1. **Create a user_id** — use a sanitized version of the name, e.g. `user-${slugify(name)}-${Date.now()}` or a UUID. Must be non-empty and unique per session.

2. **Request a Stream token** — call the auth endpoint:

```
POST https://we-make-devs.onrender.com/auth/token
Content-Type: application/json

{
  "user_id": "user-john-1234567890",
  "user_name": "John"
}
```

**Response:**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "user_id": "user-john-1234567890",
  "user_name": "John"
}
```

**Important:** `user_id` is required. Use the name (sanitized) or a generated ID. The token is used by the Stream Video SDK.

---

## Step 3: Initialize Stream Video client

```typescript
import { StreamVideoClient, User } from "@stream-io/video-react-native-sdk";

const user: User = {
  id: authResponse.user_id,
  name: authResponse.user_name || authResponse.user_id,
};

const client = StreamVideoClient.getOrCreateInstance({
  apiKey: config.stream_api_key,
  user,
  token: authResponse.token,
  // Optional: refresh token when it expires
  tokenProvider: async () => {
    const res = await fetch(
      `https://we-make-devs.onrender.com/auth/token?user_id=${encodeURIComponent(user.id)}&user_name=${encodeURIComponent(user.name || "")}`,
      { method: "GET" }
    );
    const data = await res.json();
    return data.token;
  },
});
```

---

## Step 4: Create/join call and start the agent

1. **Generate a unique call_id** — e.g. `call-${user.id}-${Date.now()}` or a UUID.

2. **Create or join the Stream Video call** using your Stream Video SDK:
   - `call_type`: `"default"`
   - `call_id`: the unique ID from step 1

3. **Tell the backend to join** — so the ISL Voice agent joins the same call:

```
POST https://we-make-devs.onrender.com/sessions
Content-Type: application/json

{
  "call_type": "default",
  "call_id": "call-user-john-1234567890-1234567890"
}
```

Use the **same** `call_type` and `call_id` as the Stream call. The backend agent will join and start processing sign language from the user's camera.

---

## Step 5: End session

When the user leaves the call, optionally end the session:

```
DELETE https://we-make-devs.onrender.com/sessions/{session_id}
```

(The session_id is returned from `POST /sessions` if you need it.)

---

## API endpoints summary

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/config` | Get Stream API key and base URL (no auth) |
| GET | `/health` | Health check |
| POST | `/auth/token` | Get Stream token (body: `user_id`, `user_name`) |
| GET | `/auth/token?user_id=xxx&user_name=yyy` | Get Stream token (query params) |
| POST | `/sessions` | Start agent session (body: `call_type`, `call_id`) |
| DELETE | `/sessions/{id}` | End session |

---

## Common auth errors and fixes

| Error | Cause | Fix |
|-------|-------|-----|
| 404 Not Found | Wrong URL or path | Use `https://we-make-devs.onrender.com` (no trailing slash) and paths `/auth/token`, `/sessions` |
| 400 user_id required | Empty or missing user_id | Always send `user_id` in body or query. Derive from the name: e.g. `user-${slugify(name)}-${timestamp}` |
| Auth error when joining call | Token not passed to Stream client, or wrong apiKey | Ensure you use `stream_api_key` from `/config` and `token` from `/auth/token` when creating `StreamVideoClient` |
| CORS error | Backend allows all origins | Backend has CORS enabled for `*`. If you still see CORS, the request may be going to the wrong URL. |

---

## Flow checklist

1. [ ] Fetch `GET /config` on app launch
2. [ ] User enters name
3. [ ] Create `user_id` (e.g. from name + timestamp)
4. [ ] Call `POST /auth/token` with `{ user_id, user_name }`
5. [ ] Create `StreamVideoClient` with `apiKey`, `user`, `token` from config and auth response
6. [ ] Generate unique `call_id`
7. [ ] Join Stream call with `call_type: "default"`, `call_id`
8. [ ] Call `POST /sessions` with same `call_type` and `call_id`
9. [ ] User signs → agent speaks
