# pizza_solver

A Django web app for coordinating group pizza orders. Each person records their topping preferences (like, neutral, dislike, allergy), and the app uses an ILP solver to assign people to pizzas and select toppings that best satisfy the group.

## How it works

- Users belong to **groups**, and orders are placed within a group
- Each person sets per-topping preferences: like (+1), neutral (0), dislike (−1), allergy (hard constraint)
- When creating an order, the host picks a restaurant, number of pizzas, and which group members to include
- Guests can join via invite link without creating an account
- The solver (PuLP/CBC) assigns each person to exactly one pizza and picks up to 3 toppings per pizza
- Two optimization modes: **maximize likes** or **minimize dislikes**

## Setup

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Toppings and restaurants can be managed via the admin panel or bulk-imported through the staff import page (plain-text format with `[toppings]` and `[restaurants]` sections).

## Stack

- Python / Django
- django-allauth (authentication)
- PuLP + CBC (ILP optimization)
