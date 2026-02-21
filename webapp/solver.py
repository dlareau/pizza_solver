"""
Pizza optimization solver.

The solver assigns people to pizzas and selects toppings to maximize satisfaction
while respecting hard constraints (allergies).

Constraints:
  - ALLERGY (preference=-2): A person must NEVER be assigned to a pizza containing
    a topping they are allergic to. This is a hard constraint.

Soft objectives (by optimization_mode):
  - 'maximize_likes': Maximize the total LIKE (+1) scores for toppings on each person's pizza.
  - 'minimize_dislikes': Minimize the total DISLIKE (-1) violations.

Input:
  - An Order object (saved to DB) with .vendor, .people, .num_pizzas, .pizza_mode,
    and .optimization_mode set.
  - The order's people M2M must already be populated.

Output:
  - A list of saved OrderedPizza objects, each with left_toppings, right_toppings,
    and people M2M relations fully populated in the database.

Pizza mode semantics:
  - 'whole': All people on a pizza share the same toppings. Only left_toppings is used;
    right_toppings is always empty.
  - 'half': Each pizza can be split into two halves. left_toppings applies to the left
    group of people, right_toppings to the right group.
"""

import math

import pulp

from .models import Order, OrderedPizza, PersonToppingPreference


def _build_prefs(people, toppings):
    """Build a preference matrix for all (person, topping) pairs.

    Returns a dict mapping (p_idx, t_idx) -> int preference value.
    Queries the DB in a single hit, then fills in defaults based on
    each person's unrated_is_dislike flag.
    """
    # Fetch all existing preferences in one query
    existing = {}
    prefs_qs = PersonToppingPreference.objects.filter(
        person__in=people,
        topping__in=toppings,
    ).values_list('person_id', 'topping_id', 'preference')
    for person_id, topping_id, pref in prefs_qs:
        existing[(person_id, topping_id)] = pref

    person_ids = [p.id for p in people]
    topping_ids = [t.id for t in toppings]

    result = {}
    for p_idx, person in enumerate(people):
        default = PersonToppingPreference.DISLIKE if person.unrated_is_dislike else PersonToppingPreference.NEUTRAL
        for t_idx, topping in enumerate(toppings):
            key = (person.id, topping.id)
            result[(p_idx, t_idx)] = existing.get(key, default)

    return result


def solve(order: Order) -> list[OrderedPizza]:
    """
    Run the pizza optimization algorithm for the given order.

    Saves each OrderedPizza and its M2M relations (left_toppings, right_toppings,
    people) to the database before returning.

    Args:
        order: A saved Order instance with vendor, people, num_pizzas, pizza_mode,
               and optimization_mode populated.

    Returns:
        A list of saved OrderedPizza instances with all M2M relations populated.

    Raises:
        ValueError: If num_pizzas > num_people or order configuration is invalid.
    """
    num_people = order.people.count()
    if order.num_pizzas > num_people:
        raise ValueError(
            f"Cannot have more pizzas ({order.num_pizzas}) than people ({num_people})."
        )

    if order.pizza_mode == 'half':
        return solve_half(order)
    else:
        return solve_whole(order)


