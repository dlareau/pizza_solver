"""
Pizza optimization solver.

The solver assigns people to pizzas and selects toppings to maximize
satisfaction while respecting hard constraints such as allergies.

Constraints:
  - ALLERGY (preference=-2): A participant must NEVER be assigned to a pizza
    containing a topping they are allergic to.

Objectives:
  - 'maximize_likes': Maximize the total LIKE (+1) scores for toppings on each
    participant's pizza.
  - 'minimize_dislikes': Minimize the total DISLIKE (-1) violations.

  Both objectives are modified by order.shareability_bonus_weight (w, default 0).
  At w=0 only assigned people's preferences count (standard behavior). At w>0,
  non-assigned people's preferences are also factored in with weight w, rewarding
  pizzas that others in the order would enjoy and penalizing those they would not.

Input:
  - An Order object (saved to DB) with .restaurant, .people, .num_pizzas,
    and .optimization_mode set and people M2M already populated
    (including guests as Persons).

Output:
  - A list of saved OrderedPizza objects, each with toppings and people
    M2M relations fully populated in the database.
"""

import math

import pulp
from constance import config

from .models import Order, OrderedPizza, PersonToppingPreference


def _build_prefs(people, toppings):
    """Build a preference matrix for all (person, topping) pairs.

    Returns a dict mapping (person_index, topping_index) -> int preference.
    """
    result = {}

    existing = {}
    if people:
        prefs_qs = PersonToppingPreference.objects.filter(
            person__in=people,
            topping__in=toppings,
        ).values_list('person_id', 'topping_id', 'preference')
        for person_id, topping_id, pref in prefs_qs:
            existing[(person_id, topping_id)] = pref

    for p_idx, person in enumerate(people):
        default = PersonToppingPreference.DISLIKE if person.unrated_is_dislike else PersonToppingPreference.NEUTRAL
        for t_idx, topping in enumerate(toppings):
            result[(p_idx, t_idx)] = existing.get((person.id, topping.id), default)

    return result


def solve(order: Order) -> list[OrderedPizza]:
    """
    Run the pizza optimization algorithm for the given order.

    Saves each OrderedPizza and its M2M relations (toppings, people) to
    the database before returning.

    Args:
        order: A saved Order instance with restaurant, people, num_pizzas,
               and optimization_mode populated. Guests are Person objects
               with user_account=None in order.people.

    Returns:
        A list of saved OrderedPizza instances with all M2M relations populated.

    Raises:
        ValueError: If num_pizzas > num_participants or order configuration is invalid.
    """
    people = list(order.people.all())
    P = len(people)

    if order.num_pizzas > P:
        raise ValueError(
            f"Cannot have more pizzas ({order.num_pizzas}) than participants ({P})."
        )

    toppings = list(order.restaurant.toppings.all())
    K = order.num_pizzas
    T = len(toppings)

    prefs = _build_prefs(people, toppings)

    if config.DISLIKE_WEIGHT != PersonToppingPreference.DISLIKE:
        for key, val in prefs.items():
            if val == PersonToppingPreference.DISLIKE:
                prefs[key] = config.DISLIKE_WEIGHT

    prob = pulp.LpProblem("pizza", pulp.LpMaximize)

    # --- Variables ---
    # x[p,k]: participant p assigned to pizza k
    x = {(p, k): pulp.LpVariable(f"x_{p}_{k}", cat='Binary')
         for p in range(P) for k in range(K)}
    # tv[t,k]: topping t on pizza k
    tv = {(t, k): pulp.LpVariable(f"t_{t}_{k}", cat='Binary')
          for t in range(T) for k in range(K)}
    # z[p,t,k]: linearization of x[p,k] * tv[t,k] - only for LIKE/DISLIKE pairs
    nonzero_pairs = [(p, t) for p in range(P) for t in range(T)
                     if prefs[(p, t)] not in (PersonToppingPreference.NEUTRAL,
                                              PersonToppingPreference.ALLERGY)]
    z = {(p, t, k): pulp.LpVariable(f"z_{p}_{t}_{k}", cat='Binary')
         for (p, t) in nonzero_pairs for k in range(K)}

    # --- Hard constraints ---

    # 1. Each participant on exactly one pizza
    for p in range(P):
        prob += pulp.lpSum(x[p, k] for k in range(K)) == 1, f"person_{p}_once"

    # 2. Allergy: participant p cannot be on pizza k if allergic topping t is there
    for p in range(P):
        for t in range(T):
            if prefs[(p, t)] == PersonToppingPreference.ALLERGY:
                for k in range(K):
                    prob += x[p, k] + tv[t, k] <= 1, f"allergy_{p}_{t}_{k}"

    # 3. Topping cap: at most MAX_TOPPINGS_PER_PIZZA toppings per pizza
    for k in range(K):
        prob += pulp.lpSum(tv[t, k] for t in range(T)) <= config.MAX_TOPPINGS_PER_PIZZA, f"topping_cap_{k}"

    # 4. Balanced assignment: each pizza gets floor(P/K) or ceil(P/K) participants
    lo, hi = P // K, math.ceil(P / K)
    for k in range(K):
        prob += pulp.lpSum(x[p, k] for p in range(P)) >= lo, f"pizza_{k}_lo"
        prob += pulp.lpSum(x[p, k] for p in range(P)) <= hi, f"pizza_{k}_hi"

    # 5. Symmetry breaking: participant p cannot be on pizza k > p (for p < K).
    for p in range(K):
        for k in range(p + 1, K):
            prob += x[p, k] == 0, f"sym_{p}_{k}"

    # 6. Linearization constraints: z[p,t,k] = x[p,k] AND tv[t,k]
    for (p, t) in nonzero_pairs:
        for k in range(K):
            prob += z[p, t, k] <= x[p, k], f"z_le_x_{p}_{t}_{k}"
            prob += z[p, t, k] <= tv[t, k], f"z_le_t_{p}_{t}_{k}"
            prob += z[p, t, k] >= x[p, k] + tv[t, k] - 1, f"z_ge_{p}_{t}_{k}"

    # --- Objective ---
    # shareability_bonus_weight (w) blends assigned-only scoring (w=0) with
    # group-wide scoring (w=1). At w=0 this reduces to the standard
    # prefs[p,t] * z[p,t,k] used by both existing modes.
    f = order.shareability_bonus_weight
    w = f / (K - 1) if K > 1 else 0
    score = {k: pulp.lpSum(
        prefs[(p, t)] * ((1 - w) * z[p, t, k] + w * tv[t, k])
        for (p, t) in nonzero_pairs
    ) for k in range(K)}

    if order.optimization_mode == 'minimize_dislikes':
        M = pulp.LpVariable("M", cat='Continuous')
        for k in range(K):
            prob += score[k] >= M, f"min_score_{k}"
        prob += M
    else:
        prob += pulp.lpSum(score[k] for k in range(K))

    prob.solve(pulp.PULP_CBC_CMD(msg=0, threads=4, timeLimit=20))

    if prob.sol_status < 1:
        status = pulp.LpStatus[prob.status]
        raise ValueError(f"ILP solver could not find a solution. Status: {status}")

    # --- Extract solution ---
    result = []
    for k in range(K):
        pizza = OrderedPizza(order=order)
        pizza.save()

        pizza.people.set([people[p] for p in range(P) if x[p, k].value() > 0.5])
        pizza.toppings.set([toppings[t] for t in range(T) if tv[t, k].value() > 0.5])
        result.append(pizza)

    return result
