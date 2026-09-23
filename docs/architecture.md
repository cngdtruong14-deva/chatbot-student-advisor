# Kiến trúc

```text
Browser -> Nginx/frontend -> FastAPI API -> PostgreSQL
                                      -> approved artifacts (bên ngoài repo)
```

Frontend React/Vite giao tiếp với FastAPI. API dùng SQLAlchemy/Alembic cho PostgreSQL và gói `packages/advisor_core/` cho logic dùng chung. Migration là job một lần trong Compose. Mạng database được tách khỏi edge network trong cấu hình local.

Model và corpus production không được nhúng vào source export.