def solve_whole(order: Order) -> list[OrderedPizza]:
    """ILP solver for whole-pizza mode.

    Raises:
        ValueError: If the problem is infeasible or unsolved.
    """
    people = list(order.people.all())
    toppings = list(order.vendor.toppings.all())
    K = order.num_pizzas
    P = len(people)
    T = len(toppings)

    prefs = _build_prefs(people, toppings)

    prob = pulp.LpProblem("pizza_whole", pulp.LpMaximize)

    # --- Variables ---
    # x[p,k]: person p assigned to pizza k
    x = {(p, k): pulp.LpVariable(f"x_{p}_{k}", cat='Binary')
         for p in range(P) for k in range(K)}
    # t[t,k]: topping t on pizza k
    tv = {(t, k): pulp.LpVariable(f"t_{t}_{k}", cat='Binary')
          for t in range(T) for k in range(K)}
    # z[p,t,k]: linearization of x[p,k] * tv[t,k]
    z = {(p, t, k): pulp.LpVariable(f"z_{p}_{t}_{k}", cat='Binary')
         for p in range(P) for t in range(T) for k in range(K)}

    # --- Hard constraints ---

    # 1. Each person on exactly one pizza
    for p in range(P):
        prob += pulp.lpSum(x[p, k] for k in range(K)) == 1, f"person_{p}_once"

    # 2. Allergy: person p cannot be on pizza k if allergic topping t is there
    for p in range(P):
        for t in range(T):
            if prefs[(p, t)] == PersonToppingPreference.ALLERGY:
                for k in range(K):
                    prob += x[p, k] + tv[t, k] <= 1, f"allergy_{p}_{t}_{k}"

    # 3. Topping cap: at most 3 toppings per pizza
    for k in range(K):
        prob += pulp.lpSum(tv[t, k] for t in range(T)) <= 3, f"topping_cap_{k}"

    # 4. Balanced assignment: each pizza gets floor(P/K) or ceil(P/K) people
    lo, hi = P // K, math.ceil(P / K)
    for k in range(K):
        prob += pulp.lpSum(x[p, k] for p in range(P)) >= lo, f"pizza_{k}_lo"
        prob += pulp.lpSum(x[p, k] for p in range(P)) <= hi, f"pizza_{k}_hi"

    # 5. Linearization constraints: z[p,t,k] = x[p,k] AND tv[t,k]
    for p in range(P):
        for t in range(T):
            for k in range(K):
                prob += z[p, t, k] <= x[p, k], f"z_le_x_{p}_{t}_{k}"
                prob += z[p, t, k] <= tv[t, k], f"z_le_t_{p}_{t}_{k}"
                prob += z[p, t, k] >= x[p, k] + tv[t, k] - 1, f"z_ge_{p}_{t}_{k}"

    # --- Objective ---
    # score[k] = sum_{p,t} pref[p,t] * z[p,t,k]
    score = {k: pulp.lpSum(prefs[(p, t)] * z[p, t, k]
                           for p in range(P) for t in range(T))
             for k in range(K)}

    if order.optimization_mode == 'minimize_dislikes':
        # max-min: maximize the minimum pizza score
        M = pulp.LpVariable("M", cat='Continuous')
        for k in range(K):
            prob += score[k] >= M, f"min_score_{k}"
        prob += M
    else:
        # maximize_likes: maximize total score
        prob += pulp.lpSum(score[k] for k in range(K))

    prob.solve(pulp.PULP_CBC_CMD(msg=0))

    if prob.status != 1:
        status = pulp.LpStatus[prob.status]
        raise ValueError(f"ILP solver could not find a solution. Status: {status}")

    # --- Extract solution ---
    result = []
    for k in range(K):
        pizza = OrderedPizza(order=order)
        pizza.save()
        pizza.people.set([people[p] for p in range(P) if x[p, k].value() > 0.5])
        pizza.left_toppings.set([toppings[t] for t in range(T) if tv[t, k].value() > 0.5])
        # right_toppings left empty (whole mode)
        result.append(pizza)

    return result


