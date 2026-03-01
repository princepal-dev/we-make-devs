# ISL Voice — Mobile App Integration

**All API calls use the `/api` prefix.** Base URL has no trailing slash.

## Base URL (hardcoded)

```
https://we-make-devs.onrender.com
```

## Endpoints (all use /api/ prefix)

| Purpose    | Method | URL |
|------------|--------|-----|
| Health     | GET    | `{BASE_URL}/api/health` |
| Config     | GET    | `{BASE_URL}/api/config` |
| Auth token | POST   | `{BASE_URL}/api/auth/token` |
| Auth token | GET    | `{BASE_URL}/api/auth/token?user_id=xxx&user_name=yyy` |
| Sessions   | POST   | `{BASE_URL}/api/sessions` |
| Sessions   | DELETE | `{BASE_URL}/api/sessions/{id}` |

## Flow

1. **App launch** → `GET /api/config` → returns `{ stream_api_key, base_url, api_prefix }`
2. **User enters name** → create `user_id` (e.g. `user-${slugify(name)}-${Date.now()}`)
3. **Get token** → `POST /api/auth/token` with `{ user_id, user_name }`
4. **Init Stream client** → use `stream_api_key` and `token` from responses
5. **Join call** → create `call_id`, **await** `call.join()` (user must be in call first)
6. **Start agent** → `POST /api/sessions` with `{ call_type: "default", call_id }` — only after step 5 completes
