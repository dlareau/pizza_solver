from webapp.models import PersonToppingPreference

def compute_pizza_scores(pizza_list):
    """Return a dict mapping pizza.pk -> integer score based on preferences."""
    all_people = {}
    all_toppings = {}
    pizza_data = {}
    for pizza in pizza_list:
        people = list(pizza.people.all())
        toppings = list(pizza.toppings.all())
        pizza_data[pizza.pk] = (people, toppings)
        for p in people:
            all_people[p.pk] = p
        for t in toppings:
            all_toppings[t.pk] = t

    pref_map = {}
    if all_people and all_toppings:
        for person_id, topping_id, pref in PersonToppingPreference.objects.filter(
            person_id__in=all_people.keys(),
            topping_id__in=all_toppings.keys(),
        ).values_list('person_id', 'topping_id', 'preference'):
            pref_map[(person_id, topping_id)] = pref

    scores = {}
    for pizza_pk, (people, toppings) in pizza_data.items():
        score = 0
        for person in people:
            default = PersonToppingPreference.DISLIKE if person.unrated_is_dislike else PersonToppingPreference.NEUTRAL
            for topping in toppings:
                pref = pref_map.get((person.pk, topping.pk), default)
                if pref not in (PersonToppingPreference.NEUTRAL, PersonToppingPreference.ALLERGY):
                    score += pref
        scores[pizza_pk] = score
    return scores