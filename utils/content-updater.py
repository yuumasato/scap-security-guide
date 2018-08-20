#!/usr/bin/env python

import argparse
import json

import ssg.build_yaml
import ssg.rules
import ssg.rule_dir_stats as rds

# query can have form of: products.contains:rhel7
# query can have form of: ovals.products.contains:rhel7
def apply_query(rule_obj, query):
    full_query_field, query_value = query.split(':')
    try:
        language, field, comparator = full_query_field.split('.')
        field_value = rule_obj[language][field]
    except ValueError:
        field, comparator = full_query_field.split('.')
        field_value = rule_obj[field]

    # TODO: Are all field_values lists?
    # This should either be optimized for lists, or made generic for string and dictionary
    if comparator == "is":
        if isinstance(field_value, list):
            if len(field_value)==1 and query_value in field_value:
                return True
        elif isinstance(field_value, str):
            if query_value == field_value:
                return True
    elif comparator == "contains":
        if isinstance(field_value, list):
            if query_value in field_value:
                return True
        elif isinstance(field_value, str):
            if field_value.contains(query_value):
                return True
    else:
        # TODO: Raise error, unknown comparator
        return False

    return False


def update_contents(rule_obj, remove_exp, add_exp):
    if remove_exp:
        # TODO
        pass

    if add_exp:
        full_add_field, value_to_add = add_exp.split(':')

        try:
            language, field = full_add_field.split('.')
            field_value = rule_obj[language][field]
        except ValueError:
            field = full_add_field
            field_value = rule_obj[field]

        if isinstance(field_value, list):
            if value_to_add not in field_value:
                field_value.append(value_to_add)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", type=str, action="store", default="build/rule_dirs.json",
                        help="File to read json output of rule_dir_json from (defaults to build/rule_dirs.json)")
    parser.add_argument("-q", "--query", type=str, action="store", default=None,
                        help="Query witch rules to update.")
    parser.add_argument("-r", "--remove", type=str, action="store", default=None,
                        help="Field to remove from rules that match the query.")
    parser.add_argument("-a", "--add", type=str, action="store", default=None,
                        help="Field to add into rules that match the query.")

    return parser.parse_args()

def main():
    args = parse_args()

    json_file = open(args.input, 'r')
    known_rules = json.load(json_file)

    for rule_id in known_rules:
        if args.query is None or apply_query(known_rules[rule_id], args.query):
            if (args.remove or args.add):
                update_contents(known_rules[rule_id], args.remove, args.add)

                # Reflect changes on filesystem
                rule_file = ssg.rules.get_rule_dir_yaml(known_rules[rule_id]['dir'])
                rule_yaml = ssg.build_yaml.Rule.from_yaml(rule_file)
                # Update Rule
                # Write to file

                #print(rule_id +": "+ str(known_rules[rule_id]["products"]))
            else:
                # Nothing to change, just print rules that matched query
                print(rule_id +": "+ str(known_rules[rule_id]["products"]))

    # regenerate rule_dirs.json

if __name__ == "__main__":
    main()
