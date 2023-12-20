#!/usr/bin/env python3

import argparse
import os
import pathlib
import re
import shlex
import subprocess
import threading

from generate_profile import XLSXParser
from pycompliance import pycompliance
from add_kubernetes_rule import needs_oc, needs_working_cluster


OC_COMMANDS_FILE = "./oc_commands.txt"

class AuditCommandRunnner:
    def __init__(self, test_func, requirements, output_dir, n_workers=7):
        self.test_func = test_func
        self.requirements = requirements
        self.n_workers = n_workers
        self.output_dir = output_dir

        self.workers = []
        for index in range(self.n_workers):
            worker = threading.Thread(
                name="Command runner #%i" % (index),
                target=lambda index=index: self.run_list_of_commands(index)
            )
            self.workers.append(worker)

    def _requirement_queue_generator(self, n_workers, index):
        for i in range(len(self.requirements)):
            if i % n_workers == index:
                print(f".", end="")
                yield self.requirements[i]
    
    def run_list_of_commands(self, index):
        for requirement in self._requirement_queue_generator(self.n_workers, index):
            for command in requirement.commands:
                # Write commands to shell file
                # Executee shell file
                command_file = pathlib.Path(self.output_dir, f"{requirement.id_}.sh")
                with open(command_file, "w") as cf:
                    cf.write("#!/bin/bash\n")
                    cf.write("set -x\n")
                    cf.write(command.command)
                command_file.chmod(0o744)
                output_path = pathlib.Path(self.output_dir,  f"{requirement.id_}.log")
                with open(output_path, "w") as output_file:
                    oc_p = self.test_func(str(command_file.resolve()), output_file)
                command.return_code = oc_p.returncode
            self.dump_test(requirement)

    def run(self):
        for worker in self.workers:
            worker.start()

        for worker in self.workers:
            worker.join()

        # yuumasato: Sometimes the terminal settings get borked when running with multiple threads.
        # I was not able to fix this issue, so I implemented a workaround.
        # This restores the  terminal settings.
        os.system("stty sane")

    def dump_test(self, req):
        req_results_path = pathlib.Path(self.output_dir, f"{req.id_}.txt")
        with open(req_results_path, "w") as f:
            f.write(f"{req.id_} ===\n")
            f.write(f"Audit text ===\n{req.audit_text}\n")
            for command in req.commands:
                f.write(f"Command ===\n{command.command}\n")
                f.write(f"Return code: {command.return_code}\n")
                f.write(f"Output:\n{command.output}\n")



def oc_test_command(command, outfile):
    return subprocess.run(command, stdout=outfile, stderr=subprocess.STDOUT)

class AuditCommand:
    def __init__(self,command, verify_value=None):
        self.command = command
        self.verify_value = verify_value
        self.return_code = None
        self.output = None

    def __str__(self):
        return f"{self.command}\n-> {self.return_code}\n"

    def __repr__(self):
        return f"AuditCommand('{self.command}')"

    def verify_output(self):
        for output in self.output.splitlines():
            if not output == self.verify_value:
                return False
        return True


class Requirement:

    def __init__(self, id_, audit_text):
        self.id_ = id_
        self.audit_text = audit_text
        self.commands = []

    def __str__(self):
        return f"== {self.id_} ==\n{self.audit_text}\n# commands: {len(self.commands)}\n"

    def __repr__(self):
        return f"Requirement('{self.id_}', '{self.audit_text}',)"

    def set_commands(self, commands_list):
        self.commands = commands_list
    

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--input-file', type=str, action="store", required=True,
                        help="The file to parse for oc commands.")
    parser.add_argument('-o', '--output-dir',  type=str, default="./test_command_output",
                        help="Directory where to dump output from commands")
    parser.add_argument('-y', '--verify-output',  action="store", default=False,
                        help="Whether to check if output match expected verify value (Applies only to CIS XLSX)")
    return parser.parse_args()


# This is specific to CIS XLSX files
def parse_cis_verbatim_commands(text) -> list:
    # Find all occurrences of verbatim text
    verbatim_texts = re.findall(r"```\n([\w\W]*?)\n```", text)

    full_command = ""
    # A Control text may have more than one verbatim text blocks
    for verbatim_text in verbatim_texts :
        # Only gather those that contain an `oc` command
        oc_command = re.search(r'\boc\b', verbatim_text)
        if oc_command:
            full_command += oc_command.string + "\n"

    oc_verify = re.search(r'Verify.*`(.*)`.*', text)
    verify_value = None
    if oc_verify:
        verify_value = oc_verify.group(1)

    return [AuditCommand(full_command, verify_value)]



def main() -> None:
    args = parse_args()

    # Parse all commands onto a list
    parser = XLSXParser(args.input_file)
    benchmark = parser.parse()

    benchmark_requirements = []
    for n in benchmark.traverse(benchmark):
        if isinstance(n, pycompliance.Control):
            req = Requirement(n.id, n.audit)
            req.set_commands(parse_cis_verbatim_commands(n.audit))
            benchmark_requirements.append(req)

    # Test limiting
    #benchmark_requirements = benchmark_requirements[50:80]

    output_dir = pathlib.Path(args.output_dir)
    try:
        os.mkdir(output_dir)
    except FileExistsError:
        pass

    # Test commands in parallel
    tester = AuditCommandRunnner(oc_test_command, benchmark_requirements, output_dir)
    tester.run()


    # Write out the results and output of testing
    unsuccessful_runs = []
    for req in benchmark_requirements:
        for command in req.commands:
            if command.return_code != 0:
                unsuccessful_runs.append(req)
            if args.verify_output and not command.verify_output():
                f.write(f"{req.id_}: Expected and actual value differ\n")
                f.write(f"\tCommand: {command.command}\n")
                f.write(f"\tExpected verify value: {command.verify_value}\n")
                f.write(f"\tActual output: {command.output}\n")

    print("\n= Summary =")
    print(f"Successful run:\t\t{len(benchmark_requirements)}")
    print(f"Unsuccessful run::\t\t{len(unsuccessful_runs)}")
    for req in unsuccessful_runs:
        print(f"{req.id_}")



if __name__ == '__main__':
    main()
