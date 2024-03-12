#!/usr/bin/env python3
import sys
import os
import errno
import subprocess
import datetime
import delorean
import calendar
import argparse
import re
import platform
import time
import glob
from pathlib import Path
import xml.etree.ElementTree as ET
import grp

### cron example
# ISILON quota reports generated at 23:30 every night
# Example of job definition:
# .---------------- minute (0 - 59)
# |  .------------- hour (0 - 23)
# |  |  .---------- day of month (1 - 31)
# |  |  |  .------- month (1 - 12) OR jan,feb,mar,apr ...
# |  |  |  |  .---- day of week (0 - 6) (Sunday=0 or 7) OR sun,mon,tue,wed,thu,fri,sat
# |  |  |  |  |
# *  *  *  *  * user-name command to be executed
# 55 23  *  *  * root /usr/local/bin/python3.9 /ifs/sysadmin/bin/isilon_rcm_disk_usage_maybe.py >> /var/log/rcm_disk_usage.log 2>&1
# 15 04  1  *  * root /usr/local/bin/python3.9 /ifs/sysadmin/bin/generate_monthly_sreports.py >> /var/log/rcm_sreports.log 2>&1

#
# On MYCLUSTER:
# * du output goes to /ifs/sysadmin/RCM/YYYY-MM/disk_usage
# * du output in kibibytes (du -sk)
#
# We want to get disk usage on the 7th, 14th, 21st, 28th, and last day of the month
# because we don't have a simple "last day of month" in the datetime packages, we use
# the first of the following month
#
# This script will be run by cron on 1,7,14,21,28 day of the month.
# This script will check for day of month, and write out a file named
#     du_group-YYYY-MM-DD.txt
# to directory
#     /ifs/sysadmin/RCM/YYYY-MM
# If day of month is 01, the filename is changed to previous month; i.e. use an
# effective date.

RCM_PREFIX = None
GROUPS_PREFIX = None


def debug_print_maybe(fstr, debug_p=False):
    if debug_p:
        print(eval(f'f"DEBUG: {fstr}"'))


def get_list_of_reports(reports_dir, debug_p=False):
    reports = glob.glob(str(reports_dir / 'scheduled_quota_report_*.xml'))
    times = [delorean.epoch(int(r.split('.xml')[0].split('_')[-1])).shift('US/Eastern') for r in reports]

    debug_print_maybe(f'reports = {reports}', debug_p)
    for t in times:
        t_str = t.datetime.strftime('%c')
        debug_print_maybe(f'time = {t_str}', debug_p)

    retval = list(zip(times, reports))
    retval.sort(key=lambda k: k[0])

    return retval


def isilon_disk_usage_maybe(when, debug_p=False, verbose_p=False, force_p=False):
    global RCM_PREFIX

    debug_print_maybe(f"DEBUG: when = {when}", debug_p)

    QUOTA_REPORTS_DIR = RCM_PREFIX / 'isilon' / 'reports'

    debug_print_maybe(f"QUOTA_REPORTS_DIR={QUOTA_REPORTS_DIR}", debug_p)

    # obsolete groups and their replacement groups
    obsolete_groups = {}

    # read disk usage (physical) from Isilon quota reports and output to outdir
    # output format like du:
    #
    #     kB dirname
    #     20018680    /ifs/groups/tanGrp

    du_by_group = {}

    KIBI = 1024
    MINGID = 10000

    # this is a list of tuples (Delorean, string)
    reports = get_list_of_reports(QUOTA_REPORTS_DIR, debug_p)

    for report in reports:
        debug_print_maybe(f'report[0].date = {report[0].date}; when = {when}', debug_p)
        if report[0].date == when:
            tree = ET.parse(report[1])
            root = tree.getroot()

            debug_print_maybe(f'report = {report}; type(report_fn) = {type(report)}', debug_p)
            debug_print_maybe(f"Report time: {delorean.epoch(int(root.attrib['time'])).shift('US/Eastern').datetime.strftime('%Y-%m-%d %X %Z')}", debug_p)

            for domain in root.iter('domain'):
                if domain.attrib['type'] == 'group':
                    gid = int(domain.attrib['id'])
                    debug_print_maybe(f'gid = {gid}', debug_p)
                    # research groups have GIDs starting at 10001
                    if gid > MINGID:
                        gr_name = grp.getgrgid(gid).gr_name
                        # FIXME this results in two lines for the valid group;
                        #       real fix is to chgrp all the affected files;
                        #       currently kludge below to add obsolete group's
                        #       usage into replacement group
                        if gr_name in obsolete_groups:
                            gr_name = obsolete_groups[gr_name]

                        for usage in domain.findall('usage'):
                            # NOTE: du(1) reports physical storage
                            if usage.attrib['resource'] == 'physical':
                                # quota reports show usage in bytes
                                # want output in kiB to be in same units as "du -sk" before
                                usage_kiB = round(float(usage.text)/KIBI)

                                debug_print_maybe(f'gr_name = {gr_name}')
                                # check if group already has du entry
                                if gr_name not in du_by_group.keys():
                                    du_by_group[gr_name] = usage_kiB
                                else:
                                    du_by_group[gr_name] += usage_kiB

    # build du_output
    du_output = []
    grdir_prefix = Path('/ifs/groups')
    for gr_name, du in du_by_group.items():
        grdir = grdir_prefix / gr_name
        du_output.append(f'{du}\t{grdir}')

    yyyymm = '{}-{:02d}'.format(when.year, when.month)
    yyyymmdd = '{}-{:02d}'.format(yyyymm, when.day)

    rcm_dir = RCM_PREFIX /yyyymm / 'disk_usage'

    du_outfn = f'du_group-{yyyymmdd}.txt'

    debug_print_maybe(f'when = {when}, rcm_dir = {rcm_dir}, du_outfm = {du_outfn}', debug_p)

    debug_print_maybe('Trying to write du output now…', debug_p)

    # du output file format, from "du -sk"; units kiB
    # e.g.
    # 5732576\t/ifs/groups/tanGrp
    # 32\t/ifs/groups/daiGrp
    # 450516856\t/ifs/groups/albertGrp
    # 10616\t/ifs/groups/woerdemanGrp
    debug_print_maybe(f'rcm_dir = {rcm_dir} ; du_outfn = {du_outfn}', debug_p)
    try:
        os.makedirs(rcm_dir, mode=0o770, exist_ok=True)
        with open(rcm_dir / du_outfn, 'w') as du_file:
            for du in du_output:
                du_file.write(du + '\n')
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise

    # return the du_by_group dict
    return du_by_group


