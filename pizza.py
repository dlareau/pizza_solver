from __future__ import print_function
from googleapiclient.discovery import build
from httplib2 import Http
from oauth2client import file, client, tools
from oauth2client.service_account import ServiceAccountCredentials
import itertools
import numpy as np
from flask import Flask, render_template
import time
import math

app = Flask(__name__)

# If modifying these scopes, delete the file token.json.
SCOPES = 'https://www.googleapis.com/auth/spreadsheets.readonly'

SPREADSHEET_ID = '1IJayJVNFkGPc-isqgZeqI0MaWgPXg5fTuJEBlMe4TDM'
RANGE_NAME = 'Preferences!A1:Z35'

BASE_TOPPING_SCORE = 1 # Some impossibly large number
BASE_TOPPING_END_INDEX = 2


# # Returns all possible approximately n sized groupings of elements in lst
# def get_groups(lst, n):
#     per_list = len(lst) // n
#     leftover = len(lst) - (n * per_list)
#     lengths = [per_list] * n

#     # Spread leftovers over the first few groups
#     for i in range(leftover):
#         lengths[i] = lengths[i] + 1

#     return get_groups_helper(lst, lengths)

# # Recursive helper function for get_groups.
# # len_list is a list of sizes the groups must adhere to
# # assumes len(lst) == sum(len_list)
# def get_groups_helper(lst, len_list):
#     # Base case, if there is only one group left to make, return the list
#     if len(len_list) == 1:
#         yield [tuple(lst)]
#     else:
#         for g in itertools.combinations(lst, len_list[0]):
#             leftover_list = [x for x in lst if x not in g]
#             for gs in get_groups_helper(leftover_list, len_list[1:]):
#                 yield [tuple(g)] + gs

def r_helper(nums, group, curr_index, num_people, group_size, results):
    if(nums == []):
        results.append(group[:])
        return
    if(group[curr_index] != -1):
        curr_index = group.index(-1)
    if(curr_index % group_size == 0):
        for num in nums:
            if(num > group[curr_index - group_size]):
                new_nums = nums[:]
                new_nums.remove(num)
                group[curr_index] = num
                r_helper(new_nums, group, (curr_index + 1) % num_people, num_people, group_size, results)
            else:
                group[curr_index] = -1
                return
    else:
        for num in nums:
            if(num > group[curr_index - 1]):
                new_nums = nums[:]
                new_nums.remove(num)
                group[curr_index] = num
                r_helper(new_nums, group, (curr_index + 1) % num_people, num_people, group_size, results)
            else:
                group[curr_index] = -1
                return
    group[curr_index] = -1


def get_groups(lst, p):
    results = []
    n = len(lst)
    group_size = int(math.ceil(n / float(p)))
    r_helper(sorted(lst, reverse=True)[:-1], [min(lst)] + [-1]*(n-1), 1, n, group_size, results)
    return [[tuple(result[i * group_size:(i + 1) * group_size]) for i in range((len(result) + group_size - 1) // group_size)] for result in results]

# Get the acceptable set of toppings for a person with the given index
# Currently "acceptable" == "non-negative"
def get_topping_set(table, index):
    return set([i for i, row in enumerate(table) if int(row[index+1]) >= 0])

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

    # Extend all sublists to the same length
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
    topping_set = set(range(len(toppings)))
    person_topping_sets = [get_topping_set(values[1:], i) for i in range(len(names))]
    # strip names/topping names and flip to col(person) major order
    topping_values = zip(*values[1:])[1:]
    topping_values = np.asarray(topping_values).astype(int)

    best_score = 0
    best_groupset = []
    best_toppingset = []

    print("Getting groups")
    memo_dict = {}
    start = time.time()

    i = 0
    # Iterate over all possible pizza groupings, finding the best score
    for groupset in get_groups(p_list, num_pizzas):
        i += 1
        if(i % 100000 == 0):
            print(i)
        group_score = 999999999  # overall score for this set of grouping's pizzas
        toppingset = []  # list of tuples representing groups toppings

        # Iterate over each group in a set of groups, scoring their pizza
        for group in groupset:
            if(group in memo_dict):
                total_score, topping_scores = memo_dict[group]
            else:
                group_toppings = topping_set.copy()  # start with all possible toppings

                # For each person, intersect their acceptable toppings
                for person in group:
                    group_toppings = group_toppings & person_topping_sets[person]
                group_toppings = list(group_toppings)

                # Score toppings, remove neutral toppings, and sort by score

                topping_scores = np.sum(topping_values[group, :][:, group_toppings], axis=0)
                topping_scores = zip(topping_scores.tolist(), group_toppings)

                total_score = sum([score for score, topping in topping_scores])
                memo_dict[group] = (total_score, topping_scores)
            group_score = min(group_score, total_score)

            toppingset.append(topping_scores)

        # store the result if it's the best so far
        if(group_score > best_score):
            best_score = group_score
            best_groupset = groupset
            best_toppingset = toppingset

    end = time.time()
    print("Checked groups in %f seconds" % (end-start))
    # convert indices to names
    best_groupset = [[names[x] for x in group] for group in best_groupset]
    best_toppingset = [[(score, toppings[idx]) for score, idx in t_scores if score > 0] for t_scores in best_toppingset]
    best_toppingset = [sorted(t_scores, key=lambda x: x[0], reverse=True) for t_scores in best_toppingset]

    return render_template('pizza.html', num_pizzas=num_pizzas,
                           grp_tps=zip(best_groupset, best_toppingset))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
