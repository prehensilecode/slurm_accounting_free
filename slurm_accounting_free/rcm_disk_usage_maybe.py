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
from pathlib import Path

### cron example
# Example of job definition:
# .---------------- minute (0 - 59)
# |  .------------- hour (0 - 23)
# |  |  .---------- day of month (1 - 31)
# |  |  |  .------- month (1 - 12) OR jan,feb,mar,apr ...
# |  |  |  |  .---- day of week (0 - 6) (Sunday=0 or 7) OR sun,mon,tue,wed,thu,fri,sat
# |  |  |  |  |
# *  *  *  *  * user-name command to be executed
# 23 23  *  *  * root /usr/local/bin/python3.9 /ifs/sysadmin/bin/rcm_disk_usage_maybe.py >> /var/log/rcm_disk_usage.log 2>&1
#  15 04  1  *  * root /usr/local/bin/python3.9 /ifs/sysadmin/bin/generate_monthly_sreports.py >> /var/log/rcm_sreports.log 2>&1

#
# On Mgmt Node:
# * du output goes to /ifs/sysadmin/RCM/YYYY-MM/disk_usage
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

rcm_prefix = None
groups_prefix = None

def xfs_quota_report_maybe(when, debug_p=False, verbose_p=False, force_p=False):
    global rcm_prefix
    global groups_prefix

    # if we use xfs_quota_report_maybe, we are on the fileserver
    yymm = '{}-{:02d}'.format(when.date.year, when.date.month)
    yymmdd = '{}-{:02d}'.format(yymm, when.date.day)
    rcm_dir = '/'.join([rcm_prefix, yymm])
    du_outfn = 'du_group-{}.txt'.format(yymmdd)

    if debug_p:
        du_outfn = 'debug-du_group-{}-{:02d}-{:02d}.txt'.format(when.date.year, when.date.month, when.date.day)
        print('DEBUG: xfs_quota_report_maybe(): when = {}'.format(when))
        print('DEBUG: xfs_quota_report_maybe(): rcm_dir  = {}'.format(rcm_dir))
        print('DEBUG: xfs_quota_report_maybe(): du_outfn = {}'.format(du_outfn))

    try:
        os.makedirs(rcm_dir, mode=0o770)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise

    quota_report = subprocess.run(['xfs_quota', '-x', '-c', 'report -p', '/mnt/xfs1'],
            stdout=subprocess.PIPE, check=False).stdout.decode('utf-8')

    if debug_p:
        print(quota_report.split('\n'))

    grp_pat = re.compile(r'\w+Grp')

    ### quota report: groupname  usage  softlimit hardlimit grace
    ### want to output du format:  usage  group_directory
    with open(os.path.join(rcm_dir, du_outfn), 'w') as du_file:
        for line in quota_report.split('\n'):
            if grp_pat.match(line):
                line_split = line.split()
                print("{}\t/mnt/HA/groups/{}".format(line_split[1], line_split[0]), file=du_file)

    return

def disk_usage_maybe(when, hostname, debug_p=False, verbose_p=False, force_p=False):
    """when is a delorean.Delorean object"""

    global rcm_prefix
    global groups_prefix

    ### measure disk usage, and output to outdir
    yyyymm = '{}-{:02d}'.format(when.date.year, when.date.month)
    yyyymmdd = '{}-{:02d}'.format(yyyymm, when.date.day)

    if hostname == 'myclusterhead':
        rcm_dir = rcm_prefix / yyyymm / 'disk_usage'
    else:
        rcm_dir = rcm_prefix / yyyymm

    du_outfn = 'du_group-{}.txt'.format(yyyymmdd)

    if debug_p:
        print('DEBUG: disk_usage_maybe(): when = {}'.format(when))
        print('DEBUG: disk_usage_maybe(): rcm_dir  = {}'.format(rcm_dir))
        print('DEBUG: disk_usage_maybe(): du_outfn = {}'.format(du_outfn))

    try:
        os.makedirs(rcm_dir, mode=0o770)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise

    with open(rcm_dir / du_outfn, 'w') as du_file:
        grpdirpat = re.compile(r'.*Grp$')
        for groupdir in [dir for dir in Path(groups_prefix).glob('*Grp') if dir.is_dir()]:
            fullgroupdir = groups_prefix / groupdir
            if grpdirpat.match(str(groupdir)):
                if verbose_p:
                    print(f'INFO: Running du on {fullgroupdir}')
                try:
                    subprocess.run(['du', '-sk', fullgroupdir], stdout=du_file, check=False)
                except OSError as err:
                    print(f'ERROR: OS error: {err}')
                    continue
            else:
                print(f'non-group directory: {groupdir} ... skipping')

    return