def main():
    global RCM_PREFIX
    global GROUPS_PREFIX

    # current date-time (local)
    today = datetime.date.today()

    parser = argparse.ArgumentParser(description="Measure group disk usage if it's the right day of month")
    parser.add_argument('-w', '--when', default=f'{today.strftime(format="%Y-%m-%d")}', help='Date (local timezone) for measuring usage in format YYYY-MM-DD (default today)')
    parser.add_argument('-d', '--debug', action='store_true', help='debugging output')
    parser.add_argument('-v', '--verbose', action='store_true', help='verbose output')
    parser.add_argument('-f', '--force', action='store_true', help='run du even if not an appropriate date')
    args = parser.parse_args()

    debug_p   = args.debug
    verbose_p = args.verbose
    force_p   = args.force

    debug_print_maybe(f'main(): debug_p = {debug_p}', debug_p)
    debug_print_maybe(f'main(): today = {today}', debug_p)
    debug_print_maybe(f'main(): args.when = {args.when}', debug_p)

    y, m, d = args.when.split('-')
    try:
        when = datetime.date(int(y), int(m), int(d))
    except ValueError as e:
        print(f'ERROR: {e}')
        sys.exit(3)

    debug_print_maybe(f'main(): when = {when}', debug_p)

    hostname = platform.node()
    if hostname == 'myclusterhead':
        if debug_p:
            RCM_PREFIX = Path('/ifs/sysadmin/RCM/DEBUG')
        else:
            RCM_PREFIX = Path('/ifs/sysadmin/RCM')

        GROUPS_PREFIX = Path('/ifs/groups')
    else:
        debug_print_maybe(f'ERROR: unknown host {hostname}', debug_p)
        sys.exit(1)

    if force_p:
        debug_print_maybe(f'{when} - isilon_rcm_disk_usage_maybe.py - starting to read isilon reports', debug_p)
        debug_print_maybe(f'{when} - isilon_rcm_disk_usage_maybe.py', debug_p)
        tic = time.time()
        isilon_disk_usage_maybe(when, debug_p, verbose_p, force_p)
        toc = time.time()
        min, sec = divmod(toc - tic, 60)
        debug_print_maybe(f'{when} - isilon_rcm_disk_usage_maybe.py - completed in {int(min)}m {int(sec)}s', debug_p)
    else:
        last_day_of_month = calendar.monthrange(when.year, when.month)[1]

        if when.day in (7, 14, 21, 28, last_day_of_month):
            debug_print_maybe(f'{when} - isilon_rcm_disk_usage_maybe.py - starting du', debug_p)
            tic = time.time()
            isilon_disk_usage_maybe(when, debug_p, verbose_p, force_p)
            toc = time.time()
            min, sec = divmod(toc - tic, 60)
            debug_print_maybe(f'{when} - isilon_rcm_disk_usage_maybe.py - completed in {int(min)}m {int(sec)}s', debug_p)
        else:
            debug_print_maybe(f'{when} - isilon_rcm_disk_usage_maybe.py - day-of-month not in list', debug_p)

    return


if __name__ == '__main__':
    main()

