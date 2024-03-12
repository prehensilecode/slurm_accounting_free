#!/usr/bin/env python3
import os
import sys
import subprocess
import datetime
import delorean
import calendar
import argparse
from pathlib import Path
import grp
import csv
import io
import glob
import xml.etree.ElementTree as ET
import time
import math

DOLLARS_TO_SU = 60./0.0123
RCM_PREFIX = None

# Storage rate = 1081 SU per TiB-month; $0.0123 per SU

# To update without asking, use "-Q" or "--quiet" option:
#  sacctmgr --quiet modify account somethingprj set grptresmins=billing=123456

# To read the current GrpTRESMins:
#  sacctmgr -p show assoc format=cluster,account,user,grptresmins

# * read daily isilon quota report
# * for each group which has no charge code - know if the GrpTRESMins field exists
#   * reduce the GrpTRESMins by some amount

def get_list_of_reports(reports_dir: Path, debug_p=False):
    reports = glob.glob(str(reports_dir / 'scheduled_quota_report_*.xml'))
    times = [delorean.epoch(int(r.split('.xml')[0].split('_')[-1])).shift('US/Eastern') for r in reports]

    retval = list(zip(times, reports))
    retval.sort(key=lambda k: k[0])

    return retval


def get_disk_usage(when: datetime.date, debug_p=False):
    global RCM_PREFIX

    #              = 1081/(1024*1024*1024*1024) SU per byte-month
    # divide by number of days in month

    TIBI = 1024. * 1024. * 1024. * 1024.
    base_rate = 1081. / TIBI
    ndays = float(calendar.monthrange(when.year, when.month)[1])
    if debug_p:
        print(f'DEBUG: base_rate = {base_rate}')
        print(f'DEBUG: ndays for {when} = {ndays}')

    MINGID = 10000
    reports_dir = RCM_PREFIX / 'isilon' / 'reports'
    reports = get_list_of_reports(reports_dir)
    acct_usage = {}
    for r in reports:
        if r[0].date == when:
            if debug_p:
                print(f'FOUND DATE MATCH: {r[0].date}, {r[1]}')

            tree = ET.parse(r[1])
            root = tree.getroot()
            for domain in root.iter('domain'):
                if domain.attrib['type'] == 'group':
                    gid = int(domain.attrib['id'])
                    if gid > MINGID:
                        gr_name = grp.getgrgid(gid).gr_name

                        # translate group name to account name
                        acct = gr_name.lower().replace('grp', 'prj')
                        if debug_p:
                            print(f'DEBUG: gr_name = {gr_name}; acct = {acct}')

                        for usage in domain.findall('usage'):
                            if usage.attrib['resource'] == 'physical':
                                # amount of SU consumed for one day = usage * base_rate / ndays
                                acct_usage[acct] = round(float(usage.text) * base_rate / ndays)
        else:
            if debug_p:
                print(f'NO DATE MATCH: {r[0].date}, {r[1]}')
            pass

    if debug_p:
        for a, u in acct_usage.items():
            print(f'DEBUG: acct = {a}, usage = {u}')

    return acct_usage


def get_myorg_grants(debug_p=False):
    global RCM_PREFIX
    global DOLLARS_TO_SU
    grants_file = RCM_PREFIX / 'board_grants.csv'

    grantees = []
    with open(grants_file, 'r') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            if debug_p:
                print(row)
            grantees.append((row['Account'], math.floor(float(row['Grant ($)']) * DOLLARS_TO_SU)))

    return grantees


def get_associations(grantees):
    associations = subprocess.run(
        ['/cm/shared/apps/slurm/current/bin/sacctmgr', '--quiet', '--parsable2', 'show',
         'assoc', 'format=cluster,account,grptresmins'],
        stdout=subprocess.PIPE, check=False).stdout.decode('utf-8')

    grantee_prjs = []
    for g in grantees:
        grantee_prjs.append(g[0])

    reader = csv.DictReader(io.StringIO(associations), delimiter='|')

    return dict([(row['Account'], int(row['GrpTRESMins'].split('=')[1])) for row in reader if (row['GrpTRESMins'] != '' and row['Account'] not in grantee_prjs)])


