from __future__ import print_function
from googleapiclient.discovery import build
from httplib2 import Http
from oauth2client import file, client, tools
from oauth2client.service_account import ServiceAccountCredentials
import itertools
import numpy as np
from flask import Flask, render_template

app = Flask(__name__)

# If modifying these scopes, delete the file token.json.
SCOPES = 'https://www.googleapis.com/auth/spreadsheets.readonly'

SPREADSHEET_ID = '1IJayJVNFkGPc-isqgZeqI0MaWgPXg5fTuJEBlMe4TDM'
RANGE_NAME = 'Preferences!A1:Z35'

# Returns all possible approximately n sized groupings of elements in lst 
def get_groups(lst, n):
    per_list = len(lst) // n
    leftover = len(lst) - (n * per_list)
    lengths = [per_list] * n

    # Spread leftovers over the first few groups
    for i in range(leftover):
        lengths[i] = lengths[i] + 1

    # alphabetically sort names in groups
    group_list = [sorted(groups) for groups in get_groups_helper(lst, lengths)]

    return group_list

# Recursive helper function for get_groups.
# len_list is a list of sizes the groups must adhere to
# assumes len(lst) == sum(len_list)
def get_groups_helper(lst, len_list):
    # Base case, if there is only one group left to make, return the list
    if len(len_list) == 1:
        yield [tuple(lst)]
    else:
        for g in itertools.combinations(lst, len_list[0]):
            leftover_list = list(set(lst) - set(g))
            for gs in get_groups_helper(leftover_list, len_list[1:]):
                yield [tuple(g)] + gs

# Get the acceptable set of toppings for a person with the given index
# Currently "acceptable" == "non-negative"
def get_topping_set(table, index):
    return set([row[0] for row in table if int(row[index+1]) >= 0])

# Score a pizza given a 2d list of the score part of the sheet,
#   the people involved in the pizza and the set of possible pizza toppings
def score_pizza(topping_scores, people_idxs, topping_idxs):
    score = 0
    for person in people_idxs:
        for topping in topping_idxs:
            score += int(topping_scores[person][topping])
    return score

# get the spreadsheet values, returns a 2d list in row-major order
def get_values():
    # Boilerplate auth and fetch code:
    creds = ServiceAccountCredentials.from_json_keyfile_name('fpizza_key.json', SCOPES)
    service = build('sheets', 'v4', http=creds.authorize(Http()))

    # Call the Sheets API
    result = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID,
                                                 range=RANGE_NAME).execute()
    values = result.get('values', [])

    return values

# index page, show the names from the sheet
@app.route("/")
def show_selection():
    values = get_values()
    names = enumerate(values[0][1:])
    return render_template('index.html', names=names)

# pizza solver page, solve for the best pizzas and display them
@app.route("/solve/<people>/<int:num_pizzas>")
def get_best_pizzas(people, num_pizzas):
    p_list = [int(x) for x in people.split(",")]
    values = get_values()

    # Extend all sublists tot he same length
    values = [row for row in values if len(row) > 1]
    max_len = max(len(row) for row in values)
    for row in values:
        if len(row) < max_len:
            row.extend([u''] * (max_len - len(row)))

    # Populate empty cells with -1
    values = [[val if val != u'' else u'-1' for val in row] for row in values]

    # Generate some helpful derivative lists
    names = values[0][1:]
    toppings = [row[0] for row in values[1:]]
    topping_scores = zip(*values[1:])[1:]

    best_score = 0
    best_group_list = []
    best_topping_set = []

    # Iterate over all possible pizza groupings, finding the best score
    for group_list in get_groups(p_list, num_pizzas):
        score = 0  # overall score for this set of grouping's pizzas
        group_toppings = []  # list of tuples representing groups toppings

        # Iterate over each group in a set of groups, scoring their pizza
        for group in group_list:
            topping_set = set(toppings)  # start with all possible toppings

            # For each person, intersect their acceptable toppings
            for person in group:
                topping_set = topping_set & get_topping_set(values[1:], person)
            topping_idxs = [toppings.index(x) for x in list(topping_set)]
            score += score_pizza(topping_scores, group, topping_idxs)
            group_toppings.append(zip(topping_set, topping_idxs))

        # store the result if it's the best so far
        if(score > best_score):
            best_score = score
            best_group_list = group_list
            best_topping_set = group_toppings

    # convert indexes to names
    best_group_list = [[names[x] for x in group] for group in best_group_list]
    
    # sort toppings by index
    best_topping_set = [sorted(list(toppings), key = lambda x: x[1]) 
                            for toppings in best_topping_set]
    
    return render_template('pizza.html', num_pizzas=num_pizzas,
                           grp_tps=zip(best_group_list, best_topping_set))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
