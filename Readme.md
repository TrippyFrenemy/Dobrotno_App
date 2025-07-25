# Dobrotno App

Dobrotno App is a web application for small business management built with [FastAPI](https://fastapi.tiangolo.com/). It provides tools for tracking TikTok orders, returns, shifts and payouts, as well as managing cafe cash records. The project includes user authentication with role based permissions, logging of user actions and scheduled background tasks using Celery.

## Features

- **Authentication** – Login via JWT stored in cookies, token refresh and logout.
- **User management** – CRUD operations for users with roles: `admin`, `manager`, `employee` and `coffee`.
- **TikTok module** – Manage orders, returns, shifts and payroll reports.
- **Cafe module** – Manage coffee shops and daily cash records.
- **Logs** – View collected user activity logs (admin only).
- **Scheduled tasks** – Database backups and log cleanup through Celery workers.

## Requirements

- Python 3.11
- PostgreSQL database
- Redis instance

All Python dependencies are listed in `requirements.txt`.

## Getting started

1. **Clone the repository** and install dependencies. Use Python 3.11.
2. Create an `.env` file with the following variables:

```
DB_HOST=<postgres-host>
DB_PORT=<postgres-port>
DB_NAME=<postgres-database>
DB_USER=<postgres-user>
DB_PASS=<postgres-password>
REDIS_HOST=<redis-host>
REDIS_PORT=<redis-port>
SECRET=<jwt-secret>
SECRET_MANAGER=<secret-manager>
TG_BOT_TOKEN=<telegram-token>
TG_CHAT_ID=<telegram-chat-id>
ADMIN_EMAIL=<admin-email>
ADMIN_PASSWORD=<admin-password>
ADMIN_NAME=<admin-name>
ADMIN_ROLE=admin
CSRF_TOKEN_EXPIRY=3600
CELERY_BACHUP_RATE=43200
```

3. **Run database migrations**:

```bash
alembic upgrade head
```

4. **Start the application** using Uvicorn:

```bash
uvicorn src.main:app --reload
```

Alternatively, run with Docker Compose:

```bash
docker-compose up --build
```

This spins up a Redis container, Celery worker and the FastAPI web server.

## API overview

The application is structured into several routers. Most pages render HTML templates, but they can also be accessed programmatically. All routes starting with `/auth`, `/users`, `/orders`, `/returns`, `/shifts`, `/reports`, `/cafe` and `/logs` are included under the main FastAPI app.

### Authentication

| Method & Path | Description |
|--------------|------------|
| `GET /auth/login` | Login page. |
| `POST /auth/login` | Authenticate user and set JWT cookies. |
| `POST /auth/refresh` | Refresh the access token using the refresh cookie. |
| `GET /auth/me` | Return information about the current user. |
| `GET /auth/logout` | Remove cookies and redirect to login page. |

### Users

Requires `admin` role unless noted otherwise.

| Method & Path | Description |
|--------------|------------|
| `GET /users/create` | Show user creation form. |
| `POST /users/create` | Create a new user. |
| `GET /users/me` | View personal account page (any logged-in user). |
| `GET /users/{id}/edit` | Edit user details. |
| `POST /users/{id}/edit` | Save updated user information. |
| `POST /users/{id}/delete` | Delete a user. |

### TikTok orders

| Method & Path | Description |
|--------------|------------|
| `GET /orders/create` | Show order creation form. |
| `POST /orders/create` | Create a new order. |
| `GET /orders/all/list` | List all orders (admin). |
| `GET /orders/{user_id}/list` | List orders created by a specific user. |
| `GET /orders/{order_id}/edit` | Edit an order. |
| `POST /orders/{order_id}/edit` | Save order changes. |
| `POST /orders/{order_id}/delete` | Delete an order (admin). |

### TikTok returns

| Method & Path | Description |
|--------------|------------|
| `GET /returns/create` | Show return creation form. |
| `POST /returns/create` | Create a return record. |
| `GET /returns/all/list` | List all returns (admin). |
| `GET /returns/{user_id}/list` | List returns created by a user. |
| `GET /returns/{id}/edit` | Edit a return record. |
| `POST /returns/{id}/edit` | Save return changes. |
| `POST /returns/{id}/delete` | Delete a return record (admin). |

### TikTok shifts

| Method & Path | Description |
|--------------|------------|
| `GET /shifts/create` | Show shift creation form. |
| `POST /shifts/create` | Create a new shift. |
| `GET /shifts/list` | List shifts for a month. |
| `GET /shifts/{id}/edit` | Edit a shift. |
| `POST /shifts/{id}/edit` | Save shift changes. |
| `POST /shifts/{id}/delete` | Delete a shift (admin). |
| `GET /shifts/employees?date=YYYY-MM-DD` | Return employee names assigned to a date. |

### Reports & payouts

| Method & Path | Description |
|--------------|------------|
| `GET /reports/monthly` | Monthly salary report for TikTok employees. |
| `POST /reports/pay` | Record a manual payout. |

### Cafe module

Accessible to `admin` only.

| Method & Path | Description |
|--------------|------------|
| `GET /cafe/` | List coffee shops. |
| `GET /cafe/create` | Create a shop form. |
| `POST /cafe/create` | Add a coffee shop. |
| `GET /cafe/{shop_id}/edit` | Edit shop details. |
| `POST /cafe/{shop_id}/edit` | Save shop changes. |
| `GET /cafe/{shop_id}/records` | List cash records for a shop. |
| `GET /cafe/{shop_id}/records/create` | Create a record form. |
| `POST /cafe/{shop_id}/records/create` | Create a cash record. |
| `GET /cafe/{shop_id}/records/edit/{record_id}` | Edit a cash record. |
| `POST /cafe/{shop_id}/records/edit/{record_id}` | Save record changes. |
| `POST /cafe/{shop_id}/records/delete/{record_id}` | Delete a record. |
| `GET /cafe/{shop_id}/reports` | Monthly cash report. |

### Logs

| Method & Path | Description |
|--------------|------------|
| `GET /logs/` | Display user activity logs (admin). |

## Background tasks

Celery is configured in `src/utils/celery_worker.py`. Two periodic tasks are defined:

- **Database backup** (`src.tasks.backup.send_db_backup_task`) — creates a PostgreSQL dump and sends it to Telegram. Controlled by `CELERY_BACHUP_RATE`.
- **Log cleanup** (`src.tasks.cleanup.clean_old_logs`) — removes log records older than seven days.

Both tasks require Redis and run automatically when the Celery worker and beat containers are started via Docker Compose.

## Development notes

- All HTML templates live in `src/templates` and static files in `src/static`.
- User actions are logged through `LogUserActionMiddleware` into the `user_logs` table and the log file `logs/user_activity.log`.
- An admin user is automatically created at startup using the credentials from the environment variables.

## License

This project is provided as-is without any warranty.