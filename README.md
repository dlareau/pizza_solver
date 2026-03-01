# pizza_solver

A Django web app for coordinating group pizza orders. Each person records their topping preferences (like, neutral, dislike, allergy), and the app uses an ILP solver to assign people to pizzas and select toppings that best satisfy the group.

## How it works

- Users belong to **groups**, and orders are placed within a group
- Each person sets per-topping preferences: like, neutral, dislike, or allergy
- When creating an order, the host picks a restaurant, number of pizzas, and which group members to include
- Guests can join via invite link without creating an account
- The solver (PuLP) assigns each person to exactly one pizza and picks up to 4 toppings per pizza

## Running with Docker

```yaml
# docker-compose.yml
services:
  db:
    image: postgres:16
    volumes:
      - pizza_data:/var/lib/postgresql/data
    environment:
      - POSTGRES_DB=pizza_solver
      - POSTGRES_USER=pizza_solver
      - POSTGRES_PASSWORD=change-me-in-production

  web:
    image: ghcr.io/dlareau/pizza_solver:latest
    ports:
      - "8000:8000"
    depends_on:
      db:
        condition: service_healthy
    environment:
      - SECRET_KEY=change-me-in-production
      - DEBUG=False
      - DATABASE_URL=postgres://pizza_solver:change-me-in-production@db:5432/pizza_solver
      # - CSRF_TRUSTED_ORIGINS=https://yourdomain.com

volumes:
  pizza_data:
```

```bash
docker compose up
```

Set `ALLOWED_HOSTS` to your domain or IP to restrict access (e.g. `ALLOWED_HOSTS=mypizzasite.com`).

The `DATABASE_URL` environment variable configures the database. The format is `postgres://user:password@host:port/dbname`. Make sure the password in `DATABASE_URL` matches `POSTGRES_PASSWORD` on the `db` service.

## Setup

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Stack

- Python / Django
- django-allauth (authentication)
- PuLP + CBC (ILP optimization)
- PostgreSQL (database)
