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
    """Build a preference matrix and allergy set for all (person, topping) pairs.

    Returns:
        prefs: dict mapping (person_index, topping_index) -> numeric score (never ALLERGY)
        allergy_pairs: set of (person_index, topping_index) pairs with ALLERGY preference
    """
    prefs = {}
    allergy_pairs = set()

    existing = {}
    if people:
        prefs_qs = PersonToppingPreference.objects.filter(
            person__in=people,
            topping__in=toppings,
        ).values_list('person_id', 'topping_id', 'preference')
        for person_id, topping_id, pref in prefs_qs:
            existing[(person_id, topping_id)] = pref

    use_dislike_weight = config.DISLIKE_WEIGHT != PersonToppingPreference.DISLIKE
    for p_idx, person in enumerate(people):
        default = PersonToppingPreference.DISLIKE if person.unrated_is_dislike else PersonToppingPreference.NEUTRAL
        for t_idx, topping in enumerate(toppings):
            pref = existing.get((person.id, topping.id), default)
            if pref == PersonToppingPreference.ALLERGY:
                allergy_pairs.add((p_idx, t_idx))
            elif use_dislike_weight and pref == PersonToppingPreference.DISLIKE:
                prefs[(p_idx, t_idx)] = config.DISLIKE_WEIGHT
            else:
                prefs[(p_idx, t_idx)] = pref

    return prefs, allergy_pairs


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
    toppings = list(order.restaurant.toppings.all())

    num_pizzas = order.num_pizzas
    num_people = len(people)
    num_toppings = len(toppings)

    if order.num_pizzas > num_people:
        raise ValueError(
            f"Cannot have more pizzas ({order.num_pizzas}) than participants ({num_people})."
        )

    prefs, allergy_pairs = _build_prefs(people, toppings)

    prob = pulp.LpProblem("pizza", pulp.LpMaximize)

    # --- Variables ---

    assign = {}
    topping_on = {}
    for k in range(num_pizzas):
        # assign[p,k]: participant p assigned to pizza k
        for p in range(num_people):
            assign[p, k] = pulp.LpVariable(f"assign_{p}_{k}", cat='Binary')

        # topping_on[t,k]: topping t on pizza k
        for t in range(num_toppings):
            topping_on[t, k] = pulp.LpVariable(f"topping_on_{t}_{k}", cat='Binary')

    # pref_active[p,t,k]: linearization of assign[p,k] * topping_on[t,k] - only for LIKE/DISLIKE pairs
    pref_active = {}
    nonzero_pairs = []
    for p in range(num_people):
        for t in range(num_toppings):
            if prefs.get((p, t), PersonToppingPreference.NEUTRAL) != PersonToppingPreference.NEUTRAL:
                nonzero_pairs.append((p, t))
                for k in range(num_pizzas):
                    pref_active[p, t, k] = pulp.LpVariable(f"pref_active_{p}_{t}_{k}", cat='Binary')

    # --- Hard constraints ---

    # 1. Each participant on exactly one pizza
    for p in range(num_people):
        prob += pulp.lpSum(assign[p, k] for k in range(num_pizzas)) == 1, f"person_{p}_once"

    # 2. Allergy: participant p cannot be on pizza k if allergic topping t is there
    for (p, t) in allergy_pairs:
        for k in range(num_pizzas):
            prob += assign[p, k] + topping_on[t, k] <= 1, f"allergy_{p}_{t}_{k}"

    # 3. Topping cap: at most MAX_TOPPINGS_PER_PIZZA toppings per pizza
    for k in range(num_pizzas):
        prob += pulp.lpSum(topping_on[t, k] for t in range(num_toppings)) <= config.MAX_TOPPINGS_PER_PIZZA, f"topping_cap_{k}"

    # 4. Balanced assignment: each pizza gets floor(P/K) or ceil(P/K) participants
    min_per_pizza, max_per_pizza = num_people // num_pizzas, math.ceil(num_people / num_pizzas)
    for k in range(num_pizzas):
        prob += pulp.lpSum(assign[p, k] for p in range(num_people)) >= min_per_pizza, f"pizza_{k}_lo"
        prob += pulp.lpSum(assign[p, k] for p in range(num_people)) <= max_per_pizza, f"pizza_{k}_hi"

    # 5. Symmetry breaking: participant p cannot be on pizza k > p (for p < num_pizzas).
    for p in range(num_pizzas):
        for k in range(p + 1, num_pizzas):
            prob += assign[p, k] == 0, f"sym_{p}_{k}"

    # 6. Linearization constraints: pref_active[p,t,k] = assign[p,k] AND topping_on[t,k]
    for (p, t) in nonzero_pairs:
        for k in range(num_pizzas):
            prob += pref_active[p, t, k] <= assign[p, k], f"pref_le_assign_{p}_{t}_{k}"
            prob += pref_active[p, t, k] <= topping_on[t, k], f"pref_le_topping_{p}_{t}_{k}"
            prob += pref_active[p, t, k] >= assign[p, k] + topping_on[t, k] - 1, f"pref_ge_{p}_{t}_{k}"

    # --- Objective ---
    # shareability_bonus_weight blends assigned-only scoring (w=0) with
    # group-wide scoring (w=1). At w=0 this reduces to the standard
    # prefs[p,t] * pref_active[p,t,k] used by both existing modes.
    shareability_weight = order.shareability_bonus_weight
    norm_share_weight = shareability_weight / (num_pizzas - 1) if num_pizzas > 1 else 0
    pizza_score = {k: pulp.lpSum(
        prefs[(p, t)] * ((1 - norm_share_weight) * pref_active[p, t, k] + norm_share_weight * topping_on[t, k])
        for (p, t) in nonzero_pairs
    ) for k in range(num_pizzas)}

    if order.optimization_mode == 'minimize_dislikes':
        min_pizza_score = pulp.LpVariable("min_pizza_score", cat='Continuous')
        for k in range(num_pizzas):
            prob += pizza_score[k] >= min_pizza_score, f"min_score_{k}"
        prob += min_pizza_score
    else:
        prob += pulp.lpSum(pizza_score[k] for k in range(num_pizzas))

    prob.solve(pulp.PULP_CBC_CMD(msg=0, threads=4, timeLimit=20))

    if prob.sol_status < 1:
        status = pulp.LpStatus[prob.status]
        raise ValueError(f"ILP solver could not find a solution. Status: {status}")

    # --- Extract solution ---
    result = []
    for k in range(num_pizzas):
        pizza = OrderedPizza(order=order)
        pizza.save()

        pizza.people.set([people[p] for p in range(num_people) if assign[p, k].value() > 0.5])
        pizza.toppings.set([toppings[t] for t in range(num_toppings) if topping_on[t, k].value() > 0.5])
        result.append(pizza)

    return result
