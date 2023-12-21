#!/usr/bin/python3
import argparse
import csv
import json
import os
import re
from pathlib import Path
import yaml

from ssg.constants import (
    xml_version, oval_header, timestamp, PREFIX_TO_NS, XCCDF11_NS, XCCDF12_NS)
from ssg import xml
import ssg.controls
import ssg.environment
import ssg.products

ns = {
    "xccdf-1.1": XCCDF11_NS,
}


SSG_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RULES_JSON = os.path.join(SSG_ROOT, "build", "rule_dirs.json")
BUILD_CONFIG = os.path.join(SSG_ROOT, "build", "build_config.yml")
CONTROLS_DIR = os.path.join(SSG_ROOT, "controls")

def parse_args():
    parser = argparse.ArgumentParser(
        description="Compare items between a STIG spreasheet and a release")

    parser.add_argument("--csv-file", "-f", required=True,
                        help=f"Path to CSV from DISA Spreadsheet")
    parser.add_argument("--disa-stig", required=True,
                        help="Path to published DISA STIG XML file")
    return parser.parse_args()


def find_matching_rule(csv_row, stig_dict):

    row_srg_id_list = csv_row["SRGID"]

    # Grab first SRG, in case multiple SRGs are defined
    row_srg_id = row_srg_id_list.split(",")[0].strip()

    groups_list = stig_dict.get(row_srg_id, [])

    row_title = csv_row["Requirement"]
    row_checktext = csv_row["Check"]
    row_fixtext = csv_row["Fix"]
    for group in groups_list:
        rule_title = group.find("xccdf-1.1:Rule/xccdf-1.1:title", ns).text
        if row_title == rule_title:
            print("identical checktext")
            return True


    # Render the XPath query so that no curly braces are input to findall() 
    #query = (f".//xccdf-1.1:Rule/xccdf-1.1:title[.='{row_title}']")
    #results = xml_stig.findall(query, ns)

    #if len(results) == 1:
        #return True

        rule_checktext = group.find("xccdf-1.1:Rule/xccdf-1.1:check/xccdf-1.1:check-content", ns).text
        print(row_checktext)
        print("---")
        print(rule_checktext)
        if row_checktext == rule_checktext:
            print("identical checktext")
            return True

        rule_fixtext = group.find("xccdf-1.1:Rule/xccdf-1.1:fixtext", ns).text
        print(row_fixtext)
        print("---")
        print(rule_fixtext)
        if row_fixtext == rule_fixtext:
            print("identical fixtext")
            return True

    #escaped_row_checktext = re.sub(r'"', r"&quote;", row_checktext)
    #query = (f'.//xccdf-1.1:Rule/xccdf-1.1:check-content[.="{escaped_row_checktext}"]')
    #results = xml_stig.findall(query, ns)

    return False


def load_up_xml_stig(tree):
    disa_groups = tree.findall("xccdf-1.1:Group", ns)
    groups_dict = dict()
    
    for group in disa_groups:
        group_title = group.find("xccdf-1.1:title", ns).text
        group_dict = groups_dict.get(group_title, False)
        if group_dict:
            group_dict.append(group)
        else:
            groups_dict[group_title] = [group]

    return groups_dict

def main():
    args = parse_args()

    # Read XML file
    tree = xml.parse_file(args.disa_stig)
    stig_dict = load_up_xml_stig(tree)

    # Read CSV file
    with open(args.csv_file, newline='') as csvfile:
        csv_rows = csv.DictReader(csvfile)

        rows_not_found = []
        for row in csv_rows:
            found = find_matching_rule(row, stig_dict)
            if not found:
                rows_not_found.append(row)
            # Find corresponding Group/Rule in the XMl
            # List the items not found
            # List any item in the XML not found in the spreadheet

    if rows_not_found:
        print(f"{len(rows_not_found)} were not found in the XML")
    for row in rows_not_found:
        print(row['SRGID'].strip())

if __name__ == "__main__":
    main()