def solve_half(order: Order) -> list[OrderedPizza]:
    """ILP solver for half-and-half mode.

    Raises:
        ValueError: If the problem is infeasible or unsolved.
    """
    people = list(order.people.all())
    toppings = list(order.vendor.toppings.all())
    K = order.num_pizzas
    P = len(people)
    T = len(toppings)

    prefs = _build_prefs(people, toppings)

    prob = pulp.LpProblem("pizza_half", pulp.LpMaximize)

    # --- Variables ---
    x_left = {(p, k): pulp.LpVariable(f"xl_{p}_{k}", cat='Binary')
               for p in range(P) for k in range(K)}
    x_right = {(p, k): pulp.LpVariable(f"xr_{p}_{k}", cat='Binary')
                for p in range(P) for k in range(K)}
    t_left = {(t, k): pulp.LpVariable(f"tl_{t}_{k}", cat='Binary')
               for t in range(T) for k in range(K)}
    t_right = {(t, k): pulp.LpVariable(f"tr_{t}_{k}", cat='Binary')
                for t in range(T) for k in range(K)}
    is_split = {k: pulp.LpVariable(f"split_{k}", cat='Binary')
                for k in range(K)}
    z_left = {(p, t, k): pulp.LpVariable(f"zl_{p}_{t}_{k}", cat='Binary')
               for p in range(P) for t in range(T) for k in range(K)}
    z_right = {(p, t, k): pulp.LpVariable(f"zr_{p}_{t}_{k}", cat='Binary')
                for p in range(P) for t in range(T) for k in range(K)}

    # --- Hard constraints ---

    # 1. Each person on exactly one half of exactly one pizza
    for p in range(P):
        prob += (pulp.lpSum(x_left[p, k] + x_right[p, k] for k in range(K)) == 1,
                 f"person_{p}_once")

    # 2. Right half only if split
    for k in range(K):
        for p in range(P):
            prob += x_right[p, k] <= is_split[k], f"xr_le_split_{p}_{k}"
        for t in range(T):
            prob += t_right[t, k] <= is_split[k], f"tr_le_split_{t}_{k}"

    # 3. Allergy (both halves)
    for p in range(P):
        for t in range(T):
            if prefs[(p, t)] == PersonToppingPreference.ALLERGY:
                for k in range(K):
                    prob += x_left[p, k] + t_left[t, k] <= 1, f"allergy_l_{p}_{t}_{k}"
                    prob += x_right[p, k] + t_right[t, k] <= 1, f"allergy_r_{p}_{t}_{k}"

    # 4. Topping cap: at most 3 toppings per half
    for k in range(K):
        prob += pulp.lpSum(t_left[t, k] for t in range(T)) <= 3, f"cap_l_{k}"
        prob += pulp.lpSum(t_right[t, k] for t in range(T)) <= 3, f"cap_r_{k}"

    # 5. Balanced assignment: each pizza gets floor(P/K) or ceil(P/K) people
    lo, hi = P // K, math.ceil(P / K)
    for k in range(K):
        total = pulp.lpSum(x_left[p, k] + x_right[p, k] for p in range(P))
        prob += total >= lo, f"pizza_{k}_lo"
        prob += total <= hi, f"pizza_{k}_hi"

    # 6. Linearization (left and right halves)
    for p in range(P):
        for t in range(T):
            for k in range(K):
                prob += z_left[p, t, k] <= x_left[p, k], f"zl_le_xl_{p}_{t}_{k}"
                prob += z_left[p, t, k] <= t_left[t, k], f"zl_le_tl_{p}_{t}_{k}"
                prob += z_left[p, t, k] >= x_left[p, k] + t_left[t, k] - 1, f"zl_ge_{p}_{t}_{k}"
                prob += z_right[p, t, k] <= x_right[p, k], f"zr_le_xr_{p}_{t}_{k}"
                prob += z_right[p, t, k] <= t_right[t, k], f"zr_le_tr_{p}_{t}_{k}"
                prob += z_right[p, t, k] >= x_right[p, k] + t_right[t, k] - 1, f"zr_ge_{p}_{t}_{k}"

    # --- Score and objective ---
    # score[k] = sum_{p,t} pref[p,t] * (z_left + z_right) + 2 * (1 - is_split[k])
    score = {
        k: (pulp.lpSum(prefs[(p, t)] * (z_left[p, t, k] + z_right[p, t, k])
                       for p in range(P) for t in range(T))
            + 2 * (1 - is_split[k]))
        for k in range(K)
    }

    if order.optimization_mode == 'minimize_dislikes':
        M = pulp.LpVariable("M", cat='Continuous')
        for k in range(K):
            prob += score[k] >= M, f"min_score_{k}"
        prob += M
    else:
        prob += pulp.lpSum(score[k] for k in range(K))

    prob.solve(pulp.PULP_CBC_CMD(msg=0))

    if prob.status != 1:
        status = pulp.LpStatus[prob.status]
        raise ValueError(f"ILP solver could not find a solution. Status: {status}")

    # --- Extract solution ---
    result = []
    for k in range(K):
        pizza = OrderedPizza(order=order)
        pizza.save()
        left_people = [people[p] for p in range(P) if x_left[p, k].value() > 0.5]
        right_people = [people[p] for p in range(P) if x_right[p, k].value() > 0.5]
        pizza.people.set(left_people + right_people)
        pizza.left_toppings.set([toppings[t] for t in range(T) if t_left[t, k].value() > 0.5])
        pizza.right_toppings.set([toppings[t] for t in range(T) if t_right[t, k].value() > 0.5])
        result.append(pizza)

    return result
