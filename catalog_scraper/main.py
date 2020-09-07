import os
import requests
from bs4 import BeautifulSoup
import json
import re
import sys
from tqdm import tqdm
from copy import deepcopy


def scrapePage(s, url, data):
    response = s.get(url=url)
    soup = BeautifulSoup(response.text.encode("utf8"), "lxml")

    rows = soup.find(
        "div", {"id": "advanced_filter_section"}
    ).nextSibling.nextSibling.findAll("tr")
    final_row = None
    for row in tqdm(rows):
        final_row = row
        if len(row.findAll("td")) <= 1:
            continue
        data_url_end = (
            row.findAll("td")[1]
            .findChildren("a", recursive=False)[0]["href"]
            .split("?")[1]
        )
        data_url = f"http://catalog.rpi.edu/preview_course.php?{data_url_end}&print"
        # print(data_url)

        course_results = requests.get(data_url)
        data_soup = BeautifulSoup(course_results.text.encode("utf8"), "lxml")
        course = data_soup.find("h1").contents[0].split("-")
        course_code = course[0].split()
        key = course_code[0].strip() + "-" + course_code[1].strip()
        data[key] = {}
        data[key]["subj"] = course_code[0].strip()
        data[key]["crse"] = course_code[1].strip()
        data[key]["name"] = course[1].strip()
        # data[key]['url'] = data_url
        # data[key]['coid'] = data_url_end.split('=')[-1]

        description = data_soup.find("hr")
        if description:
            description = description.parent.encode_contents().decode().strip()
            description = re.split("<\/?hr ?\/?>", description)[1]
            description = re.split("<\/?br ?\/?>\s*<strong>", description)[0]
            description = re.sub("<.*?>", "", description)
            data[key]["description"] = description.strip()

        # when_offered = data_soup.find('strong', text='When Offered:')
        # if when_offered:
        #     data[key]['when_offered'] = when_offered.nextSibling.strip()
        #
        # cross_listed = data_soup.find('strong', text='Cross Listed:')
        # if cross_listed:
        #     data[key]['cross_listed'] = cross_listed.nextSibling.strip()
        #
        # pre_req = data_soup.find('strong', text='Prerequisites/Corequisites:')
        # if pre_req:
        #     data[key]['pre_req'] = pre_req.nextSibling.strip()
        #
        # credit_hours = data_soup.find('em', text='Credit Hours:')
        # if credit_hours:
        #     credit_hours = credit_hours.nextSibling.nextSibling.text.strip()
        #     if(credit_hours == 'Variable'):
        #         data[key]['credit_hours_max'] = 0
        #         data[key]['credit_hours_min'] = 999
        #     else:
        #         data[key]['credit_hours'] = credit_hours

    next_page = final_row.findChildren("strong")[0].findNext("a", recursive=False)
    if next_page["href"] != "#" and next_page["href"] != "javascript:void(0);":
        return next_page["href"]
    return None


BASE_URL = "http://catalog.rpi.edu"


def get_years(homepage):
    soup = BeautifulSoup(homepage.text.encode("utf8"), "lxml")
    title = soup.find("span", {"id": "acalog-catalog-name"}).string

    years = title[len("Rensselaer Catalog ") :].split("-")
    return years


def get_schools(s, data):
    page = s.get(f"{BASE_URL}/content.php?catoid=5&navoid=110")
    soup = BeautifulSoup(page.text.encode("utf8"), "lxml")
    schools = soup.find("h3", text="Four-Letter Subject Codes by School")
    num_schools = len(
        list(
            filter(lambda x: str(x).strip(), schools.next_siblings),
        )
    )

    school = schools
    for _ in range(num_schools):
        school = school.findNext("p")

        strings = list(school.stripped_strings)
        school_title = strings[0]
        school_name_end = school_title.index("(") - 1
        school_name = school_title[:school_name_end]
        if school_name not in data:
            data[school_name] = []

        for dept in strings[1:]:
            first_space = dept.index(" ")
            code = dept[:first_space]
            name = dept[first_space + 1 :]
            data[school_name].append({"code": code, "name": name})


def calculate_score(columns):
    if not columns:
        return 99999999999  # some arbitrarily large number

    def column_sum(column):
        return sum(map(lambda x: len(x["depts"]), column))

    mean = sum(map(column_sum, columns)) / len(columns)
    return sum(map(lambda x: abs(mean - column_sum(x)), columns)) / len(columns)


# Recursively finds the most balanced set of columns.
# Since `best` needs to be passed by reference, it's
# actually [best], so we only manipulate best[0].
def optimize_ordering_inner(data, i, columns, best):
    if i == len(data):
        this_score = calculate_score(columns)
        best_score = calculate_score(best[0])

        if this_score < best_score:
            best[0] = deepcopy(columns)
        return

    for column in columns:
        column.append(data[i])
        optimize_ordering_inner(data, i + 1, columns, best)
        column.pop()


def optimize_ordering(data, num_columns=3):
    """
    Because we want the QuACS homepage to be as "square-like" as possible,
    we need to re-order departments in such a way that once they're laid out
    in multiple columns, each column is a similar height.
    """

    columns = [[] for _ in range(num_columns)]
    best_result = [[]]

    optimize_ordering_inner(data, 0, columns, best_result)

    best_result = best_result[0]

    for i in range(len(best_result)):
        best_result[i] = sorted(
            best_result[i], key=lambda s: len(s["depts"]), reverse=True
        )

    best_result = sorted(best_result, key=lambda c: len(c[0]["depts"]), reverse=True)

    flattened = []
    for column in best_result:
        flattened.extend(column)

    return flattened


HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
}

for year_select in tqdm(range(21)):
    with requests.Session() as s:
        catalog_home = s.post(
            f"{BASE_URL}/index.php",
            headers=HEADERS,
            data={"catalog": year_select, "sel_cat_submit": "GO"},
        )

        years = get_years(catalog_home)

        data = {}
        if sys.argv[-1] == "schools":
            get_schools(s, data)
            data = list(map(lambda x: {"name": x[0], "depts": x[1]}, data.items()))
            data = optimize_ordering(data)
        elif sys.argv[-1] == "catalog":
            next_url = "/content.php?catoid=20&navoid=498"
            while True:
                if next_url == None:
                    break
                next_url = scrapePage(s, BASE_URL + next_url, data)
        else:
            print(f"ERROR: {sys.argv[-1]} is not a valid argument")
            sys.exit(1)

        for directory in (f"{years[0]}09", f"{years[1]}01", f"{years[1]}05"):
            directory = "data/" + directory
            os.makedirs(directory, exist_ok=True)
            with open(f"{directory}/{sys.argv[-1]}.json", "w") as outfile:
                json.dump(data, outfile, sort_keys=False, indent=2)
