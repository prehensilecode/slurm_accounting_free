#!/usr/bin/env python3
import sys
import os
from pathlib import Path
from io import StringIO
import argparse
import delorean
import re
import csv
import pandas as pd
import decimal
from decimal import Decimal

debug_p = True

sreport_file = 'RCM/2021-04/testreport.txt'
rate = 0.0123
penny = Decimal('0.01')

decimal.getcontext().rounding = decimal.ROUND_HALF_UP

def read_courses(courses_filename):
    courses = []
    with open(courses_filename, 'r') as f:
        for l in f:
            courses.append(l.strip())

    return courses



### annoyance - the "-n/--noheader" option to sreport also drops the useful
###   field names line


def generate_statement(sreport_file):
    global debug_p
    global rate
    global penny

    if debug_p:
        print('DEBUG: sreport_file = {}'.format(sreport_file))

    usage = []
    with open(sreport_file, 'r') as f:
        with StringIO() as csvio:
            count = 0
            for l in f:
                if count < 4:
                    count += 1
                    continue
                else:
                    csvio.write(l)

            csvio.seek(0)
            #for l in csvio:
            #    print(l)
            reader = csv.DictReader(csvio, delimiter='|')
            for l in reader:
                usage.append(l)

    print(usage)

    # Account field:
    # * no leading space - PI's last name
    # * 1 leading space - project
    # * 2 leading spaces - user usage

    # Want:
    # a dict keyed on project
    #  value is a list of users' usage

    accounts = []
    user_usage = {}
    for u in usage:
        su = float(u['Used']) / 60.
        charge = Decimal(su * rate).quantize(penny)
        if u['Account'][0] != ' ':
            print('FOO: ', u)
        #elif u['Account'][0] == ' ' and u['Account'][1] != ' ':
        elif u['Account'][1] != ' ':
            accounts.append(u['Account'].strip())
            if debug_p:
                print('DEBUG: accounts ... ', accounts)
        elif u['Account'][1] == ' ':
            if debug_p:
                print('DEBUG: u = ', u)
                print('')

            if not user_usage or not u['Account'].strip() in user_usage:
                user_usage[u['Account'].strip()] = [{'Proper Name' : u['Proper Name'], 'SU' : su, 'Charge ($)': float(charge)}]
            else:
                user_usage[u['Account'].strip()].append({'Proper Name' : u['Proper Name'], 'SU' : su, 'Charge ($)': float(charge)})

            if debug_p:
                print('DEBUG: user_usage = ', user_usage)
                print('')

    print('user_usage: ')
    for k,v in user_usage.items():
        print(k)
        for u in v:
            print('   ', u)
        print('')


if __name__ == '__main__':
    with os.scandir('RCM/2021-04') as it:
        for entry in it:
            if entry.is_file():
                print("READING file {}".format(entry.path))
                generate_statement(entry.path)
                print("- - - - - - - - - - - - - - - - - - - - - -")

courses = read_courses('courses.txt')
print(courses)

