#!/usr/bin/python3
import argparse
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
        description="Update the sources with policy data from a STIG publication")

    parser.add_argument("--control", required=True,
                        help="Identifier of the control to update, e.g.: srg_ctr, srg_gpos")
    parser.add_argument("--controls-dir", default=f"{CONTROLS_DIR}",
                        help=f"Directory where project controls can be found (defaults to {CONTROLS_DIR}")
    parser.add_argument("--json", default=f"{RULES_JSON}",
                        help=f"Path to the rules_dir.json (defaults to {RULES_JSON})")
    parser.add_argument("--product", required=True,
                        help="Identifier of the product to render, e.g.: ocp4, rhel9")
    parser.add_argument("input", help="Input Manual DISA XCCDF file")
    return parser.parse_args()

def get_env_yaml(product):
    product_yaml_path = ssg.products.product_yaml_path(SSG_ROOT, product)
    return ssg.products.load_product_yaml(product_yaml_path)

def update_control(control, xml_rule):
    updated = False
    rule_fixtext = xml_rule.get_fixtext_element().text

    if control.fixtext != None and control.fixtext != rule_fixtext:
        control.fixtext = rule_fixtext
        updated = True
    
    xml_check = xml_rule.get_first_check_element()
    rule_check_content = xml_rule.get_check_content_element(xml_check).text
    if control.check != None and control.check != rule_check_content:
        control.check = rule_check_content
        updated = True
    
    if updated:
        print(f"{control.id} - {updated}")

    return updated

def update_policy_file(policy_file_path, xml_rule, env_yaml):
    updated = False

    policy_contents = ssg.yaml.open_and_macro_expand(policy_file_path, env_yaml)

    rule_title = xml_rule.get_title().text
    if "srg_requirement" in policy_contents and policy_contents["srg_requirement"] != rule_title:
        policy_contents["srg_requirement"] = rule_title
        updated = True

    rule_fixtext = xml_rule.get_fixtext_element().text
    if "fixtext" in policy_contents and policy_contents["fixtext"] != rule_fixtext:
        policy_contents["fixtext"] = rule_fixtext
        updated = True
    
    xml_check = xml_rule.get_first_check_element()
    rule_check_content = xml_rule.get_check_content_element(xml_check).text
    if "checktext" in policy_contents and policy_contents["checktext"] != rule_check_content:
        policy_contents["checktext"]  = rule_check_content
        updated = True
    
    if updated:
        print(f"{xml_rule.get_attr('id')} - {updated}")

    reordered_policy = ssg.yaml.reorder_keys_from_file(policy_contents, policy_file_path, env_yaml)

    keys_to_unexpand = ["srg_requirement"]

    # Unexpand Jinja
    unexpand_env = dict()
    unexpand_env["full_name"] = env_yaml["full_name"]
    for k in keys_to_unexpand:
        reordered_policy[k] = ssg.jinja.unexpand(unexpand_env, reordered_policy[k])

    class LiteralUnicode(str):
        pass

    def literal_unicode_representer(dumper, data):
        # NOTE(rhmdnd): pyyaml will not format a string using the style we define for the scalar below
        # if any strings in the data end with a space (e.g., 'some text ' instead of 'some text'). This
        # has been reported upstream in https://github.com/yaml/pyyaml/issues/121. This particular code
        # goes through every line of data and strips any whitespace characters from the end of the
        # string, and reconstructs the string with newlines so that it will format properly.
        text = [line.rstrip() for line in data.splitlines()]
        sanitized = '\n'.join(text)
        return dumper.represent_scalar(u'tag:yaml.org,2002:str', sanitized, style='|')


    yaml.add_representer(LiteralUnicode, literal_unicode_representer)

    # Make LiteralUnicode Force block chomping
    keys_to_block_chomp = ["srg_requirement", "checktext", "fixtext", "vuldiscussion"] 
    for key in keys_to_block_chomp:
        if key in reordered_policy:
            reordered_policy[key] = LiteralUnicode(reordered_policy[key])


    indent_length = ssg.yaml.get_indent_length(policy_file_path)
    with open(policy_file_path, "w") as f:
        yaml_contents = yaml.dump(reordered_policy, None, indent=indent_length, sort_keys=False, canonical=False, default_flow_style=False, width=70)
        formatted_yaml_contents = re.sub(r"\n(\w+:.*\n)", r"\n\n\1", yaml_contents)
        f.write(formatted_yaml_contents)

    return updated

def check_for_changes(srg, control, xml_rule):
    rule_stigid = xml_rule.get_version().text
    rule_description = xml_rule.get_description_element().text
    rule_identifiers = xml_rule.get_idenfifier_elements()


    print(f"{rule_stigid} - {srg}")
    update_control(control, xml_rule)

def get_rule_json(json_path: str) -> dict:
    with open(json_path, 'r') as json_file:
        rule_json = json.load(json_file)
    return rule_json

def get_env_yaml(root: str, product_path: str, build_config_yaml: str) -> dict:
    product_dir = os.path.join(root, "products", product_path)
    product_yaml_path = os.path.join(product_dir, "product.yml")
    env_yaml = ssg.environment.open_environment(
            build_config_yaml, product_yaml_path, os.path.join(root, "product_properties"))
    return env_yaml

def main():
    args = parse_args()
    tree = xml.parse_file(args.input)

    env_yaml = get_env_yaml(SSG_ROOT, args.product, BUILD_CONFIG)

    # TODO: Check if relative or absolute path
    main_control_file = Path(args.controls_dir, f"{args.control}.yml")
    policy = ssg.controls.Policy(main_control_file, env_yaml)
    policy.load()

    json_rules = get_rule_json(args.json)

    disa_groups = tree.findall("xccdf-1.1:Group", ns)
    groups_dict = dict()
    
    for group in disa_groups:
        group_title = group.find("xccdf-1.1:title", ns).text
        if groups_dict.get(group_title, False):
            print("more")
            groups_dict[group_title] += 1
        else:
            groups_dict[group_title] = 1

    print(groups_dict)

    updated_control_ids = []
    for group in disa_groups:
        group_title = group.find("xccdf-1.1:title", ns).text
        rule = group.find("xccdf-1.1:Rule", ns)

        xml_rule = xml.XMLRule(rule)
        control = policy.get_control(group_title)

        updated = update_control(control, xml_rule)
        if updated:
            print(f"Updated {control.id}")
            # The controls are written all at once at the end
            updated_control_ids.append(control.id)
        #else:

        # Check policy files in control selections
        for s in control.selections:
            rule_dir = json_rules[s]["dir"]

            policy_dir = Path(rule_dir, "policy", "stig")
            if Path.exists(policy_dir) and Path.is_dir(policy_dir):
                stig_policy_file = Path(policy_dir, "shared.yml")

                # The policy files are written as we go
                update_policy_file(stig_policy_file, xml_rule, env_yaml)
                     
                # Write to file
            #rule_file = ssg.rules.get_rule_dir_yaml(rule_dir)

            #rule_yaml = ssg.build_yaml.Rule.from_yaml(rule_file, env_yaml=env_yaml)

    local_controls = policy.controls
    local_controls_by_id = policy.controls_by_id

    policy.controls = []
    policy.controls_by_id = dict()

    for c in local_controls:
        if c.id in updated_control_ids:
            print(f"Adding {c.id}")
            policy.controls.append(c)
            policy.controls_by_id[c.id] = c
    
    policy.save()

if __name__ == "__main__":
    main()