def main():
    global rcm_prefix
    global groups_prefix

    parser = argparse.ArgumentParser(description="Measure group disk usage if it's the right day of month")
    parser.add_argument('-d', '--debug', action='store_true', help='debugging output')
    parser.add_argument('-v', '--verbose', action='store_true', help='verbose output')
    parser.add_argument('-f', '--force', action='store_true', help='run du even if not an appropriate date')
    args = parser.parse_args()

    debug_p   = args.debug
    verbose_p = args.verbose
    force_p   = args.force

    # current date-time
    now = delorean.Delorean()

    if debug_p:
        print(f'main(): debug_p = {debug_p}')
        print(f'main(): now = {now}')

    hostname = platform.node()
    if hostname == 'oldclusterhead':
        rcm_prefix = '/mnt/HA/sysadmin/RCM'
        groups_prefix = '/mnt/HA/groups'
    elif hostname == 'nfsserver':
        rcm_prefix = '/mnt/xfs1/sysadmin/RCM'
        groups_prefix = '/mnt/xfs1/groups'
    elif hostname == 'myclusterhead':
        rcm_prefix = Path('/ifs/sysadmin/RCM')
        groups_prefix = Path('/ifs/groups')

    xfs_quota_path = Path('/usr/sbin/xfs_quota')
    xfs_groups_dir = Path('/mnt/xfs1/groups')

    if force_p:
        if os.path.isdir(xfs_groups_dir) and os.path.isfile(xfs_quota_path) and os.access(xfs_quota_path, os.X_OK):
           print('{} - rcm_disk_usage_maybe.py - starting xfs_quota report'.format(now.datetime.strftime('%Y-%m-%d %H:%M:%S UTC'))) 
           xfs_quota_report_maybe(now, debug_p, verbose_p, force_p)
        else:
            print('{} - rcm_disk_usage_maybe.py - starting du'.format(now.datetime.strftime('%Y-%m-%d %H:%M:%S UTC')))
            tic = time.time()
            disk_usage_maybe(now, hostname, debug_p, verbose_p, force_p)
            toc = time.time()
            min, sec = divmod(toc - tic, 60)
            now = delorean.Delorean()
            print(f'{now.datetime.strftime("%Y-%m-%d %H:%M:%S UTC")} - rcm_disk_usage_maybe.py - completed in {int(min)}m {int(sec)}s')
    else:
        last_day_of_month = calendar.monthrange(now.date.year, now.date.month)[1]

        if now.date.day in (7,14,21,28,last_day_of_month):
            if hostname == 'nfsserver':
                # uses an XFS filesystem
                print('{} - rcm_disk_usage_maybe.py - starting xfs_quota report'.format(now.datetime.strftime('%Y-%m-%d %H:%M:%S UTC')))
                xfs_quota_report_maybe(now, debug_p, verbose_p, force_p)
            else:
                print('{} - rcm_disk_usage_maybe.py - starting du'.format(now.datetime.strftime('%Y-%m-%d %H:%M:%S UTC')))
                tic = time.time()
                disk_usage_maybe(now, hostname, debug_p, verbose_p, force_p)
                toc = time.time()
                min, sec = divmod(toc - tic, 60)
                now = delorean.Delorean()
                print(f'{now.datetime.strftime("%Y-%m-%d %H:%M:%S UTC")} - rcm_disk_usage_maybe.py - completed in {int(min)}m {int(sec)}s')
        else:
            print(f'{now.datetime.strftime("%Y-%m-%d %H:%M:%S UTC")} - rcm_disk_usage_maybe.py - day-of-month not in list')

    return


if __name__ == '__main__':
    main()


