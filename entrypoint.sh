#!/bin/sh
set -e
python manage.py migrate --noinput
exec gunicorn pizza_solver.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 2 \
  --timeout 120