def main():
    global RCM_PREFIX

    parser = argparse.ArgumentParser(description='Update GrpTRESMins based on disk usage for the date')
    parser.add_argument('-d', '--debug', action='store_true', help='Debugging output')

    # today's date in local timezone
    today = datetime.date.today()
    parser.add_argument('-w', '--when', default=f'{today}', help='Date (local timezone) in format YYYY-MM-DD (default today)')

    args = parser.parse_args()

    debug_p = args.debug

    if debug_p:
        RCM_PREFIX = Path('/ifs/sysadmin/RCM/DEBUG')
        print(f'DEBUG: get_disk_usage(): args.when = {args.when}')
    else:
        RCM_PREFIX = Path('/ifs/sysadmin/RCM')

    # storage rate = 1081 SU per TiB-month
    date_of_interest = None
    if not args.when:
        date_of_interest = today
        print(f'date_of_interest = today = {date_of_interest}')
    else:
        try:
            date_of_interest = delorean.parse(args.when, timezone='US/Eastern').date
        except delorean.exceptions.DeloreanError as e:
            print(f'ERROR: {e}')
            sys.exit(1)

    if debug_p:
        print(f'DEBUG: date_of_interest = {date_of_interest}')

    grantees = get_myorg_grants(debug_p=debug_p)

    if debug_p:
        for g in grantees:
            print(f'DEBUG: grantee - {g}')

    associations = get_associations(grantees)

    if debug_p:
        for a in associations.items():
            print(f'DEBUG: association - {a}')

    du = get_disk_usage(date_of_interest, debug_p)

    if debug_p:
        for k, v in du.items():
            print(f'DEBUG: du - du[{k}] = {v}')

    # find matching group
    du_keyset = set(k.lower() for k in du.keys())

    if debug_p:
        print(f'DEBUG: du_keyset = {du_keyset}')


    tic = time.time()
    # sacctmgr cmdline:
    #    sacctmgr modify account math540prj set grptresmins=billing=2880000

    for acct, grptresmins in associations.items():
        if debug_p:
            print(f'DEBUG: acct = {acct}; acct in du = {acct in du}; grptresmins = {grptresmins}')

        if (acct.replace('prj', 'grp') in du_keyset) and (grptresmins > 0):
            if debug_p:
                print(f'DEBUG: found {acct} in du - {du[acct]}')

            # fiddle factor of +5 to avoid underflow
            new_grptresmins = grptresmins - du[acct] + 5

            # FYI
            # $100 per month credit = 100/0.0123 hrs = 100/0.0123*60 mins
            # = 487804.8780 ~= 487805

            # to perform sacctmgr operation without prompting, use "-i";
            # "-Q" for quiet operation
            cmdline = f'/cm/shared/apps/slurm/current/bin/sacctmgr -Q -i modify account {acct} set grptresmins=billing={new_grptresmins}'

            if debug_p:
                print(f'DEBUG: {acct} - GrpTRESMins = {grptresmins}, du = {du[acct]}')
                print(f'DEBUG: cmdline = {cmdline}')
                print()

            try:
                sacctmgr_output = subprocess.run(
                    cmdline.split(),
                    stdout=subprocess.PIPE,
                    check=False).stdout.decode('utf-8')

                if debug_p:
                    print(f'DEBUG: sacctmgr_output = {sacctmgr_output}')
            except subprocess.CalledProcessError as e:
                print(f'ERROR: {e.cmd} - {e.returncode} - {e.stderr}')
                continue

    toc = time.time()
    now = delorean.Delorean(timezone='US/Eastern')
    print(f'{now.datetime.strftime("%Y-%m-%d %H:%M:%S %Z")} - update_grptresmins.py - completed in {toc - tic} sec.')


if __name__ == '__main__':
    main()
